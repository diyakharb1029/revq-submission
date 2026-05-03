#!/usr/bin/env python3
"""
RevQ take-home exercise — ingestion script.

Reads all three platform JSON files (blinkit, zepto, instamart),
normalises them into the shared schema, and writes to a SQLite DB.

Usage:
    python ingest.py                          # uses ../data/ and ../revq.db
    python ingest.py --data /path/to/data     # custom data directory
    python ingest.py --db /path/to/db.sqlite  # custom DB path
"""

import argparse
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Schema DDL (mirrors schema.sql exactly)
# ---------------------------------------------------------------------------
SCHEMA = """
CREATE TABLE IF NOT EXISTS brands (
    id   INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT    NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS canonical_products (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    brand_id       INTEGER NOT NULL REFERENCES brands(id),
    canonical_name TEXT    NOT NULL,
    category       TEXT,
    weight_grams   INTEGER,
    pack_count     INTEGER NOT NULL DEFAULT 1,
    created_at     TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE(brand_id, canonical_name, weight_grams, pack_count)
);

CREATE TABLE IF NOT EXISTS platform_listings (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    canonical_product_id INTEGER NOT NULL REFERENCES canonical_products(id),
    platform             TEXT    NOT NULL CHECK(platform IN ('blinkit','zepto','instamart')),
    platform_product_id  TEXT    NOT NULL,
    display_name         TEXT    NOT NULL,
    image_url            TEXT,
    created_at           TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE(platform, platform_product_id)
);

CREATE TABLE IF NOT EXISTS price_snapshots (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    listing_id    INTEGER NOT NULL REFERENCES platform_listings(id),
    scraped_at    TEXT    NOT NULL,
    mrp           INTEGER NOT NULL,
    selling_price INTEGER NOT NULL,
    discount_pct  REAL,
    UNIQUE(listing_id, scraped_at)
);

CREATE TABLE IF NOT EXISTS pincodes (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    pincode TEXT    NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS availability_snapshots (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    listing_id    INTEGER NOT NULL REFERENCES platform_listings(id),
    pincode_id    INTEGER NOT NULL REFERENCES pincodes(id),
    scraped_at    TEXT    NOT NULL,
    in_stock      INTEGER NOT NULL CHECK(in_stock IN (0,1)),
    available_qty INTEGER,
    UNIQUE(listing_id, pincode_id, scraped_at)
);

CREATE INDEX IF NOT EXISTS idx_price_listing_time
    ON price_snapshots(listing_id, scraped_at DESC);
CREATE INDEX IF NOT EXISTS idx_avail_listing_time
    ON availability_snapshots(listing_id, scraped_at DESC, in_stock);
CREATE INDEX IF NOT EXISTS idx_listing_canonical
    ON platform_listings(canonical_product_id);
CREATE INDEX IF NOT EXISTS idx_avail_time_stock
    ON availability_snapshots(scraped_at, in_stock);
"""

# ---------------------------------------------------------------------------
# Name / weight normalisation helpers
# ---------------------------------------------------------------------------

# Words that carry no flavour information
_STOP = {
    "yogabar", "protein", "bar", "bars", "energy", "muesli", "cereal", "peanut",
    "butter", "oats", "rolled", "natural", "breakfast", "snack", "healthy",
    "and", "the", "pack", "of", "single", "with", "grain", "wholegrain",
    "multigrain", "bar",
}

_RE_BRAND        = re.compile(r"^\s*yogabar\s*", re.I)
_RE_PARENS_SIZE  = re.compile(r"\(\s*\d+\s*(?:g|gm|kg|gram)\s*\)", re.I)
_RE_TRAIL_PIPE   = re.compile(r"\s*\|.*$")                    # instamart pipe sections
_RE_TRAIL_PACK   = re.compile(r"\s*-\s*pack\s+of\s+\d+.*$", re.I)  # blinkit "- Pack of 6 (360g)"
_RE_TRAIL_SIZE   = re.compile(r"\s+\d+\s*(?:g|gm|gram|kg)\s*$", re.I)  # trailing "60GM"
_RE_PACK_END     = re.compile(r"\s+pack\s+of\s+\d+.*$", re.I)


def canonical_name(raw: str) -> str:
    """
    Produce a clean, platform-agnostic display name.
    Strips brand prefix, size annotations, and pack suffixes.
    Title-cases the result.
    """
    s = raw.strip()
    s = _RE_BRAND.sub("", s)
    s = _RE_PARENS_SIZE.sub("", s)       # "(60 g)", "(360g)"
    s = re.sub(r"\(\s*pack\s+of\s+\d+\s*\)", "", s, flags=re.I)  # "(Pack of 6)"
    s = _RE_TRAIL_PIPE.sub("", s)        # "| Chocolate Chunk & Nuts | 60g | Pack of 1"
    s = _RE_TRAIL_PACK.sub("", s)        # " - Pack of 6 (360g)"
    s = _RE_PACK_END.sub("", s)          # " PACK OF 6 - 360GM"
    s = _RE_TRAIL_SIZE.sub("", s)        # trailing "60GM", "400GM"
    # Title-case and normalise common abbreviations
    s = " ".join(w.capitalize() for w in s.lower().split())
    for abbr, full in [("Choc", "Chocolate"), ("Alm", "Almond"), ("Cran", "Cranberry")]:
        s = re.sub(rf"\b{abbr}\b", full, s)
    return s.strip()


def flavor_tokens(name: str) -> frozenset:
    """
    Return a bag of meaningful flavor/descriptor words after stripping
    brand, category, size, and stop words.  Used for Jaccard matching.
    """
    s = name.lower()
    s = re.sub(r"\byogabar\b", " ", s)
    # Strip protein-content labels like "21g protein" before weight parsing
    # so "21g" isn't mistaken for product weight.
    s = re.sub(r"\b\d+\s*g\s+protein\b", " protein ", s)
    # Normalise common abbreviations across platforms
    s = re.sub(r"\bchoc\b", "chocolate", s)
    s = re.sub(r"\bpb\b", "peanut butter", s)
    s = re.sub(r"\bdc\b", "dark chocolate", s)
    s = re.sub(r"\balm\b", "almond", s)
    s = re.sub(r"\bcran\b", "cranberry", s)
    s = re.sub(r"\b\d+\s*(?:g|gm|gram|kg)\b", " ", s)
    s = re.sub(r"\bpack\s+of\s+\d+\b", " ", s)
    s = re.sub(r"\b\d+\s*x\s*\d+\s*(?:g|gm)?\b", " ", s)
    s = re.sub(r"[|&+\-,.()\[\]/]", " ", s)
    tokens = {t for t in s.split() if len(t) > 2 and t not in _STOP}
    return frozenset(tokens)


def jaccard(a: frozenset, b: frozenset) -> float:
    if not a and not b:
        return 1.0
    union = a | b
    return len(a & b) / len(union)


# ---------------------------------------------------------------------------
# Weight / pack extraction
# ---------------------------------------------------------------------------

def _pack_from_name(name: str) -> int:
    m = re.search(r"pack\s+of\s+(\d+)", name, re.I)
    if m:
        return int(m.group(1))
    m = re.search(r"\b(\d+)\s*x\s*\d+\s*(?:g|gm)\b", name, re.I)
    if m:
        return int(m.group(1))
    # "6 Bars Mixed" (Instamart variety pack)
    m = re.search(r"\b(\d+)\s+bars?\b", name, re.I)
    if m:
        return int(m.group(1))
    return 1


def extract_weight_pack(
    name: str,
    weight_field=None,
    weight_unit: Optional[str] = None,
    pack_from_field: Optional[int] = None,
):
    """
    Returns (weight_grams_per_unit: int|None, pack_count: int).

    Strategy:
      1. Use structured fields (Instamart) if available.
      2. Parse "NxNg" or "N x Ng" patterns (Blinkit energy bar packs).
      3. Parse trailing "(Ng)" or "NKG".
      4. For pack products, divide total weight by pack count.

    Note: protein-content labels like "21g Protein Bar" or "20G PROTEIN BAR"
    are explicitly stripped so the protein gram claim isn't misread as weight.
    """
    # Strip protein-content labels ("21g protein", "20g protein bar") before parsing
    name_clean = re.sub(r"\b\d+\s*g\s+protein\b", "", name, flags=re.I)
    pack = pack_from_field or _pack_from_name(name_clean)

    # Instamart provides explicit weight + unit fields
    if weight_field is not None and weight_unit is not None:
        total_g = float(weight_field)
        if str(weight_unit).lower() == "kg":
            total_g *= 1000
        per_unit = round(total_g / pack) if pack > 1 else round(total_g)
        return per_unit, pack

    # Work on the cleaned name (protein labels stripped)
    n = name_clean

    # "38g x 6" or "6X60GM" style
    m = re.search(r"(\d+)\s*(?:g|gm)\s*x\s*(\d+)", n, re.I)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = re.search(r"(\d+)\s*x\s*(\d+)\s*(?:g|gm)", n, re.I)
    if m:
        return int(m.group(2)), int(m.group(1))

    # "- 6X60G" Zepto style
    m = re.search(r"-\s*(\d+)[xX](\d+)\s*(?:g|gm|gram)\b", n, re.I)
    if m:
        return int(m.group(2)), int(m.group(1))

    # "(360g)" or "360GM" or "400GM"
    m = re.search(r"[\(\s](\d+)\s*(?:g|gm|gram)\b", n + " ", re.I)
    if m:
        total = int(m.group(1))
        per_unit = round(total / pack) if pack > 1 else total
        return per_unit, pack

    # "1 kg" or "1KG"
    m = re.search(r"(\d+(?:\.\d+)?)\s*kg\b", n, re.I)
    if m:
        return round(float(m.group(1)) * 1000), pack

    return None, pack


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def get_or_create_id(db: sqlite3.Connection, table: str, col: str, val) -> int:
    row = db.execute(f"SELECT id FROM {table} WHERE {col} = ?", (val,)).fetchone()
    if row:
        return row["id"]
    db.execute(f"INSERT INTO {table} ({col}) VALUES (?)", (val,))
    return db.execute(f"SELECT id FROM {table} WHERE {col} = ?", (val,)).fetchone()["id"]


class CanonicalMatcher:
    """
    In-memory index for finding / creating canonical products.
    Key: (brand_lower, weight_grams, pack_count)
    Value: list of {id, tokens}

    Matching uses Jaccard similarity on flavor tokens with a threshold of 0.35.
    This is deliberately lenient because platform names vary a lot
    (e.g. "CHOC CHUNK NUTS BAR" vs "Chocolate Chunk & Nuts Protein Bar").
    """

    _MATCH_THRESHOLD = 0.35

    def __init__(self):
        self._index: dict[tuple, list] = {}

    def load_from_db(self, db: sqlite3.Connection):
        rows = db.execute("""
            SELECT cp.id, cp.canonical_name, cp.weight_grams, cp.pack_count,
                   b.name AS brand
            FROM canonical_products cp
            JOIN brands b ON b.id = cp.brand_id
        """).fetchall()
        for r in rows:
            key = (r["brand"].lower(), r["weight_grams"], r["pack_count"])
            self._index.setdefault(key, []).append(
                {"id": r["id"], "tokens": flavor_tokens(r["canonical_name"])}
            )

    def find(self, brand: str, name: str, weight_grams, pack_count: int) -> Optional[int]:
        key = (brand.lower(), weight_grams, pack_count)
        candidates = self._index.get(key, [])
        if not candidates:
            return None
        toks = flavor_tokens(name)
        best = max(candidates, key=lambda c: jaccard(toks, c["tokens"]))
        if jaccard(toks, best["tokens"]) >= self._MATCH_THRESHOLD:
            return best["id"]
        return None

    def register(self, canon_id: int, brand: str, name: str, weight_grams, pack_count: int):
        key = (brand.lower(), weight_grams, pack_count)
        self._index.setdefault(key, []).append(
            {"id": canon_id, "tokens": flavor_tokens(name)}
        )


def get_or_create_canonical(
    db: sqlite3.Connection,
    matcher: CanonicalMatcher,
    brand_id: int,
    brand_name: str,
    display_name: str,
    category: Optional[str],
    weight_grams,
    pack_count: int,
) -> int:
    cname = canonical_name(display_name)
    canon_id = matcher.find(brand_name, display_name, weight_grams, pack_count)
    if canon_id:
        return canon_id
    db.execute(
        """
        INSERT OR IGNORE INTO canonical_products
            (brand_id, canonical_name, category, weight_grams, pack_count)
        VALUES (?, ?, ?, ?, ?)
        """,
        (brand_id, cname, category, weight_grams, pack_count),
    )
    row = db.execute(
        """
        SELECT id FROM canonical_products
        WHERE brand_id=? AND canonical_name=? AND weight_grams IS ? AND pack_count=?
        """,
        (brand_id, cname, weight_grams, pack_count),
    ).fetchone()
    canon_id = row["id"]
    matcher.register(canon_id, brand_name, display_name, weight_grams, pack_count)
    return canon_id


def upsert_listing(
    db: sqlite3.Connection,
    canon_id: int,
    platform: str,
    platform_id: str,
    display_name: str,
    image_url: Optional[str],
) -> int:
    db.execute(
        """
        INSERT INTO platform_listings
            (canonical_product_id, platform, platform_product_id, display_name, image_url)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(platform, platform_product_id) DO UPDATE SET
            display_name = excluded.display_name,
            image_url    = COALESCE(excluded.image_url, platform_listings.image_url)
        """,
        (canon_id, platform, platform_id, display_name, image_url),
    )
    return db.execute(
        "SELECT id FROM platform_listings WHERE platform=? AND platform_product_id=?",
        (platform, platform_id),
    ).fetchone()["id"]


def insert_price(db, listing_id, scraped_at, mrp, selling_price, discount_pct):
    db.execute(
        """
        INSERT OR IGNORE INTO price_snapshots
            (listing_id, scraped_at, mrp, selling_price, discount_pct)
        VALUES (?, ?, ?, ?, ?)
        """,
        (listing_id, scraped_at, mrp, selling_price, discount_pct),
    )


def insert_availability(db, listing_id, pincode_id, scraped_at, in_stock, available_qty=None):
    db.execute(
        """
        INSERT OR IGNORE INTO availability_snapshots
            (listing_id, pincode_id, scraped_at, in_stock, available_qty)
        VALUES (?, ?, ?, ?, ?)
        """,
        (listing_id, pincode_id, scraped_at, int(in_stock), available_qty),
    )


# ---------------------------------------------------------------------------
# Platform-specific parsers
# ---------------------------------------------------------------------------

def ingest_blinkit(db: sqlite3.Connection, data: dict, matcher: CanonicalMatcher):
    brand_name = data["brand"]
    scraped_at = data["scraped_at"]
    brand_id = get_or_create_id(db, "brands", "name", brand_name)

    for p in data["products"]:
        weight_g, pack = extract_weight_pack(p["name"])
        category = (p.get("category") or "").split(">")[-1].strip() or None

        canon_id = get_or_create_canonical(
            db, matcher, brand_id, brand_name,
            p["name"], category, weight_g, pack,
        )
        listing_id = upsert_listing(
            db, canon_id, "blinkit", p["blinkit_id"], p["name"], p.get("image_url"),
        )
        insert_price(
            db, listing_id, scraped_at,
            p["mrp"], p["selling_price"], p.get("discount_percent"),
        )
        for avail in p.get("availability", []):
            pincode_id = get_or_create_id(db, "pincodes", "pincode", avail["pincode"])
            insert_availability(db, listing_id, pincode_id, scraped_at, avail["in_stock"])


def ingest_zepto(db: sqlite3.Connection, data: dict, matcher: CanonicalMatcher):
    brand_name = "Yogabar"
    scraped_at = data["fetched_on"] + "T00:00:00Z"
    brand_id = get_or_create_id(db, "brands", "name", brand_name)

    for p in data["items"]:
        weight_g, pack = extract_weight_pack(p["title"])
        category = (p.get("category_path") or [""])[-1] or None

        canon_id = get_or_create_canonical(
            db, matcher, brand_id, brand_name,
            p["title"], category, weight_g, pack,
        )
        listing_id = upsert_listing(
            db, canon_id, "zepto", p["sku_code"], p["title"], p.get("image"),
        )
        mrp = p["price"]["mrp"]
        final = p["price"]["final"]
        disc = round((mrp - final) / mrp * 100, 1) if mrp > 0 else None
        insert_price(db, listing_id, scraped_at, mrp, final, disc)

        for pincode, status in (p.get("stock_by_pincode") or {}).items():
            pincode_id = get_or_create_id(db, "pincodes", "pincode", pincode)
            insert_availability(
                db, listing_id, pincode_id, scraped_at, status == "available",
            )


def ingest_instamart(db: sqlite3.Connection, data: dict, matcher: CanonicalMatcher):
    brand_name = "Yogabar"
    ts = int(data["snapshot_time"])
    scraped_at = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    brand_id = get_or_create_id(db, "brands", "name", brand_name)

    for p in data["results"]:
        pack = _pack_from_name(p["display_name"])
        weight_g, pack = extract_weight_pack(
            p["display_name"],
            weight_field=p.get("weight"),
            weight_unit=p.get("weight_unit"),
            pack_from_field=pack,
        )
        canon_id = get_or_create_canonical(
            db, matcher, brand_id, brand_name,
            p["display_name"], None, weight_g, pack,
        )
        listing_id = upsert_listing(
            db, canon_id, "instamart", p["product_id"], p["display_name"], p.get("image"),
        )
        mrp = p["store_mrp"]
        selling = p["store_selling_price"]
        disc = round((mrp - selling) / mrp * 100, 1) if mrp > 0 else None
        insert_price(db, listing_id, scraped_at, mrp, selling, disc)

        for avail in p.get("store_availability", []):
            pincode_id = get_or_create_id(db, "pincodes", "pincode", avail["pin"])
            qty = avail.get("available_qty")
            in_stock = qty is None or qty > 0
            insert_availability(db, listing_id, pincode_id, scraped_at, in_stock, qty)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="RevQ ingestion script")
    parser.add_argument(
        "--db", default=None,
        help="SQLite DB path (default: ../revq.db relative to this script)",
    )
    parser.add_argument(
        "--data", default=None,
        help="Directory containing sample JSON files (default: ../data relative to this script)",
    )
    args = parser.parse_args()

    script_dir = Path(__file__).parent
    db_path   = Path(args.db)   if args.db   else script_dir.parent / "revq.db"
    data_dir  = Path(args.data) if args.data else script_dir.parent / "data"

    db = sqlite3.connect(str(db_path))
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    db.execute("PRAGMA journal_mode = WAL")
    db.executescript(SCHEMA)

    matcher = CanonicalMatcher()
    matcher.load_from_db(db)

    files = [
        ("blinkit_sample.json",  ingest_blinkit),
        ("zepto_sample.json",    ingest_zepto),
        ("instamart_sample.json", ingest_instamart),
    ]

    for filename, fn in files:
        filepath = data_dir / filename
        if not filepath.exists():
            print(f"[WARN] {filepath} not found — skipping")
            continue
        print(f"Ingesting {filepath.name} ...")
        with open(filepath) as f:
            raw = json.load(f)
        with db:
            fn(db, raw, matcher)
        print(f"  done")

    # Summary
    stats = {
        "brands":                 db.execute("SELECT COUNT(*) FROM brands").fetchone()[0],
        "canonical_products":     db.execute("SELECT COUNT(*) FROM canonical_products").fetchone()[0],
        "platform_listings":      db.execute("SELECT COUNT(*) FROM platform_listings").fetchone()[0],
        "price_snapshots":        db.execute("SELECT COUNT(*) FROM price_snapshots").fetchone()[0],
        "availability_snapshots": db.execute("SELECT COUNT(*) FROM availability_snapshots").fetchone()[0],
    }
    print(f"\nDB written to: {db_path}")
    for k, v in stats.items():
        print(f"  {k:<28} {v}")
    db.close()


if __name__ == "__main__":
    main()

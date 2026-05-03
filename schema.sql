-- ============================================================
-- RevQ Schema
-- Supports: cross-platform product identity, time-series
--           price history, and per-pincode availability.
-- ============================================================

-- -------------------------------------------------------
-- 1. brands
-- -------------------------------------------------------
CREATE TABLE IF NOT EXISTS brands (
    id   INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT    NOT NULL UNIQUE
);

-- -------------------------------------------------------
-- 2. canonical_products
--    One row per real-world SKU (platform-agnostic).
--    A "product" is identified by brand + name + weight
--    per unit + pack count.  Two listings that describe
--    the same physical item resolve to ONE row here.
-- -------------------------------------------------------
CREATE TABLE IF NOT EXISTS canonical_products (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    brand_id       INTEGER NOT NULL REFERENCES brands(id),
    canonical_name TEXT    NOT NULL,        -- clean display name
    category       TEXT,
    weight_grams   INTEGER,                 -- per-unit weight in grams; NULL = unknown
    pack_count     INTEGER NOT NULL DEFAULT 1,
    created_at     TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE(brand_id, canonical_name, weight_grams, pack_count)
);

-- -------------------------------------------------------
-- 3. platform_listings
--    One row per platform SKU.  Many listings can point
--    to the same canonical_product (cross-platform match).
-- -------------------------------------------------------
CREATE TABLE IF NOT EXISTS platform_listings (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    canonical_product_id INTEGER NOT NULL REFERENCES canonical_products(id),
    platform             TEXT    NOT NULL CHECK(platform IN ('blinkit','zepto','instamart')),
    platform_product_id  TEXT    NOT NULL,  -- native ID (blinkit_id / sku_code / UUID)
    display_name         TEXT    NOT NULL,  -- raw name as scraped
    image_url            TEXT,
    created_at           TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE(platform, platform_product_id)
);

-- -------------------------------------------------------
-- 4. price_snapshots
--    Append-only time-series.  One row per (listing, scrape).
--    Supports Query 1 (latest price) and Query 2 (history).
-- -------------------------------------------------------
CREATE TABLE IF NOT EXISTS price_snapshots (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    listing_id    INTEGER NOT NULL REFERENCES platform_listings(id),
    scraped_at    TEXT    NOT NULL,
    mrp           INTEGER NOT NULL,
    selling_price INTEGER NOT NULL,
    discount_pct  REAL,
    UNIQUE(listing_id, scraped_at)
);

-- -------------------------------------------------------
-- 5. pincodes
--    Normalised pincode dictionary to avoid storing the
--    same string millions of times in availability rows.
-- -------------------------------------------------------
CREATE TABLE IF NOT EXISTS pincodes (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    pincode TEXT    NOT NULL UNIQUE
);

-- -------------------------------------------------------
-- 6. availability_snapshots
--    Append-only time-series.  One row per (listing, pincode, scrape).
--    Supports Query 3 (out-of-stock pincodes).
--    available_qty is NULL for platforms that only report
--    in-stock / out-of-stock (Blinkit, Zepto).
-- -------------------------------------------------------
CREATE TABLE IF NOT EXISTS availability_snapshots (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    listing_id    INTEGER NOT NULL REFERENCES platform_listings(id),
    pincode_id    INTEGER NOT NULL REFERENCES pincodes(id),
    scraped_at    TEXT    NOT NULL,
    in_stock      INTEGER NOT NULL CHECK(in_stock IN (0,1)),
    available_qty INTEGER,
    UNIQUE(listing_id, pincode_id, scraped_at)
);


-- ============================================================
-- Indexes
-- ============================================================

-- Query 1 & 2: price history lookups by listing + time
CREATE INDEX IF NOT EXISTS idx_price_listing_time
    ON price_snapshots(listing_id, scraped_at DESC);

-- Query 3: availability lookups by listing + time + stock flag
CREATE INDEX IF NOT EXISTS idx_avail_listing_time
    ON availability_snapshots(listing_id, scraped_at DESC, in_stock);

-- Cross-platform lookup: all listings for a canonical product
CREATE INDEX IF NOT EXISTS idx_listing_canonical
    ON platform_listings(canonical_product_id);

-- Out-of-stock scan across all pincodes at a given time
CREATE INDEX IF NOT EXISTS idx_avail_time_stock
    ON availability_snapshots(scraped_at, in_stock);


-- ============================================================
-- Reference Queries (not executed at schema creation time)
-- ============================================================

-- Query 1: Current price of Product X on all 3 platforms
-- SELECT pl.platform, ps.mrp, ps.selling_price, ps.discount_pct, ps.scraped_at
-- FROM platform_listings pl
-- JOIN price_snapshots ps ON ps.listing_id = pl.id
-- WHERE pl.canonical_product_id = :id
--   AND ps.scraped_at = (
--       SELECT MAX(scraped_at) FROM price_snapshots WHERE listing_id = pl.id
--   );

-- Query 2: 30-day price history of Product X on Blinkit
-- SELECT ps.scraped_at, ps.mrp, ps.selling_price, ps.discount_pct
-- FROM platform_listings pl
-- JOIN price_snapshots ps ON ps.listing_id = pl.id
-- WHERE pl.canonical_product_id = :id
--   AND pl.platform = 'blinkit'
--   AND ps.scraped_at >= datetime('now', '-30 days')
-- ORDER BY ps.scraped_at ASC;

-- Query 3: Pincodes where Product X is out of stock, per platform
-- SELECT pl.platform, pc.pincode
-- FROM platform_listings pl
-- JOIN availability_snapshots a ON a.listing_id = pl.id
-- JOIN pincodes pc ON pc.id = a.pincode_id
-- WHERE pl.canonical_product_id = :id
--   AND a.in_stock = 0
--   AND a.scraped_at = (
--       SELECT MAX(scraped_at) FROM availability_snapshots WHERE listing_id = pl.id
--   )
-- ORDER BY pl.platform, pc.pincode;

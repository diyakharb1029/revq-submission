# Schema Design Notes

## 1. Cross-platform product identity

The model uses a **hub-and-spoke** design:

- `canonical_products` is the hub — one row per real-world SKU, platform-agnostic.
- `platform_listings` are the spokes — one row per platform SKU, each foreign-keyed to a canonical product.

A canonical product is identified by `(brand, canonical_name, weight_grams, pack_count)`. When the ingestion script sees a new platform listing, it extracts the per-unit weight in grams and the pack count from the raw name, then uses Jaccard similarity over a bag of "flavor tokens" (meaningful words after stripping brand, category, size, and stop words) to find the closest existing canonical. If the best match scores ≥ 0.35 it links to that canonical; otherwise it creates a new one.

**What this approach breaks on:**

- **Ambiguous flavors at the same weight/MRP.** Blinkit lists "Almond Crunch Muesli 400g" and Instamart lists "Almond + Cashew Crunch Muesli 400g". Both have MRP 399 and similar tokens. The matcher treats them as the same canonical — which may be wrong if they are genuinely separate SKUs. Without a manufacturer barcode (EAN/GTIN) in the scrape data there is no reliable way to disambiguate them.
- **Name drift over time.** If a platform renames a product (e.g. "21g Protein Bar" → "20g Protein Bar"), a new canonical is created rather than updating the existing one, unless the flavour tokens still match.
- **Pack-count embedded in product title only.** If a platform omits pack info in the title and provides it only in a structured field we don't scrape, the weight normalisation will be wrong and the match will fail.

---

## 2. Denormalization / index for scale

**Index added:** `idx_price_listing_time` on `price_snapshots(listing_id, scraped_at DESC)`.

The 30-day price history query (Query 2) is the hottest read: it filters by `listing_id` then scans backward by time. Without this index the query degrades to a full table scan of `price_snapshots`, which at production scrape frequency (hourly × 100+ brands × 3 platforms × ~20 products) grows to tens of millions of rows quickly. The composite index makes the query an index range scan bounded by `listing_id`.

**One denormalization worth considering at scale:** pre-materialise the "latest price per listing" into a `current_prices` table (updated by the ingest pipeline on every write). Query 1 (current prices across platforms) runs on every product page load; re-computing the MAX subquery each time is cheap at small scale but becomes a bottleneck with many concurrent users. A maintained `current_prices` table turns that query into a simple primary-key lookup.

---

## 3. What changes at 100× scrape volume

Current bottleneck is SQLite's single-writer model. At 100× volume:

- **Switch to PostgreSQL** (or CockroachDB for multi-region). The schema is portable — all queries are standard SQL with no SQLite-specific syntax.
- **Partition `price_snapshots` and `availability_snapshots` by month.** Both tables are append-only time-series; range partitioning keeps old data accessible for analytics without slowing down the hot partition covering the last 30 days.
- **Separate the write path from the read path.** Ingest workers write to a hot write replica; the product API reads from a read replica. The current schema supports this without changes since all writes are inserts (no updates to historical rows).
- **Compress old availability data.** At 100× volume the availability table grows fastest (products × pincodes × scrape interval). For rows older than 30 days, aggregate to daily snapshots (e.g. "out of stock for N hours on date D") rather than keeping every hourly snapshot.

import initSqlJs from 'sql.js';
import { readFileSync } from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

let db;
async function getDb() {
  if (db) return db;
  const SQL = await initSqlJs();
  const dbPath = path.join(process.cwd(), 'revq.db');
  db = new SQL.Database(readFileSync(dbPath));
  return db;
}

function query(db, sql, params = []) {
  const stmt = db.prepare(sql);
  stmt.bind(params);
  const rows = [];
  while (stmt.step()) rows.push(stmt.getAsObject());
  stmt.free();
  return rows;
}

function queryOne(db, sql, params = []) {
  const rows = query(db, sql, params);
  return rows.length ? rows[0] : null;
}

export default async function handler(req, res) {
  const id = parseInt(req.query.id, 10);
  if (Number.isNaN(id)) return res.status(400).json({ error: 'Invalid product ID' });

  try {
    const db = await getDb();

    const product = queryOne(db, `
      SELECT cp.id, cp.canonical_name, cp.category, cp.weight_grams, cp.pack_count,
             b.name AS brand
      FROM canonical_products cp
      JOIN brands b ON b.id = cp.brand_id
      WHERE cp.id = ?
    `, [id]);

    if (!product) return res.status(404).json({ error: 'Product not found' });

    const listings = query(db, `
      SELECT
        pl.id    AS listing_id,
        pl.platform,
        pl.display_name,
        pl.image_url,
        ps.mrp,
        ps.selling_price,
        ps.discount_pct,
        ps.scraped_at
      FROM platform_listings pl
      JOIN price_snapshots ps ON ps.listing_id = pl.id
      WHERE pl.canonical_product_id = ?
        AND ps.scraped_at = (
          SELECT MAX(scraped_at) FROM price_snapshots WHERE listing_id = pl.id
        )
      ORDER BY pl.platform
    `, [id]);

    const availRows = query(db, `
      SELECT
        pl.id AS listing_id,
        SUM(CASE WHEN a.in_stock = 1 THEN 1 ELSE 0 END) AS in_stock_count,
        COUNT(*) AS total_pincodes,
        GROUP_CONCAT(CASE WHEN a.in_stock = 0 THEN p.pincode ELSE NULL END) AS oos_pincodes
      FROM platform_listings pl
      JOIN availability_snapshots a ON a.listing_id = pl.id
      JOIN pincodes p ON p.id = a.pincode_id
      WHERE pl.canonical_product_id = ?
        AND a.scraped_at = (
          SELECT MAX(scraped_at) FROM availability_snapshots WHERE listing_id = pl.id
        )
      GROUP BY pl.id
    `, [id]);

    const availByListing = Object.fromEntries(
      availRows.map(r => [r.listing_id, {
        in_stock_count: r.in_stock_count,
        total_pincodes: r.total_pincodes,
        oos_pincodes: r.oos_pincodes ? r.oos_pincodes.split(',').sort() : [],
      }])
    );

    const platforms = listings.map(l => ({
      platform:      l.platform,
      display_name:  l.display_name,
      image_url:     l.image_url,
      mrp:           l.mrp,
      selling_price: l.selling_price,
      discount_pct:  l.discount_pct,
      scraped_at:    l.scraped_at,
      availability:  availByListing[l.listing_id] ?? null,
    }));

    res.json({ product, platforms });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
}

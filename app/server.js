import express from 'express';
import initSqlJs from 'sql.js';
import { readFileSync, existsSync } from 'fs';
import { fileURLToPath } from 'url';
import path from 'path';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PORT = process.env.PORT || 3001;
const DB_PATH = process.env.DB_PATH || path.join(__dirname, '..', 'revq.db');

if (!existsSync(DB_PATH)) {
  console.error(`\nSQLite database not found at: ${DB_PATH}`);
  console.error('Run the ingestion step first:\n');
  console.error('  cd ingest && python3 ingest.py\n');
  process.exit(1);
}

// sql.js loads the entire DB file into memory (fine for this scale).
const SQL = await initSqlJs();
const db  = new SQL.Database(readFileSync(DB_PATH));

// Helper: run a SELECT and return an array of plain objects.
function query(sql, params = []) {
  const stmt = db.prepare(sql);
  stmt.bind(params);
  const rows = [];
  while (stmt.step()) rows.push(stmt.getAsObject());
  stmt.free();
  return rows;
}

// Helper: return a single row or null.
function queryOne(sql, params = []) {
  const rows = query(sql, params);
  return rows.length ? rows[0] : null;
}

const app = express();
app.use(express.json());

// ---------------------------------------------------------------------------
// GET /api/products
// ---------------------------------------------------------------------------
app.get('/api/products', (_req, res) => {
  try {
    const rows = query(`
      SELECT
        cp.id,
        cp.canonical_name,
        cp.category,
        cp.weight_grams,
        cp.pack_count,
        b.name  AS brand,
        GROUP_CONCAT(DISTINCT pl.platform) AS platforms,
        MAX(pl.image_url) AS image_url
      FROM canonical_products cp
      JOIN brands b ON b.id = cp.brand_id
      LEFT JOIN platform_listings pl ON pl.canonical_product_id = cp.id
      GROUP BY cp.id
      ORDER BY cp.category, cp.canonical_name, cp.weight_grams, cp.pack_count
    `);

    res.json(rows.map(r => ({
      ...r,
      platforms: r.platforms ? r.platforms.split(',') : [],
    })));
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// ---------------------------------------------------------------------------
// GET /api/products/:id
// ---------------------------------------------------------------------------
app.get('/api/products/:id', (req, res) => {
  const id = parseInt(req.params.id, 10);
  if (Number.isNaN(id)) return res.status(400).json({ error: 'Invalid product ID' });

  try {
    // 1. Canonical product
    const product = queryOne(`
      SELECT cp.id, cp.canonical_name, cp.category, cp.weight_grams, cp.pack_count,
             b.name AS brand
      FROM canonical_products cp
      JOIN brands b ON b.id = cp.brand_id
      WHERE cp.id = ?
    `, [id]);

    if (!product) return res.status(404).json({ error: 'Product not found' });

    // 2. Latest price + listing info per platform
    const listings = query(`
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

    // 3. Availability summary per listing
    const availRows = query(`
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
        oos_pincodes:   r.oos_pincodes ? r.oos_pincodes.split(',').sort() : [],
      }])
    );

    // 4. Merge
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
});

// Serve built React app in production
const distPath = path.join(__dirname, 'dist');
if (existsSync(distPath)) {
  app.use(express.static(distPath));
  app.get('*', (_req, res) => res.sendFile(path.join(distPath, 'index.html')));
}

app.listen(PORT, () => {
  console.log(`RevQ API running → http://localhost:${PORT}/api/products`);
});

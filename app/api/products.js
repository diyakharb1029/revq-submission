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

export default async function handler(req, res) {
  try {
    const db = await getDb();
    const rows = query(db, `
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
}

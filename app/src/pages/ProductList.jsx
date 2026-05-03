import { Link } from 'react-router-dom';
import useFetch from '../hooks/useFetch';

function weightLabel(weight_grams, pack_count) {
  if (!weight_grams) return null;
  if (pack_count > 1) return `${weight_grams}g × ${pack_count}`;
  const kg = weight_grams >= 1000;
  return kg ? `${weight_grams / 1000}kg` : `${weight_grams}g`;
}

export default function ProductList() {
  const { data, loading, error } = useFetch('/api/products');

  if (loading) {
    return (
      <div className="status-box">
        <div className="spinner" />
        Loading products…
      </div>
    );
  }

  if (error) {
    return (
      <div className="status-box error">
        Failed to load products: {error}
      </div>
    );
  }

  if (!data || data.length === 0) {
    return (
      <div className="status-box">
        No products found. Run the ingestion step first.
      </div>
    );
  }

  // Group by category for display
  const grouped = data.reduce((acc, p) => {
    const cat = p.category ?? 'Other';
    (acc[cat] ??= []).push(p);
    return acc;
  }, {});

  return (
    <>
      <h1 className="page-title">Yogabar — {data.length} products tracked</h1>
      {Object.entries(grouped).map(([cat, products]) => (
        <section key={cat} style={{ marginBottom: '2rem' }}>
          <h2 style={{ fontSize: '0.75rem', fontWeight: 700, textTransform: 'uppercase',
                        letterSpacing: 1, color: '#888', marginBottom: '0.75rem' }}>
            {cat}
          </h2>
          <div className="product-grid">
            {products.map(p => (
              <Link key={p.id} to={`/product/${p.id}`} className="product-card">
                <div className="product-card-name">{p.canonical_name}</div>
                <div className="product-card-meta">
                  {p.brand} · {weightLabel(p.weight_grams, p.pack_count) ?? 'unknown size'}
                </div>
                <div className="platform-badges">
                  {(p.platforms ?? []).map(pl => (
                    <span key={pl} className={`platform-badge badge-${pl}`}>{pl}</span>
                  ))}
                  {(!p.platforms || p.platforms.length === 0) && (
                    <span style={{ fontSize: '0.75rem', color: '#aaa' }}>No listings</span>
                  )}
                </div>
              </Link>
            ))}
          </div>
        </section>
      ))}
    </>
  );
}

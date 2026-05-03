import { useParams, Link } from 'react-router-dom';
import useFetch            from '../hooks/useFetch';
import PriceTable          from '../components/PriceTable';
import AvailabilitySection from '../components/AvailabilitySection';

function weightLabel(weight_grams, pack_count) {
  if (!weight_grams) return null;
  if (pack_count > 1) {
    const kg = weight_grams >= 1000;
    const per = kg ? `${weight_grams / 1000}kg` : `${weight_grams}g`;
    return `${per} × ${pack_count} (${weight_grams * pack_count}g total)`;
  }
  return weight_grams >= 1000 ? `${weight_grams / 1000}kg` : `${weight_grams}g`;
}

// Pick the best available image from platform listings
function bestImage(platforms) {
  if (!platforms) return null;
  for (const p of platforms) {
    if (p.image_url) return p.image_url;
  }
  return null;
}

export default function ProductDetail() {
  const { id } = useParams();
  const { data, loading, error } = useFetch(`/api/products/${id}`);

  if (loading) {
    return (
      <>
        <Link to="/" className="back-link">← All products</Link>
        <div className="status-box">
          <div className="spinner" />
          Loading product…
        </div>
      </>
    );
  }

  if (error) {
    return (
      <>
        <Link to="/" className="back-link">← All products</Link>
        <div className="status-box error">
          {error === 'HTTP 404'
            ? 'Product not found.'
            : `Error loading product: ${error}`}
        </div>
      </>
    );
  }

  if (!data) {
    return (
      <>
        <Link to="/" className="back-link">← All products</Link>
        <div className="status-box">No data returned.</div>
      </>
    );
  }

  const { product, platforms } = data;
  const imageUrl = bestImage(platforms);

  return (
    <>
      <Link to="/" className="back-link">← All products</Link>

      <div className="product-detail">

        {/* ── Header ─────────────────────────────────────────── */}
        <div className="product-header">
          {imageUrl
            ? <img className="product-image" src={imageUrl} alt={product.canonical_name}
                   onError={e => { e.target.style.display = 'none'; }} />
            : <div className="product-image-placeholder">🛒</div>
          }
          <div className="product-header-text">
            <div className="product-brand">{product.brand}</div>
            <h1>{product.canonical_name}</h1>
            <div className="product-meta">
              {product.category && <span>{product.category} · </span>}
              {weightLabel(product.weight_grams, product.pack_count) ?? 'Size unknown'}
              {' · '}
              {platforms.length === 0
                ? 'No platform listings'
                : `${platforms.length} platform listing${platforms.length > 1 ? 's' : ''}`}
            </div>
          </div>
        </div>

        {/* ── Price table ─────────────────────────────────────── */}
        <PriceTable platforms={platforms} />

        {/* ── Availability ────────────────────────────────────── */}
        <AvailabilitySection platforms={platforms} />

      </div>
    </>
  );
}

/**
 * PriceTable
 *
 * Props:
 *   platforms — array from /api/products/:id  (may be empty)
 *
 * Each row = one platform listing.
 * Columns: Platform | Selling Price | MRP | Discount % | Last scraped
 */

const PLATFORM_LABELS = {
  blinkit:   'Blinkit',
  zepto:     'Zepto',
  instamart: 'Instamart',
};

function fmtDate(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  return d.toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' });
}

export default function PriceTable({ platforms }) {
  if (!platforms || platforms.length === 0) {
    return (
      <section className="section">
        <p className="section-title">Price Comparison</p>
        <p style={{ color: '#aaa', fontSize: '0.9rem' }}>No pricing data available.</p>
      </section>
    );
  }

  return (
    <section className="section">
      <p className="section-title">Price Comparison</p>
      <table className="price-table">
        <thead>
          <tr>
            <th>Platform</th>
            <th>Price</th>
            <th>MRP</th>
            <th>Discount</th>
            <th>Last scraped</th>
          </tr>
        </thead>
        <tbody>
          {platforms.map(p => (
            <tr key={p.platform}>
              <td>
                <div className="platform-name">
                  <span className={`platform-dot dot-${p.platform}`} />
                  {PLATFORM_LABELS[p.platform] ?? p.platform}
                </div>
              </td>
              <td className="price-cell">₹{p.selling_price}</td>
              <td className="mrp-cell">₹{p.mrp}</td>
              <td className="discount-cell">
                {p.discount_pct != null ? `${p.discount_pct}% off` : '—'}
              </td>
              <td>
                <span className="scrape-time">{fmtDate(p.scraped_at)}</span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

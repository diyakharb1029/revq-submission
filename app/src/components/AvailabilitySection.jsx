/**
 * AvailabilitySection
 *
 * Props:
 *   platforms — array from /api/products/:id  (may be empty)
 *
 * Shows per-platform: "Live in X of Y pincodes", a fill bar, OOS pincode list.
 */

const PLATFORM_LABELS = {
  blinkit:   'Blinkit',
  zepto:     'Zepto',
  instamart: 'Instamart',
};

function barClass(inStock, total) {
  if (!total) return 'none';
  const ratio = inStock / total;
  if (ratio === 1) return 'full';
  if (ratio === 0) return 'none';
  return 'partial';
}

export default function AvailabilitySection({ platforms }) {
  // Only show platforms that have availability data
  const rows = (platforms ?? []).filter(p => p.availability != null);

  if (rows.length === 0) {
    return (
      <section className="section">
        <p className="section-title">Availability</p>
        <p style={{ color: '#aaa', fontSize: '0.9rem' }}>No availability data.</p>
      </section>
    );
  }

  return (
    <section className="section">
      <p className="section-title">Availability</p>
      <div className="avail-list">
        {rows.map(p => {
          const { in_stock_count, total_pincodes, oos_pincodes } = p.availability;
          const pct = total_pincodes > 0 ? (in_stock_count / total_pincodes) * 100 : 0;

          return (
            <div key={p.platform} className="avail-row">
              <div className="avail-header">
                <div className="avail-platform">
                  <span className={`platform-dot dot-${p.platform}`} />
                  {PLATFORM_LABELS[p.platform] ?? p.platform}
                </div>
                <span className="avail-count">
                  {in_stock_count === total_pincodes
                    ? <span style={{ color: '#16a34a', fontWeight: 600 }}>
                        Live in all {total_pincodes} pincodes
                      </span>
                    : in_stock_count === 0
                    ? <span style={{ color: '#e74c3c', fontWeight: 600 }}>
                        Out of stock everywhere
                      </span>
                    : <span>
                        Live in <strong>{in_stock_count}</strong> of {total_pincodes} pincodes
                      </span>
                  }
                </span>
              </div>

              <div className="avail-bar-wrap">
                <div
                  className={`avail-bar ${barClass(in_stock_count, total_pincodes)}`}
                  style={{ width: `${pct}%` }}
                />
              </div>

              {oos_pincodes.length > 0 && (
                <p className="oos-pincodes">
                  <span className="oos-label">Out of stock: </span>
                  {oos_pincodes.join(', ')}
                </p>
              )}
            </div>
          );
        })}
      </div>
    </section>
  );
}

function BagIcon() {
  return (
    <svg width="34" height="34" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M6 2L3 6v14a2 2 0 002 2h14a2 2 0 002-2V6l-3-4z" />
      <line x1="3" y1="6" x2="21" y2="6" />
      <path d="M16 10a4 4 0 01-8 0" />
    </svg>
  );
}

function normaliseSizes(buyerSizes) {
  if (!buyerSizes) return [];
  const raw = Array.isArray(buyerSizes) ? buyerSizes : Object.values(buyerSizes);
  return raw
    .filter(v => typeof v === 'string' && v.length > 0)
    .map(v => v.trim().toUpperCase());
}

function priceLabel(price) {
  if (!price) return '';
  const amount = typeof price === 'object' ? price.amount : price;
  if (amount === undefined || amount === null || amount === '') return '';
  return `₹${amount}`;
}

export default function ProductShelf({ products, buyerSizes, onProductClick }) {
  const list = products || [];
  const preferred = new Set(normaliseSizes(buyerSizes));

  return (
    <aside className="shelf-panel" aria-label="Currently showing products">
      <div className="shelf-header">
        <span>Currently Showing</span>
        {list.length > 0 && <span className="shelf-count-badge">{list.length}</span>}
      </div>

      {list.length === 0 ? (
        <div className="shelf-empty">
          <BagIcon />
          <div>Products you explore will appear here</div>
        </div>
      ) : (
        list.map((p, i) => {
          const handleClick = () => onProductClick && onProductClick(p);
          const onKey = (e) => {
            if (e.key === 'Enter' || e.key === ' ') {
              e.preventDefault();
              handleClick();
            }
          };
          return (
            <div
              key={p.id || i}
              className="shelf-card"
              role="button"
              tabIndex={0}
              onClick={handleClick}
              onKeyDown={onKey}
            >
              <div className="shelf-card-image">
                {p.image_url && <img src={p.image_url} alt={p.title} />}
              </div>
              <div className="shelf-card-body">
                <div className="shelf-card-title">{p.title}</div>
                {priceLabel(p.price) && (
                  <div className="shelf-card-price">{priceLabel(p.price)}</div>
                )}
                {p.variants && p.variants.length > 0 && (
                  <div className="shelf-card-variants">
                    {p.variants.map((v, j) => {
                      const title = (v.title || v.id || '').toString();
                      const isPreferred = preferred.has(title.trim().toUpperCase());
                      const soldOut = v.available === false;
                      const cls = [
                        'variant-chip',
                        soldOut ? 'sold-out' : '',
                        isPreferred && !soldOut ? 'preferred-size' : '',
                      ].filter(Boolean).join(' ');
                      return (
                        <span key={v.id || j} className={cls}>
                          {title}
                        </span>
                      );
                    })}
                  </div>
                )}
              </div>
            </div>
          );
        })
      )}
    </aside>
  );
}

export default function CartDrawer({ cart, open, onClose }) {
  if (!open) return null;

  const lines = cart?.lines || [];
  const hasItems = lines.length > 0;

  return (
    <>
      <div className="cart-overlay" onClick={onClose} />
      <div className="cart-drawer">
        <div className="cart-handle" />
        <div className="cart-header">
          <div>
            <span className="cart-header-title">Your cart</span>
            {hasItems && (
              <span className="cart-header-count">
                {' '}&middot; {cart.total_quantity || lines.length} item{(cart.total_quantity || lines.length) > 1 ? 's' : ''}
              </span>
            )}
          </div>
          <button className="cart-close" onClick={onClose}>&times;</button>
        </div>

        {hasItems ? (
          <>
            <div className="cart-items">
              {lines.map((line, i) => (
                <div className="cart-line" key={line.line_id || i}>
                  <div className="cart-line-thumb" />
                  <div className="cart-line-info">
                    <b>{line.title}</b>
                    <div className="cart-line-detail">
                      &times;{line.quantity}
                    </div>
                  </div>
                  <div className="cart-line-price">&#8377;{line.line_price || line.unit_price}</div>
                </div>
              ))}
            </div>
            <div className="cart-footer">
              <div className="cart-subtotal">
                <span className="cart-subtotal-label">Subtotal</span>
                <span className="cart-subtotal-value">&#8377;{cart.subtotal}</span>
              </div>
              {cart.checkout_url && (
                <a
                  className="cart-checkout-btn"
                  href={cart.checkout_url}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  Checkout on Shopify &#8599;
                </a>
              )}
              <div className="cart-trust">Secure checkout hosted by Shopify</div>
            </div>
          </>
        ) : (
          <div className="cart-empty">
            <div className="cart-empty-icon" />
            <div className="cart-empty-title">Cart's empty</div>
            <div className="cart-empty-text">
              Ask me to add something — I'll confirm before anything lands here.
            </div>
          </div>
        )}
      </div>
    </>
  );
}

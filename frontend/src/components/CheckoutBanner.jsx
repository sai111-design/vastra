export default function CheckoutBanner({ cart }) {
  if (!cart || !cart.checkout_url || !cart.total_quantity) return null;

  return (
    <div className="checkout-banner">
      <div className="checkout-banner-content">
        <div className="checkout-banner-title">Ready to check out</div>
        <div className="checkout-banner-subtitle">
          {cart.total_quantity} item{cart.total_quantity > 1 ? 's' : ''} &middot; Subtotal &#8377;{cart.subtotal}
        </div>
        <div className="checkout-banner-trust">
          You'll finish payment securely on Shopify
        </div>
      </div>
      <a
        className="checkout-banner-cta"
        href={cart.checkout_url}
        target="_blank"
        rel="noopener noreferrer"
      >
        Checkout &#8599;
      </a>
    </div>
  );
}

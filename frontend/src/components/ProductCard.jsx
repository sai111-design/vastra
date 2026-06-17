export default function ProductCard({ product }) {
  const price = product.price;
  const priceStr = price
    ? `₹${price.amount || price}`
    : '';

  const handleClick = () => {
    if (product.url) window.open(product.url, '_blank', 'noopener,noreferrer');
  };

  return (
    <div className="product-card" onClick={handleClick} role="button" tabIndex={0}>
      <div className="product-card-image">
        {product.image_url ? (
          <img src={product.image_url} alt={product.title} />
        ) : (
          <span className="product-card-image-placeholder">img</span>
        )}
      </div>
      <div className="product-card-title">{product.title}</div>
      {priceStr && <div className="product-card-price">{priceStr}</div>}
      {product.variants && product.variants.length > 0 && (
        <div className="product-card-variants">
          {product.variants.map((v, i) => (
            <span
              key={v.id || i}
              className={`variant-chip${v.available === false ? ' sold-out' : ''}`}
            >
              {v.title || v.id}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

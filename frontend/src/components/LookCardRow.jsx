import ProductCard from './ProductCard';

export default function LookCardRow({ products, intro }) {
  if (!products || products.length === 0) return null;

  return (
    <div className="look-section">
      <div className="look-header">✨ Complete the Look</div>
      {intro && <div className="look-intro">{intro}</div>}
      <div className="look-card-row">
        {products.map((p, i) => (
          <ProductCard key={p.id || i} product={p} />
        ))}
      </div>
    </div>
  );
}

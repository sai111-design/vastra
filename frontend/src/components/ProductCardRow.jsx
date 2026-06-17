import ProductCard from './ProductCard';

export default function ProductCardRow({ products }) {
  if (!products || products.length === 0) return null;

  return (
    <div className="product-card-row">
      {products.map((p, i) => (
        <ProductCard key={p.id || i} product={p} />
      ))}
    </div>
  );
}

import { useState } from 'react';

export default function ConfirmChip({ request, resolved, onConfirm }) {
  const [loading, setLoading] = useState(false);

  if (!request) return null;

  if (resolved) {
    const ok = resolved === 'confirmed';
    return (
      <div className={`confirm-resolved${ok ? '' : ' confirm-resolved-cancelled'}`}>
        <span className="confirm-resolved-icon">{ok ? '✓' : '✗'}</span>
        <div className="confirm-resolved-text">
          {ok
            ? <><b>{request.line?.title || 'Item'}</b> added to cart</>
            : 'Cart unchanged'}
        </div>
      </div>
    );
  }

  const handle = async (approved) => {
    if (loading) return;
    setLoading(true);
    try { await onConfirm(approved); } finally { setLoading(false); }
  };

  return (
    <div className="confirm-chip">
      <div className="confirm-chip-label">Confirm cart change</div>
      <div className="confirm-chip-body">
        <div className="confirm-chip-thumb" />
        <div className="confirm-chip-text">
          {request.summary || `Add ${request.line?.title || 'item'} to cart?`}
        </div>
      </div>
      <div className="confirm-chip-actions">
        <button className="confirm-btn" onClick={() => handle(true)} disabled={loading}>
          {loading ? <span className="btn-spinner" /> : '✓ Confirm'}
        </button>
        <button className="cancel-btn" onClick={() => handle(false)} disabled={loading}>
          Cancel
        </button>
      </div>
    </div>
  );
}

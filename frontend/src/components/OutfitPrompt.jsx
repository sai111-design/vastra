export default function OutfitPrompt({ visible, onAccept, onDismiss }) {
  if (!visible) return null;

  return (
    <div className="outfit-prompt-banner" role="status">
      <span className="outfit-prompt-icon" aria-hidden="true">✨</span>
      <span className="outfit-prompt-text">
        Want me to find pieces that go with it?
      </span>
      <button
        type="button"
        className="outfit-prompt-accept"
        onClick={onAccept}
      >
        Complete the Look
      </button>
      <button
        type="button"
        className="outfit-prompt-dismiss"
        onClick={onDismiss}
        aria-label="Dismiss outfit suggestion"
      >
        ✕
      </button>
    </div>
  );
}

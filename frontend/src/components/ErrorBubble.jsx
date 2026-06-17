export default function ErrorBubble({ message, recoverable, onRetry }) {
  return (
    <div className="error-bubble">
      <div className="error-bubble-text">
        {message || "Something went wrong. Your message is safe."}
      </div>
      {recoverable !== false && onRetry && (
        <button className="error-retry-btn" onClick={onRetry}>
          Retry
        </button>
      )}
    </div>
  );
}

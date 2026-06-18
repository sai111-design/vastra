export default function SuggestionChips({ suggestions, onSelect, disabled }) {
  if (disabled || !suggestions || suggestions.length === 0) return null;

  return (
    <div className="suggestion-chips" role="list" aria-label="Suggested replies">
      {suggestions.map((text, i) => (
        <button
          key={`${i}-${text}`}
          type="button"
          role="listitem"
          className="suggestion-chip"
          onClick={() => onSelect && onSelect(text)}
        >
          {text}
        </button>
      ))}
    </div>
  );
}

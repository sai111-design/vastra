import { useState, useRef, useCallback } from 'react';

export default function Composer({ onSend, disabled, locked }) {
  const [text, setText] = useState('');
  const textareaRef = useRef(null);

  const autoResize = useCallback(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = Math.min(el.scrollHeight, 120) + 'px';
  }, []);

  const handleSubmit = () => {
    if (!text.trim() || disabled) return;
    onSend(text.trim());
    setText('');
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
    }
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  return (
    <div className="composer-wrap">
      {locked && (
        <div className="composer-lock">
          Confirm or cancel above to continue
        </div>
      )}
      <div className="composer" style={locked ? { opacity: 0.4 } : undefined}>
        <textarea
          ref={textareaRef}
          className="composer-input"
          placeholder="Message vastra..."
          value={text}
          onChange={(e) => { setText(e.target.value); autoResize(); }}
          onKeyDown={handleKeyDown}
          disabled={disabled || locked}
          rows={1}
        />
        <button
          className="composer-send"
          onClick={handleSubmit}
          disabled={disabled || locked || !text.trim()}
          aria-label="Send"
        >
          &#8593;
        </button>
      </div>
    </div>
  );
}

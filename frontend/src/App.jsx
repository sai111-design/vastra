import { useRef, useEffect, useCallback } from 'react';
import useChatStream from './hooks/useChatStream';
import ProductCardRow from './components/ProductCardRow';
import ConfirmChip from './components/ConfirmChip';
import CheckoutBanner from './components/CheckoutBanner';
import CartDrawer from './components/CartDrawer';
import Composer from './components/Composer';
import ThinkingDots from './components/ThinkingDots';
import ErrorBubble from './components/ErrorBubble';

const PROMPTS = [
  'Oversized black tee under ₹600, size L',
  'Blue denim jacket for men',
  'Floral summer dress, size M',
  'White sneakers under ₹1500',
];

const AVATAR_COLORS = ['#1A1A1A', '#2D6B4F', '#E85D3A', '#8FB83A', '#F2D03B'];

function relativeTime(d) {
  if (!d) return '';
  const m = Math.floor((Date.now() - new Date(d).getTime()) / 60000);
  if (m < 1) return 'now';
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h`;
  return `${Math.floor(h / 24)}d`;
}

function initials(text) {
  if (!text) return '?';
  return text.trim().split(/\s+/).slice(0, 2).map(w => (w[0] || '').toUpperCase()).join('');
}

function avatarColor(id) {
  let h = 0;
  for (let i = 0; i < (id || '').length; i++) h = ((h << 5) - h) + id.charCodeAt(i);
  return AVATAR_COLORS[Math.abs(h) % AVATAR_COLORS.length];
}

function CartIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M6 2L3 6v14a2 2 0 002 2h14a2 2 0 002-2V6l-3-4z"/>
      <line x1="3" y1="6" x2="21" y2="6"/>
      <path d="M16 10a4 4 0 01-8 0"/>
    </svg>
  );
}

export default function App() {
  const chat = useChatStream();
  const endRef = useRef(null);

  const view = chat.currentSessionId ? 'chat' : 'sessions';
  const cartCount = chat.cart?.total_quantity || chat.cart?.lines?.length || 0;

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [chat.messages, chat.streamingMessage]);

  const handleNewPrompt = useCallback(async (text) => {
    const sid = await chat.createSession();
    if (sid) chat.sendMessage(text, sid);
  }, [chat]);

  if (!chat.appReady) {
    return (
      <div className="app-loading">
        <img src="/assets/vastra-mark-v2.png" alt="Vastra" className="app-loading-logo" />
        <div className="app-loading-title">vastra</div>
        <div className="app-loading-text">
          Waking up the store… first load can take a few seconds.
        </div>
        <div className="app-loading-bar"><div className="app-loading-bar-fill" /></div>
      </div>
    );
  }

  const allMessages = [...chat.messages];
  if (chat.streamingMessage) allMessages.push(chat.streamingMessage);

  const renderMessage = (msg, idx) => {
    const isLast = idx === allMessages.length - 1;
    const items = [];

    if (msg.role === 'assistant' && msg.route) {
      items.push(<div key={`r${idx}`} className="message-route">{msg.route}</div>);
    }

    if (msg.role === 'user') {
      items.push(<div key={`b${idx}`} className="bubble bubble-user">{msg.content}</div>);
    } else if (msg.error && !msg.content) {
      items.push(
        <ErrorBubble key={`e${idx}`} message={msg.error.message || String(msg.error)} recoverable={msg.error.recoverable} />
      );
    } else if (msg.content) {
      items.push(
        <div key={`b${idx}`} className="bubble bubble-assistant">
          {msg.content}
          {msg.fallbackUsed && <span className="fallback-badge">fallback</span>}
        </div>
      );
    } else if (msg.isStreaming) {
      items.push(<ThinkingDots key={`t${idx}`} />);
    }

    if (msg.productCards) {
      items.push(<ProductCardRow key={`pc${idx}`} products={msg.productCards} />);
    }

    if (msg.confirmRequest && !msg.confirmResolved && chat.pendingConfirm) {
      items.push(
        <ConfirmChip key={`cc${idx}`} request={msg.confirmRequest} onConfirm={chat.confirmAction} />
      );
    } else if (msg.confirmRequest && msg.confirmResolved) {
      items.push(
        <ConfirmChip key={`cc${idx}`} request={msg.confirmRequest} resolved={msg.confirmResolved} />
      );
    }

    if (msg.cartUpdate && msg.cartUpdate.checkout_url && msg.cartUpdate.total_quantity > 0) {
      items.push(<CheckoutBanner key={`cb${idx}`} cart={msg.cartUpdate} />);
    }

    return items;
  };

  return (
    <div className="app-layout" data-view={view}>

      {/* ── Desktop sidebar ── */}
      <aside className="sidebar">
        <div className="sidebar-header">
          <img src="/assets/vastra-mark-v2.png" alt="" className="sidebar-logo" />
          <span className="sidebar-brand">vastra</span>
        </div>
        <button className="sidebar-new-btn" onClick={chat.createSession}>+ New conversation</button>
        <div className="sidebar-sessions">
          {chat.sessions.map(s => (
            <div
              key={s.session_id}
              className={`session-card${s.session_id === chat.currentSessionId ? ' active' : ''}`}
              onClick={() => chat.openSession(s.session_id)}
            >
              <div className="session-card-top">
                <span className="session-card-title">{s.preview || 'New conversation'}</span>
                <span className="session-card-time">{relativeTime(s.last_active)}</span>
              </div>
              {s.preview && <div className="session-card-preview">{s.preview}</div>}
            </div>
          ))}
        </div>
      </aside>

      {/* ── Mobile sessions ── */}
      <div className="mobile-sessions">
        <div className="mobile-sessions-header">
          <img src="/assets/vastra-mark-v2.png" alt="" className="mobile-sessions-logo" />
          <span className="mobile-sessions-title">Chats</span>
        </div>
        <div className="mobile-sessions-list">
          {chat.sessions.length === 0 && (
            <div style={{ textAlign: 'center', padding: '40px 20px', color: 'var(--body)' }}>
              <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 8 }}>No chats yet</div>
              <div style={{ fontSize: 13 }}>Tap + to start shopping</div>
            </div>
          )}
          {chat.sessions.map(s => (
            <div key={s.session_id} className="mobile-session-card" onClick={() => chat.openSession(s.session_id)}>
              <div className="mobile-session-avatar" style={{ background: avatarColor(s.session_id) }}>
                {initials(s.preview)}
              </div>
              <div className="mobile-session-info">
                <div className="mobile-session-top">
                  <span className="mobile-session-name">{s.preview || 'New conversation'}</span>
                  <span className="mobile-session-time">{relativeTime(s.last_active)}</span>
                </div>
                {s.preview && <div className="mobile-session-preview">{s.preview}</div>}
              </div>
            </div>
          ))}
        </div>
        <button className="mobile-fab" onClick={chat.createSession}>+</button>
      </div>

      {/* ── Chat area ── */}
      <main className="chat-main">
        {chat.currentSessionId ? (
          <>
            {/* Header */}
            <div className="chat-header">
              <button className="chat-header-back" onClick={chat.goBack}>&#8249;</button>
              <img src="/assets/vastra-mark-v2.png" alt="" className="chat-header-logo" />
              <span className="chat-header-title">vastra</span>
              <button className="chat-header-cart" onClick={chat.toggleCart}>
                <CartIcon />
                {cartCount > 0 && <span className="chat-header-cart-badge">{cartCount}</span>}
              </button>
            </div>

            {/* Messages or empty */}
            {allMessages.length === 0 && !chat.isStreaming ? (
              <div className="chat-empty">
                <img src="/assets/vastra-mark-v2.png" alt="" className="chat-empty-logo" />
                <div className="chat-empty-title">What are you shopping for?</div>
                <div className="chat-empty-prompts">
                  {PROMPTS.map(p => (
                    <button key={p} className="chat-empty-prompt" onClick={() => chat.sendMessage(p)}>{p}</button>
                  ))}
                </div>
              </div>
            ) : (
              <div className="message-list">
                {allMessages.map((msg, i) => (
                  <div key={msg.id || `s${i}`} style={{ display: 'contents' }}>
                    {renderMessage(msg, i)}
                  </div>
                ))}
                <div ref={endRef} />
              </div>
            )}

            <Composer
              onSend={chat.sendMessage}
              disabled={chat.isStreaming}
              locked={!!chat.pendingConfirm}
            />
            <CartDrawer cart={chat.cart} open={chat.cartOpen} onClose={chat.toggleCart} />
          </>
        ) : (
          /* Desktop empty detail pane */
          <div className="chat-empty">
            <img src="/assets/vastra-mark-v2.png" alt="" className="chat-empty-logo" />
            <div className="chat-empty-title">Pick a chat or start fresh</div>
            <div className="chat-empty-text">
              Tell me what you're shopping for and I'll pull live products from the store.
            </div>
            <div className="chat-empty-prompts">
              {PROMPTS.map(p => (
                <button key={p} className="chat-empty-prompt" onClick={() => handleNewPrompt(p)}>{p}</button>
              ))}
            </div>
          </div>
        )}
      </main>
    </div>
  );
}

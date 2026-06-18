import { useRef, useEffect, useCallback, useState } from 'react';
import useChatStream from './hooks/useChatStream';
import ProductCardRow from './components/ProductCardRow';
import ProductShelf from './components/ProductShelf';
import SuggestionChips from './components/SuggestionChips';
import OutfitPrompt from './components/OutfitPrompt';
import LookCardRow from './components/LookCardRow';
import OnboardingFlow from './components/OnboardingFlow';
import ConfirmChip from './components/ConfirmChip';

const ONBOARDED_KEY = 'vastra_onboarded';

function readOnboarded() {
  try {
    return typeof window !== 'undefined' && window.localStorage?.getItem(ONBOARDED_KEY) === '1';
  } catch {
    return false;
  }
}

function markOnboarded() {
  try { window.localStorage?.setItem(ONBOARDED_KEY, '1'); } catch {}
}

const CATEGORY_LABELS = {
  tops: 'tops',
  bottoms: 'bottoms',
  dresses: 'dresses',
  footwear: 'footwear',
  accessories: 'accessories',
};

function firstMessageFromAnswers({ vibe, budget, categories }) {
  if (!categories || categories.length === 0) return null;
  if (categories.includes('surprise_me')) {
    return 'Surprise me with something nice';
  }
  const labels = categories.map(c => CATEGORY_LABELS[c]).filter(Boolean);
  if (labels.length === 0) return null;
  const joined = labels.length === 1
    ? labels[0]
    : labels.slice(0, -1).join(', ') + ' or ' + labels.at(-1);
  const vibeWord = vibe && vibe !== 'casual' ? ` (${vibe} vibe)` : '';
  const budgetWord = budget === 'under_500'
    ? ' under ₹500'
    : budget === '500_1500'
      ? ' between ₹500 and ₹1500'
      : budget === 'above_1500'
        ? ' over ₹1500'
        : '';
  return `Show me some ${joined}${budgetWord}${vibeWord}`;
}
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
  const [shelfOpen, setShelfOpen] = useState(true);
  const [showOnboarding, setShowOnboarding] = useState(() => !readOnboarded());

  const view = chat.currentSessionId ? 'chat' : 'sessions';
  const cartCount = chat.cart?.total_quantity || chat.cart?.lines?.length || 0;
  const buyerSizes = chat.buyerProfile?.sizes ?? [];

  const handleShelfClick = useCallback((product) => {
    if (!product?.title) return;
    chat.sendMessage(`Tell me more about ${product.title}`);
  }, [chat]);

  const handleSuggestionSelect = useCallback((text) => {
    chat.clearSuggestions();
    chat.sendMessage(text);
  }, [chat]);

  const handleComposerInput = useCallback(() => {
    if (chat.suggestions && chat.suggestions.length > 0) {
      chat.clearSuggestions();
    }
  }, [chat]);

  const toggleShelf = useCallback(() => setShelfOpen(o => !o), []);

  const handleOnboardingComplete = useCallback(async (answers) => {
    markOnboarded();
    setShowOnboarding(false);
    const sid = await chat.createSession(answers);
    if (!sid) return;
    const firstMessage = firstMessageFromAnswers(answers);
    if (firstMessage) chat.sendMessage(firstMessage, sid);
  }, [chat]);

  const handleOnboardingSkip = useCallback(() => {
    markOnboarded();
    setShowOnboarding(false);
  }, []);

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

  if (showOnboarding) {
    return (
      <OnboardingFlow
        onComplete={handleOnboardingComplete}
        onSkip={handleOnboardingSkip}
      />
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
      if (msg.lookCompletion) {
        items.push(
          <LookCardRow
            key={`lc${idx}`}
            products={msg.productCards}
            intro={msg.lookIntro || ''}
          />
        );
      } else {
        items.push(<ProductCardRow key={`pc${idx}`} products={msg.productCards} />);
      }
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

    if (msg.outfitPrompt) {
      const promptKey = msg.id != null ? `op-${msg.id}` : `op-i-${idx}`;
      const dismissed = chat.dismissedOutfitPrompts?.has(promptKey);
      if (!dismissed) {
        items.push(
          <OutfitPrompt
            key={`op${idx}`}
            visible={true}
            onAccept={() => {
              chat.dismissOutfitPrompt(promptKey);
              chat.sendMessage('Yes, complete the look');
            }}
            onDismiss={() => chat.dismissOutfitPrompt(promptKey)}
          />
        );
      }
    }

    return items;
  };

  const layoutClass = `app-layout${shelfOpen ? '' : ' shelf-collapsed'}`;

  return (
    <div className={layoutClass} data-view={view}>

      {/* ── Desktop sidebar ── */}
      <aside className="sidebar">
        <div className="sidebar-header">
          <img src="/assets/vastra-mark-v2.png" alt="" className="sidebar-logo" />
          <span className="sidebar-brand">vastra</span>
        </div>
        <button className="sidebar-new-btn" onClick={() => chat.createSession()}>+ New conversation</button>
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
        <button className="mobile-fab" onClick={() => chat.createSession()}>+</button>
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

            <SuggestionChips
              suggestions={chat.suggestions}
              onSelect={handleSuggestionSelect}
              disabled={chat.isStreaming || !!chat.pendingConfirm}
            />
            <Composer
              onSend={chat.sendMessage}
              onInput={handleComposerInput}
              disabled={chat.isStreaming}
              locked={!!chat.pendingConfirm}
            />
            <CartDrawer cart={chat.cart} open={chat.cartOpen} onClose={chat.toggleCart} />
            <button
              className="shelf-toggle-btn"
              onClick={toggleShelf}
              aria-label={shelfOpen ? 'Hide product shelf' : 'Show product shelf'}
            >
              {shelfOpen ? '↓' : '↑'}
            </button>
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

      <ProductShelf
        products={chat.shelfProducts}
        buyerSizes={buyerSizes}
        onProductClick={handleShelfClick}
      />
    </div>
  );
}

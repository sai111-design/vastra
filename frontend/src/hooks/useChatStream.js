import { useState, useCallback, useEffect } from 'react';
import * as api from '../api/client';

function enrichMessage(msg) {
  const rich = {
    id: msg.id,
    role: msg.role,
    content: msg.content || '',
    route: null,
    productCards: null,
    lookCompletion: false,
    lookIntro: '',
    confirmRequest: null,
    confirmResolved: null,
    cartUpdate: null,
    outfitPrompt: null,
    error: null,
    fallbackUsed: false,
  };
  if (msg.events && Array.isArray(msg.events)) {
    for (const evt of msg.events) {
      // Stored events use {event, data}; live SSE events use {type, data}.
      // Read either so this function works for both code paths.
      const kind = evt.event || evt.type;
      switch (kind) {
        case 'route': rich.route = evt.data?.agent; break;
        case 'product_cards':
          rich.productCards = evt.data?.products;
          rich.lookCompletion = !!evt.data?.look_completion;
          rich.lookIntro = evt.data?.look_intro || '';
          break;
        case 'confirm_request': rich.confirmRequest = evt.data; break;
        case 'cart_update': rich.cartUpdate = evt.data; break;
        case 'outfit_prompt': rich.outfitPrompt = evt.data; break;
        case 'error': rich.error = evt.data; break;
        case 'done': rich.fallbackUsed = evt.data?.fallback_used || false; break;
      }
    }
  }
  return rich;
}

function resolveConfirms(messages) {
  for (let i = 0; i < messages.length; i++) {
    if (!messages[i].confirmRequest) continue;
    const after = messages.slice(i + 1);
    if (after.some(m => m.cartUpdate)) {
      messages[i].confirmResolved = 'confirmed';
    } else if (after.length > 0) {
      messages[i].confirmResolved = 'cancelled';
    }
  }
  return messages;
}

function deriveCart(messages) {
  for (let i = messages.length - 1; i >= 0; i--) {
    if (messages[i].cartUpdate) return messages[i].cartUpdate;
  }
  return null;
}

export default function useChatStream() {
  const [appReady, setAppReady] = useState(false);
  const [sessions, setSessions] = useState([]);
  const [currentSessionId, setCurrentSessionId] = useState(null);
  const [messages, setMessages] = useState([]);
  const [streamingMessage, setStreamingMessage] = useState(null);
  const [cart, setCart] = useState(null);
  const [pendingConfirm, setPendingConfirm] = useState(null);
  const [isStreaming, setIsStreaming] = useState(false);
  const [route, setRoute] = useState(null);
  const [error, setError] = useState(null);
  const [cartOpen, setCartOpen] = useState(false);
  const [shelfProducts, setShelfProducts] = useState([]);
  const [buyerProfile, setBuyerProfile] = useState(null);
  const [suggestions, setSuggestions] = useState([]);
  const [dismissedOutfitPrompts, setDismissedOutfitPrompts] = useState(() => new Set());

  const refreshSessions = useCallback(async () => {
    try {
      const data = await api.listSessions();
      setSessions(data.sessions || []);
    } catch {}
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        await api.listSessions().then(d => {
          if (!cancelled) { setSessions(d.sessions || []); setAppReady(true); }
        });
      } catch {
        try { await api.checkHealth(); } catch {}
        await new Promise(r => setTimeout(r, 3000));
        if (!cancelled) {
          try {
            const d = await api.listSessions();
            setSessions(d.sessions || []);
          } catch {}
          setAppReady(true);
        }
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const createSession = useCallback(async (initialProfile = null) => {
    try {
      const data = await api.createSession(initialProfile);
      const sid = data.session_id;
      setCurrentSessionId(sid);
      setMessages([]);
      setCart(null);
      setPendingConfirm(null);
      setRoute(null);
      setError(null);
      setShelfProducts([]);
      setSuggestions([]);
      setDismissedOutfitPrompts(new Set());
      setSessions(prev => [{ session_id: sid, preview: null, last_active: new Date().toISOString() }, ...prev]);
      return sid;
    } catch (e) {
      setError(e.message);
      return null;
    }
  }, []);

  const openSession = useCallback(async (sessionId) => {
    setCurrentSessionId(sessionId);
    setStreamingMessage(null);
    setPendingConfirm(null);
    setRoute(null);
    setError(null);
    setCartOpen(false);
    setSuggestions([]);
    setDismissedOutfitPrompts(new Set());
    try {
      const data = await api.getSession(sessionId);
      const enriched = resolveConfirms((data.messages || []).map(enrichMessage));
      setMessages(enriched);
      setCart(deriveCart(enriched));
      const lastCards = [...enriched].reverse().find(m => m.productCards && m.productCards.length > 0);
      setShelfProducts(lastCards ? lastCards.productCards : []);
      const lastConfirm = [...enriched].reverse().find(m => m.confirmRequest && !m.confirmResolved);
      if (lastConfirm) setPendingConfirm(lastConfirm.confirmRequest);
    } catch (e) {
      setError(e.message);
      setMessages([]);
    }
  }, []);

  const sendMessage = useCallback(async (text, sessionIdOverride) => {
    const sid = sessionIdOverride || currentSessionId;
    if (!sid || !text.trim() || isStreaming) return;

    setMessages(prev => [...prev, { id: Date.now(), role: 'user', content: text.trim() }]);
    setIsStreaming(true);
    setError(null);
    setRoute(null);
    setSuggestions([]);

    const acc = {
      text: '', route: null, cards: null, lookCompletion: false, lookIntro: '',
      confirm: null, cartUpd: null, outfit: null,
      err: null, fallback: false, gotDone: false,
    };

    const updateStream = () => {
      setStreamingMessage({
        id: null, role: 'assistant', content: acc.text, route: acc.route,
        productCards: acc.cards, lookCompletion: acc.lookCompletion, lookIntro: acc.lookIntro,
        confirmRequest: acc.confirm, cartUpdate: acc.cartUpd, outfitPrompt: acc.outfit,
        error: acc.err, fallbackUsed: acc.fallback, isStreaming: true,
      });
    };

    setStreamingMessage({ id: null, role: 'assistant', content: '', isStreaming: true });

    try {
      await api.streamChat(sid, text.trim(), (event) => {
        switch (event.type) {
          case 'route':
            acc.route = event.data.agent;
            setRoute(event.data.agent);
            break;
          case 'token':
            acc.text += event.data.text;
            updateStream();
            break;
          case 'product_cards':
            acc.cards = event.data.products;
            acc.lookCompletion = !!event.data.look_completion;
            acc.lookIntro = event.data.look_intro || '';
            if (event.data.products && event.data.products.length > 0) {
              setShelfProducts(event.data.products);
            }
            updateStream();
            break;
          case 'confirm_request':
            acc.confirm = event.data;
            setPendingConfirm(event.data);
            setSuggestions([]);
            updateStream();
            break;
          case 'cart_update':
            acc.cartUpd = event.data;
            setCart(event.data);
            updateStream();
            break;
          case 'error':
            acc.err = event.data;
            setError(event.data.message);
            updateStream();
            break;
          case 'done':
            acc.gotDone = true;
            acc.fallback = event.data.fallback_used || false;
            setMessages(prev => [...prev, {
              id: event.data.turn_id, role: 'assistant', content: acc.text,
              route: acc.route, productCards: acc.cards,
              lookCompletion: acc.lookCompletion, lookIntro: acc.lookIntro,
              confirmRequest: acc.confirm, confirmResolved: null,
              cartUpdate: acc.cartUpd, outfitPrompt: acc.outfit,
              error: acc.err, fallbackUsed: acc.fallback,
            }]);
            setStreamingMessage(null);
            if (!acc.confirm) {
              setSuggestions(Array.isArray(event.data.suggestions) ? event.data.suggestions : []);
            }
            break;
        }
      });
    } catch (e) {
      setError(e.message);
    } finally {
      if (!acc.gotDone && (acc.text || acc.confirm || acc.cards || acc.cartUpd || acc.err)) {
        setMessages(prev => [...prev, {
          id: Date.now(), role: 'assistant', content: acc.text,
          route: acc.route, productCards: acc.cards,
          lookCompletion: acc.lookCompletion, lookIntro: acc.lookIntro,
          confirmRequest: acc.confirm, confirmResolved: null,
          cartUpdate: acc.cartUpd, outfitPrompt: acc.outfit,
          error: acc.err, fallbackUsed: acc.fallback,
        }]);
      }
      setStreamingMessage(null);
      setIsStreaming(false);
      refreshSessions();
    }
  }, [currentSessionId, isStreaming, refreshSessions]);

  const handleConfirm = useCallback(async (approved) => {
    if (!currentSessionId || !pendingConfirm || isStreaming) return;

    setIsStreaming(true);
    setError(null);

    const resolvedState = approved ? 'confirmed' : 'cancelled';
    setMessages(prev => prev.map(m =>
      m.confirmRequest?.action_id === pendingConfirm.action_id
        ? { ...m, confirmResolved: resolvedState }
        : m
    ));

    const acc = {
      text: '', route: null, cards: null, lookCompletion: false, lookIntro: '',
      cartUpd: null, outfit: null,
      err: null, fallback: false, gotDone: false,
    };

    const updateStream = () => {
      setStreamingMessage({
        id: null, role: 'assistant', content: acc.text, route: acc.route,
        productCards: acc.cards, lookCompletion: acc.lookCompletion, lookIntro: acc.lookIntro,
        cartUpdate: acc.cartUpd, outfitPrompt: acc.outfit,
        error: acc.err, fallbackUsed: acc.fallback, isStreaming: true,
      });
    };

    setStreamingMessage({ id: null, role: 'assistant', content: '', isStreaming: true });

    try {
      await api.confirmAction(currentSessionId, pendingConfirm.action_id, approved, (event) => {
        switch (event.type) {
          case 'route': acc.route = event.data.agent; setRoute(event.data.agent); break;
          case 'token': acc.text += event.data.text; updateStream(); break;
          case 'product_cards':
            acc.cards = event.data.products;
            acc.lookCompletion = !!event.data.look_completion;
            acc.lookIntro = event.data.look_intro || '';
            if (event.data.products && event.data.products.length > 0) {
              setShelfProducts(event.data.products);
            }
            updateStream();
            break;
          case 'cart_update': acc.cartUpd = event.data; setCart(event.data); updateStream(); break;
          case 'outfit_prompt': acc.outfit = event.data; updateStream(); break;
          case 'error': acc.err = event.data; setError(event.data.message); updateStream(); break;
          case 'done':
            acc.gotDone = true;
            acc.fallback = event.data.fallback_used || false;
            setMessages(prev => [...prev, {
              id: event.data.turn_id, role: 'assistant', content: acc.text,
              route: acc.route, productCards: acc.cards,
              lookCompletion: acc.lookCompletion, lookIntro: acc.lookIntro,
              cartUpdate: acc.cartUpd, outfitPrompt: acc.outfit,
              error: acc.err, fallbackUsed: acc.fallback,
            }]);
            setStreamingMessage(null);
            setSuggestions(Array.isArray(event.data.suggestions) ? event.data.suggestions : []);
            break;
        }
      });
    } catch (e) {
      setError(e.message);
    } finally {
      if (!acc.gotDone && acc.text) {
        setMessages(prev => [...prev, {
          id: Date.now(), role: 'assistant', content: acc.text,
          route: acc.route, productCards: acc.cards,
          lookCompletion: acc.lookCompletion, lookIntro: acc.lookIntro,
          cartUpdate: acc.cartUpd, outfitPrompt: acc.outfit,
          error: acc.err, fallbackUsed: acc.fallback,
        }]);
      }
      setPendingConfirm(null);
      setStreamingMessage(null);
      setIsStreaming(false);
      refreshSessions();
    }
  }, [currentSessionId, pendingConfirm, isStreaming, refreshSessions]);

  const toggleCart = useCallback(() => setCartOpen(prev => !prev), []);
  const clearError = useCallback(() => setError(null), []);
  const goBack = useCallback(() => {
    setCurrentSessionId(null);
    setMessages([]);
    setStreamingMessage(null);
    setCart(null);
    setPendingConfirm(null);
    setRoute(null);
    setError(null);
    setCartOpen(false);
    setShelfProducts([]);
    setSuggestions([]);
    setDismissedOutfitPrompts(new Set());
  }, []);

  const clearSuggestions = useCallback(() => setSuggestions([]), []);

  const dismissOutfitPrompt = useCallback((messageKey) => {
    setDismissedOutfitPrompts(prev => {
      if (prev.has(messageKey)) return prev;
      const next = new Set(prev);
      next.add(messageKey);
      return next;
    });
  }, []);

  return {
    appReady, sessions, currentSessionId, messages, streamingMessage,
    cart, pendingConfirm, isStreaming, route, error, cartOpen,
    shelfProducts, buyerProfile, suggestions, dismissedOutfitPrompts,
    createSession, openSession, sendMessage, confirmAction: handleConfirm,
    toggleCart, goBack, clearError, clearSuggestions, dismissOutfitPrompt,
  };
}

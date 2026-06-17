import { useState, useCallback, useEffect } from 'react';
import * as api from '../api/client';

function enrichMessage(msg) {
  const rich = {
    id: msg.id,
    role: msg.role,
    content: msg.content || '',
    route: null,
    productCards: null,
    confirmRequest: null,
    confirmResolved: null,
    cartUpdate: null,
    error: null,
    fallbackUsed: false,
  };
  if (msg.events && Array.isArray(msg.events)) {
    for (const evt of msg.events) {
      switch (evt.type) {
        case 'route': rich.route = evt.data?.agent; break;
        case 'product_cards': rich.productCards = evt.data?.products; break;
        case 'confirm_request': rich.confirmRequest = evt.data; break;
        case 'cart_update': rich.cartUpdate = evt.data; break;
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

  const createSession = useCallback(async () => {
    try {
      const data = await api.createSession();
      const sid = data.session_id;
      setCurrentSessionId(sid);
      setMessages([]);
      setCart(null);
      setPendingConfirm(null);
      setRoute(null);
      setError(null);
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
    try {
      const data = await api.getSession(sessionId);
      const enriched = resolveConfirms((data.messages || []).map(enrichMessage));
      setMessages(enriched);
      setCart(deriveCart(enriched));
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

    const acc = { text: '', route: null, cards: null, confirm: null, cartUpd: null, err: null, fallback: false, gotDone: false };

    const updateStream = () => {
      setStreamingMessage({
        id: null, role: 'assistant', content: acc.text, route: acc.route,
        productCards: acc.cards, confirmRequest: acc.confirm, cartUpdate: acc.cartUpd,
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
            updateStream();
            break;
          case 'confirm_request':
            acc.confirm = event.data;
            setPendingConfirm(event.data);
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
              route: acc.route, productCards: acc.cards, confirmRequest: acc.confirm,
              confirmResolved: null, cartUpdate: acc.cartUpd, error: acc.err,
              fallbackUsed: acc.fallback,
            }]);
            setStreamingMessage(null);
            break;
        }
      });
    } catch (e) {
      setError(e.message);
    } finally {
      if (!acc.gotDone && (acc.text || acc.confirm || acc.cards || acc.cartUpd || acc.err)) {
        setMessages(prev => [...prev, {
          id: Date.now(), role: 'assistant', content: acc.text,
          route: acc.route, productCards: acc.cards, confirmRequest: acc.confirm,
          confirmResolved: null, cartUpdate: acc.cartUpd, error: acc.err,
          fallbackUsed: acc.fallback,
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

    const acc = { text: '', route: null, cards: null, cartUpd: null, err: null, fallback: false, gotDone: false };

    const updateStream = () => {
      setStreamingMessage({
        id: null, role: 'assistant', content: acc.text, route: acc.route,
        productCards: acc.cards, cartUpdate: acc.cartUpd,
        error: acc.err, fallbackUsed: acc.fallback, isStreaming: true,
      });
    };

    setStreamingMessage({ id: null, role: 'assistant', content: '', isStreaming: true });

    try {
      await api.confirmAction(currentSessionId, pendingConfirm.action_id, approved, (event) => {
        switch (event.type) {
          case 'route': acc.route = event.data.agent; setRoute(event.data.agent); break;
          case 'token': acc.text += event.data.text; updateStream(); break;
          case 'product_cards': acc.cards = event.data.products; updateStream(); break;
          case 'cart_update': acc.cartUpd = event.data; setCart(event.data); updateStream(); break;
          case 'error': acc.err = event.data; setError(event.data.message); updateStream(); break;
          case 'done':
            acc.gotDone = true;
            acc.fallback = event.data.fallback_used || false;
            setMessages(prev => [...prev, {
              id: event.data.turn_id, role: 'assistant', content: acc.text,
              route: acc.route, productCards: acc.cards, cartUpdate: acc.cartUpd,
              error: acc.err, fallbackUsed: acc.fallback,
            }]);
            setStreamingMessage(null);
            break;
        }
      });
    } catch (e) {
      setError(e.message);
    } finally {
      if (!acc.gotDone && acc.text) {
        setMessages(prev => [...prev, {
          id: Date.now(), role: 'assistant', content: acc.text,
          route: acc.route, productCards: acc.cards, cartUpdate: acc.cartUpd,
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
  }, []);

  return {
    appReady, sessions, currentSessionId, messages, streamingMessage,
    cart, pendingConfirm, isStreaming, route, error, cartOpen,
    createSession, openSession, sendMessage, confirmAction: handleConfirm,
    toggleCart, goBack, clearError,
  };
}

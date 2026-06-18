const API = '/api';

async function* parseSSE(response) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      const parts = buffer.split('\n\n');
      buffer = parts.pop();

      for (const part of parts) {
        if (!part.trim()) continue;
        let eventType = 'message';
        const dataLines = [];
        for (const line of part.split('\n')) {
          if (line.startsWith(':')) continue;
          if (line.startsWith('event:')) eventType = line.slice(6).trim();
          else if (line.startsWith('data:')) dataLines.push(line.slice(5).replace(/^ /, ''));
        }
        if (dataLines.length) {
          try {
            yield { type: eventType, data: JSON.parse(dataLines.join('\n')) };
          } catch {
            // skip malformed JSON
          }
        }
      }
    }
  } finally {
    reader.releaseLock();
  }
}

async function ssePost(url, body, onEvent) {
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });

  if (!res.ok) {
    const text = await res.text();
    let detail = text;
    try { detail = JSON.parse(text).detail || text; } catch {}
    throw new Error(detail);
  }

  for await (const event of parseSSE(res)) {
    onEvent(event);
  }
}

export async function createSession(initialProfile = null) {
  const init = {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(initialProfile ? { initial_profile: initialProfile } : {}),
  };
  const res = await fetch(`${API}/sessions`, init);
  if (!res.ok) throw new Error('Failed to create session');
  return res.json();
}

export async function listSessions() {
  const res = await fetch(`${API}/sessions`);
  if (!res.ok) throw new Error('Failed to load sessions');
  return res.json();
}

export async function getSession(sessionId) {
  const res = await fetch(`${API}/sessions/${sessionId}`);
  if (!res.ok) throw new Error('Session not found');
  return res.json();
}

export async function streamChat(sessionId, message, onEvent) {
  return ssePost(`${API}/chat`, { session_id: sessionId, message }, onEvent);
}

export async function confirmAction(sessionId, actionId, approved, onEvent) {
  return ssePost(`${API}/confirm`, { session_id: sessionId, action_id: actionId, approved }, onEvent);
}

export async function checkHealth() {
  const res = await fetch(`${API}/health`);
  if (!res.ok) throw new Error('Backend unavailable');
  return res.json();
}

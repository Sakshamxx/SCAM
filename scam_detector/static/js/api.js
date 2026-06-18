/* ═══════════════════════════════════════════════
   ScamShield API Client
   Modular ES module for future React migration
   ═══════════════════════════════════════════════ */

export const ScamShieldAPI = {
  // ── Stats Endpoint ───────────────────────────
  getStats: async () => {
    const res = await fetch('/api/stats');
    if (!res.ok) throw new Error('Failed to fetch statistics');
    return await res.json();
  },

  // ── Job Analysis Endpoint ────────────────────
  analyzeJob: async (payload) => {
    const res = await fetch('/analyze', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    const data = await res.json();
    if (data.error) throw new Error(data.error);
    return data;
  },

  // ── Web Scraper Endpoint ─────────────────────
  scrapeJob: async (url) => {
    const res = await fetch('/scrape', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url })
    });
    const data = await res.json();
    if (data.error) throw new Error(data.error);
    return data;
  },

  // ── Scam Reporting Endpoint ──────────────────
  reportScam: async (payload) => {
    const res = await fetch('/report-scam', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/x-www-form-urlencoded',
        'Accept': 'application/json'
      },
      body: new URLSearchParams(payload)
    });
    const data = await res.json();
    if (data.error) throw new Error(data.error);
    return data;
  },

  // ── AI Chat Session Endpoints ────────────────
  getSessions: async () => {
    const res = await fetch('/api/ai-chat/sessions');
    if (!res.ok) throw new Error('Failed to load chat history');
    return await res.json();
  },

  createSession: async (title = 'New Conversation') => {
    const res = await fetch('/api/ai-chat/sessions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title })
    });
    if (!res.ok) throw new Error('Failed to create new session');
    return await res.json();
  },

  deleteSession: async (sessionId) => {
    const res = await fetch(`/api/ai-chat/sessions/${sessionId}`, {
      method: 'DELETE'
    });
    if (!res.ok) throw new Error('Failed to delete session');
    return await res.json();
  },

  getMessages: async (sessionId) => {
    const res = await fetch(`/api/ai-chat/messages?session_id=${sessionId}`);
    if (!res.ok) throw new Error('Failed to load messages');
    return await res.json();
  },

  uploadDocument: async (file, docType) => {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('doc_type', docType);

    const res = await fetch('/api/ai-chat/upload', {
      method: 'POST',
      body: formData
    });
    const data = await res.json();
    if (data.error) throw new Error(data.error);
    return data;
  },

  sendMessage: async (sessionId, message, docText = '', docType = '', docName = '') => {
    console.log('[API] 📡 sendMessage called with:', { sessionId, message: message.substring(0, 50) + (message.length > 50 ? '...' : ''), docType, docName });
    
    const payload = {
      session_id: sessionId,
      message: message,
      doc_text: docText,
      doc_type: docType,
      doc_name: docName
    };
    
    console.log('[API] 📦 Fetch payload:', payload);
    
    const res = await fetch('/api/ai-chat/send', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    
    console.log('[API] 📥 Response status:', res.status, res.ok);
    
    if (!res.ok) {
      console.error('[API] 🔴 HTTP error:', res.statusText);
      throw new Error('Failed to send message');
    }
    
    const data = await res.json();
    console.log('[API] ✅ Response data:', data);
    return data;
  }
};

// Bind to window for backward compatibility with inline script handlers
window.ScamShieldAPI = ScamShieldAPI;

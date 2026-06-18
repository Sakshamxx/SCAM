/* ═══════════════════════════════════════════════
   ScamShield AI Assistant UI controller
   ═══════════════════════════════════════════════ */

import { ScamShieldAPI } from '../api.js';

console.log('[CHAT] 📦 chat.js module loading...');

// ── State Management ───────────────────────────
let activeSessionId = null;
let activeDocument = null; // { text: '', type: '', name: '' }
let activeDocType = 'resume'; // default tab

// ── DOM References ─────────────────────────────
// DEFERRED: Initialize after DOM is ready
let DOM = {};

// ── Markdown Parser Helper ─────────────────────
function parseMarkdown(text) {
  // Safe HTML escape
  let escaped = text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');

  // Simple formatting rules
  escaped = escaped.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
  escaped = escaped.replace(/\*(.*?)\*/g, '<em>$1</em>');
  escaped = escaped.replace(/`(.*?)`/g, '<code class="chat-inline-code">$1</code>');
  
  // Code blocks (multiline)
  escaped = escaped.replace(/```([\s\S]*?)```/g, '<pre class="chat-code-block"><code>$1</code></pre>');

  // Split by line to format lists and paragraphs
  const lines = escaped.split('\n');
  let resultHtml = '';
  let inList = false;
  let inNumList = false;

  for (let line of lines) {
    line = line.trim();
    if (!line) {
      if (inList) { resultHtml += '</ul>'; inList = false; }
      if (inNumList) { resultHtml += '</ol>'; inNumList = false; }
      continue;
    }

    // Bullet list items
    if (line.startsWith('- ') || line.startsWith('* ')) {
      if (inNumList) { resultHtml += '</ol>'; inNumList = false; }
      if (!inList) { resultHtml += '<ul class="chat-list">'; inList = true; }
      resultHtml += `<li>${line.substring(2)}</li>`;
    }
    // Numbered list items
    else if (/^\d+\.\s/.test(line)) {
      if (inList) { resultHtml += '</ul>'; inList = false; }
      if (!inNumList) { resultHtml += '<ol class="chat-num-list">'; inNumList = true; }
      const matched = line.match(/^\d+\.\s(.*)/);
      resultHtml += `<li>${matched ? matched[1] : line}</li>`;
    }
    // Standard paragraph
    else {
      if (inList) { resultHtml += '</ul>'; inList = false; }
      if (inNumList) { resultHtml += '</ol>'; inNumList = false; }
      resultHtml += `<p class="chat-para">${line}</p>`;
    }
  }

  if (inList) resultHtml += '</ul>';
  if (inNumList) resultHtml += '</ol>';

  return resultHtml;
}

// ── Render Utilities ───────────────────────────
function scrollToBottom() {
  DOM.chatMessages.scrollTop = DOM.chatMessages.scrollHeight;
}

function showToast(message, type = 'success') {
  if (window.showGlobalToast) {
    window.showGlobalToast(message, type);
  } else {
    alert(`${type.toUpperCase()}: ${message}`);
  }
}

// ── App Workflows ──────────────────────────────
async function initSidebar() {
  try {
    const sessions = await ScamShieldAPI.getSessions();
    DOM.sessionsList.innerHTML = '';
    
    if (sessions && sessions.length > 0) {
      sessions.forEach(sess => {
        const item = document.createElement('div');
        item.className = `session-item ${activeSessionId === sess.id ? 'active' : ''}`;
        item.dataset.id = sess.id;
        
        item.innerHTML = `
          <span class="session-title-text" title="${sess.title}">💬 ${sess.title}</span>
          <button class="delete-session-btn" data-id="${sess.id}">×</button>
        `;
        
        // Select session handler
        item.addEventListener('click', (e) => {
          if (e.target.classList.contains('delete-session-btn')) return;
          selectSession(sess.id, sess.title);
        });

        // Delete session handler
        const delBtn = item.querySelector('.delete-session-btn');
        delBtn.addEventListener('click', async (e) => {
          e.stopPropagation();
          const targetId = delBtn.dataset.id;
          if (confirm('Delete this conversation history?')) {
            await ScamShieldAPI.deleteSession(targetId);
            if (activeSessionId === targetId) {
              activeSessionId = null;
              DOM.activeSessionTitle.textContent = 'ScamShield AI Assistant';
              DOM.chatMessages.innerHTML = '';
              DOM.chatMessages.appendChild(DOM.emptyState);
              DOM.emptyState.style.display = 'flex';
            }
            initSidebar();
            showToast('Conversation deleted', 'success');
          }
        });

        DOM.sessionsList.appendChild(item);
      });
    } else {
      DOM.sessionsList.innerHTML = `<div style="color:var(--text-sub); text-align:center; font-size:0.75rem; margin-top:20px;">No conversation history</div>`;
    }
  } catch (err) {
    console.error('Sidebar initialization error:', err);
  }
}

async function selectSession(sessionId, title) {
  activeSessionId = sessionId;
  DOM.activeSessionTitle.textContent = title || 'Active Conversation';
  DOM.emptyState.style.display = 'none';
  
  // Highlight active session item
  document.querySelectorAll('.session-item').forEach(el => {
    if (el.dataset.id === sessionId) {
      el.classList.add('active');
    } else {
      el.classList.remove('active');
    }
  });

  try {
    // Clear chat timeline (except typing indicator)
    DOM.chatMessages.querySelectorAll('.message-bubble').forEach(el => el.remove());
    
    const messages = await ScamShieldAPI.getMessages(sessionId);
    
    if (messages && messages.length > 0) {
      messages.forEach(msg => {
        appendMessageToTimeline(msg.role, msg.content, msg.documents);
      });
    } else {
      // show welcome text if no messages yet
      appendMessageToTimeline('assistant', 'Hello! How can I assist you today? You can ask about internship vacancies, resume structures, offer validation details or spot check suspicious postings.');
    }
    scrollToBottom();
  } catch (err) {
    showToast('Failed to load messages: ' + err.message, 'error');
  }
}

function appendMessageToTimeline(role, content, documents = null) {
  const bubble = document.createElement('div');
  bubble.className = `message-bubble ${role}`;
  
  let docsHtml = '';
  if (documents && documents.length > 0) {
    documents.forEach(d => {
      const icon = d.type === 'resume' ? '📄' : '📜';
      docsHtml += `<div class="message-doc-tag">${icon} Loaded Context: ${d.name || d.type}</div>`;
    });
  }

  bubble.innerHTML = docsHtml + parseMarkdown(content);
  
  // Insert before typing indicator
  DOM.chatMessages.insertBefore(bubble, DOM.typingIndicator);
}

async function sendMessage() {
  console.log('[CHAT] 🟢 sendMessage() called');
  const text = DOM.chatInputField.value.trim();
  console.log('[CHAT] Message text:', text);
  if (!text) {
    console.log('[CHAT] 🔴 Empty message, returning');
    return;
  }

  // Ensure an active session exists
  if (!activeSessionId) {
    console.log('[CHAT] ⚠️  No active session, creating one...');
    try {
      const sess = await ScamShieldAPI.createSession(text.substring(0, 30) + '...');
      activeSessionId = sess.id;
      console.log('[CHAT] ✓ Session created:', sess.id);
      await initSidebar();
    } catch (err) {
      console.error('[CHAT] 🔴 Session creation failed:', err);
      showToast('Failed to initialize session: ' + err.message, 'error');
      return;
    }
  }

  console.log('[CHAT] Active Session ID:', activeSessionId);

  // Clear input
  DOM.chatInputField.value = '';

  // Append user message immediately
  appendMessageToTimeline('user', text);
  DOM.emptyState.style.display = 'none';
  scrollToBottom();

  // Show typing indicator
  DOM.typingIndicator.style.display = 'flex';
  scrollToBottom();

  try {
    let docText = '';
    let docType = '';
    let docName = '';

    if (activeDocument) {
      docText = activeDocument.text;
      docType = activeDocument.type;
      docName = activeDocument.name;
      console.log('[CHAT] 📎 Document attached:', { type: docType, name: docName, length: docText.length });
      
      // Clear document attachment context from active state after attaching once
      activeDocument = null;
      DOM.activeAttachmentBar.style.display = 'none';
    }

    console.log('[CHAT] 📤 Calling ScamShieldAPI.sendMessage with payload:', {
      sessionId: activeSessionId,
      message: text,
      docText: docText.substring(0, 50) + (docText.length > 50 ? '...' : ''),
      docType,
      docName
    });

    const reply = await ScamShieldAPI.sendMessage(activeSessionId, text, docText, docType, docName);
    
    console.log('[CHAT] ✓ API Response received:', reply);
    
    // Hide typing indicator and append reply
    DOM.typingIndicator.style.display = 'none';
    appendMessageToTimeline('assistant', reply.content, reply.documents);
    scrollToBottom();
    
    console.log('[CHAT] ✅ Message processing complete');

  } catch (err) {
    console.error('[CHAT] 🔴 Error in sendMessage:', err);
    DOM.typingIndicator.style.display = 'none';
    showToast('Send message failed: ' + err.message, 'error');
  }
}

// ── Bind Interactive Event Listeners ──────────
document.addEventListener('DOMContentLoaded', () => {
  console.log('[CHAT] ✨ DOMContentLoaded fired, initializing chat UI');
  
  // CRITICAL: Initialize DOM references NOW that HTML is parsed
  DOM = {
    sessionsList: document.getElementById('sessionsList'),
    newChatBtn: document.getElementById('newChatBtn'),
    chatInputField: document.getElementById('chatInputField'),
    sendBtn: document.getElementById('sendBtn'),
    chatMessages: document.getElementById('chatMessages'),
    activeSessionTitle: document.getElementById('activeSessionTitle'),
    emptyState: document.getElementById('emptyState'),
    typingIndicator: document.getElementById('typingIndicator'),
    
    // Attachments
    attachBtn: document.getElementById('attachBtn'),
    uploadDrawer: document.getElementById('uploadDrawer'),
    drawerCloseBtn: document.getElementById('drawerCloseBtn'),
    tabResume: document.getElementById('tabResume'),
    tabOffer: document.getElementById('tabOffer'),
    uploadDropzone: document.getElementById('uploadDropzone'),
    pdfFileInput: document.getElementById('pdfFileInput'),
    activeAttachmentBar: document.getElementById('activeAttachmentBar'),
    attachmentName: document.getElementById('attachmentName'),
    attachmentType: document.getElementById('attachmentType'),
    removeAttachmentBtn: document.getElementById('removeAttachmentBtn')
  };

  console.log('[CHAT] ✓ DOM References initialized:', {
    sendBtn: DOM.sendBtn !== null ? '✓ found' : '❌ MISSING',
    chatInputField: DOM.chatInputField !== null ? '✓ found' : '❌ MISSING',
    chatMessages: DOM.chatMessages !== null ? '✓ found' : '❌ MISSING',
    sessionsList: DOM.sessionsList !== null ? '✓ found' : '❌ MISSING'
  });
  
  // Load initial sidebar history
  initSidebar();

  // New Chat Click
  DOM.newChatBtn.addEventListener('click', async () => {
    console.log('[CHAT] 🔘 New Chat button clicked');
    try {
      const sess = await ScamShieldAPI.createSession('New Conversation');
      await initSidebar();
      selectSession(sess.id, sess.title);
    } catch (err) {
      showToast('Error creating new conversation: ' + err.message, 'error');
    }
  });

  // Suggestion click
  document.querySelectorAll('.suggestion-card').forEach(card => {
    card.addEventListener('click', () => {
      const promptText = card.dataset.prompt;
      DOM.chatInputField.value = promptText;
      DOM.chatInputField.focus();
    });
  });

  // Send click
  console.log('[CHAT] 🔌 Binding send button click handler to:', DOM.sendBtn);
  DOM.sendBtn.addEventListener('click', (e) => {
    console.log('[CHAT] 📤 Send button clicked!', e);
    sendMessage();
  });

  // Send via Enter key
  console.log('[CHAT] 🔌 Binding input field Enter key handler to:', DOM.chatInputField);
  DOM.chatInputField.addEventListener('keypress', (e) => {
    console.log('[CHAT] ⌨️  Key pressed:', e.key, e.keyCode);
    if (e.key === 'Enter') {
      console.log('[CHAT] 📤 Enter key detected, calling sendMessage()');
      sendMessage();
    }
  });

  // Attach button drawer toggles
  DOM.attachBtn.addEventListener('click', () => {
    const isVisible = DOM.uploadDrawer.style.display === 'block';
    DOM.uploadDrawer.style.display = isVisible ? 'none' : 'block';
  });

  DOM.drawerCloseBtn.addEventListener('click', () => {
    DOM.uploadDrawer.style.display = 'none';
  });

  // Tabs toggle inside drawer
  DOM.tabResume.addEventListener('click', () => {
    activeDocType = 'resume';
    DOM.tabResume.classList.add('active');
    DOM.tabOffer.classList.remove('active');
  });

  DOM.tabOffer.addEventListener('click', () => {
    activeDocType = 'offer_letter';
    DOM.tabOffer.classList.add('active');
    DOM.tabResume.classList.remove('active');
  });

  // Dropzone click triggers hidden file input
  DOM.uploadDropzone.addEventListener('click', () => {
    DOM.pdfFileInput.click();
  });

  // File selected handler
  DOM.pdfFileInput.addEventListener('change', async (e) => {
    const file = e.target.files[0];
    if (!file) return;

    if (!file.name.endsWith('.pdf')) {
      showToast('Please select a PDF file.', 'error');
      return;
    }

    DOM.uploadDrawer.style.display = 'none';
    showToast(`Parsing ${activeDocType.replace('_', ' ')}...`, 'info');

    try {
      const data = await ScamShieldAPI.uploadDocument(file, activeDocType);
      
      activeDocument = {
        text: data.text,
        type: activeDocType,
        name: file.name
      };

      // Show the active attachment bar
      DOM.attachmentName.textContent = file.name;
      DOM.attachmentType.textContent = activeDocType.replace('_', ' ');
      DOM.activeAttachmentBar.style.display = 'flex';

      showToast('Document parsed successfully! Type your message to analyze.', 'success');

    } catch (err) {
      showToast('PDF parsing failed: ' + err.message, 'error');
    } finally {
      // Clear file input value to allow uploading same file again
      DOM.pdfFileInput.value = '';
    }
  });

  // Remove attachment click
  DOM.removeAttachmentBtn.addEventListener('click', () => {
    activeDocument = null;
    DOM.activeAttachmentBar.style.display = 'none';
    showToast('Attachment context removed', 'info');
  });
});

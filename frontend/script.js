// Shell-Mind web client — threads, attachments, tier switching.
//
// Backend URL resolution (in order):
//   1. ?server=<url> query parameter — explicit override
//   2. same origin — when the backend itself serves this page
//   3. probe http://localhost:8000, then http://127.0.0.1:8000 —
//      when the page is hosted by a separate static server or opened
//      as a local file (each candidate must actually answer /health)
let SERVER_URL = location.protocol.startsWith("http")
  ? location.origin : "http://localhost:8000";
// N9: set when a validated ?server= override is active — checkBackend
// uses this to keep a visible warning in the status bar.
let serverOverrideActive = false;  

async function detectServer() {
  const override = new URLSearchParams(location.search).get("server");
  if (override) {
    try {
      const u = new URL(override);
      if (u.protocol !== "http:" && u.protocol !== "https:") {
        throw new Error(`invalid scheme '${u.protocol}'`);
      }
      serverOverrideActive = true;
      console.warn("Shell-Mind: ?server= override active →", u.origin);
      return u.origin;   // normalized — strips path/query/fragment
    } catch (e) {
      console.warn(
        "Shell-Mind: ignoring invalid ?server= override:", override, "—", e.message
      );
      // fall through to auto-detection
    }
  }


  const candidates = [];
  if (location.protocol.startsWith("http")) candidates.push(location.origin);
  for (const c of ["http://localhost:8000", "http://127.0.0.1:8000"]) {
    if (!candidates.includes(c)) candidates.push(c);
  }
  for (const c of candidates) {
    try {
      if ((await fetch(`${c}/health`)).ok) return c;
    } catch { /* try the next candidate */ }
  }
  return candidates[0];   // none answered — show it in the status bar
}

let currentThread = [];
let allThreads = [];
let currentImagePath = null;
let currentPdfPath = null;
let activeThreadIndex = 0;

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

// Load history; corrupted storage resets instead of bricking the UI.
try {
  const savedThreads = localStorage.getItem('shellMindThreads');
  if (savedThreads) allThreads = JSON.parse(savedThreads);
  if (!Array.isArray(allThreads)) allThreads = [];
} catch (err) {
  console.warn('Corrupted local thread history — starting fresh:', err);
  allThreads = [];
}

const messagesEl     = document.getElementById('messages');
const emptyStateEl   = document.getElementById('emptyState');
const promptInput    = document.getElementById('promptInput');
const sendBtn        = document.getElementById('sendBtn');
const statusDot      = document.getElementById('statusDot');
const backendBar     = document.getElementById('backendBar');
const threadListEl   = document.getElementById('threadList');
const newChatBtn     = document.getElementById('newChatBtn');
const clearAllBtn    = document.getElementById('clearAllBtn');
const clockEl        = document.getElementById('clock');

// Mobile drawer
const menuBtn        = document.getElementById('menuBtn');
const sidebarEl      = document.querySelector('.sidebar');

// Attachments
const attachBtn      = document.getElementById('attachBtn');
const visionInput    = document.getElementById('visionInput');
const imageIndicator = document.getElementById('imageIndicator');
const imageName      = document.getElementById('imageName');

// PDF / document upload
const uploadZone     = document.getElementById('uploadZone');
const pdfInput       = document.getElementById('pdfInput');
const pdfIndicator   = document.getElementById('pdfIndicator');
const pdfName        = document.getElementById('pdfName');

function updateClock() {
  const now = new Date();
  let h = now.getHours();
  const m = now.getMinutes().toString().padStart(2, '0');
  const ampm = h >= 12 ? 'PM' : 'AM';
  h = h % 12 || 12;
  clockEl.textContent = `${h}:${m} ${ampm}`;
}
updateClock();
setInterval(updateClock, 1000 * 30);

async function checkBackend() {
  try {
    const res = await fetch(`${SERVER_URL}/health`, { method: 'GET', headers: authHeaders() });
    if (res.ok) {
      const info = await res.json();
      const narrow = window.innerWidth <= 900;
      const vram = info.free_vram_gb != null
        ? (narrow ? ` · ${info.free_vram_gb}G` : ` · ${info.free_vram_gb} GB free`)
        : '';
      const auth = info.auth_required ? (narrow ? ' · key' : ' · auth on') : '';
      const busy = info.busy ? ' · BUSY' : '';
      const tier = info.tier ?? '?';
      statusDot.style.background = info.busy ? '#C99B3D' : '#3FB950';
      statusDot.style.boxShadow = `0 0 8px ${info.busy ? '#C99B3D' : '#3FB950'}`;
      const overrideTag = serverOverrideActive ? ' · OVERRIDE' : '';
      if (narrow) {
        backendBar.textContent = `${tier}${vram}${auth}${busy}${overrideTag}`;
      } else {
        backendBar.textContent = `Connected · ${tier}${vram}${auth}${busy}${overrideTag}`;
      }
      backendBar.title = serverOverrideActive
        ? `⚠ Override active: ${SERVER_URL} — verify this is your own server`
        : `Server: ${SERVER_URL}`;
    } else {
      throw new Error('not ok');
    }
  } catch (e) {
    statusDot.style.background = '#C99B3D';
    statusDot.style.boxShadow = '0 0 8px #C99B3D';
    backendBar.textContent = 'Backend offline';
    backendBar.title = SERVER_URL;
  }
}
backendBar.textContent = `Backend: searching...`;
const serverReady = detectServer().then(url => {
  if (url !== SERVER_URL) SERVER_URL = url;
  checkBackend();
  setInterval(checkBackend, 15000);  // refresh busy/VRAM status
  return url;
});

// --- Authenticated fetch -------------------------------------------------
function authHeaders(extra = {}) {
  const key = localStorage.getItem('shellMindApiKey');
  return key ? { ...extra, 'X-API-Key': key } : extra;
}

async function serverFetch(path, opts = {}) {
  await serverReady;
  const doFetch = () => fetch(`${SERVER_URL}${path}`, {
    ...opts,
    headers: authHeaders(opts.headers),
  });
  let res = await doFetch();
  if (res.status === 401) {
    localStorage.removeItem('shellMindApiKey');  // old/rotated key — force re-prompt
    const key = prompt(
      'This server requires an API key (or the previous key was rotated).\n' +
      'Enter the current key from the server owner:'
    );
    if (key) {
      localStorage.setItem('shellMindApiKey', key.trim());
      res = await doFetch();
      if (res.status === 401) {
        localStorage.removeItem('shellMindApiKey');
      }
    }
  }
  return res;
}

function friendlyError(status, detail) {
  if (status === 429) {
    return 'Rate limit reached — too many requests from this device. Wait about a minute and try again.';
  }
  if (status === 503) {
    return detail || 'Server is busy with another request. Retry in a moment.';
  }
  if (status === 401) {
    return 'API key rejected. If the owner rotated the key, enter the new one when prompted.';
  }
  return detail || `Server returned status ${status}`;
}

// --- Message Rendering & <think> Parsing ---
function renderMessages() {
  messagesEl.innerHTML = '';
  if (currentThread.length === 0) {
    messagesEl.appendChild(emptyStateEl);
    return;
  }

  currentThread.forEach(msg => {
    const div = document.createElement('div');
    div.className = `msg ${msg.role}${msg.error ? ' error' : ''}`;

    if (msg.role === 'bot' && !msg.error) {
      const text = msg.text;
      const thinkMatch = text.match(/<think>([\s\S]*?)<\/think>/);

      if (thinkMatch) {
        const thoughtProcess = thinkMatch[1].trim();
        const finalAnswer = text.replace(thinkMatch[0], '').trim();

        div.innerHTML = `
          <details class="thought-process">
            <summary>🧠 View AI's Thought Process</summary>
            <div class="thought-content">${escapeHtml(thoughtProcess)}</div>
          </details>
          <div class="final-answer">${escapeHtml(finalAnswer)}</div>
        `;
      } else {
        div.textContent = text;
      }
    } else {
      div.textContent = msg.text;
    }

    messagesEl.appendChild(div);
  });
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function showTypingIndicator() {
  const div = document.createElement('div');
  div.className = 'neural-loader';
  div.id = 'typingIndicator';
  div.innerHTML = `
    <div class="nodes">
      <div class="node"></div><div class="link"></div>
      <div class="node"></div><div class="link"></div>
      <div class="node"></div>
    </div>
    Model is generating...
  `;
  messagesEl.appendChild(div);
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function persistThreads() {
  const MAX_THREADS = 30;
  const MAX_MSG_CHARS = 8000;
  try {
    localStorage.setItem('shellMindThreads', JSON.stringify(allThreads));
  } catch (err) {
    // QuotaExceededError or similar — prune oldest, trim huge messages, retry once
    try {
      let threads = Array.isArray(allThreads) ? allThreads.slice() : [];
      if (threads.length > MAX_THREADS) {
        threads = threads
          .slice()
          .sort((a, b) => (b.updatedAt || 0) - (a.updatedAt || 0))
          .slice(0, MAX_THREADS);
      }
      threads = threads.map(t => ({
        ...t,
        messages: (t.messages || []).map(m => ({
          ...m,
          text: typeof m.text === 'string' && m.text.length > MAX_MSG_CHARS
            ? m.text.slice(0, MAX_MSG_CHARS) + '\n…[truncated]'
            : m.text,
        })),
      }));

      allThreads = threads;
      localStorage.setItem('shellMindThreads', JSON.stringify(allThreads));
    } catch (_) {
      // give up silently — history is best-effort
    }
  }
}



function removeTypingIndicator() {
  const el = document.getElementById('typingIndicator');
  if (el) el.remove();
}

async function sendMessage(text) {
  if (!text || !text.trim()) return;
  if (sendBtn.disabled) return;

  const thread = currentThread;
  let entry = allThreads[activeThreadIndex];

  if (!entry) {
    entry = { title: "New Chat", messages: thread };
    allThreads.unshift(entry);
    activeThreadIndex = 0;
  }

  thread.push({ role: 'user', text: text });

  if (thread.length === 1) {
    const title = text.slice(0, 22) + (text.length > 22 ? "..." : "");
    entry.title = title;
    renderThreadList();
  }

  renderMessages();
  promptInput.value = '';
  sendBtn.disabled = true;
  showTypingIndicator();

  try {
    const selectedMode = document.getElementById('modeSelect').value;
    if (currentImagePath && selectedMode !== 'agent') {
      removeTypingIndicator();
      thread.push({
        role: 'bot',
        error: true,
        text: '⚠ Image attachments only work in Agent mode. Switch the mode dropdown to "Agent" and retry, or remove the image to continue text-only.'
      });
      renderMessages();
      sendBtn.disabled = false;
      persistThreads();
      return;
    }
    const payload = { prompt: text, mode: selectedMode };
    if (currentImagePath) payload.image_path = currentImagePath;
    if (currentPdfPath) payload.document_path = currentPdfPath;

    const res = await serverFetch('/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });

    removeTypingIndicator();
    if (!res.ok) {
      const detail = await res.json().catch(() => ({}));
      throw new Error(friendlyError(res.status, detail.detail));
    }

    const data = await res.json();
    thread.push({ role: 'bot', text: data.answer });

    statusDot.style.background = '#3FB950';
    statusDot.style.boxShadow = '0 0 8px #3FB950';

    currentImagePath = null;
    currentPdfPath = null;
    imageIndicator.style.display = 'none';
    pdfIndicator.style.display = 'none';
    visionInput.value = "";
    pdfInput.value = "";

  } catch (err) {
    removeTypingIndicator();
    thread.push({
      role: 'bot',
      error: true,
      text: `⚠ ${err.message}`
    });
    statusDot.style.background = '#B84A4A';
    statusDot.style.boxShadow = '0 0 8px #B84A4A';
  }

  entry.messages = thread;
  persistThreads();

  renderMessages();
  sendBtn.disabled = false;
  promptInput.focus();
  checkBackend();
}

sendBtn.addEventListener('click', () => sendMessage(promptInput.value));
promptInput.addEventListener('keydown', (e) => {
  // L5: do not send while IME composition is active (CJK input)
  if (e.isComposing || e.keyCode === 229) return;
  if (e.key === 'Enter') sendMessage(promptInput.value);
});

document.querySelectorAll('.chip').forEach(chip => {
  chip.addEventListener('click', () => {
    sendMessage(chip.getAttribute('data-text'));
  });
});

newChatBtn.addEventListener('click', () => {
  // L6: reuse an already-empty active thread instead of spawning empties
  if (Array.isArray(currentThread) && currentThread.length === 0) {
    const active = allThreads[activeThreadIndex];
    if (active && Array.isArray(active.messages) && active.messages.length === 0) {
      renderMessages();
      return;
    }
  }
  currentThread = [];
  allThreads.unshift({ title: "New Chat", messages: [] });
  activeThreadIndex = 0;
  persistThreads();
  renderThreadList();
  renderMessages();
});

clearAllBtn.addEventListener('click', () => {
  if (confirm("Delete all local chat history and forget the stored API key on this device?")) {
    allThreads = [];
    currentThread = [];
    localStorage.removeItem('shellMindThreads');
    localStorage.removeItem('shellMindApiKey');
    renderThreadList();
    renderMessages();
  }
});

const backdropEl = document.getElementById('sidebarBackdrop');

function closeSidebar() {
  sidebarEl.classList.remove('open');
  if (backdropEl) backdropEl.classList.remove('visible');
}
function openSidebar() {
  sidebarEl.classList.add('open');
  if (backdropEl) backdropEl.classList.add('visible');
}
function toggleSidebar() {
  if (sidebarEl.classList.contains('open')) closeSidebar();
  else openSidebar();
}

menuBtn.addEventListener('click', (e) => {
  e.stopPropagation();
  toggleSidebar();
});
if (backdropEl) backdropEl.addEventListener('click', closeSidebar);
document.querySelector('.main')?.addEventListener('click', () => {
  if (window.innerWidth <= 900) closeSidebar();
});
threadListEl.addEventListener('click', () => {
  if (window.innerWidth <= 900) closeSidebar();
});
newChatBtn.addEventListener('click', () => {
  if (window.innerWidth <= 900) closeSidebar();
});

function renderThreadList() {
  threadListEl.innerHTML = '';
  allThreads.forEach((t, index) => {
    const div = document.createElement('div');
    div.className = 'thread-item';
    if (index === activeThreadIndex) div.classList.add('active');

    div.textContent = `💬 ${t.title || "New Chat"}`;
    div.addEventListener('click', () => {
      activeThreadIndex = index;
      currentThread = t.messages;
      renderThreadList();
      renderMessages();
    });
    threadListEl.appendChild(div);
  });
}

attachBtn.addEventListener('click', () => visionInput.click());
visionInput.addEventListener('change', async () => {
  const file = visionInput.files[0];
  if (!file) return;
  const formData = new FormData();
  formData.append('file', file);
  try {
    const res = await serverFetch('/upload_image', { method: 'POST', body: formData });
    if (res.ok) {
      const data = await res.json();
      currentImagePath = data.image_path;
      imageName.textContent = file.name;
      imageIndicator.style.display = 'block';
    } else {
      const detail = await res.json().catch(() => ({}));
      alert(`Image upload rejected: ${friendlyError(res.status, detail.detail)}`);
    }
  } catch (err) {
    alert(`Image upload failed — is the backend running at ${SERVER_URL}?`);
  }
});

uploadZone.addEventListener('click', () => pdfInput.click());
pdfInput.addEventListener('change', async () => {
  const file = pdfInput.files[0];
  if (!file) return;

  const formData = new FormData();
  formData.append('file', file);

  pdfName.textContent = file.name + " (Uploading...)";
  pdfIndicator.style.display = 'block';

  try {
    const res = await serverFetch('/upload', { method: 'POST', body: formData });
    if (res.ok) {
        const data = await res.json();
        currentPdfPath = data.document_path;
        pdfName.textContent = file.name + " (Ready — first 3 pages / 3k chars)";
    } else {
        const detail = await res.json().catch(() => ({}));
        alert(`Document upload rejected: ${friendlyError(res.status, detail.detail)}`);
        pdfIndicator.style.display = 'none';
    }
  } catch (err) {
    alert(`Document upload failed — is the backend running at ${SERVER_URL}?`);
    pdfIndicator.style.display = 'none';
  }
});

const modeSelectEl = document.getElementById('modeSelect');
const applyModeToAttach = () => {
  const isAgent = modeSelectEl.value === 'agent';
  attachBtn.disabled = !isAgent;
  attachBtn.title = isAgent
    ? 'Attach an image (agent vision)'
    : 'Images only work in Agent mode — switch the dropdown';
  attachBtn.style.opacity = isAgent ? '' : '0.4';
};
modeSelectEl.addEventListener('change', applyModeToAttach);
applyModeToAttach();

renderThreadList();
renderMessages();

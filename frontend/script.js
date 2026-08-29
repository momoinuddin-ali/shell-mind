
const SERVER_URL = "http://localhost:8000"; 


let currentThread = [];      // abhi chal rahi chat ke messages
let allThreads = [];         // sab purani chats ki list (sirf is session ke liye, refresh pe reset)

/* ===============================================================
   3) DOM REFERENCES — HTML elements ko JS variables mein pakadna
   =============================================================== */
const messagesEl   = document.getElementById('messages');
const emptyStateEl = document.getElementById('emptyState');
const promptInput  = document.getElementById('promptInput');
const sendBtn      = document.getElementById('sendBtn');
const statusDot    = document.getElementById('statusDot');
const backendBar   = document.getElementById('backendBar');
const threadListEl = document.getElementById('threadList');
const newChatBtn   = document.getElementById('newChatBtn');
const clockEl      = document.getElementById('clock');
const uploadBtn    = document.getElementById('uploadBtn');
const pdfInput     = document.getElementById('pdfInput');

/* ===============================================================
   4) CLOCK — top bar mein time dikhana (sirf cosmetic)
   =============================================================== */
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

/* ===============================================================
   5) BACKEND HEALTH CHECK
   Server zinda hai ya nahi, ye check karne ke liye ek GET request
   maarte hain. Agar shell-mind mein "/health" route nahi hai to
   ye fail hoga — tab bhi UI kaam karega, bas dot yellow rahega jab
   tak tum message bhejo.
   =============================================================== */
async function checkBackend() {
  try {
    const res = await fetch(`${SERVER_URL}/health`, { method: 'GET' });
    if (res.ok) {
      statusDot.style.background = '#3FB950'; // green = connected
      backendBar.textContent = `Backend: connected (${SERVER_URL}) · RAG supervisor active · local only`;
    } else {
      throw new Error('not ok');
    }
  } catch (e) {
    statusDot.style.background = '#C99B3D'; // yellow = unknown / not confirmed
    backendBar.textContent = `Backend: ${SERVER_URL} (status unknown — will confirm on first message)`;
  }
}
checkBackend();

/* ===============================================================
   6) RENDER MESSAGES — chat bubbles ko screen par draw karna
   =============================================================== */
function renderMessages() {
  messagesEl.innerHTML = '';

  if (currentThread.length === 0) {
    messagesEl.appendChild(emptyStateEl);
    return;
  }

  currentThread.forEach(msg => {
    const div = document.createElement('div');
    div.className = `msg ${msg.role}${msg.error ? ' error' : ''}`;
    div.textContent = msg.text;
    messagesEl.appendChild(div);
  });

  messagesEl.scrollTop = messagesEl.scrollHeight; // hamesha neeche scroll
}

function showTypingIndicator() {
  const div = document.createElement('div');
  div.className = 'msg typing';
  div.id = 'typingIndicator';
  div.textContent = 'Local model is thinking...';
  messagesEl.appendChild(div);
  messagesEl.scrollTop = messagesEl.scrollHeight;
}
function removeTypingIndicator() {
  const el = document.getElementById('typingIndicator');
  if (el) el.remove();
}

/* ===============================================================
   7) SEND MESSAGE — ye asli "connect to backend" wala part hai
   =============================================================== */
async function sendMessage(text) {
  if (!text || !text.trim()) return;

  // 1. user ka message turant screen par dikhao
  currentThread.push({ role: 'user', text: text });
  renderMessages();
  promptInput.value = '';
  sendBtn.disabled = true;
  showTypingIndicator();

  try {
    // 2. shell-mind server ko POST /chat call karo
    const res = await fetch(`${SERVER_URL}/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ prompt: text })
    });

    removeTypingIndicator();

    if (!res.ok) {
      throw new Error(`Server returned status ${res.status}`);
    }

    // ui.py ke Gradio wrapper ke hisaab se response plain text hai
    const replyText = await res.text();

    currentThread.push({ role: 'bot', text: replyText });
    statusDot.style.background = '#3FB950'; // connect ho gaya, dot green
    backendBar.textContent = `Backend: connected (${SERVER_URL}) · RAG supervisor active · local only`;

  } catch (err) {
    removeTypingIndicator();
    currentThread.push({
      role: 'bot',
      error: true,
      text: `⚠ Server ${SERVER_URL} not reachable.\nCheck ki shell-mind backend (ai_core.py / supervisor) chal raha hai ya nahi, aur CORS enabled hai.\n\nDetail: ${err.message}`
    });
    statusDot.style.background = '#B84A4A'; // red = error
  }

  renderMessages();
  sendBtn.disabled = false;
  promptInput.focus();
}

/* ===============================================================
   8) EVENT LISTENERS — buttons aur inputs ko JS se jodna
   =============================================================== */

// Send button click
sendBtn.addEventListener('click', () => sendMessage(promptInput.value));

// Enter key se bhi bhej sako
promptInput.addEventListener('keydown', (e) => {
  if (e.key === 'Enter') sendMessage(promptInput.value);
});

// Suggestion chips par click karne se wo text seedha bhej jaye
document.querySelectorAll('.chip').forEach(chip => {
  chip.addEventListener('click', () => {
    sendMessage(chip.getAttribute('data-text'));
  });
});

// New chat button — current thread ko save karke naya thread shuru karo
newChatBtn.addEventListener('click', () => {
  if (currentThread.length > 0) {
    const title = currentThread[0].text.slice(0, 30) || 'New chat';
    allThreads.unshift({ title, messages: currentThread });
    renderThreadList();
  }
  currentThread = [];
  renderMessages();
});

function renderThreadList() {
  threadListEl.innerHTML = '';
  allThreads.slice(0, 8).forEach((t) => {
    const div = document.createElement('div');
    div.className = 'thread-item';
    div.textContent = t.title;
    div.addEventListener('click', () => {
      currentThread = t.messages;
      renderMessages();
    });
    threadListEl.appendChild(div);
  });
}

// PDF upload — file select karke server ko /upload route par bhejta hai
// (shell-mind ke upload route ka naam apne backend code se confirm kar lena)
uploadBtn.addEventListener('click', () => pdfInput.click());
pdfInput.addEventListener('change', async () => {
  const file = pdfInput.files[0];
  if (!file) return;

  const formData = new FormData();
  formData.append('file', file);

  try {
    const res = await fetch(`${SERVER_URL}/upload`, {
      method: 'POST',
      body: formData
    });
    if (res.ok) {
      currentThread.push({ role: 'bot', text: `📄 "${file.name}" uploaded for RAG indexing.` });
    } else {
      throw new Error(`status ${res.status}`);
    }
  } catch (err) {
    currentThread.push({ role: 'bot', error: true, text: `⚠ Upload failed: ${err.message}. Check "/upload" route apne shell-mind server mein hai ya nahi.` });
  }
  renderMessages();
});

// Initial render
renderMessages();
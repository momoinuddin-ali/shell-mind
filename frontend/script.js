const SERVER_URL = "http://localhost:8000"; 

let currentThread = [];      
let allThreads = [];         
let currentImagePath = null; // Holds the uploaded image for the next prompt

const messagesEl     = document.getElementById('messages');
const emptyStateEl   = document.getElementById('emptyState');
const promptInput    = document.getElementById('promptInput');
const sendBtn        = document.getElementById('sendBtn');
const statusDot      = document.getElementById('statusDot');
const backendBar     = document.getElementById('backendBar');
const threadListEl   = document.getElementById('threadList');
const newChatBtn     = document.getElementById('newChatBtn');
const clockEl        = document.getElementById('clock');
const uploadBtn      = document.getElementById('uploadBtn');
const pdfInput       = document.getElementById('pdfInput');

// Vision Upload Elements
const attachBtn      = document.getElementById('attachBtn');
const visionInput    = document.getElementById('visionInput');
const imageIndicator = document.getElementById('imageIndicator');
const imageName      = document.getElementById('imageName');

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
    const res = await fetch(`${SERVER_URL}/health`, { method: 'GET' });
    if (res.ok) {
      statusDot.style.background = '#3FB950'; 
      backendBar.textContent = `Backend: connected (${SERVER_URL}) · RAG supervisor active · local only`;
    } else {
      throw new Error('not ok');
    }
  } catch (e) {
    statusDot.style.background = '#C99B3D'; 
    backendBar.textContent = `Backend: ${SERVER_URL} (status unknown — will confirm on first message)`;
  }
}
checkBackend();

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
  messagesEl.scrollTop = messagesEl.scrollHeight; 
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

async function sendMessage(text) {
  if (!text || !text.trim()) return;

  currentThread.push({ role: 'user', text: text });
  renderMessages();
  promptInput.value = '';
  sendBtn.disabled = true;
  showTypingIndicator();

  try {
    const selectedMode = document.getElementById('modeSelect').value;
    
    // Attach the image path if one was uploaded
    const payload = { prompt: text, mode: selectedMode };
    if (currentImagePath) {
      payload.image_path = currentImagePath;
    }

    const res = await fetch(`${SERVER_URL}/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });

    removeTypingIndicator();

    if (!res.ok) throw new Error(`Server returned status ${res.status}`);

    const data = await res.json();
    currentThread.push({ role: 'bot', text: data.answer });
    statusDot.style.background = '#3FB950'; 
    backendBar.textContent = `Backend: connected (${SERVER_URL}) · RAG supervisor active · local only`;

    // Clear the image attachment after a successful send
    currentImagePath = null;
    imageIndicator.style.display = 'none';
    visionInput.value = "";

  } catch (err) {
    removeTypingIndicator();
    currentThread.push({
      role: 'bot',
      error: true,
      text: `⚠ Server ${SERVER_URL} not reachable.\nDetail: ${err.message}`
    });
    statusDot.style.background = '#B84A4A'; 
  }

  renderMessages();
  sendBtn.disabled = false;
  promptInput.focus();
}

sendBtn.addEventListener('click', () => sendMessage(promptInput.value));
promptInput.addEventListener('keydown', (e) => {
  if (e.key === 'Enter') sendMessage(promptInput.value);
});

document.querySelectorAll('.chip').forEach(chip => {
  chip.addEventListener('click', () => {
    sendMessage(chip.getAttribute('data-text'));
  });
});

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

// Vision Upload Logic
attachBtn.addEventListener('click', () => visionInput.click());
visionInput.addEventListener('change', async () => {
  const file = visionInput.files[0];
  if (!file) return;

  const formData = new FormData();
  formData.append('file', file);

  try {
    const res = await fetch(`${SERVER_URL}/upload_image`, {
      method: 'POST',
      body: formData
    });
    if (res.ok) {
      const data = await res.json();
      currentImagePath = data.image_path;
      imageName.textContent = file.name;
      imageIndicator.style.display = 'block';
    } else {
      throw new Error(`status ${res.status}`);
    }
  } catch (err) {
    alert("Image upload failed. Is the backend server running?");
  }
});

// PDF upload logic remains unchanged
uploadBtn.addEventListener('click', () => pdfInput.click());
pdfInput.addEventListener('change', async () => {
  const file = pdfInput.files[0];
  if (!file) return;
  const formData = new FormData();
  formData.append('file', file);
  try {
    const res = await fetch(`${SERVER_URL}/upload`, { method: 'POST', body: formData });
    if (res.ok) {
      currentThread.push({ role: 'bot', text: `📄 "${file.name}" uploaded for RAG indexing.` });
    } else throw new Error(`status ${res.status}`);
  } catch (err) {
    currentThread.push({ role: 'bot', error: true, text: `⚠ Upload failed: ${err.message}.` });
  }
  renderMessages();
});

renderMessages();
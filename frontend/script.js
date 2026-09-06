const SERVER_URL = "http://localhost:8000"; 

let currentThread = [];      
let allThreads = [];         
let currentImagePath = null; 
let currentPdfPath = null;
let activeThreadIndex = 0; 

// Load history
const savedThreads = localStorage.getItem('shellMindThreads');
if (savedThreads) {
  allThreads = JSON.parse(savedThreads);
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

// Attachments
const attachBtn      = document.getElementById('attachBtn');
const visionInput    = document.getElementById('visionInput');
const imageIndicator = document.getElementById('imageIndicator');
const imageName      = document.getElementById('imageName');

// PDF Upload
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
    const res = await fetch(`${SERVER_URL}/health`, { method: 'GET' });
    if (res.ok) {
      statusDot.style.background = '#3FB950'; 
      statusDot.style.boxShadow = '0 0 8px #3FB950';
      backendBar.textContent = `Backend: Connected (${SERVER_URL}) · RTX 5050 Active`;
    } else {
      throw new Error('not ok');
    }
  } catch (e) {
    statusDot.style.background = '#C99B3D'; 
    statusDot.style.boxShadow = '0 0 8px #C99B3D';
    backendBar.textContent = `Backend: ${SERVER_URL} (Status unknown — awaiting first prompt)`;
  }
}
checkBackend();

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
      // Parse <think> tags for the Expander
      const text = msg.text;
      const thinkMatch = text.match(/<think>([\s\S]*?)<\/think>/);
      
      if (thinkMatch) {
        const thoughtProcess = thinkMatch[1].trim();
        const finalAnswer = text.replace(thinkMatch[0], '').trim();
        
        div.innerHTML = `
          <details class="thought-process">
            <summary>🧠 View AI's Thought Process</summary>
            <div class="thought-content">${thoughtProcess}</div>
          </details>
          <div class="final-answer">${finalAnswer}</div>
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

// --- Neural Network Loader ---
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

function removeTypingIndicator() {
  const el = document.getElementById('typingIndicator');
  if (el) el.remove();
}

async function sendMessage(text) {
  if (!text || !text.trim()) return;

  currentThread.push({ role: 'user', text: text });
  
  if (currentThread.length === 1) {
    const title = text.slice(0, 22) + (text.length > 22 ? "..." : "");
    if (allThreads[activeThreadIndex]) {
        allThreads[activeThreadIndex].title = title;
    } else {
        allThreads.unshift({ title, messages: currentThread });
        activeThreadIndex = 0;
    }
    renderThreadList();
  }
  
  renderMessages();
  promptInput.value = '';
  sendBtn.disabled = true;
  showTypingIndicator();

  try {
    const selectedMode = document.getElementById('modeSelect').value;
    const payload = { prompt: text, mode: selectedMode };
    
    // Attach paths if files are present
    if (currentImagePath) payload.image_path = currentImagePath;
    if (currentPdfPath) payload.document_path = currentPdfPath; 

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
    statusDot.style.boxShadow = '0 0 8px #3FB950';

    // Clear attachments after successful send
    currentImagePath = null;
    currentPdfPath = null;
    imageIndicator.style.display = 'none';
    pdfIndicator.style.display = 'none';
    visionInput.value = "";
    pdfInput.value = "";

  } catch (err) {
    removeTypingIndicator();
    currentThread.push({
      role: 'bot',
      error: true,
      text: `⚠ Server ${SERVER_URL} not reachable.\nDetail: ${err.message}`
    });
    statusDot.style.background = '#B84A4A'; 
    statusDot.style.boxShadow = '0 0 8px #B84A4A';
  }

  // Save to local storage
  if (allThreads[activeThreadIndex]) {
      allThreads[activeThreadIndex].messages = currentThread;
  }
  localStorage.setItem('shellMindThreads', JSON.stringify(allThreads));

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

// --- Sidebar Buttons ---
newChatBtn.addEventListener('click', () => {
  currentThread = [];
  allThreads.unshift({ title: "New Chat", messages: [] });
  activeThreadIndex = 0;
  localStorage.setItem('shellMindThreads', JSON.stringify(allThreads));
  renderThreadList();
  renderMessages();
});

clearAllBtn.addEventListener('click', () => {
  if(confirm("Are you sure you want to delete all local chat history?")) {
    allThreads = [];
    currentThread = [];
    localStorage.removeItem('shellMindThreads');
    renderThreadList();
    renderMessages();
  }
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

// --- Attachments (Image & PDF) ---
attachBtn.addEventListener('click', () => visionInput.click());
visionInput.addEventListener('change', async () => {
  const file = visionInput.files[0];
  if (!file) return;
  const formData = new FormData();
  formData.append('file', file);
  try {
    const res = await fetch(`${SERVER_URL}/upload_image`, { method: 'POST', body: formData });
    if (res.ok) {
      const data = await res.json();
      currentImagePath = data.image_path;
      imageName.textContent = file.name;
      imageIndicator.style.display = 'block';
    } else throw new Error();
  } catch (err) {
    alert("Image upload failed. Ensure FastAPI backend is running.");
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
    const res = await fetch(`${SERVER_URL}/upload`, { method: 'POST', body: formData });
    if (res.ok) {
        const data = await res.json();
        currentPdfPath = data.document_path; 
        pdfName.textContent = file.name + " (Ready for processing)";
    } else {
        throw new Error();
    }
  } catch (err) {
    alert("PDF upload failed. Ensure backend is running.");
    pdfIndicator.style.display = 'none';
  }
});

renderThreadList();
renderMessages();
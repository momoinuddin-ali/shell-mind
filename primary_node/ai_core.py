"""
ai_core.py — SHELL MIND server (final merge: product layer + engine).
"""

import gc
import uuid
import logging
import os
import shutil
import tempfile
import threading
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, Union

from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)-7s %(message)s",
                    datefmt="%H:%M:%S")

# ==========================================
# 0. DATABASE INITIALIZATION (For the Professor!)
# ==========================================
DB_PATH = "shell_mind_history.db"

def init_db():
    """Creates a local relational database to log all AI interactions."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS interactions
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  timestamp TEXT,
                  compute_mode TEXT,
                  prompt TEXT,
                  response TEXT,
                  attached_file TEXT)''')
    conn.commit()
    conn.close()
    print(f"🗄️ Database initialized at {DB_PATH}")

init_db()

def log_to_db(mode: str, prompt: str, response: str, attached_file: str = "None"):
    """Saves the chat to the SQLite database."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO interactions (timestamp, compute_mode, prompt, response, attached_file) VALUES (?, ?, ?, ?, ?)",
              (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), mode, prompt, response, attached_file))
    conn.commit()
    conn.close()

# ==========================================
# 1. CACHE SETUP 
# ==========================================
_WS_ROOT = Path(__file__).resolve().parents[2]
CACHE = str(_WS_ROOT / "models" / "hf_cache")

os.environ["HF_HOME"] = CACHE
os.environ["HF_HUB_CACHE"] = str(Path(CACHE) / "hub")
os.environ["TRANSFORMERS_CACHE"] = str(Path(CACHE) / "hub")

from workstation.model_zoo import get_zoo                  # noqa: E402
from workstation.orchestrator import run_agentic_pipeline  # noqa: E402
import torch                                               # noqa: E402
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig # noqa: E402

# ==========================================
# 2. FASTAPI SETUP
# ==========================================
app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# ==========================================
# 3. HARDWARE DETECTION
# ==========================================
HAS_GPU = torch.cuda.is_available()
model: Any = None
tokenizer: Any = None

if HAS_GPU:
    MODEL_ID = "Qwen/Qwen2.5-Coder-7B-Instruct"
    device_map: Union[Dict[str, Any], str] = {"": "cuda:0"}
    torch_dtype = torch.bfloat16
    quant_config = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_compute_dtype=torch.bfloat16, bnb_4bit_quant_type="nf4")
else:
    MODEL_ID = "Qwen/Qwen2.5-0.5B-Instruct"
    device_map = {"": "cpu"}
    torch_dtype = torch.float32
    quant_config = None

tokenizer = AutoTokenizer.from_pretrained(MODEL_ID)
model = AutoModelForCausalLM.from_pretrained(MODEL_ID, quantization_config=quant_config, device_map=device_map, torch_dtype=torch_dtype)

# ==========================================
# 4. MODE MANAGEMENT
# ==========================================
GEN_LOCK = threading.Lock()
_tier: Dict[str, str] = {"current": "copilot"}

def _evict_copilot() -> None:
    global model, tokenizer
    if model is None: return
    model = None
    tokenizer = None
    gc.collect(); gc.collect()
    torch.cuda.empty_cache(); torch.cuda.ipc_collect()

def _ensure_copilot() -> None:
    global model, tokenizer
    if model is not None: return
    if HAS_GPU:
        zoo = get_zoo()
        zoo.unload_worker()
        zoo.unload_resident()
    tokenizer = AutoTokenizer.from_pretrained(MODEL_ID)
    model = AutoModelForCausalLM.from_pretrained(MODEL_ID, quantization_config=quant_config, device_map=device_map, torch_dtype=torch_dtype)
    _tier["current"] = "copilot"
#IT MAKES THE FILE SAFE AND GIVE UNIQUE NAME TO EVERY FILE
ALLOWED_EXT={".jpeg",".png",".jpg",".gif",".pdf",".txt",".csv"}

MAX_UPLOAD_BYTES=25*1024*1024

def _save_upload(file: UploadFile) -> str:
   
    if not file.filename:
        return ""
    suffix = Path(file.filename).suffix.lower()
    if suffix not in ALLOWED_EXT:          # whitelist = traversal ka aadhaar hi khatam
        return ""
    save_path = Path(tempfile.gettempdir()) / f"{uuid.uuid4().hex}{suffix}"
    written = 0
    try:
        with open(save_path, "wb") as out:
            while chunk := file.file.read(1024 * 1024):
                written += len(chunk)
                if written > MAX_UPLOAD_BYTES:
                    raise ValueError("too large")
                out.write(chunk)
    except ValueError:
        save_path.unlink(missing_ok=True)
        return ""
    return str(save_path)

# ==========================================
# 5. API ENDPOINTS
# ==========================================
class UserRequest(BaseModel):
    prompt: str
    mode: str = "gpu"
    image_path: Optional[str] = None
    document_path: Optional[str] = None  

@app.get("/health")
def health_check() -> Dict[str, Any]:
    info: Dict[str, Any] = {"status": "ok", "tier": _tier["current"]}
    if HAS_GPU:
        try:
            info.update(get_zoo().status())
        except Exception:
            pass
    return info

@app.post("/upload_image")
def upload_image_endpoint(file: UploadFile = File(...)) -> Dict[str, str]:
      return {"image_path": _save_upload(file)}


@app.post("/upload")
def upload_document_endpoint(file: UploadFile = File(...)) -> Dict[str, str]:
    path = _save_upload(file)
    return {"document_path": path, "status": "stored_for_processing" if path else "rejected"}
@app.post("/chat")
def ask_ai(request: UserRequest) -> Dict[str, Any]:
    with GEN_LOCK:
        # --- PDF "LITE" EXTRACTION ---
        pdf_context = ""
        file_logged = "None"
        if request.document_path and os.path.exists(request.document_path):
            file_logged = os.path.basename(request.document_path)
            try:
                import PyPDF2
                with open(request.document_path, "rb") as f:
                    reader = PyPDF2.PdfReader(f)
                    extracted = "".join([page.extract_text() or "" for page in reader.pages[:3]])
                    pdf_context = f"\n\n[CONTEXT FROM UPLOADED PDF]:\n{extracted[:3000]}...\n\n"
            except Exception as e:
                print(f"⚠️ Failed to read PDF: {e}")

        if request.image_path:
            file_logged = os.path.basename(request.image_path)

        final_prompt = request.prompt + pdf_context

        # --- TIER 3: AGENT WORKSTATION ---
        if request.mode == "agent":
            if _tier["current"] != "agent":
                _evict_copilot()
                _tier["current"] = "agent"
            try:
                result = run_agentic_pipeline(final_prompt, image_path=request.image_path)
                answer_text = f"🤖 Agent Workstation [{str(result.get('task', 'agent')).upper()}]\n\n{result.get('answer', '')}"
                log_to_db("Agent Pipeline", request.prompt, answer_text, file_logged)
                return {"answer": answer_text, "stages": result.get("stages"), "total_s": result.get("total_s")}
            except Exception as exc:
                err_name = type(exc).__name__
                del exc
                get_zoo().purge()
                return {"answer": f"⚠️ Agent pipeline error ({err_name}). VRAM purged — try again."}

        # --- TIER 1 & 2: CPU LITE / GPU COPILOT ---
        _ensure_copilot()
        messages = [
            {"role": "system", "content": "You are a highly capable coding assistant."},
            {"role": "user", "content": final_prompt},
        ]
        formatted_prompt = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        inputs = tokenizer(formatted_prompt, return_tensors="pt").to(model.device)

        with torch.inference_mode():
            outputs = model.generate(**inputs, max_new_tokens=1500, do_sample=True, temperature=0.6, pad_token_id=tokenizer.eos_token_id)

        input_length = inputs["input_ids"].shape[1]
        reply = tokenizer.decode(outputs[0][input_length:], skip_special_tokens=True).strip()
        
        log_to_db(request.mode.upper(), request.prompt, reply, file_logged)
        return {"answer": reply}
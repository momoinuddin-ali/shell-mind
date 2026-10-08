"""
ai_core.py — the Shell-Mind FastAPI server (product layer + engine wiring).

Responsibilities:
  * Tier switching: CPU Lite (0.5B) / GPU Copilot (7B) / Agent Workstation,
    with zero-sum eviction — only one tier's models ever hold VRAM.
  * Upload handling: extension whitelist, 25 MB cap, server-issued paths.
    /chat only ever opens files this server itself stored.
  * RAG-lite context injection for uploaded documents (PDF / TXT / CSV).
  * Append-only SQLite audit log of every interaction.

The copilot models load lazily on the first request of each tier, so the
server accepts connections within seconds of start.

Run single-worker from the repo root, then open http://localhost:8000
for the web UI (the API server serves the frontend itself):
    uvicorn primary_node.ai_core:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import gc
import logging
import os
import sqlite3
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Literal, Optional

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from workstation import paths

os.environ.setdefault("HF_HOME", str(paths.HF_HOME))
os.environ.setdefault("HF_HUB_CACHE", str(paths.HF_HUB_CACHE))
os.environ.setdefault("TRANSFORMERS_CACHE", str(paths.HF_HUB_CACHE))

from workstation.model_zoo import get_zoo                  # noqa: E402
from workstation.orchestrator import run_agentic_pipeline  # noqa: E402
import torch                                               # noqa: E402
from transformers import (                                 # noqa: E402
    AutoModelForCausalLM,
    AutoTokenizer,
    BitsAndBytesConfig,
)

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger("shell-mind.server")

# ==========================================
# 1. AUDIT LOG (append-only SQLite)
# ==========================================
def init_db() -> None:
    conn = sqlite3.connect(paths.DB_PATH)
    conn.execute("""CREATE TABLE IF NOT EXISTS interactions
                    (id INTEGER PRIMARY KEY AUTOINCREMENT,
                     timestamp TEXT,
                     compute_mode TEXT,
                     prompt TEXT,
                     response TEXT,
                     attached_file TEXT)""")
    conn.commit()
    conn.close()
    log.info("audit log ready at %s", paths.DB_PATH)


def log_to_db(mode: str, prompt: str, response: str,
              attached_file: str = "None") -> None:
    conn = sqlite3.connect(paths.DB_PATH)
    conn.execute(
        "INSERT INTO interactions (timestamp, compute_mode, prompt, response, attached_file) "
        "VALUES (?, ?, ?, ?, ?)",
        (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), mode, prompt,
         response, attached_file),
    )
    conn.commit()
    conn.close()


init_db()

# ==========================================
# 2. UPLOAD HANDLING (server-issued paths only)
# ==========================================
ALLOWED_EXT = {".jpeg", ".jpg", ".png", ".gif", ".pdf", ".txt", ".csv"}
MAX_UPLOAD_BYTES = 25 * 1024 * 1024      # keep in sync with the frontend label
UPLOAD_MAX_AGE_S = 24 * 3600             # stale uploads are purged on each new upload

paths.UPLOADS_DIR.mkdir(parents=True, exist_ok=True)


def _purge_stale_uploads() -> None:
    """Best-effort cleanup so the uploads directory never grows unbounded."""
    try:
        cutoff = time.time() - UPLOAD_MAX_AGE_S
        for f in paths.UPLOADS_DIR.iterdir():
            if f.is_file() and f.stat().st_mtime < cutoff:
                f.unlink(missing_ok=True)
    except OSError as exc:
        log.warning("upload purge failed: %s", exc)


def _save_upload(file: UploadFile) -> Path:
    """Validate and store an upload under a fresh UUID name in UPLOADS_DIR.

    The original filename never touches the filesystem — only the
    whitelisted extension does — which removes any path-traversal surface.
    """
    if not file.filename:
        raise HTTPException(400, "upload has no filename")
    suffix = Path(file.filename).suffix.lower()
    if suffix not in ALLOWED_EXT:
        raise HTTPException(
            415, f"file type '{suffix or '(none)'}' not allowed "
                 f"(allowed: {', '.join(sorted(ALLOWED_EXT))})")

    _purge_stale_uploads()
    save_path = paths.UPLOADS_DIR / f"{uuid.uuid4().hex}{suffix}"
    written = 0
    try:
        with open(save_path, "wb") as out:
            while chunk := file.file.read(1024 * 1024):
                written += len(chunk)
                if written > MAX_UPLOAD_BYTES:
                    raise HTTPException(
                        413, f"upload exceeds the "
                             f"{MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit")
                out.write(chunk)
    except HTTPException:
        save_path.unlink(missing_ok=True)
        raise
    except OSError as exc:
        save_path.unlink(missing_ok=True)
        raise HTTPException(500, f"failed to store upload: {exc}") from exc
    return save_path


def _validated_upload(path_str: Optional[str]) -> Optional[Path]:
    """Resolve a client-supplied path to a file this server stored.

    Anything outside UPLOADS_DIR (or no longer on disk) is rejected —
    /chat must never become an arbitrary-file-read primitive on the
    machine running the server.
    """
    if not path_str:
        return None
    resolved = Path(path_str).resolve()
    if paths.UPLOADS_DIR.resolve() not in resolved.parents:
        raise HTTPException(
            400, "path was not issued by this server — "
                 "upload the file via /upload or /upload_image first")
    if not resolved.is_file():
        raise HTTPException(404, "uploaded file no longer exists — upload it again")
    return resolved


def _document_context(doc: Optional[Path]) -> str:
    """RAG-lite: first 3 pages of a PDF, or the first 3 000 chars of a
    plain-text document, injected into the prompt."""
    if doc is None:
        return ""
    try:
        if doc.suffix.lower() == ".pdf":
            import PyPDF2
            with open(doc, "rb") as f:
                reader = PyPDF2.PdfReader(f)
                text = "".join(page.extract_text() or ""
                               for page in reader.pages[:3])
        else:                                   # .txt / .csv
            text = doc.read_text(errors="ignore")
        if not text.strip():
            return ""
        return (f"\n\n[CONTEXT FROM UPLOADED DOCUMENT '{doc.name}']:\n"
                f"{text[:3000]}\n\n")
    except Exception as exc:
        log.warning("failed to extract context from %s: %s", doc.name, exc)
        return ""

# ==========================================
# 3. FASTAPI SETUP & HARDWARE DETECTION
# ==========================================
app = FastAPI(title="Shell-Mind")
# Local workstation served to a trusted LAN/Tailscale network; the clients
# are plain browsers/CLIs with no cookies, so wildcard origins are fine —
# credentials stay disabled (an invalid CORS combination anyway).
app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_credentials=False, allow_methods=["*"],
                   allow_headers=["*"])

HAS_GPU = torch.cuda.is_available()

# ==========================================
# 4. COPILOT TIERS (lazy-loaded, zero-sum with the agent zoo)
# ==========================================
COPILOT_IDS = {
    "gpu": "Qwen/Qwen2.5-Coder-7B-Instruct",   # 4-bit NF4 on the GPU
    "cpu": "Qwen/Qwen2.5-0.5B-Instruct",       # fp32 on CPU, GPU stays free
}

model: Any = None
tokenizer: Any = None
_copilot_key: Dict[str, Optional[str]] = {"tier": None}   # None | "gpu" | "cpu"
_tier: Dict[str, str] = {"current": "cpu" if not HAS_GPU else "copilot-idle"}

GEN_LOCK = threading.Lock()


def _note_zoo(event: str) -> None:
    """Record copilot swaps on the zoo's VRAM timeline (GPU hosts only)."""
    if not HAS_GPU:
        return
    try:
        get_zoo().note(event)
    except Exception:
        pass


def _evict_copilot() -> None:
    global model, tokenizer
    if model is not None:
        model = None
        tokenizer = None
        gc.collect(); gc.collect()
        if HAS_GPU:
            torch.cuda.empty_cache()
            torch.cuda.ipc_collect()
        _note_zoo("copilot:unloaded")
    _copilot_key["tier"] = None


def _ensure_copilot(want: str) -> None:
    """Load the requested copilot tier, evicting whatever currently
    owns GPU memory (previous copilot or agent-zoo models)."""
    global model, tokenizer
    if want == "gpu" and not HAS_GPU:
        want = "cpu"
    if _copilot_key["tier"] == want and model is not None:
        return

    _evict_copilot()
    if HAS_GPU:
        zoo = get_zoo()
        zoo.unload_worker()
        zoo.unload_resident()

    model_id = COPILOT_IDS[want]
    if want == "gpu":
        quant = BitsAndBytesConfig(load_in_4bit=True,
                                   bnb_4bit_compute_dtype=torch.bfloat16,
                                   bnb_4bit_quant_type="nf4")
        device_map: Any = {"": 0}
        dtype: Any = torch.bfloat16
    else:
        quant = None
        device_map = {"": "cpu"}
        dtype = torch.float32

    t0 = time.perf_counter()
    log.info("loading copilot (%s): %s ...", want, model_id)
    tokenizer = AutoTokenizer.from_pretrained(model_id)
    model = AutoModelForCausalLM.from_pretrained(
        model_id, quantization_config=quant, device_map=device_map,
        torch_dtype=dtype)
    _copilot_key["tier"] = want
    _tier["current"] = want
    _note_zoo(f"copilot:{want}")
    log.info("copilot '%s' ready in %.1fs", want, time.perf_counter() - t0)

# ==========================================
# 5. API ENDPOINTS
# ==========================================
class UserRequest(BaseModel):
    prompt: str
    mode: Literal["cpu", "gpu", "agent"] = "gpu"
    image_path: Optional[str] = None
    document_path: Optional[str] = None


@app.get("/health")
def health_check() -> Dict[str, Any]:
    info: Dict[str, Any] = {"status": "ok", "tier": _tier["current"],
                            "gpu": HAS_GPU}
    if HAS_GPU:
        try:
            info.update(get_zoo().status())
        except Exception:
            pass
    return info


@app.post("/upload_image")
def upload_image_endpoint(file: UploadFile = File(...)) -> Dict[str, str]:
    return {"image_path": str(_save_upload(file))}


@app.post("/upload")
def upload_document_endpoint(file: UploadFile = File(...)) -> Dict[str, str]:
    return {"document_path": str(_save_upload(file)),
            "status": "stored_for_processing"}


@app.post("/chat")
def ask_ai(request: UserRequest) -> Dict[str, Any]:
    with GEN_LOCK:
        # Paths are validated BEFORE any model work: only files this
        # server stored may enter a prompt.
        doc = _validated_upload(request.document_path)
        img = _validated_upload(request.image_path)
        file_logged = doc.name if doc else (img.name if img else "None")

        final_prompt = request.prompt + _document_context(doc)

        # --- TIER 3: AGENT WORKSTATION ---
        if request.mode == "agent":
            if not HAS_GPU:
                return {"answer": "⚠️ The Agent Workstation requires CUDA. "
                                  "Use mode 'cpu' or 'gpu' on this host."}
            if _tier["current"] != "agent":
                _evict_copilot()
                _tier["current"] = "agent"
            try:
                result = run_agentic_pipeline(final_prompt,
                                              image_path=str(img) if img else None)
                answer_text = (f"🤖 Agent Workstation "
                               f"[{str(result.get('task', 'agent')).upper()}]\n\n"
                               f"{result.get('answer', '')}")
                log_to_db("Agent Pipeline", request.prompt, answer_text,
                          file_logged)
                return {"answer": answer_text,
                        "stages": result.get("stages"),
                        "total_s": result.get("total_s")}
            except Exception as exc:
                err_name = type(exc).__name__
                del exc      # drop the traceback's frame references first
                get_zoo().purge()
                log_to_db("Agent Pipeline", request.prompt,
                          f"(error: {err_name})", file_logged)
                return {"answer": f"⚠️ Agent pipeline error ({err_name}). "
                                  f"VRAM purged — try again."}

        # --- TIER 1 & 2: CPU LITE / GPU COPILOT ---
        _ensure_copilot(request.mode)
        messages = [
            {"role": "system", "content": "You are a highly capable coding assistant."},
            {"role": "user", "content": final_prompt},
        ]
        formatted_prompt = tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True)
        inputs = tokenizer(formatted_prompt, return_tensors="pt").to(model.device)

        with torch.inference_mode():
            outputs = model.generate(**inputs, max_new_tokens=1500,
                                     do_sample=True, temperature=0.6,
                                     pad_token_id=tokenizer.eos_token_id)

        input_length = inputs["input_ids"].shape[1]
        reply = tokenizer.decode(outputs[0][input_length:],
                                 skip_special_tokens=True).strip()

        log_to_db(request.mode.upper(), request.prompt, reply, file_logged)
        return {"answer": reply}

# ==========================================
# 6. FRONTEND — served by the API server itself
# ==========================================
# Mounting the UI on the same origin removes the need for a separate
# static server: one terminal, one port, no CORS round-trip for the
# browser. API routes above take precedence over this catch-all mount.
_FRONTEND_DIR = paths.REPO_ROOT / "frontend"
if _FRONTEND_DIR.is_dir():
    app.mount("/", StaticFiles(directory=_FRONTEND_DIR, html=True),
              name="frontend")

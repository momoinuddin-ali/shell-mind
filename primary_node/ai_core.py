"""
ai_core.py — the Shell-Mind FastAPI server (product layer + engine wiring).

Responsibilities:
  * Tier switching: CPU Lite / GPU Copilot / Agent Workstation,
    with zero-sum eviction — only one tier's models ever hold VRAM.
  * Upload handling: extension whitelist, 25 MB cap, server-issued paths.
    /chat only ever opens files this server itself stored.
  * RAG-lite context injection for uploaded documents (PDF / TXT / CSV).
  * Append-only SQLite audit log of every interaction.
  * Optional API-key auth + per-IP rate limiting to protect the GPU.

The copilot models load lazily on the first request of each tier, so the
server accepts connections within seconds of start.

Run single-worker from the repo root, then open http://localhost:8000
for the web UI (the API server serves the frontend itself):
    uvicorn primary_node.ai_core:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations
import json 
import gc
import logging
import hmac
import os
import secrets
import sqlite3
import threading
import time
import uuid
from collections import defaultdict, deque
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Literal, Optional

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from workstation import paths

os.environ.setdefault("HF_HOME", str(paths.HF_HOME))
os.environ.setdefault("HF_HUB_CACHE", str(paths.HF_HUB_CACHE))
os.environ.setdefault("TRANSFORMERS_CACHE", str(paths.HF_HUB_CACHE))

from workstation.model_zoo import (
    has_model,                         # noqa: E402
    get_zoo, REGISTRY, role_key, active_models_summary,
)
from workstation.orchestrator import run_agentic_pipeline  # noqa: E402
import torch                                               # noqa: E402
from transformers import (                                 # noqa: E402
    AutoModelForCausalLM,
    AutoTokenizer,
    BitsAndBytesConfig,
    TextIteratorStreamer,
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
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("""CREATE TABLE IF NOT EXISTS interactions
                    (id INTEGER PRIMARY KEY AUTOINCREMENT,
                     timestamp TEXT,
                     compute_mode TEXT,
                     prompt TEXT,
                     response TEXT,
                     attached_file TEXT)""")
    try:
        conn.execute("ALTER TABLE interactions ADD COLUMN client TEXT DEFAULT 'unknown'")
    except sqlite3.OperationalError:
        pass        # column already exists
    conn.commit()
    conn.close()
    log.info("audit log ready at %s", paths.DB_PATH)


_AUDIT_MAX_BYTES = int(os.environ.get("SHELL_MIND_AUDIT_MAX_BYTES", str(50 * 1024 * 1024)))


def _rotate_audit_db_if_needed() -> None:
    """L10: when the audit DB grows past the cap, rotate to .1.db (keep one generation)."""
    try:
        db = Path(paths.DB_PATH)
        if not db.is_file() or db.stat().st_size < _AUDIT_MAX_BYTES:
            return
        rotated = db.with_suffix(db.suffix + ".1")
        if rotated.exists():
            rotated.unlink()
        db.rename(rotated)
        log.info("audit log rotated -> %s (size exceeded %d bytes)",
                 rotated, _AUDIT_MAX_BYTES)
    except OSError as exc:
        log.warning("audit rotation skipped: %s", exc)


def log_to_db(mode: str, prompt: str, response: str,
              attached_file: str = "None", client: str = "unknown") -> None:
    _rotate_audit_db_if_needed()
    conn = sqlite3.connect(paths.DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL;")
    # Re-create schema if we just rotated the file away
    conn.execute("""CREATE TABLE IF NOT EXISTS interactions
                    (id INTEGER PRIMARY KEY AUTOINCREMENT,
                     timestamp TEXT,
                     compute_mode TEXT,
                     prompt TEXT,
                     response TEXT,
                     attached_file TEXT,
                     client TEXT DEFAULT 'unknown')""")
    conn.execute(
        "INSERT INTO interactions (timestamp, compute_mode, prompt, response, attached_file, client) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), mode, prompt,
         response, attached_file, client),
    )
    conn.commit()
    conn.close()


init_db()

# ==========================================
# 2. UPLOAD HANDLING (server-issued paths only)
# ==========================================
ALLOWED_EXT = {".jpeg", ".jpg", ".png", ".gif", ".pdf", ".txt", ".csv"}
MAX_UPLOAD_BYTES = 25 * 1024 * 1024      # keep in sync with the frontend label
UPLOAD_MAX_AGE_S = 24 * 3600             # stale uploads are purged
UPLOADS_TOTAL_CAP_BYTES = 500 * 1024 * 1024   # disk-fill guard across ALL uploads

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


# Purge on startup so leftover files from previous sessions don't linger
# until the next upload arrives.
_purge_stale_uploads()


def _uploads_dir_bytes() -> int:
    """Total bytes currently stored in uploads/ (disk-fill guard)."""
    total = 0
    try:
        for f in paths.UPLOADS_DIR.iterdir():
            try:
                if f.is_file():
                    total += f.stat().st_size
            except OSError:
                continue
    except OSError:
        pass
    return total


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
    stored_total = _uploads_dir_bytes()
    if stored_total >= UPLOADS_TOTAL_CAP_BYTES:
        raise HTTPException(413, "server upload storage is full — try again later")
    save_path = paths.UPLOADS_DIR / f"{uuid.uuid4().hex}{suffix}"
    written = 0
    committed = False
    try:
        with open(save_path, "wb") as out:
            while chunk := file.file.read(1024 * 1024):
                written += len(chunk)
                if written > MAX_UPLOAD_BYTES:
                    raise HTTPException(
                        413, f"upload exceeds the "
                             f"{MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit")
                if stored_total + written > UPLOADS_TOTAL_CAP_BYTES:
                    raise HTTPException(413, "server upload storage limit reached")
                out.write(chunk)

        # M5: content sniff — extension alone is not enough
        head = save_path.read_bytes()[:16]
        if suffix == ".pdf":
            if not head.startswith(b"%PDF"):
                raise HTTPException(415, "file extension is .pdf but content is not a PDF")
        elif suffix in {".png", ".jpg", ".jpeg", ".gif"}:
            try:
                from PIL import Image
                with Image.open(save_path) as im:
                    im.verify()
            except HTTPException:
                raise
            except Exception:
                raise HTTPException(
                    415, "file extension looks like an image but content is not valid"
                )
        committed = True
        return save_path
    except HTTPException:
        raise
    except OSError as exc:
        raise HTTPException(500, f"failed to store upload: {exc}") from exc
    finally:
        # Always delete partial / rejected uploads (storage-cap + oversize tests)
        if not committed:
            save_path.unlink(missing_ok=True)


def _validated_upload(path_str: Optional[str]) -> Optional[Path]:
    """Resolve a client-supplied upload token to a file this server stored.

    Preferred form: opaque UUID filename returned by /upload* (no directories).
    Legacy absolute paths under UPLOADS_DIR are still accepted.
    Paths outside UPLOADS_DIR → 400. Missing file → 404.
    """
    if not path_str:
        return None
    s = path_str.strip()
    uploads_root = paths.UPLOADS_DIR.resolve()
    norm = s.replace("\\", "/")

    # Directory components or absolute/legacy paths: only legal if under UPLOADS_DIR
    if norm.startswith("/") or norm.startswith("..") or "/" in norm:
        try:
            resolved = Path(s).resolve()
        except (OSError, RuntimeError):
            raise HTTPException(
                400, "path was not issued by this server — "
                     "upload the file via /upload or /upload_image first")
        if uploads_root not in resolved.parents:
            raise HTTPException(
                400, "path was not issued by this server — "
                     "upload the file via /upload or /upload_image first")
        if not resolved.is_file():
            raise HTTPException(404, "uploaded file is no longer available")
        return resolved

    # Opaque token (basename only)
    resolved = (paths.UPLOADS_DIR / Path(norm).name).resolve()
    if uploads_root not in resolved.parents and resolved.parent != uploads_root:
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
            import pypdf
            with open(doc, "rb") as f:
                reader = pypdf.PdfReader(f)
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
# 3. RATE LIMITING (protect the GPU from abuse)
# ==========================================
# Even a valid API key can stress the hardware if an attacker (or a buggy
# client) floods /chat. This is a simple in-memory sliding-window limiter
# per client IP. Tune via env vars; defaults are conservative for a single
# consumer GPU shared over Tailscale.
#
#   SHELL_MIND_RATE_LIMIT   max requests per window (default 20)
#   SHELL_MIND_RATE_WINDOW  window length in seconds (default 60)
#
# Agent runs already take 1–3 minutes and serialize on GEN_LOCK, so the
# limit mainly stops upload spam and rapid copilot hammering.

_RATE_LIMIT = int(os.environ.get("SHELL_MIND_RATE_LIMIT", "20"))
_RATE_WINDOW = float(os.environ.get("SHELL_MIND_RATE_WINDOW", "60"))
_rate_hits: dict[str, deque] = defaultdict(deque)
_rate_lock = threading.Lock()


def _check_rate_limit(client_ip: str) -> float | None:
    """Consume one rate-limit slot. Returns the timestamp appended, or None
    if limiting is disabled. Raise 429 with Retry-After when over budget."""
    if _RATE_LIMIT <= 0:
        return None
    now = time.monotonic()
    with _rate_lock:
        q = _rate_hits[client_ip]
        while q and q[0] < now - _RATE_WINDOW:
            q.popleft()
        if not q and client_ip in _rate_hits:
            # Drop quiet IPs so the dict cannot grow without bound (audit).
            _rate_hits.pop(client_ip, None)
            q = _rate_hits[client_ip]
        if len(q) >= _RATE_LIMIT:
            raise HTTPException(
                status_code=429,
                detail=(
                    f"rate limit exceeded — max {_RATE_LIMIT} requests per "
                    f"{int(_RATE_WINDOW)}s from your address. Wait and retry."
                ),
                headers={"Retry-After": str(int(_RATE_WINDOW))},
            )
        q.append(now)
        return now


def _rollback_rate_hit(client_ip: str, stamp: float | None) -> None:
    """Undo a rate-limit consumption (e.g. request rejected as 503 busy)."""
    if stamp is None or _RATE_LIMIT <= 0:
        return
    with _rate_lock:
        q = _rate_hits.get(client_ip)
        if not q:
            return
        # Remove the matching stamp if still present (usually the last entry).
        for i in range(len(q) - 1, -1, -1):
            if q[i] == stamp:
                del q[i]
                break
        if not q:
            _rate_hits.pop(client_ip, None)

# ==========================================
# 4. FASTAPI SETUP & HARDWARE DETECTION
# ==========================================
app = FastAPI(title="Shell-Mind")
# Local workstation served to a trusted LAN/Tailscale network; the clients
# are plain browsers/CLIs with no cookies, so wildcard origins are fine —
# credentials stay disabled (an invalid CORS combination anyway).
# H3: allow_origins=['*'] is convenient for Tailscale UIs but any browser
# page can call the API if no SHELL_MIND_API_KEY is set. Prefer setting a key
# (or bind Tailscale-only) on shared networks.
# Optional shared-key auth: set SHELL_MIND_API_KEY on the server to require
# an X-API-Key header on /chat and the upload endpoints. Unset = open access
# (appropriate inside a private tailnet with no untrusted devices).
#
# ROTATION: change the value in .env and restart the server. The old key
# is gone immediately — there is no key history, no grace period, no
# secondary valid key. Clients that still hold the old key get 401 until
# they enter the new one.
API_KEY = os.environ.get("SHELL_MIND_API_KEY")
_PROTECTED_PATHS = {"/chat", "/upload", "/upload_image"}

# H3: without an API key, lock CORS to local origins so random websites cannot
# drive the GPU via the browser. With a key set, ["*"] is fine for Tailscale UIs.
# CORSMiddleware is registered after auth/body middlewares (below) so it runs
# outermost and answers OPTIONS preflights before API-key checks (R3).
_cors_origins = (
    ["*"]
    if API_KEY
    else ["http://localhost:8000", "http://127.0.0.1:8000"]
)

_UPLOAD_PATHS = {"/upload", "/upload_image"}
_UPLOAD_BODY_CAP = 26 * 1024 * 1024   # 25 MB file + multipart overhead

@app.middleware("http")
async def _limit_body_size(request: Request, call_next):
    """Path-aware body cap (N1). Closes chunked Transfer-Encoding bypass (R1)."""
    if request.method in ("POST", "PUT", "PATCH"):
        path = request.url.path
        if path in _UPLOAD_PATHS:
            limit = _UPLOAD_BODY_CAP
        elif path in _PROTECTED_PATHS:
            limit = 1_000_000
        else:
            limit = None
        if limit is not None:
            te = (request.headers.get("transfer-encoding") or "").lower()
            if "chunked" in te:
                return JSONResponse(
                    {"detail": "chunked transfer encoding is not allowed; "
                               "send Content-Length"},
                    status_code=411,
                )
            cl = request.headers.get("content-length")
            if cl is None:
                return JSONResponse(
                    {"detail": "Content-Length required"},
                    status_code=411,
                )
            try:
                n = int(cl)
            except ValueError:
                return JSONResponse({"detail": "invalid Content-Length"}, status_code=400)
            if n > limit:
                mb = max(1, limit // (1024 * 1024))
                return JSONResponse(
                    {"detail": f"request body too large (max {mb} MB)"},
                    status_code=413,
                )
    return await call_next(request)


HAS_GPU = torch.cuda.is_available()


@app.middleware("http")
async def _require_api_key(request: Request, call_next):
    # R3: CORS preflight never sends X-API-Key
    if request.method == "OPTIONS":
        return await call_next(request)
    if API_KEY and request.url.path in _PROTECTED_PATHS:
        supplied = request.headers.get("x-api-key", "")
        if not secrets.compare_digest(supplied, API_KEY):
            return JSONResponse(
                {"detail": "invalid or missing API key (X-API-Key header). "
                           "If the key was rotated, update it on this device."},
                status_code=401)
    return await call_next(request)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==========================================
# 5. COPILOT TIERS (lazy-loaded, zero-sum with the agent zoo)
# ==========================================
# Copilot tiers route through the role system — models.json remaps
# them exactly like the agent roles (with not-cached fallback).
COPILOT_IDS = {
    "gpu": REGISTRY[role_key("copilot_gpu")].hf_id,   # 4-bit NF4 on the GPU
    "cpu": REGISTRY[role_key("copilot_cpu")].hf_id,   # fp32 on CPU, GPU free
}

model: Any = None
tokenizer: Any = None
_copilot_key: Dict[str, Optional[str]] = {"tier": None}   # None | "gpu" | "cpu"
_tier: Dict[str, str] = {"current": "cpu" if not HAS_GPU else "copilot-idle"}

GEN_LOCK = threading.Lock()
_busy_since: Dict[str, Optional[float]] = {"t": None}   # for queue feedback


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
# 6. API ENDPOINTS
# ==========================================
class UserRequest(BaseModel):
    prompt: str = Field(..., max_length=32_000)
    mode: Literal["cpu", "gpu", "agent"] = "gpu"
    image_path: Optional[str] = None
    document_path: Optional[str] = None


@app.get("/health")
def health_check(request: Request) -> Dict[str, Any]:
    """Minimal public payload when API_KEY is set and the caller is unauthenticated.
    Full telemetry (VRAM, models, roles) requires a valid X-API-Key (M10)."""
    busy = _busy_since["t"] is not None
    if API_KEY:
        provided = request.headers.get("X-API-Key") or request.headers.get("x-api-key")
        if not provided or not hmac.compare_digest(provided, API_KEY):
            return {
                "status": "ok",
                "busy": busy,
                "auth_required": True,
            }
    try:
        effective_roles = {
            r: role_key(r) for r in (
                "router", "vision", "code", "reasoning",
                "critic", "copilot_gpu", "copilot_cpu",
            )
        }
    except Exception:
        effective_roles = {}
    info: Dict[str, Any] = {
        "status": "ok",
        "tier": _tier["current"],
        "gpu": HAS_GPU,
        "auth_required": bool(API_KEY),
        "busy": busy,
        "models": active_models_summary(),
        "roles_effective": effective_roles,
    }
    if HAS_GPU:
        try:
            info.update(get_zoo().status())
        except Exception:
            pass
    return info


@app.post("/upload_image")
def upload_image_endpoint(file: UploadFile = File(...),
                          request: Request = None) -> Dict[str, str]:
    client_ip = request.client.host if request and request.client else "unknown"
    rate_stamp = _check_rate_limit(client_ip)
    return {"image_path": _save_upload(file).name}


@app.post("/upload")
def upload_document_endpoint(file: UploadFile = File(...),
                             request: Request = None) -> Dict[str, str]:
    client_ip = request.client.host if request and request.client else "unknown"
    _check_rate_limit(client_ip)
    return {"document_path": _save_upload(file).name,
            "status": "stored_for_processing"}

@app.post("/chat/stream")
async def ask_ai_stream(request: UserRequest, http_request: Request):
    """SSE streaming variant of /chat — copilot modes only."""
    client_ip = http_request.client.host if http_request.client else "unknown"
    rate_stamp = _check_rate_limit(client_ip)

    if request.mode == "agent":
        _rollback_rate_hit(client_ip, rate_stamp)
        raise HTTPException(
            status_code=400,
            detail="Streaming not supported in agent mode — use /chat",
        )

    if not GEN_LOCK.acquire(blocking=False):
        waited = (time.monotonic() - _busy_since["t"]
                  if _busy_since["t"] else 0)
        _rollback_rate_hit(client_ip, rate_stamp)
        raise HTTPException(
            status_code=503,
            detail=f"server busy (running ~{int(waited)}s). Retry shortly.",
            headers={"Retry-After": "60"},
        )

    _busy_since["t"] = time.monotonic()
    try:
        doc = _validated_upload(request.document_path)
        img = _validated_upload(request.image_path)
        if doc is not None:
            suf = doc.suffix.lower()
            if suf in {".png", ".jpg", ".jpeg", ".gif"}:
                raise HTTPException(400, "Images must go via image_path")
            if suf not in {".pdf", ".txt", ".csv"}:
                raise HTTPException(400, "document_path only accepts .pdf/.txt/.csv")
        if img is not None:
            raise HTTPException(400, "Images only work in agent mode")

        file_logged = doc.name if doc else "None"
        doc_context = _document_context(doc)
        final_prompt = request.prompt + doc_context

        copilot_role = "copilot_gpu" if request.mode == "gpu" else "copilot_cpu"
        if not has_model(role_key(copilot_role)):
            raise HTTPException(503, f"{request.mode} copilot not cached")

        _ensure_copilot(request.mode)

        messages = [
            {"role": "system", "content": "You are a highly capable coding assistant."},
            {"role": "user", "content": final_prompt},
        ]
        formatted_prompt = tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True)
        inputs = tokenizer(formatted_prompt, return_tensors="pt").to(model.device)

        streamer = TextIteratorStreamer(
            tokenizer, skip_prompt=True, skip_special_tokens=True)

        def _run_generation():
            try:
                with torch.inference_mode():
                    model.generate(
                        **inputs,
                        max_new_tokens=1500,
                        do_sample=True,
                        temperature=0.6,
                        pad_token_id=tokenizer.eos_token_id,
                        streamer=streamer,
                    )
            except Exception:
                log.exception("streaming generation failed")

        async def event_generator():
            accumulated: list[str] = []
            try:
                thread = threading.Thread(target=_run_generation, daemon=True)
                thread.start()
                for token in streamer:
                    accumulated.append(token)
                    yield f"data: {json.dumps({'token': token})}\n\n"
                full_reply = "".join(accumulated).strip()
                log_to_db(request.mode.upper(), request.prompt, full_reply,
                          file_logged, client=client_ip)
                yield f"data: {json.dumps({'done': True, 'answer': full_reply})}\n\n"
            except GeneratorExit:
                log.info("client disconnected mid-stream")
                raise
            finally:
                _busy_since["t"] = None
                GEN_LOCK.release()

        return StreamingResponse(event_generator(), media_type="text/event-stream")

    except HTTPException:
        _busy_since["t"] = None
        GEN_LOCK.release()
        raise  
    except Exception:
        _busy_since["t"] = None
        GEN_LOCK.release()
        raise
   
@app.post("/chat")
def ask_ai(request: UserRequest, http_request: Request) -> Dict[str, Any]:
    client_ip = http_request.client.host if http_request.client else "unknown"
    rate_stamp = _check_rate_limit(client_ip)

    # Non-blocking check so the client can show "server is busy" instead
    # of hanging silently for minutes behind GEN_LOCK.
    if not GEN_LOCK.acquire(blocking=False):
        waited = (time.monotonic() - _busy_since["t"]
                  if _busy_since["t"] else 0)
        # M11: do not charge the rate budget for a rejected busy response
        _rollback_rate_hit(client_ip, rate_stamp)
        raise HTTPException(
            status_code=503,
            detail=(
                f"server is busy with another request "
                f"(running for ~{int(waited)}s). Retry in a moment."
            ),
            headers={"Retry-After": "60"},
        )
    _busy_since["t"] = time.monotonic()
    try:
        # Paths are validated BEFORE any model work: only files this
        # server stored may enter a prompt.
        doc = _validated_upload(request.document_path)
        img = _validated_upload(request.image_path)
        if doc is not None:
            suf = doc.suffix.lower()
            if suf in {".png", ".jpg", ".jpeg",".gif"}:
                raise HTTPException(
                    400,
                    "Images must be sent via image_path, not document_path",
                )
            if suf not in {".pdf", ".txt", ".csv"}:
                raise HTTPException(
                    400,
                    f"document_path only accepts .pdf, .txt, .csv (got '{suf}')",
                )
        file_logged = doc.name if doc else (img.name if img else "None")

        doc_context = _document_context(doc)
        # Copilot tiers use concatenated prompt; agent routes on raw user text only.
        final_prompt = request.prompt + doc_context

        # --- TIER 3: AGENT WORKSTATION ---
        if request.mode == "agent":
            if not HAS_GPU:
                return {"answer": "⚠️ The Agent Workstation requires CUDA. "
                                  "Use mode 'cpu' or 'gpu' on this host."}
            if _tier["current"] != "agent":
                _evict_copilot()
                _tier["current"] = "agent"
            try:
                result = run_agentic_pipeline(
                    request.prompt,
                    image_path=str(img) if img else None,
                    document_context=doc_context)
                answer_text = (f"🤖 Agent Workstation "
                               f"[{str(result.get('task', 'agent')).upper()}]\n\n"
                               f"{result.get('answer', '')}")
                log_to_db("Agent Pipeline", request.prompt, answer_text,
                          file_logged, client=client_ip)
                return {"answer": answer_text,
                        "stages": result.get("stages"),
                        "total_s": result.get("total_s")}
            except Exception as exc:
                log.exception("agent pipeline failed")
                err_name = type(exc).__name__
                del exc
                get_zoo().purge()
                log_to_db("Agent Pipeline", request.prompt,
                          f"(error: {err_name})", file_logged, client=client_ip)
                return {"answer": f"⚠️ Agent pipeline error ({err_name}). "
                                  f"VRAM purged — try again."}

        # --- TIER 1 & 2: CPU LITE / GPU COPILOT ---
        # H6: never start a multi-GB download inside an HTTP request
        copilot_role = "copilot_gpu" if request.mode == "gpu" else "copilot_cpu"
        # cpu mode on a GPU host still uses copilot_cpu role
        if request.mode in ("gpu", "cpu") and not has_model(role_key(copilot_role)):
            return {
                "answer": (
                    f"⚠️ The {request.mode} copilot model is not in the local cache yet. "
                    "Preload it once on this machine, then retry:\n\n"
                    "  python -c \"from huggingface_hub import snapshot_download; "
                    "snapshot_download('<hf_id from models.json / README>')\"\n\n"
                    "See README → Model Registry. Agent mode is also unavailable until "
                    "the required specialists are cached."
                )
            }
        if img is not None:
            return {
                "answer": (
                    "⚠️ Image attachments only work in Agent mode. "
                    "The GPU/CPU copilot tiers cannot read images — they read "
                    "PDFs and text only. Switch the mode dropdown to 'Agent' "
                    "and re-send, or remove the attachment to continue text-only."
                )
            }    
        _ensure_copilot(request.mode)
        messages = [
            {"role": "system",
             "content": "You are a highly capable coding assistant."},
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

        log_to_db(request.mode.upper(), request.prompt, reply, file_logged,
                  client=client_ip)
        return {"answer": reply}
    finally:
        _busy_since["t"] = None
        GEN_LOCK.release()

# ==========================================
# 7. FRONTEND — served by the API server itself
# ==========================================
class NoCacheStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope):
        resp = await super().get_response(path, scope)
        resp.headers["Cache-Control"] = "no-cache"
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["Referrer-Policy"] = "no-referrer"
        # Minimal CSP for the glass UI (inline handlers are not used; scripts are same-origin)
        resp.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
            "script-src 'self'; connect-src 'self'",
        )
        return resp


_FRONTEND_DIR = paths.REPO_ROOT / "frontend"
if _FRONTEND_DIR.is_dir():
    app.mount("/", NoCacheStaticFiles(directory=_FRONTEND_DIR, html=True),
              name="frontend")

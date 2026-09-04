"""
ai_core.py — SHELL MIND server (final merge: product layer + engine).

Layers:
  * THIS FILE: transport only — FastAPI, tiers, locking, mode switching.
  * workstation/: the engine (models, agents, orchestration).

Rules enforced here:
  1. One generation at a time (GEN_LOCK) — the 8 GB card is zero-sum.
  2. Tiers are exclusive: agent mode evicts the copilot; copilot mode
     parks the workstation's resident router (measured: 5.2 + 1.2 GB
     leaves 0.1 GB free — not enough for a real prompt's KV cache).
  3. The copilot is never bricked: an evicted model reloads on demand.

Launch (from the shell-mind repo root, venv active, ONE process only —
multiple workers = multiple model zoos = OOM):
    uvicorn primary_node.ai_core:app --host 0.0.0.0 --port 8000
"""

import gc
import os
import threading
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import logging
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)-7s %(message)s",
                    datefmt="%H:%M:%S")

# ==========================================
# 1. CACHE SETUP (Portable Workspace Drive)
# ==========================================
# Same path math as workstation/model_zoo.py: shell-mind/../models/hf_cache.
# One cache for both layers — zero duplicate downloads.
_WS_ROOT = Path(__file__).resolve().parents[2]
CACHE = str(_WS_ROOT / "models" / "hf_cache")

os.environ["HF_HOME"] = CACHE
os.environ["HF_HUB_CACHE"] = str(Path(CACHE) / "hub")
os.environ["TRANSFORMERS_CACHE"] = str(Path(CACHE) / "hub")

print(f"Using portable HF cache: {CACHE}")

# Engine imports AFTER the env is set (model_zoo also sets its CUDA env
# defensively — this ordering keeps everything consistent).
from workstation.model_zoo import get_zoo                    # noqa: E402
from workstation.orchestrator import run_agentic_pipeline    # noqa: E402

import torch                                                  # noqa: E402
from transformers import (                                    # noqa: E402
    AutoModelForCausalLM,
    AutoTokenizer,
    BitsAndBytesConfig,
)

# ==========================================
# 2. FASTAPI & CORS SETUP
# ==========================================
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==========================================
# 3. HARDWARE DETECTION & STARTUP MODEL
# ==========================================
HAS_GPU = torch.cuda.is_available()

if HAS_GPU:
    print("🟢 GPU Detected! Booting Workstation Server Mode.")
    MODEL_ID = "Qwen/Qwen2.5-Coder-7B-Instruct"
    device_map = {"": "cuda:0"}
    torch_dtype = torch.bfloat16
    quant_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_compute_dtype=torch.bfloat16,
        bnb_4bit_quant_type="nf4",
    )
else:
    print("🟡 No GPU Detected. Booting Lightweight CPU Mode.")
    MODEL_ID = "Qwen/Qwen2.5-0.5B-Instruct"
    device_map = {"": "cpu"}
    torch_dtype = torch.float32
    quant_config = None

print(f"Waking up {MODEL_ID}... (May take a few minutes if downloading for the first time)")

tokenizer = AutoTokenizer.from_pretrained(MODEL_ID)
model = AutoModelForCausalLM.from_pretrained(
    MODEL_ID,
    quantization_config=quant_config,
    device_map=device_map,
    torch_dtype=torch_dtype,
)
print("✅ Kitchen is ready! Listening on Port 8000...")

# ==========================================
# 4. MODE MANAGEMENT (VRAM is zero-sum!)
# ==========================================
# One generation at a time, ever. The browser AND the CLI can both be
# connected — they must queue here, not fight over the 8 GB card.
GEN_LOCK = threading.Lock()
_tier = {"current": "copilot"}   # honest: startup just loaded the copilot


def _evict_copilot() -> None:
    """Free the GPU Copilot so the agent workstation can take the card.
    References dropped BEFORE empty_cache — the smoke-test lesson: VRAM
    cannot free while Python still holds the weights."""
    global model, tokenizer
    if model is None:
        return
    model = None
    tokenizer = None
    gc.collect(); gc.collect()
    torch.cuda.empty_cache()
    torch.cuda.ipc_collect()
    print("🛌 GPU Copilot evicted — the agent workstation owns the card now")


def _ensure_copilot() -> None:
    """(Re)load the GPU Copilot after agent mode evicted it. Parks the
    workstation's resident router first: copilot (5.2 GB) + router
    (1.2 GB) = 0.1 GB free — measured, and not enough for a real prompt."""
    global model, tokenizer
    if model is not None:
        return
    if HAS_GPU:
        get_zoo().unload_resident()
    print("🔄 Reloading GPU Copilot (was evicted for agent mode)...")
    tokenizer = AutoTokenizer.from_pretrained(MODEL_ID)
    model = AutoModelForCausalLM.from_pretrained(
        MODEL_ID,
        quantization_config=quant_config,
        device_map=device_map,
        torch_dtype=torch_dtype,
    )
    _tier["current"] = "copilot"
    print("✅ GPU Copilot back online")


# ==========================================
# 5. API ENDPOINTS
# ==========================================
class UserRequest(BaseModel):
    prompt: str
    mode: str = "gpu"               # "gpu" | "cpu" | "agent"
    image_path: str | None = None   # future GUI: screenshot for the vision expert


@app.get("/health")
def health_check():
    """Your Web UI (script.js) pings this to confirm the server is alive."""
    info = {
        "status": "ok",
        "default_model": MODEL_ID,
        "hardware": "GPU" if HAS_GPU else "CPU",
        "tier": _tier["current"],
    }
    if HAS_GPU:
        try:
            info["free_vram_gb"] = round(get_zoo().free_vram_gb(), 2)
        except Exception:
            pass    # never let a VRAM probe kill the health check
    return info


@app.post("/chat")
def ask_ai(request: UserRequest):
    with GEN_LOCK:

        # --- TIER 3: AGENT WORKSTATION ---
        if request.mode == "agent":
            if not HAS_GPU:
                return {"answer": "🟡 Agent Workstation needs the GPU. "
                                  "This server booted in CPU Lite mode."}
            if _tier["current"] != "agent":
                _evict_copilot()
                _tier["current"] = "agent"
            try:
                result = run_agentic_pipeline(request.prompt,
                                              image_path=request.image_path)
            except Exception as exc:
                # Purge and keep serving — a failed pipeline must never
                # take the server down with it.
                get_zoo().purge()
                print(f"⚠️ Agent pipeline error: {type(exc).__name__}: {exc}")
                return {"answer": f"⚠️ Agent pipeline error "
                                  f"({type(exc).__name__}). VRAM purged — try again."}
            if isinstance(result, dict):          # current orchestrator
                return {
                    "answer": f"🤖 Agent Workstation "
                              f"[{str(result.get('task', 'agent')).upper()}]\n\n"
                              f"{result.get('answer', '')}",
                    "stages": result.get("stages"),
                    "total_s": result.get("total_s"),
                }
            return {"answer": result}             # older orchestrator returned a string

        # --- TIER 1: CPU LITE ---
        # On GPU machines the CPU tier is served by the copilot (fast path)
        # instead of a costly 7B->0.5B swap on every request.
        prefix = ""
        if request.mode == "cpu" and HAS_GPU:
            print("ℹ️ CPU tier requested — serving via GPU Copilot (fast path).")
            prefix = "🖥️ (CPU tier routes through the GPU Copilot on this machine)\n\n"

        # --- TIER 2: GPU COPILOT (default execution) ---
        _ensure_copilot()

        messages = [
            {"role": "system", "content": "You are a highly capable coding and shell assistant. Keep your answers clear, accurate, and concise."},
            {"role": "user", "content": request.prompt},
        ]

        formatted_prompt = tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True)
        inputs = tokenizer(formatted_prompt, return_tensors="pt").to(model.device)

        with torch.inference_mode():
            outputs = model.generate(
                **inputs,
                max_new_tokens=500,
                do_sample=True,
                temperature=0.6,
                pad_token_id=tokenizer.eos_token_id,
            )

        input_length = inputs["input_ids"].shape[1]
        reply = tokenizer.decode(outputs[0][input_length:],
                                 skip_special_tokens=True).strip()

        return {"answer": prefix + reply}
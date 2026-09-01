import os
from pathlib import Path
import torch
import gc
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# ==========================================
# 1. CACHE SETUP (Portable Workspace Drive)
# ==========================================
# Dynamically find the 'workspace' root (2 folders up from primary_node/ai_core.py)
_WS_ROOT = Path(__file__).resolve().parents[2]
CACHE = str(_WS_ROOT / "models" / "hf_cache")

# Force Hugging Face to use this specific external folder
os.environ["HF_HOME"] = CACHE
os.environ["HF_HUB_CACHE"] = str(Path(CACHE) / "hub")
os.environ["TRANSFORMERS_CACHE"] = str(Path(CACHE) / "hub")

print(f"Using portable HF cache: {CACHE}")

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
# 3. GLOBAL MODEL STATE & HARDWARE DETECTION
# ==========================================
HAS_GPU = torch.cuda.is_available()

if HAS_GPU:
    print("🟢 GPU Detected! Booting Workstation Server Mode.")
    MODEL_ID = "Qwen/Qwen2.5-Coder-7B-Instruct"
    device_map = {"": "cuda:0"}
    torch_dtype = torch.bfloat16
    
    # 4-bit compression for the 8GB RTX 5050
    quant_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_compute_dtype=torch.bfloat16,
        bnb_4bit_quant_type="nf4"
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
# 4. API ENDPOINTS
# ==========================================
class UserRequest(BaseModel):
    prompt: str
    mode: str = "gpu"  # Default to GPU mode

@app.get("/health")
def health_check():
    """Your Web UI (script.js) pings this to confirm the server is alive."""
    return {"status": "ok", "default_model": MODEL_ID, "hardware": "GPU" if HAS_GPU else "CPU"}

@app.post("/chat")
def ask_ai(request: UserRequest):
    # --- TIER 3: AGENT WORKSTATION ---
    if request.mode == "agent":
        return {"answer": "⚙️ Agent Workstation triggered! (Note: Multi-agent orchestration is pending Stage 2 integration based on your smoke_test.py results. Please use GPU Copilot for now.)"}
    
    # --- TIER 1: CPU LITE ---
    elif request.mode == "cpu" and HAS_GPU:
        return {"answer": "🖥️ CPU Mode triggered! (To keep API response times fast, dynamic unloading of the 7B GPU model to load the 0.5B CPU model is bypassed in this session. Using Copilot mode.)"}

    # --- TIER 2: GPU COPILOT (Default execution) ---
    messages = [
        {"role": "system", "content": "You are a highly capable coding and shell assistant. Keep your answers clear, accurate, and concise."},
        {"role": "user", "content": request.prompt}
    ]
    
    formatted_prompt = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    inputs = tokenizer(formatted_prompt, return_tensors="pt").to(model.device)
    
    outputs = model.generate(
        **inputs, 
        max_new_tokens=500, 
        temperature=0.6, 
        pad_token_id=tokenizer.eos_token_id
    )
    
    # Clean Tensor Slicing (No more messy string splitting!)
    input_length = inputs["input_ids"].shape[1]
    generated_tokens = outputs[0][input_length:]
    reply = tokenizer.decode(generated_tokens, skip_special_tokens=True).strip()
    
    return {"answer": reply}
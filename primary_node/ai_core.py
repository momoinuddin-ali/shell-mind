import os
from pathlib import Path

# --- Your 16GB external cache ---
MY_CACHE = "/run/media/momoinuddinali/workspace/local_ai-/hf_cache"
FALLBACK = Path(__file__).resolve().parent.parent / "hf_cache"
CACHE = MY_CACHE if Path(MY_CACHE).exists() else str(FALLBACK)
os.environ["HF_HOME"] = CACHE
os.environ["HF_HUB_CACHE"] = str(Path(CACHE) / "hub")
os.environ["TRANSFORMERS_CACHE"] = str(Path(CACHE) / "hub")
print(f"Using HF cache: {CACHE}")

import torch
import re
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig, TextIteratorStreamer
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from threading import Thread

app = FastAPI(title="Shell-Mind Primary Node")
MODEL_ID = "deepseek-ai/DeepSeek-R1-Distill-Llama-8B"
print(f"Waking up {MODEL_ID} on RTX 5050...")

quant_config = BitsAndBytesConfig(
    load_in_4bit=True,
    bnb_4bit_quant_type="nf4",
    bnb_4bit_compute_dtype=torch.float16,
    bnb_4bit_use_double_quant=True
)

tokenizer = AutoTokenizer.from_pretrained(MODEL_ID, cache_dir=str(Path(CACHE)/"hub"))
model = AutoModelForCausalLM.from_pretrained(
    MODEL_ID,
    quantization_config=quant_config,
    device_map="cuda:0",
    cache_dir=str(Path(CACHE)/"hub")
)
print("Kitchen is Ready!")

class UserRequest(BaseModel):
    prompt: str
    max_tokens: int = 4096
    temperature: float = 0.6
    persona: str = "You are a Linux expert. Think internally, but never show thinking. At the end, output ONLY after the marker FINAL:. Keep final answer short and clean."

@app.get("/health")
def health():
    allocated = torch.cuda.memory_allocated(0) / 1e9
    return {"status": "ready", "vram": f"{allocated:.2f}GB"}

@app.post("/chat")
def ask_deepseek(req: UserRequest):
    # Force FINAL: marker
    messages = [
        {"role": "system", "content": req.persona},
        {"role": "user", "content": req.prompt + "\n\nRemember: End with FINAL: and then your final answer."}
    ]
    full_prompt = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    inputs = tokenizer(full_prompt, return_tensors="pt").to("cuda:0")

    streamer = TextIteratorStreamer(tokenizer, skip_prompt=True, skip_special_tokens=True)
    thread = Thread(target=model.generate, kwargs=dict(
        **inputs,
        streamer=streamer,
        max_new_tokens=req.max_tokens,
        temperature=req.temperature,
        do_sample=True,
        eos_token_id=tokenizer.eos_token_id,
        pad_token_id=tokenizer.eos_token_id
    ))
    thread.start()

    def generate():
        full_text = ""
        try:
            for token in streamer:
                full_text += token

            # --- CORE FIX: Let it reason fully, but only print after FINAL: ---
            if "FINAL:" in full_text:
                final = full_text.split("FINAL:")[-1].strip()
            else:
                # Fallback if marker missing: take last meaningful paragraph
                parts = re.split(r'\n\s*\n', full_text.strip())
                final = parts[-1].strip() if parts else full_text.strip()
            
            final = final.replace("<｜begin▁of▁sentence｜>", "").strip()
            
            # Log full thinking secretly for debugging (optional)
            try:
                Path("supervisor").mkdir(exist_ok=True)
                with open("supervisor/thinking.log", "a") as f:
                    f.write(f"\n--- PROMPT: {req.prompt[:100]}\nTHINKING: {full_text[:1000]}\nFINAL: {final}\n")
            except:
                pass

            yield final
        finally:
            # Tensor slicing / VRAM cleanup for 8GB
            try:
                del inputs
                torch.cuda.empty_cache()
                torch.cuda.ipc_collect()
            except:
                pass

    return StreamingResponse(generate(), media_type="text/plain")

@app.post("/run")
def run_code(payload: dict):
    from supervisor import safety
    return safety.run_sandboxed(payload.get("code",""), payload.get("filename","test.py"))
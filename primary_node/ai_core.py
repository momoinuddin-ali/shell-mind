import os
from pathlib import Path

MY_CACHE = "/run/media/momoinuddin-ali/workspace/local_ai-/hf_cache"
FALLBACK = Path(__file__).resolve().parent.parent / "hf_cache"
CACHE = MY_CACHE if Path(MY_CACHE).exists() else str(FALLBACK)
os.environ["HF_HOME"] = CACHE
os.environ["HF_HUB_CACHE"] = str(Path(CACHE) / "hub")
os.environ["TRANSFORMERS_CACHE"] = str(Path(CACHE) / "hub")
print(f"Using HF cache: {CACHE}")

import torch, re
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig, TextIteratorStreamer
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from threading import Thread

app = FastAPI(title="Shell-Mind Primary Node")

HAS_GPU = torch.cuda.is_available()
if HAS_GPU:
    MODEL_ID = "deepseek-ai/DeepSeek-R1-Distill-Llama-8B"
    print(f"GPU FOUND: Using {MODEL_ID}")
    quant_config = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_compute_dtype=torch.float16, bnb_4bit_use_double_quant=True)
else:
    MODEL_ID = "Qwen/Qwen2-0.5B-Instruct"
    print(f"NO dGPU: Using lightweight {MODEL_ID} for CPU")
    quant_config = None

tokenizer = AutoTokenizer.from_pretrained(MODEL_ID, cache_dir=str(Path(CACHE)/"hub"))
if HAS_GPU:
    model = AutoModelForCausalLM.from_pretrained(MODEL_ID, quantization_config=quant_config, device_map="cuda:0", cache_dir=str(Path(CACHE)/"hub"))
else:
    model = AutoModelForCausalLM.from_pretrained(MODEL_ID, device_map="cpu", cache_dir=str(Path(CACHE)/"hub"))
print("Kitchen Ready!")

class UserRequest(BaseModel):
    prompt: str
    max_tokens: int = 4096
    temperature: float = 0.6

@app.get("/health")
def health():
    return {"status": "ready", "gpu": HAS_GPU, "model": MODEL_ID, "vram": f"{torch.cuda.memory_allocated(0)/1e9:.2f}GB" if HAS_GPU else "CPU"}

@app.post("/chat")
def chat(req: UserRequest):
    system = "You are Linux expert. Think internally, never show thinking. End with FINAL: + clean answer."
    messages = [{"role":"system","content":system},{"role":"user","content":req.prompt+"\nRemember FINAL:"}]
    full_prompt = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    inputs = tokenizer(full_prompt, return_tensors="pt").to(model.device)
    streamer = TextIteratorStreamer(tokenizer, skip_prompt=True, skip_special_tokens=True)
    Thread(target=model.generate, kwargs=dict(**inputs, streamer=streamer, max_new_tokens=req.max_tokens, temperature=req.temperature, do_sample=True, eos_token_id=tokenizer.eos_token_id, pad_token_id=tokenizer.eos_token_id)).start()
    def gen():
        text=""
        for t in streamer: text+=t
        final = text.split("FINAL:")[-1].strip() if "FINAL:" in text else text.strip().split("\n\n")[-1]
        try:
            Path("supervisor").mkdir(exist_ok=True)
            open("supervisor/thinking.log","a").write(f"\n--- {req.prompt[:80]}\n{text[:500]}\nFINAL:{final[:500]}\n")
        except: pass
        yield final
        try: del inputs; torch.cuda.empty_cache(); torch.cuda.ipc_collect()
        except: pass
    return StreamingResponse(gen(), media_type="text/plain")

@app.post("/run")
def run_code(payload: dict):
    from supervisor import safety
    return safety.run_sandboxed(payload.get("code",""), payload.get("filename","test.py"))
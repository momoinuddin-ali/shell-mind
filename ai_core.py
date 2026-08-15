import os

# 1. SET THE CACHE PATH FIRST (Stops the 16GB redownload!)
os.environ["HF_HOME"] = "/run/media/momoinuddinali/workspace/local_ai-/hf_cache"

import torch
import gc
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
from fastapi import FastAPI
from pydantic import BaseModel

# ==========================================
# 2. THE WAITER (FastAPI Setup)
# ==========================================
app = FastAPI()

# ==========================================
# 3. THE KITCHEN (Loading DeepSeek to GPU)
# ==========================================
MODEL_ID = "deepseek-ai/DeepSeek-R1-Distill-Llama-8B"

print("Waking up DeepSeek on RTX 5050... This takes about 60 seconds.")

# 4-bit compression so it fits nicely in your 8GB VRAM
quant_config = BitsAndBytesConfig(
    load_in_4bit=True, 
    bnb_4bit_compute_dtype=torch.float16,
    bnb_4bit_quant_type="nf4"
)

# Load the AI into the graphics card
tokenizer = AutoTokenizer.from_pretrained(MODEL_ID)
model = AutoModelForCausalLM.from_pretrained(
    MODEL_ID, 
    quantization_config=quant_config, 
    device_map="cuda:0", 
    torch_dtype=torch.float16
)
print("Kitchen is ready! The Waiter is waiting for orders...")

# ==========================================
# 4. THE ORDER TICKET (What we expect to receive)
# ==========================================
class UserRequest(BaseModel):
    prompt: str

# ==========================================
# 5. THE DOORWAY (API Endpoint)
# ==========================================
@app.post("/chat")
def ask_deepseek(request: UserRequest):
    
    messages = [
        {"role": "system", "content": "You are a helpful AI assistant. Keep your answers clear and concise."},
        {"role": "user", "content": request.prompt}
    ]
    
    formatted_prompt = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    inputs = tokenizer(formatted_prompt, return_tensors="pt").to("cuda")
    
    outputs = model.generate(**inputs, max_new_tokens=500, temperature=0.6, pad_token_id=tokenizer.eos_token_id)
    full_response = tokenizer.decode(outputs[0], skip_special_tokens=True)
    
    if "</think>" in full_response:
        reply = full_response.split("</think>")[-1].strip()
    else:
        reply = full_response.split("<| Assistant |>")[-1].strip()
    
    torch.cuda.empty_cache()
    gc.collect()
    
    return {"answer": reply}
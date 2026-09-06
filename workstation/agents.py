"""
agents.py — the four experts.

Contract for every agent: wake (load) -> work (generate) -> sleep (unload,
with all references dropped first so VRAM actually frees). Agents clean
up after themselves; the orchestrator never touches models directly.

VRAM discipline (measured on this RTX 5050, not guessed):
  * Big workers (vision / coder / thinker) PARK the router while they
    work — router (1.2 GB) + a 7-8B worker leaves 0.1 GB, not enough
    for a real prompt's KV cache.
  * The critic coexists with the router (3.3 + 1.2 GB — plenty of room).
"""

from __future__ import annotations

import logging
from pathlib import Path

from .model_zoo import get_zoo          

log = logging.getLogger("shell-mind.agents")

# bnb keeps CPU-offloaded modules in fp32 (~75+ GB for this model's experts)
# — the GPU+DDR5 4-bit split requires the llama.cpp/GGUF backend instead.
# The 7B is the production coder until that lands. Flip after integration.
CODER30_ENABLED = False

# --- special-token markers -------------------------------------------------
THINK_END = "<" + "/" + "think" + ">"
IM_END = "<" + "|im_end" + "|>"
SOFT_END = "<" + "|endoftext" + "|>"


def _generate(model, tok, text: str, max_new_tokens: int) -> str:
    import torch
    inputs = tok(text, return_tensors="pt").to(model.device)
    with torch.inference_mode():
        out = model.generate(**inputs, max_new_tokens=max_new_tokens,
                             do_sample=False,
                             pad_token_id=getattr(tok, "pad_token_id", None)
                             or tok.eos_token_id)
    raw = tok.decode(out[0, inputs["input_ids"].shape[1]:],
                     skip_special_tokens=False)
    if THINK_END in raw:
        raw = raw.split(THINK_END, 1)[1]
    for stop in (IM_END, SOFT_END):
        if stop in raw:
            raw = raw.split(stop)[0]
    return raw.strip()


def _chat_text(tok, system: str, user: str) -> str:
    msgs = [{"role": "system", "content": system},
            {"role": "user", "content": user}]
    return tok.apply_chat_template(msgs, add_generation_prompt=True,
                                   tokenize=False)


# ---------------------------------------------------------------- vision ---
_VISION_SYSTEM = """You are the vision specialist of a workstation. Describe the image with exactly what downstream text models need: any error messages (verbatim), code shown, UI elements, data/tables, and overall context. Dense and factual, ~200 words max. No pleasantries."""

def see(image_path: str | Path, question: str) -> str:
    """Image -> compact text summary (<= ~250 tokens), then sleeps.
    Parks the router: vision needs every GB of the 8 GB card."""
    import torch
    from PIL import Image
    zoo = get_zoo()
    zoo.unload_resident()
    
    model, proc = zoo.load_worker("vision")
    img = Image.open(image_path).convert("RGB")
    # 768 caps KV cache to guarantee it fits safely in the final 0.2GB of VRAM
    img.thumbnail((768, 768))   
    msgs = [{"role": "user", "content": [
        {"type": "image", "image": img},
        {"type": "text", "text":
            f"{_VISION_SYSTEM}\n\nContext question: {question}"},
    ]}]
    inputs = proc.apply_chat_template(msgs, add_generation_prompt=True,
                                      return_dict=True)
    inputs = {k: v.to(model.device) for k, v in inputs.items()}
    
    with torch.inference_mode():
        out = model.generate(**inputs, max_new_tokens=280, do_sample=False)
    summary = proc.batch_decode(out, skip_special_tokens=True)[0].strip()
    
    # Nuke local references and wake the router ONLY on success.
    # If a crash happens, it bubbles up cleanly without reloading the router.
    del model, proc, inputs, out, img, msgs        
    zoo.unload_worker()
    zoo.load_resident("router")              
    return summary


# ----------------------------------------------------------------- coder ---
_CODER_SYSTEM = ("You are an expert software engineer. Produce correct, "
                 "minimal, working code or shell commands in markdown code "
                 "blocks. No filler, no apologies.")

def code(question: str, context: str = "", prompt_tokens: int = 0) -> str:
    """Adaptive coder. Parks the router first. Small context
    -> 30B MoE (top quality) once its download lands in the cache, large
    -> 7B to protect VRAM and speed."""
    zoo = get_zoo()
    use30 = (CODER30_ENABLED and prompt_tokens < 4000
             and zoo.has_model("coder30"))
    if use30:
        log.info("coder: using Qwen3-Coder-30B-A3B (MoE, GPU+RAM split)")
    else:
        log.info("coder: using Qwen2.5-Coder-7B%s",
                 "" if prompt_tokens >= 4000 else " (30B bypassed)")
    
    zoo.unload_resident()                        
    model, tok = zoo.load_worker("coder30" if use30 else "coder7")
    user = (f"Context:\n{context}\n\n" if context else "") + question
    draft = _generate(model, tok, _chat_text(tok, _CODER_SYSTEM, user),
                      max_new_tokens=1200)
    
    del model, tok
    zoo.unload_worker()
    zoo.load_resident("router")              
    return draft


# --------------------------------------------------------------- thinker ---
_THINK_SYSTEM = ("You are a rigorous reasoner. Think step by step, then "
                 "give a clear, complete final answer.")

def think(question: str, context: str = "") -> str:
    """Reasoning expert: Qwen3-8B in thinking mode. Parks the router —
    an 8B worker needs the same headroom the coder does."""
    zoo = get_zoo()
    zoo.unload_resident()
    
    model, tok = zoo.load_worker("thinker")
    user = (f"Context:\n{context}\n\n" if context else "") + question
    draft = _generate(model, tok, _chat_text(tok, _THINK_SYSTEM, user),
                      max_new_tokens=2500)
    
    del model, tok
    zoo.unload_worker()
    zoo.load_resident("router")
    return draft


# ---------------------------------------------------------------- critic ---
_CRITIC_SYSTEM = """You are the final editor of a multi-agent workstation. You receive the user's request, any vision context, and a draft answer from a specialist. Your output IS the final answer shown directly to the user, so:
- NEVER mention the draft, the specialist, or your own deliberation. No meta-commentary, no "corrected version" sections, no visible self-corrections.
- Fix factual or code errors in the draft; complete anything missing.
- If the draft is correct, return it nearly unchanged.
- If there is no draft, answer the request directly.
- Keep the draft's structure and good content; don't rewrite for style."""

def critique(question: str, context: str, draft: str) -> str:
    """Coexists with the router, so it never parks it."""
    zoo = get_zoo()
    model, tok = zoo.load_worker("critic")
    user = (f"## Request\n{question}\n\n## Context\n{context or '(none)'}"
            f"\n\n## Draft\n{draft}")
    final = _generate(model, tok, _chat_text(tok, _CRITIC_SYSTEM, user),
                      max_new_tokens=2000)
    del model, tok
    zoo.unload_worker()
    return final


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser(description="Single-agent self-test")
    ap.add_argument("agent", choices=["code", "think", "critic", "vision"])
    ap.add_argument("question")
    ap.add_argument("--image", type=Path, default=None)
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)-7s %(message)s",
                        datefmt="%H:%M:%S")
    if args.agent == "code":
        out = code(args.question)
    elif args.agent == "think":
        out = think(args.question)
    elif args.agent == "critic":
        out = critique(args.question, "", "(no draft — answer directly)")
    else:
        out = see(args.image or "screenshot.png", args.question)
    print("\n" + "=" * 64 + "\n" + out + "\n" + "=" * 64)


if __name__ == "__main__":
    main()
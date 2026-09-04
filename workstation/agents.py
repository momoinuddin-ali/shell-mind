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

from .model_zoo import get_zoo          # keep this import first

log = logging.getLogger("shell-mind.agents")

# --- special-token markers -------------------------------------------------
# Assembled from small fragments ON PURPOSE: these exact strings get
# mangled when they travel inside a chat message as one literal. The
# fragment form always arrives intact.
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
    # Qwen3 thinking models wrap their reasoning in think-tags; the
    # scratchpad is internal. Keep only the answer after the closing tag.
    # (For non-thinking models the tag never appears — this is a no-op.)
    if THINK_END in raw:
        raw = raw.split(THINK_END, 1)[1]
    # End-of-turn markers appear in generate()'s output because we decode
    # with skip_special_tokens=False (required for the strip above).
    # Cut them so they never leak into final answers.
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
    try:
        model, proc = zoo.load_worker("vision")
        img = Image.open(image_path).convert("RGB")
        msgs = [{"role": "user", "content": [
            {"type": "image", "image": img},
            {"type": "text", "text":
                f"{_VISION_SYSTEM}\n\nContext question: {question}"},
        ]}]
        inputs = proc.apply_chat_template(msgs, add_generation_prompt=True,
                                          return_dict=True).to(model.device)
        with torch.inference_mode():
            out = model.generate(**inputs, max_new_tokens=280, do_sample=False)
        summary = proc.batch_decode(out, skip_special_tokens=True)[0].strip()
        del model, proc, inputs, out, img        # drop refs BEFORE unload
        zoo.unload_worker()
        return summary
    finally:
        zoo.unload_worker()                      # no-op if already unloaded
        zoo.load_resident("router")              # wake the router back up


# ----------------------------------------------------------------- coder ---
_CODER_SYSTEM = ("You are an expert software engineer. Produce correct, "
                 "minimal, working code or shell commands in markdown code "
                 "blocks. No filler, no apologies.")


def code(question: str, context: str = "", prompt_tokens: int = 0) -> str:
    """Adaptive coder. Parks the router first (measured, not hoped:
    1.2 + 4.3 GB + context + desktop > 7.56 GB otherwise). Small context
    -> 30B MoE (top quality) once its download lands in the cache, large
    -> 7B to protect VRAM and speed. Until the 30B is cached the 7B
    answers, and the workstation upgrades itself the night it lands."""
    zoo = get_zoo()
    use30 = prompt_tokens < 4000 and zoo.has_model("coder30")
    if use30:
        log.info("coder: using Qwen3-Coder-30B-A3B (MoE, GPU+RAM split)")
    else:
        log.info("coder: using Qwen2.5-Coder-7B%s",
                 "" if prompt_tokens >= 4000 else " (30B not cached yet)")
    zoo.unload_resident()                        # park the router
    try:
        model, tok = zoo.load_worker("coder30" if use30 else "coder7")
        user = (f"Context:\n{context}\n\n" if context else "") + question
        draft = _generate(model, tok, _chat_text(tok, _CODER_SYSTEM, user),
                          max_new_tokens=1200)
        del model, tok
        zoo.unload_worker()
        return draft
    finally:
        zoo.unload_worker()                      # no-op if already unloaded
        zoo.load_resident("router")              # wake the router


# --------------------------------------------------------------- thinker ---
_THINK_SYSTEM = ("You are a rigorous reasoner. Think step by step, then "
                 "give a clear, complete final answer.")


def think(question: str, context: str = "") -> str:
    """Reasoning expert: Qwen3-8B in thinking mode. Its scratchpad is
    internal; only the final answer is returned. Parks the router —
    an 8B worker needs the same headroom the coder does."""
    zoo = get_zoo()
    zoo.unload_resident()
    try:
        model, tok = zoo.load_worker("thinker")
        user = (f"Context:\n{context}\n\n" if context else "") + question
        draft = _generate(model, tok, _chat_text(tok, _THINK_SYSTEM, user),
                          max_new_tokens=2500)
        del model, tok
        zoo.unload_worker()
        return draft
    finally:
        zoo.unload_worker()
        zoo.load_resident("router")


# ---------------------------------------------------------------- critic ---
_CRITIC_SYSTEM = """You are the final editor of a multi-agent workstation. You receive the user's request, any vision context, and a draft answer from a specialist. Produce the FINAL answer for the user:
- fix factual or code errors; complete anything missing
- merge in relevant details from the context
- keep the draft's structure and good content; don't rewrite for style
- if the draft is already correct, return it nearly unchanged
- if there is no draft, answer the request directly."""


def critique(question: str, context: str, draft: str) -> str:
    """Coexists with the router (3.3 + 1.2 GB — verified in the acceptance
    run), so it never parks it: the router stays warm for the next request."""
    zoo = get_zoo()
    model, tok = zoo.load_worker("critic")
    user = (f"## Request\n{question}\n\n## Context\n{context or '(none)'}"
            f"\n\n## Draft\n{draft}")
    final = _generate(model, tok, _chat_text(tok, _CRITIC_SYSTEM, user),
                      max_new_tokens=1500)
    del model, tok
    zoo.unload_worker()
    return final


# --- self-tests ------------------------------------------------------------
#   python -m workstation.agents code   "write a bash one-liner ..."
#   python -m workstation.agents critic "what is 2+2"
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
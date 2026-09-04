"""
router.py — the always-resident tiny brain.

Turns a raw request into a strict JSON plan the orchestrator executes:
    {"needs_vision": bool, "task_type": "code|reasoning|chat|vision_only",
     "prompt_tokens": int}

Fails soft: garbage output -> one corrective retry -> sensible defaults.
A deterministic keyword net catches obvious technical requests the 1.5B
might miss (e.g. "fix this: ValueError: ...").
The router must NEVER crash a request.
"""

from __future__ import annotations

import json
import re

from .model_zoo import get_zoo          # keep this import first in every file

SYSTEM = """You are the router of an AI workstation. Classify the request and respond with ONLY a JSON object — no markdown, no extra text:
{"needs_vision": <true|false>, "task_type": "<code|reasoning|chat|vision_only>"}

Rules:
- needs_vision=true ONLY if an image/screenshot is attached to the request.
- task_type=code: the user wants you to PRODUCE something technical — a command, one-liner, script, regex, config, or code — even if phrased as a question or a search ("how do I...", "find the...", "show me how to...", "fix..."). Requests involving errors, tracebacks, git, docker, or terminal work are code.
- task_type=reasoning: math, logic, comparisons, analysis, explanations of concepts.
- task_type=chat: casual conversation or simple factual questions.
- task_type=vision_only: the request is purely about understanding the attached image.

Examples:
"write a bash one-liner to find the 10 largest files" -> {"needs_vision": false, "task_type": "code"}
"how do I rename all .jpeg files to .jpg?" -> {"needs_vision": false, "task_type": "code"}
"fix this Python error: IndexError: list index out of range" -> {"needs_vision": false, "task_type": "code"}
"explain the difference between TCP and UDP" -> {"needs_vision": false, "task_type": "reasoning"}
"hi, how are you?" -> {"needs_vision": false, "task_type": "chat"}
"what is in this screenshot" (image attached) -> {"needs_vision": true, "task_type": "vision_only"}"""

_PLAN_RE = re.compile(r"\{.*\}", re.DOTALL)
_VALID_TASKS = {"code", "reasoning", "chat", "vision_only"}

# Deterministic safety net: obviously-technical requests never depend on
# the 1.5B's mood. Extend this list as you find misses in testing.
_CODE_FORCE = re.compile(
    r"(one[- ]liner|bash|zsh|shell|regex|script|debug|bug|fix|crash|"
    r"error|exception|traceback|stack ?trace|segfault|"
    r"(?:Value|Type|Index|Key|Attribute|Name|Import|Module|Runtime|"
    r"ZeroDivision|Assertion|Syntax)Error\b|"
    r"\.py\b|\.js\b|\.ts\b|\.cpp\b|\.rs\b|\.sql\b|"
    r"docker|kubectl|git |pip |npm |dnf |apt )", re.IGNORECASE)


def _generate(model, tok, user_content: str) -> str:
    import torch
    msgs = [{"role": "system", "content": SYSTEM},
            {"role": "user", "content": user_content}]
    # Qwen3 models think by default; Qwen2.5 doesn't know the flag.
    # Only pass it if this tokenizer's template actually supports it.
    kw = {}
    template = getattr(tok, "chat_template", None) or ""
    if "enable_thinking" in template:
        kw["enable_thinking"] = False
    text = tok.apply_chat_template(msgs, add_generation_prompt=True,
                                   tokenize=False, **kw)
    inputs = tok(text, return_tensors="pt").to(model.device)
    with torch.inference_mode():
        out = model.generate(**inputs, max_new_tokens=60, do_sample=False,
                             pad_token_id=getattr(tok, "pad_token_id", None)
                             or tok.eos_token_id)
    raw = tok.decode(out[0, inputs["input_ids"].shape[1]:],
                     skip_special_tokens=False)
    # defensive: strip <think> blocks if a hybrid-thinking model slips one in
    return re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()


def plan(user_text: str, has_image: bool) -> dict:
    """Request -> plan dict. Never raises on bad model output."""
    model, tok = get_zoo().load_resident("router")
    n_prompt_tokens = len(tok.encode(user_text))

    user_content = (f"Image attached: {str(has_image).lower()}\n"
                    f"Request: {user_text}")
    raw = _generate(model, tok, user_content)

    p: dict = {}
    for _attempt in range(2):                   # parse, then one retry
        m = _PLAN_RE.search(raw)
        if m:
            try:
                p = json.loads(m.group(0))
                break
            except json.JSONDecodeError:
                pass
        raw = _generate(model, tok,
                        user_content + "\n\nRespond with ONLY the JSON object.")

    task = p.get("task_type", "chat")
    # Keyword net beats the model vote for obvious cases.
    if task != "vision_only" and _CODE_FORCE.search(user_text):
        task = "code"
    needs_vision = bool(p.get("needs_vision", False)) and has_image
    if task == "vision_only" and has_image:
        needs_vision = True
    return {
        "needs_vision": needs_vision,
        "task_type": task if task in _VALID_TASKS else "chat",
        "prompt_tokens": n_prompt_tokens,
    }


# --- self-test:  python -m workstation.router "your request" --------------
def main() -> None:
    import argparse
    import logging
    ap = argparse.ArgumentParser(description="Router self-test")
    ap.add_argument("request")
    ap.add_argument("--image", action="store_true",
                    help="simulate an attached image")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)-7s %(message)s",
                        datefmt="%H:%M:%S")
    print(json.dumps(plan(args.request, has_image=args.image), indent=2))


if __name__ == "__main__":
    main()
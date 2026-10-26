"""
orchestrator.py — the state machine:
    router -> (vision -> context) -> ONE worker (coder|thinker) -> critic

Contract:
  * Vision output is CONTEXT, not the final draft — "screenshot of an
    error" + "fix this" wakes vision AND the coder.
  * Missing models degrade gracefully instead of downloading tens of GB
    inside an HTTP request. A vision-only request without the vision
    model refuses honestly instead of letting the critic invent an
    answer about an image it never saw.
  * Stage timings + VRAM timeline recorded for the portfolio chart.
"""

from __future__ import annotations

import logging
import time

from . import agents, router
from .model_zoo import get_zoo, has_model, role_key

log = logging.getLogger("shell-mind.mind")


def run_agentic_pipeline(prompt: str, image_path: str | None = None,
                          document_context: str = "") -> dict:
    zoo = get_zoo()
    t0 = time.perf_counter()
    stages: list[tuple[str, float]] = []
        
    missing = []
    if not has_model(role_key("router")):
        missing.append("router")
    if not has_model(role_key("critic")):
        missing.append("critic")

    if missing:
        return {
            "answer": (
                f"⚠️ Agent mode needs these models cached locally: "
                f"{', '.join(missing)}.\n\n"
                "Preload them once on this machine, then retry:\n\n"
                "  python -c \"from huggingface_hub import snapshot_download; "
                "snapshot_download('<hf_id from models.json / README>')\"\n\n"
                "See README → Model Registry."
            ),
            "task": "preload-required",
            "stages": [],
            "total_s": round(time.perf_counter() - t0, 1),
        }
    # 1) plan (router is resident)
    t = time.perf_counter()
    plan = router.plan(prompt, has_image=bool(image_path))
    stages.append(("router", time.perf_counter() - t))
    task = plan["task_type"]
    log.info("Router Plan: %s", plan)

    # A vision-only plan is meaningless without an image; downgrade to chat.
    if task == "vision_only" and not image_path:
        task = "chat"

    # Contradictory router output: vision_only + image must always run vision
    # even if needs_vision was false (1.5B can disagree with itself).
    if task == "vision_only" and image_path:
        plan["needs_vision"] = True

    # 2) vision (optional) -> compact text CONTEXT for the worker
    vision_ready = image_path is not None and has_model(role_key("vision"))
    if task == "vision_only" and not vision_ready:
        return {
            "answer": ("⚠️ This request needs the vision specialist, but "
                       "Qwen3-VL-8B is not in the local model cache yet "
                       "(see README → Model Registry for the one-time "
                       "download). Please re-send it once the model is "
                       "available."),
            "task": "vision_only",
            "stages": [("router", round(stages[0][1], 2))],
            "total_s": round(time.perf_counter() - t0, 1),
        }

    context = ""
    if plan["needs_vision"] and image_path:
        if vision_ready:
            t = time.perf_counter()
            context = agents.see(image_path, prompt)
            stages.append(("vision", time.perf_counter() - t))
            log.info("Vision summary: %d chars", len(context))
        else:
            log.warning("vision model not downloaded yet — running text-only")

    # RAG-Lite document text is for workers/critic only — never fed to the router.
    if document_context:
        context = (context + "\n\n" + document_context).strip() if context else document_context

    est_tokens = plan["prompt_tokens"] + len(context) // 4

    # 3) exactly one worker wakes (vision_only goes straight to the critic)
    draft = ""
    t = time.perf_counter()
    if task == "vision_only" and context:
        draft, context = context, ""        # the summary IS the draft
    elif task == "code":
        code_key = role_key("code")
        if not has_model(code_key):
            return {
                "answer": (
                    "⚠️ The code specialist is not in the local model cache yet. "
                    "Preload it on the GPU machine (one-time), then retry:\n\n"
                    "  python -c \"from huggingface_hub import snapshot_download; "
                    "snapshot_download('Qwen/Qwen2.5-Coder-7B-Instruct')\"\n\n"
                    "Or map a smaller cached model to the code role in models.json. "
                    "See README → Model Registry."
                ),
                "task": "code",
                "stages": [(s, round(d, 2)) for s, d in stages],
                "total_s": round(time.perf_counter() - t0, 1),
            }
        draft = agents.code(prompt, context, prompt_tokens=est_tokens)
    elif task == "reasoning" and has_model(role_key("reasoning")):
        draft = agents.think(prompt, context)
    elif task == "reasoning":
        log.warning("thinker not downloaded yet — critic answers directly")
    # task == "chat": no draft, critic answers directly
    if draft:
        stages.append((task, time.perf_counter() - t))

    # 4) critic merges / fact-checks / answers
    t = time.perf_counter()
    final = agents.critique(prompt, context,
                            draft or "(no draft — answer directly)")
    stages.append(("critic", time.perf_counter() - t))

    zoo.dump_timeline()
    log.info("=== Pipeline complete in %.1fs ===", time.perf_counter() - t0)
    return {
        "answer": final,
        "task": task,
        "stages": [(s, round(d, 2)) for s, d in stages],
        "total_s": round(time.perf_counter() - t0, 1),
    }

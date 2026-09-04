"""
orchestrator.py — the state machine:
    router -> (vision -> context) -> ONE worker (coder|thinker) -> critic

Fixes vs. first draft:
  * Vision output is CONTEXT, not the final draft — "screenshot of an
    error" + "fix this" now wakes vision AND the coder.
  * Guards for not-yet-downloaded models: the pipeline degrades
    gracefully instead of downloading 16 GB inside an HTTP request.
  * Stage timings + VRAM timeline recorded for the portfolio chart.
"""

from __future__ import annotations

import logging
import time

from . import agents, router
from .model_zoo import get_zoo

log = logging.getLogger("shell-mind.mind")


def run_agentic_pipeline(prompt: str, image_path: str | None = None) -> dict:
    zoo = get_zoo()
    t0 = time.perf_counter()
    stages: list[tuple[str, float]] = []

    # 1) plan (router is resident)
    t = time.perf_counter()
    plan = router.plan(prompt, has_image=bool(image_path))
    stages.append(("router", time.perf_counter() - t))
    task = plan["task_type"]
    log.info("Router Plan: %s", plan)

    # 2) vision (optional) -> compact text CONTEXT for the worker
    context = ""
    if plan["needs_vision"] and image_path:
        if zoo.has_model("vision"):
            t = time.perf_counter()
            context = agents.see(image_path, prompt)
            stages.append(("vision", time.perf_counter() - t))
            log.info("Vision summary: %d chars", len(context))
        else:
            log.warning("vision model not downloaded yet — running text-only")

    est_tokens = plan["prompt_tokens"] + len(context) // 4

    # 3) exactly one worker wakes (vision_only goes straight to the critic)
    draft = ""
    t = time.perf_counter()
    if task == "vision_only" and context:
        draft, context = context, ""        # the summary IS the draft
    elif task == "code":
        draft = agents.code(prompt, context, prompt_tokens=est_tokens)
    elif task == "reasoning" and zoo.has_model("thinker"):
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

    zoo.dump_timeline("vram_timeline.json")
    log.info("=== Pipeline complete in %.1fs ===", time.perf_counter() - t0)
    return {
        "answer": final,
        "task": task,
        "stages": [(s, round(d, 2)) for s, d in stages],
        "total_s": round(time.perf_counter() - t0, 1),
    }
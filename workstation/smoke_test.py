"""
Acceptance test for the shell-mind workstation hardware.

Verifies, per model: load -> generate -> measure tok/s -> unload -> VRAM
actually freed. Plus a coexistence check (resident router + critic fit
together) — the core architecture claim.

Usage (from the shell-mind repo root, venv active):
  python -m workstation.smoke_test              # fast set: router, critic, coder7
  python -m workstation.smoke_test coder30      # the big MoE test (opt-in)
  python -m workstation.smoke_test all          # enabled models (skips coder30/cpu05)
"""

from __future__ import annotations

import argparse
import logging
import sys
import time

from .model_zoo import REGISTRY, ModelZoo  # MUST be first — sets env before torch
import torch

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)-7s %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("smoke")

# "all" excludes:
#   coder30 — disabled in production (CODER30_ENABLED=False); needs GGUF path
#   cpu05   — CPU-tier model; loading via GPU worker path is the wrong test
_ALL_SKIP = frozenset({"coder30", "cpu05"})
SETS = {
    "fast": ["router", "critic", "coder7"],
    "all": [k for k in REGISTRY if k not in _ALL_SKIP],
}


def _header(zoo: ModelZoo) -> None:
    import transformers
    try:
        import bitsandbytes as bnb
        bnb_ver = bnb.__version__
    except Exception as exc:                       # noqa: BLE001
        bnb_ver = f"BROKEN ({exc})"
    cap = torch.cuda.get_device_capability(0)
    total = torch.cuda.get_device_properties(0).total_memory / 1024**3
    log.info("torch %s (CUDA %s) | transformers %s | bitsandbytes %s",
             torch.__version__, torch.version.cuda, transformers.__version__, bnb_ver)
    log.info("GPU: %s | sm_%d%d | %.1f GB total, %.1f GB free",
             torch.cuda.get_device_name(0), cap[0], cap[1], total, zoo.free_vram_gb())
    if str(bnb_ver).startswith("BROKEN"):
        log.error("bitsandbytes won't import — 4-bit will fail. Install a "
                  "Blackwell-compatible build (latest release).")


def _decode(tok, ids) -> str:
    return getattr(tok, "tokenizer", tok).decode(ids, skip_special_tokens=True)


def run_one(zoo: ModelZoo, key: str) -> dict:
    spec = REGISTRY[key]
    free_before = zoo.free_vram_gb()
    log.info("--- %s (%s) ---", key, spec.hf_id)

    t0 = time.perf_counter()
    model, tok = zoo.load_worker(key)              # may silently fall back
    loaded_key = zoo.worker_key
    load_s = round(time.perf_counter() - t0, 1)

    messages = [{"role": "user", "content": "Reply with exactly: OK"}]
    text = tok.apply_chat_template(messages, add_generation_prompt=True, tokenize=False)
    inputs = tok(text=text, return_tensors="pt")
    inputs = {k: v.to(model.device) if hasattr(v, "to") else v for k, v in inputs.items()}

    t1 = time.perf_counter()
    with torch.inference_mode():
        out = model.generate(**inputs, max_new_tokens=16, do_sample=False)
    gen_s = time.perf_counter() - t1
    n_new = int(out.shape[-1] - inputs["input_ids"].shape[-1])
    tok_s = round(n_new / gen_s, 1) if gen_s > 0 else 0.0
    reply = _decode(tok, out[0][inputs["input_ids"].shape[-1]:])

    # Drop every local reference before unload so CUDA memory can actually free.
    del model, tok, inputs, out
    zoo.unload_worker()
    free_after = zoo.free_vram_gb()

    result = {
        "key": key,
        "loaded": loaded_key,
        "fell_back": loaded_key != key,
        "load_s": load_s,
        "tok_s": tok_s,
        "n_new": n_new,
        "reply": reply.strip()[:80],
        "free_before": round(free_before, 2),
        "free_after": round(free_after, 2),
    }
    # 1.5 GB CUDA-context tolerance: residual allocator state is a floor, not a leak.
    result["ok"] = n_new > 0 and free_after >= free_before - 1.5
    log.info("result: %s", result)
    return result


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("targets", nargs="*", default=["fast"],
                    help="'fast', 'all', or any of: " + ", ".join(sorted(REGISTRY)))
    args = ap.parse_args()

    keys: list[str] = []
    for t in args.targets:
        keys.extend(SETS.get(t, [t]))
    if bad := [k for k in keys if k not in REGISTRY]:
        ap.error(f"unknown keys: {bad}")

    zoo = ModelZoo()
    _header(zoo)

    results = []
    for k in keys:
        try:
            results.append(run_one(zoo, k))
        except Exception as exc:                   # noqa: BLE001
            err = f"{type(exc).__name__}: {exc}"
            log.error("%s crashed: %s", k, err)
            results.append({"key": k, "ok": False, "error": err})

        # OUTSIDE the except block: the live traceback keeps a crashed model's
        # weights in VRAM; purging here runs only after they're released,
        # so one failure can never starve the next test of memory.
        zoo.purge()

    # ------------------------------------------------------------------
    # Core architecture claim (always, when critic exists in the registry):
    # router + critic must coexist in VRAM. Previously this only ran when
    # keys[-1] was router/critic, so the default "fast" set (ending in
    # coder7) skipped the check entirely — C2 in the v1.0 audit.
    # ------------------------------------------------------------------
    if "critic" in REGISTRY and "router" in REGISTRY:
        log.info("--- coexistence: resident router + critic (core claim) ---")
        try:
            zoo.load_resident("router")
            zoo.load_worker("critic")
            free = zoo.free_vram_gb()
            log.info("router + critic live together: %.1f GB VRAM still free", free)
            zoo.unload_worker()
            try:
                zoo.load_resident("router")  # restore resident if production-like
            except Exception:
                log.warning("router re-resident after coexistence failed — lazy reload later")
            results.append({
                "key": "coexistence:router+critic",
                "ok": True,
                "load_s": 0,
                "tok_s": 0,
                "free_after": round(free, 2),
            })
        except Exception as exc:                   # noqa: BLE001
            err = f"{type(exc).__name__}: {exc}"
            log.error("coexistence failed: %s", err)
            results.append({"key": "coexistence:router+critic", "ok": False, "error": err})
        finally:
            zoo.purge()

    zoo.dump_timeline()

    print("\n================ SMOKE TEST SUMMARY ================")
    for r in results:
        flag = "PASS" if r.get("ok") else "FAIL"
        line = f"[{flag}] {r['key']}"
        if r.get("fell_back"):
            line += f" -> fell back to {r['loaded']}"
        line += f" | load {r.get('load_s', '—')}s | {r.get('tok_s', '—')} tok/s"
        if "error" in r:
            line += f" | ERR: {r['error']}"
        print(line)
    sys.exit(0 if all(r.get("ok") for r in results) else 1)


if __name__ == "__main__":
    main()

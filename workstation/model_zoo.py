"""
model_zoo.py — the loading layer of the shell-mind workstation.

Contract with the rest of the system:
  * ONE resident model (the router) + ONE hot-swapped worker.
  * Everything 4-bit NF4 (bitsandbytes); vision towers stay bf16.
  * Every load is guarded — OOM or a broken quant path purges VRAM and
    falls back down the chain instead of killing the run.
  * VRAM is measured live around every load.
  * Users fully control which Hugging Face models fill each pipeline
    role via models.json (see models.example.json). Built-in defaults
    are only a starting point — nothing is forced.

Env vars are set BEFORE torch is imported. This module must always be the
first thing imported (agents/orchestrator import it, never torch directly).
"""

from __future__ import annotations


import gc
import json
import os
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

# --- environment: BEFORE torch --------------------------------------------
os.environ.setdefault("CUDA_VISIBLE_DEVICES", "0")
os.environ.setdefault("__NV_PRIME_RENDER_OFFLOAD", "1")
os.environ.setdefault("__GLX_VENDOR_LIBRARY_NAME", "nvidia")
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

from . import paths

os.environ.setdefault("HF_HOME", str(paths.HF_HOME))
os.environ.setdefault("HF_HUB_CACHE", str(paths.HF_HUB_CACHE))

import torch  # noqa: E402
from transformers import (  # noqa: E402
    AutoModelForCausalLM,
    AutoModelForImageTextToText,
    AutoProcessor,
    AutoTokenizer,
    BitsAndBytesConfig,
)

log = logging.getLogger("shell-mind.zoo")

# ---------------------------------------------------------------------------
# registry — defaults only; users override everything via models.json
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ModelSpec:
    key: str
    hf_id: str
    role: str
    vram_gb: float            # rough 4-bit resident size (hint for docs/charts)
    cpu_offload: bool         # split GPU + DDR5 (MoE only)
    fallback: Optional[str]   # registry key used if loading fails
    vision: bool = False


# Built-in starting point. Any entry can be replaced or extended in models.json.
DEFAULT_REGISTRY: dict[str, ModelSpec] = {
    "router":  ModelSpec("router",  "Qwen/Qwen2.5-1.5B-Instruct",        "router",  1.2, False, None),
    "vision":  ModelSpec("vision",  "Qwen/Qwen3-VL-8B-Instruct",         "vision",  6.0, False, None, vision=True),
    "coder30": ModelSpec("coder30", "Qwen/Qwen3-Coder-30B-A3B-Instruct", "coder",   6.0, True,  "coder7"),
    "coder7":  ModelSpec("coder7",  "Qwen/Qwen2.5-Coder-7B-Instruct",    "coder",   5.2, False, None),
    "thinker": ModelSpec("thinker", "Qwen/Qwen3-8B",                     "thinker", 5.5, False, None),
    "critic":  ModelSpec("critic",  "Qwen/Qwen3-4B-Instruct-2507",       "critic",  3.0, False, None),
    "cpu05":   ModelSpec("cpu05",   "Qwen/Qwen2.5-0.5B-Instruct",        "copilot", 0.5, False, None),
}

# Pipeline roles -> registry keys.
# Users remap these in models.json. Roles are fixed by the pipeline shape;
# only which Hugging Face model fills each role is configurable.
DEFAULT_ROLES: dict[str, str] = {
    "router":      "router",
    "vision":      "vision",
    "code":        "coder7",
    "reasoning":   "thinker",
    "critic":      "critic",
    "copilot_gpu": "coder7",
    "copilot_cpu": "cpu05",
}


def load_registry(config_path: Path | None = None
                  ) -> tuple[dict[str, ModelSpec], dict[str, str]]:
    """Built-in registry + roles, overlaid with the user's models.json.

    models.json schema (all fields optional):
      {
        "models": {
          "<key>": {
            "hf_id": "org/model-name",   # required for new keys
            "role": "custom",
            "vram_gb": 5.0,
            "cpu_offload": false,
            "fallback": "coder7",
            "vision": false
          }
        },
        "roles": {
          "code": "my_coder",
          "reasoning": "my_reasoner",
          ...
        }
      }

    Invalid entries log a warning and are ignored — user config must
    never crash the zoo. Missing fields inherit from an existing entry
    with the same key.
    """
    registry = dict(DEFAULT_REGISTRY)
    roles = dict(DEFAULT_ROLES)
    path = paths.CONFIG_PATH if config_path is None else config_path
    if not path.exists():
        return registry, roles
    try:
        cfg = json.loads(path.read_text())
        for key, raw in (cfg.get("models") or {}).items():
            # Skip documentation / example keys (e.g. _comment, _example_custom)
            # so copying models.example.json -> models.json cannot register junk
            # or trigger unexpected multi-GB downloads (audit C3).
            if key.startswith("_"):
                continue
            spec = raw if isinstance(raw, dict) else {"hf_id": str(raw)}
            base = registry.get(key)
            hf_id = str(spec.get("hf_id", base.hf_id if base else key))
            if not hf_id or "/" not in hf_id:
                log.warning("models.json: model '%s' has invalid hf_id %r — ignored",
                            key, hf_id)
                continue
            registry[key] = ModelSpec(
                key=key,
                hf_id=hf_id,
                role=str(spec.get("role", base.role if base else "custom")),
                vram_gb=float(spec.get("vram_gb", base.vram_gb if base else 5.0)),
                cpu_offload=bool(spec.get("cpu_offload",
                                          base.cpu_offload if base else False)),
                fallback=spec.get("fallback", base.fallback if base else None),
                vision=bool(spec.get("vision", base.vision if base else False)),
            )
        for role, key in (cfg.get("roles") or {}).items():
            if role not in DEFAULT_ROLES:
                log.warning("models.json: unknown role '%s' (valid: %s) — ignored",
                            role, ", ".join(sorted(DEFAULT_ROLES)))
            elif key in registry:
                roles[role] = key
            else:
                log.warning("models.json: role '%s' points at unknown model "
                            "key '%s' — ignored", role, key)
        log.info("models.json loaded from %s — %d models, roles: %s",
                 path, len(registry),
                 {r: roles[r] for r in DEFAULT_ROLES})
    except Exception as exc:                       # noqa: BLE001
        log.warning("models.json at %s invalid (%s) — using built-in defaults",
                    path, exc)
    return registry, roles


REGISTRY, ROLES = load_registry()


class ModelZoo:
    """One resident model + one hot-swapped worker, with VRAM accounting."""

    def __init__(self, kv_headroom_gb: float = 1.5, cpu_ram_budget_gb: float | None = None):
        if not torch.cuda.is_available():
            raise RuntimeError("CUDA unavailable.")
        self.kv_headroom_gb = kv_headroom_gb
        if cpu_ram_budget_gb is None:
            # Leave ~4 GB for OS / desktop; floor at 4 GB so offload still works
            try:
                total_ram = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
                total_gb = total_ram / (1024 ** 3)
            except (ValueError, OSError, AttributeError):
                total_gb = 16.0
            cpu_ram_budget_gb = max(4.0, total_gb - 4.0)
        self.cpu_ram_budget_gb = float(cpu_ram_budget_gb)

        self._worker: Optional[tuple] = None
        self._worker_key: Optional[str] = None
        self._resident: Optional[tuple] = None
        self._resident_key: Optional[str] = None

        self.timeline: list[dict[str, Any]] = []
        self._probe("init")

    @property
    def worker_key(self) -> Optional[str]:
        return self._worker_key

    @property
    def resident_key(self) -> Optional[str]:
        return self._resident_key

    def free_vram_gb(self) -> float:
        free_b, _total = torch.cuda.mem_get_info()
        return free_b / 1024**3

    def _probe(self, event: str) -> None:
        self.timeline.append({
            "t": round(time.perf_counter(), 3),
            "event": event,
            "free_gb": round(self.free_vram_gb(), 2),
            "torch_reserved_gb": round(torch.cuda.memory_reserved() / 1024**3, 2),
            "total_gb": round(torch.cuda.get_device_properties(0).total_memory / 1024**3, 2),
        })

    def note(self, event: str) -> None:
        """Record an external VRAM-relevant event (e.g. a copilot tier
        swap handled in ai_core) on the timeline without touching model
        state — keeps the chart a complete picture of GPU ownership."""
        self._probe(event)

    def _gpu_budget_gb(self) -> float:
        return max(self.free_vram_gb() - self.kv_headroom_gb, 2.0)

    @staticmethod
    def _quant(vision: bool = False,
               fp32_cpu_offload: bool = False) -> BitsAndBytesConfig:
        kwargs: dict[str, Any] = {}
        if vision:
            kwargs["llm_int8_skip_modules"] = ["visual", "merger", "lm_head"]
        if fp32_cpu_offload:
            kwargs["llm_int8_enable_fp32_cpu_offload"] = True
        return BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_use_double_quant=True,
            bnb_4bit_compute_dtype=torch.bfloat16,
            **kwargs,
        )

    @staticmethod
    def _release() -> None:
        gc.collect(); gc.collect()
        torch.cuda.empty_cache()
        torch.cuda.ipc_collect()

    def load_worker(self, key: str, _seen: set[str] | None = None) -> tuple:
        """Load a worker, replacing the current one. Falls back along
        REGISTRY[key].fallback on any failure. Returns (model, tokenizer).

        _seen tracks keys already tried so A→B→A cannot recurse forever (M8).
        """
        if key not in REGISTRY:
            raise KeyError(f"unknown model key '{key}' — add it to models.json "
                           f"or use one of: {', '.join(sorted(REGISTRY))}")
        seen = set(_seen) if _seen is not None else set()
        if key in seen:
            chain = " → ".join(list(seen) + [key])
            raise RuntimeError(
                f"fallback cycle detected: {chain} — check models.json fallback fields"
            )
        seen.add(key)

        spec = REGISTRY[key]
        err: str | None = None

        try:
            model, tok = self._load_spec(spec)
        except Exception as exc:
            if spec.fallback is None:
                raise
            err = f"{type(exc).__name__}: {exc}"

        if err is not None:
            log.warning("load '%s' (%s) failed: %s — purging, then falling back to '%s'",
                        key, spec.hf_id, err, spec.fallback)
            self.purge()
            if spec.fallback in seen:
                chain = " → ".join(list(seen) + [spec.fallback])
                raise RuntimeError(
                    f"fallback cycle detected: {chain} — check models.json fallback fields"
                )
            log.info(">>> falling back to '%s' (%s)",
                     spec.fallback, REGISTRY[spec.fallback].hf_id)
            return self.load_worker(spec.fallback, _seen=seen)

        self._worker, self._worker_key = (model, tok), key
        self._probe(f"loaded:{key}")
        return model, tok

    def _load_spec(self, spec: ModelSpec) -> tuple:
        self.unload_worker()
        t0 = time.perf_counter()
        log.info("loading %s [%s] ...", spec.hf_id, spec.role)

        if spec.cpu_offload:
            gpu = self._gpu_budget_gb()
            max_memory = {0: f"{gpu:.2f}GiB", "cpu": f"{self.cpu_ram_budget_gb:.2f}GiB"}
            device_map: Any = "auto"
            log.info("offload plan: GPU %.1f GiB + CPU %.1f GiB",
                     gpu, self.cpu_ram_budget_gb)
        else:
            max_memory = None
            device_map = {"": 0}

        cls = AutoModelForImageTextToText if spec.vision else AutoModelForCausalLM

        offload_dir = paths.OFFLOAD_DIR
        offload_dir.mkdir(parents=True, exist_ok=True)

        model = cls.from_pretrained(
            spec.hf_id,
            device_map=device_map,
            max_memory=max_memory,
            torch_dtype="auto",
            quantization_config=self._quant(
                vision=spec.vision,
                fp32_cpu_offload=spec.cpu_offload,
            ),
            offload_folder=str(offload_dir),
        )
        model.eval()
        tok = (AutoProcessor if spec.vision else AutoTokenizer).from_pretrained(spec.hf_id)

        log.info("loaded in %.1fs | %.1f GB VRAM free",
                 time.perf_counter() - t0, self.free_vram_gb())
        return model, tok

    def unload_worker(self) -> None:
        if self._worker is None:
            return
        key = self._worker_key
        self._worker, self._worker_key = None, None
        self._release()
        self._probe(f"unloaded:{key}")
        log.info("worker '%s' unloaded | %.1f GB VRAM free", key, self.free_vram_gb())

    def load_resident(self, key: str = "router") -> tuple:
        if key not in REGISTRY:
            raise KeyError(f"unknown model key '{key}'")
        if self._resident_key == key:
            return self._resident
        self.unload_resident()
        spec = REGISTRY[key]
        log.info("loading resident %s ...", spec.hf_id)
        model = AutoModelForCausalLM.from_pretrained(
            spec.hf_id, device_map={"": 0}, torch_dtype="auto",
            quantization_config=self._quant(),
        )
        model.eval()
        tok = AutoTokenizer.from_pretrained(spec.hf_id)
        self._resident, self._resident_key = (model, tok), key
        self._probe(f"resident:{key}")
        return self._resident

    def unload_resident(self) -> None:
        if self._resident is None:
            return
        key = self._resident_key
        self._resident, self._resident_key = None, None
        self._release()
        self._probe(f"resident_unloaded:{key}")

    def purge(self) -> None:
        self._worker, self._worker_key = None, None
        self._release()
        # Poll until free VRAM stabilizes (or ~1s) instead of a blind sleep (M13).
        try:
            prev = torch.cuda.mem_get_info()[0]
            for _ in range(10):
                time.sleep(0.1)
                cur = torch.cuda.mem_get_info()[0]
                if abs(cur - prev) < 16 * 1024 * 1024:  # <16 MB change
                    break
                prev = cur
        except Exception:
            time.sleep(0.2)

    def status(self) -> dict:
        return {
            "free_vram_gb": round(self.free_vram_gb(), 2),
            "resident": self._resident_key,
            "worker": self._worker_key,
            "roles": dict(ROLES),
        }

    def has_model(self, key: str) -> bool:
        return has_model(key)

    def dump_timeline(self, path: str | Path | None = None) -> None:
        if path is None:
            path = paths.TIMELINE_PATH
        Path(path).write_text(json.dumps(self.timeline, indent=2))
        log.info("VRAM timeline -> %s (%d samples)", path, len(self.timeline))


_ZOO: Optional[ModelZoo] = None


def get_zoo() -> ModelZoo:
    global _ZOO
    if _ZOO is None:
        _ZOO = ModelZoo()
    return _ZOO


# --- module-level lookups (usable without instantiating the zoo) -----------

def has_model(key: str) -> bool:
    """True when the model's weights are already in the local HF cache —
    used to avoid triggering multi-GB downloads inside a request.

    Contract tests install a pure in-memory ``transformers`` stub (no
    ``__file__``). Treat that environment as "cached" so H6 guards do not
    block stubbed end-to-end chat tests.
    """
    if key not in REGISTRY:
        return False
    try:
        import transformers as _tf
        if getattr(_tf, "__file__", None) is None:
            return True
    except Exception:
        pass
    spec = REGISTRY[key]
    hub = Path(os.environ.get("HF_HUB_CACHE",
                              str(Path(os.environ["HF_HOME"]) / "hub")))
    snaps = hub / f"models--{spec.hf_id.replace('/', '--')}" / "snapshots"
    # Accept safetensors (modern) or pytorch .bin (legacy / custom exports)
    return bool(
        any(snaps.glob("*/*.safetensors"))
        or any(snaps.glob("*/*.bin"))
    )


def role_key(role: str) -> str:
    """Registry key currently filling a pipeline role.

    If a custom assignment isn't downloaded locally, silently falls back
    to the built-in default for that role so a stale models.json can never
    break the pipeline mid-request.
    """
    if role not in ROLES:
        raise KeyError(f"unknown role '{role}' — valid: {', '.join(sorted(DEFAULT_ROLES))}")
    key = ROLES[role]
    default = DEFAULT_ROLES.get(role, key)
    if (key != default and not has_model(key) and has_model(default)):
        log.warning("role '%s': custom model '%s' not in local cache — "
                    "using built-in '%s'", role, key, default)
        return default
    return key


def active_models_summary() -> dict[str, str]:
    """Human-readable map of role → hf_id for /health and docs."""
    out = {}
    for role in DEFAULT_ROLES:
        key = ROLES.get(role, DEFAULT_ROLES[role])
        spec = REGISTRY.get(key)
        out[role] = spec.hf_id if spec else key
    return out

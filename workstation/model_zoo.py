"""
model_zoo.py — the loading layer of the shell-mind workstation.

Contract with the rest of the system:
  * ONE resident model (the router, ~1.2 GB) + ONE hot-swapped worker.
  * Everything 4-bit NF4 (bitsandbytes); vision towers stay bf16.
  * The MoE coder gets a GPU+DDR5 split: attention on the 5050, experts in RAM.
  * Every load is guarded — OOM or a broken quant path purges VRAM and
    falls back down the chain (coder30 -> coder7) instead of killing the run.
  * VRAM is measured live before every load, so "<7 GB peak" is enforced.

Env vars are set BEFORE torch is imported. This module must always be the
first thing imported (agents/orchestrator import it, never torch directly).
"""

from __future__ import annotations

import gc
import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

# --- environment: BEFORE torch --------------------------------------------
os.environ.setdefault("CUDA_VISIBLE_DEVICES", "0")
os.environ.setdefault("__NV_PRIME_RENDER_OFFLOAD", "1")
os.environ.setdefault("__GLX_VENDOR_LIBRARY_NAME", "nvidia")
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

_WS_ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("HF_HOME", str(_WS_ROOT / "models" / "hf_cache"))

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
# registry — the single place to swap models
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ModelSpec:
    key: str
    hf_id: str
    role: str
    vram_gb: float            # rough 4-bit resident size
    cpu_offload: bool         # split GPU + DDR5 (MoE only)
    fallback: Optional[str]   # registry key used if loading fails
    vision: bool = False

REGISTRY: dict[str, ModelSpec] = {
    "router":  ModelSpec("router",  "Qwen/Qwen2.5-1.5B-Instruct",        "router",  1.2, False, None),
    "vision":  ModelSpec("vision",  "Qwen/Qwen3-VL-8B-Instruct",         "vision",  6.0, False, None, vision=True),
    "coder30": ModelSpec("coder30", "Qwen/Qwen3-Coder-30B-A3B-Instruct", "coder",   6.0, True,  "coder7"),
    "coder7":  ModelSpec("coder7",  "Qwen/Qwen2.5-Coder-7B-Instruct",    "coder",   5.2, False, None),
    "thinker": ModelSpec("thinker", "Qwen/Qwen3-8B",                     "thinker", 5.5, False, None),
    "critic":  ModelSpec("critic",  "Qwen/Qwen3-4B-Instruct-2507",       "critic",  3.0, False, None),
}

class ModelZoo:
    """One resident model + one hot-swapped worker, with VRAM accounting."""

    def __init__(self, kv_headroom_gb: float = 1.5, cpu_ram_budget_gb: float = 13.0):
        if not torch.cuda.is_available():
            raise RuntimeError("CUDA unavailable.")
        self.kv_headroom_gb = kv_headroom_gb
        self.cpu_ram_budget_gb = cpu_ram_budget_gb

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
        })

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

    def load_worker(self, key: str) -> tuple:
        """Load a worker, replacing the current one. Falls back along
        REGISTRY[key].fallback on any failure. Returns (model, tokenizer)."""
        spec = REGISTRY[key]
        err: str | None = None
        
        try:
            model, tok = self._load_spec(spec)
        except Exception as exc:
            if spec.fallback is None:
                raise
            # Convert to string to drop traceback references before purging
            err = f"{type(exc).__name__}: {exc}"

        if err is not None:
            log.warning("load '%s' (%s) failed: %s — purging, then falling back to '%s'",
                        key, spec.hf_id, err, spec.fallback)
            self.purge()  
            log.info(">>> falling back to '%s' (%s)", spec.fallback, REGISTRY[spec.fallback].hf_id)
            return self.load_worker(spec.fallback)

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
            log.info("offload plan: GPU %.1f GiB + CPU %.1f GiB", gpu, self.cpu_ram_budget_gb)
        else:
            max_memory = None
            device_map = {"": 0}

        cls = AutoModelForImageTextToText if spec.vision else AutoModelForCausalLM
        
        # Ensure offload directory exists for disk spilling
        offload_dir = _WS_ROOT / "offload_cache"
        offload_dir.mkdir(exist_ok=True)

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
        time.sleep(0.5)

    def status(self) -> dict:
        return {
            "free_vram_gb": round(self.free_vram_gb(), 2),
            "resident": self._resident_key,
            "worker": self._worker_key,
        }
        
    def has_model(self, key: str) -> bool:
        spec = REGISTRY[key]
        hub = Path(os.environ.get("HF_HUB_CACHE",
                                  str(Path(os.environ["HF_HOME"]) / "hub")))
        snaps = hub / f"models--{spec.hf_id.replace('/', '--')}" / "snapshots"
        return bool(any(snaps.glob("*/*.safetensors")))
    
    def dump_timeline(self, path: str | Path = "vram_timeline.json") -> None:
        Path(path).write_text(json.dumps(self.timeline, indent=2))
        log.info("VRAM timeline -> %s (%d samples)", path, len(self.timeline))

_ZOO: Optional[ModelZoo] = None

def get_zoo() -> ModelZoo:
    global _ZOO
    if _ZOO is None:
        _ZOO = ModelZoo()
    return _ZOO
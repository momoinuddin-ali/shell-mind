"""
paths.py — the single source of truth for every filesystem location
Shell-Mind writes to: model cache, offload scratch, uploads, the audit
database and the VRAM timeline.

Everything resolves relative to the repository root, so the server
behaves identically no matter which directory it was launched from.

Overrides (set before starting the server):
    SHELL_MIND_MODELS_DIR   model cache root (default: <repo>/models)
    SHELL_MIND_DB           audit log path   (default: <repo>/shell_mind_history.db)

Compatibility: 0.x releases anchored the model cache one level ABOVE the
repo (a parents[2] bug). If that legacy cache exists and the new location
does not, we keep using it so nobody re-downloads ~100 GB of weights.
Point SHELL_MIND_MODELS_DIR at the old directory (or move it to
<repo>/models) to control the migration yourself.

User model configuration lives in models.json at the repo root
(see models.example.json and the load_registry() logic in model_zoo.py).
"""

from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _prefer_existing(default: Path, legacy: Path) -> Path:
    """Use `legacy` only when it exists and `default` does not."""
    return legacy if (not default.exists() and legacy.exists()) else default


_env_models = os.environ.get("SHELL_MIND_MODELS_DIR")
MODELS_DIR = (
    Path(_env_models)
    if _env_models
    else _prefer_existing(REPO_ROOT / "models", REPO_ROOT.parent / "models")
)
HF_HOME = MODELS_DIR / "hf_cache"
HF_HUB_CACHE = HF_HOME / "hub"

OFFLOAD_DIR = _prefer_existing(REPO_ROOT / "offload_cache",
                               REPO_ROOT.parent / "offload_cache")
UPLOADS_DIR = REPO_ROOT / "uploads"
DB_PATH = Path(os.environ.get("SHELL_MIND_DB",
                              REPO_ROOT / "shell_mind_history.db"))
TIMELINE_PATH = REPO_ROOT / "vram_timeline.json"
# User model-configuration overlay (parsed by model_zoo.load_registry).
# Copy models.example.json → models.json and edit freely.
CONFIG_PATH = REPO_ROOT / "models.json"

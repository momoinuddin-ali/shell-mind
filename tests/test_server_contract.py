"""
test_server_contract.py — API contract tests for the Shell-Mind server.

These tests stub out torch/transformers, so they run on any machine
(fastapi + httpx only, no GPU, no model weights) and validate the parts
of the server that must never regress:

  * upload whitelist / size cap / UUID storage
  * /chat only opens server-issued paths (no arbitrary file reads)
  * proper HTTP status codes (413 / 415 / 400 / 404 / 422)
  * document context injection reaches the model, results hit the audit log
  * paths.py anchors everything to the repo root

Usage:
    python tests/test_server_contract.py
"""

from __future__ import annotations

import contextlib
import os
import sys
import tempfile
import types
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

# The audit DB must not touch the real one while testing.
_TMP_DB = Path(tempfile.mkdtemp(prefix="sm-test-")) / "test_history.db"
os.environ["SHELL_MIND_DB"] = str(_TMP_DB)

# ---------------------------------------------------------------------------
# Stub torch + transformers BEFORE importing the server (HAS_GPU -> False).
# ---------------------------------------------------------------------------

class _FakeBatch(dict):
    def to(self, device):
        return self


class _FakeIds(list):
    @property
    def shape(self):
        return (1, len(self))


class FakeTokenizer:
    eos_token_id = 0
    pad_token_id = 0
    captured_prompt: list[str] = []

    def apply_chat_template(self, messages, tokenize=False,
                            add_generation_prompt=True):
        return "".join(m["content"] for m in messages)

    def __call__(self, text, return_tensors="pt"):
        type(self).captured_prompt.append(text)
        return _FakeBatch({"input_ids": _FakeIds(range(8))})

    def decode(self, ids, skip_special_tokens=True):
        return "stub reply"


class FakeModel:
    device = "cpu"

    def generate(self, **kwargs):
        return [list(range(20))]


def _install_stubs() -> None:
    torch_stub = types.ModuleType("torch")
    torch_stub.cuda = types.SimpleNamespace(
        is_available=lambda: False,
        empty_cache=lambda: None,
        ipc_collect=lambda: None,
        mem_get_info=lambda: (0, 8 * 1024**3),
        memory_reserved=lambda: 0,
        get_device_properties=lambda i: types.SimpleNamespace(
            total_memory=8 * 1024**3),
    )
    torch_stub.bfloat16 = "bfloat16"
    torch_stub.float32 = "float32"
    torch_stub.inference_mode = contextlib.nullcontext
    sys.modules["torch"] = torch_stub

    tf_stub = types.ModuleType("transformers")

    class _Dummy:
        def __init__(self, *a, **k):
            pass

    class _FromPretrained:
        def __init__(self, factory):
            self._factory = factory

        def from_pretrained(self, *a, **k):
            return self._factory()

    tf_stub.AutoTokenizer = _FromPretrained(FakeTokenizer)
    tf_stub.AutoModelForCausalLM = _FromPretrained(FakeModel)
    tf_stub.AutoModelForImageTextToText = _FromPretrained(FakeModel)
    tf_stub.AutoProcessor = _FromPretrained(FakeTokenizer)
    tf_stub.BitsAndBytesConfig = _Dummy
    sys.modules["transformers"] = tf_stub


_install_stubs()

from workstation import paths                                  # noqa: E402
import primary_node.ai_core as ai_core                         # noqa: E402
from fastapi.testclient import TestClient                      # noqa: E402

PASSED: list[str] = []
FAILED: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    (PASSED if cond else FAILED).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}"
          + (f" — {detail}" if detail and not cond else ""))


def main() -> None:
    client = TestClient(ai_core.app)

    print("paths:")
    check("uploads dir inside repo", paths.UPLOADS_DIR == REPO_ROOT / "uploads")
    check("timeline anchored to repo",
          paths.TIMELINE_PATH == REPO_ROOT / "vram_timeline.json")
    check("SHELL_MIND_DB override honored", paths.DB_PATH == _TMP_DB)

    print("health:")
    r = client.get("/health")
    body = r.json()
    check("GET /health -> 200", r.status_code == 200)
    check("health reports tier + gpu flag",
          "tier" in body and body.get("gpu") is False, str(body))

    print("frontend serving:")
    r = client.get("/")
    check("GET / serves the web UI",
          r.status_code == 200 and "Shell-Mind" in r.text, f"got {r.status_code}")
    r = client.get("/script.js")
    check("GET /script.js served by the backend",
          r.status_code == 200 and "detectServer" in r.text,
          f"got {r.status_code}")

    print("upload validation:")
    r = client.post("/upload", files={"file": ("evil.sh", b"rm -rf /\n")})
    check("non-whitelisted extension -> 415", r.status_code == 415,
          f"got {r.status_code}")

    r = client.post("/upload", files={"file": ("notes.txt", b"hello world")})
    check("txt upload -> 200", r.status_code == 200, f"got {r.status_code}")
    doc_path = r.json().get("document_path", "")
    # Opaque token: UUID filename only (no absolute server path)
    stored = paths.UPLOADS_DIR / Path(doc_path).name
    check("stored inside uploads dir",
          Path(doc_path).name == doc_path and stored.is_file(),
          doc_path)
    check("stored under UUID name (original name gone)",
          stored.stem.isascii() and stored.suffix == ".txt"
          and "notes" not in stored.name, stored.name)
    check("status field present",
          r.json().get("status") == "stored_for_processing")

    ai_core.MAX_UPLOAD_BYTES = 100          # small cap for the test
    r = client.post("/upload", files={"file": ("big.txt", b"x" * 1000)})
    check("oversize upload -> 413", r.status_code == 413, f"got {r.status_code}")
    ai_core.MAX_UPLOAD_BYTES = 25 * 1024 * 1024

    print("upload storage cap:")
    ai_core.UPLOADS_TOTAL_CAP_BYTES = 50
    prior_upload_names = {f.name for f in paths.UPLOADS_DIR.iterdir()}
    r = client.post("/upload", files={"file": ("fill.txt", b"y" * 200)})
    check("total-storage overflow -> 413",
          r.status_code == 413, f"got {r.status_code}")
    # Ignore pre-existing files in uploads/; only the overflow attempt must be gone
    leftovers = [f for f in paths.UPLOADS_DIR.iterdir()
                 if f.name not in prior_upload_names and f.name != stored.name]
    check("overflowed upload deleted", not leftovers,
          str(leftovers))
    ai_core.UPLOADS_TOTAL_CAP_BYTES = 500 * 1024 * 1024

    print("chat path validation:")
    r = client.post("/chat", json={"prompt": "hi", "mode": "cpu",
                                   "document_path": "/etc/passwd"})
    check("arbitrary path -> 400", r.status_code == 400, f"got {r.status_code}")

    r = client.post("/chat", json={"prompt": "hi", "mode": "cpu",
                                   "document_path": str(paths.UPLOADS_DIR / "nope.txt")})
    check("non-existent issued path -> 404", r.status_code == 404,
          f"got {r.status_code}")

    r = client.post("/chat", json={"prompt": "hi", "mode": "turbo"})
    check("invalid mode -> 422", r.status_code == 422, f"got {r.status_code}")

    print("chat end-to-end (stubbed model):")
    import sqlite3
    with sqlite3.connect(_TMP_DB) as conn:
        before = conn.execute("SELECT COUNT(*) FROM interactions").fetchone()[0]

    FakeTokenizer.captured_prompt.clear()
    r = client.post("/chat", json={"prompt": "summarize", "mode": "cpu",
                                   "document_path": doc_path})
    check("/chat with issued doc -> 200", r.status_code == 200,
          f"got {r.status_code}: {r.text[:120]}")
    check("answer returned", r.json().get("answer") == "stub reply")
    check("document context injected into the prompt",
          any("hello world" in p for p in FakeTokenizer.captured_prompt))
    with sqlite3.connect(_TMP_DB) as conn:
        after = conn.execute("SELECT COUNT(*) FROM interactions").fetchone()[0]
    check("interaction appended to audit log", after == before + 1)
    with sqlite3.connect(_TMP_DB) as conn:
        last_client = conn.execute(
            "SELECT client FROM interactions ORDER BY id DESC LIMIT 1"
        ).fetchone()[0]
    check("audit log records the client address",
          last_client == "testclient", f"got {last_client!r}")

    print("api-key guard (reload with SHELL_MIND_API_KEY set):")
    import importlib
    import primary_node.ai_core as ai_core_mod
    os.environ["SHELL_MIND_API_KEY"] = "test-secret-key"
    try:
        locked_app = importlib.reload(ai_core_mod).app
        locked = TestClient(locked_app)

        r = locked.get("/health")
        check("/health stays open with a key set", r.status_code == 200)

        r = locked.post("/chat", json={"prompt": "hi", "mode": "cpu"})
        check("/chat without key -> 401", r.status_code == 401,
              f"got {r.status_code}")

        r = locked.post("/chat", json={"prompt": "hi", "mode": "cpu"},
                        headers={"X-API-Key": "wrong"})
        check("/chat wrong key -> 401", r.status_code == 401,
              f"got {r.status_code}")

        r = locked.post("/upload", files={"file": ("a.txt", b"k")})
        check("/upload without key -> 401", r.status_code == 401,
              f"got {r.status_code}")
        for f in paths.UPLOADS_DIR.iterdir():
            f.unlink()          # nothing should have been written

        r = locked.post("/chat", json={"prompt": "hi", "mode": "cpu"},
                        headers={"X-API-Key": "test-secret-key"})
        check("/chat with correct key -> 200", r.status_code == 200,
              f"got {r.status_code}: {r.text[:120]}")
    finally:
        del os.environ["SHELL_MIND_API_KEY"]
        importlib.reload(ai_core_mod)     # back to open mode

    # cleanup: remove files this test created in uploads/
    stored.unlink(missing_ok=True)

    print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
    if FAILED:
        print("FAILED:", ", ".join(FAILED))
        sys.exit(1)


if __name__ == "__main__":
    main()

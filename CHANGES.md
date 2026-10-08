# Shell-Mind — Professionalization Changelog (October 2026)

Full record of the hardening pass applied after the October 7 code analysis.
Everything below is **verified**: 20/20 automated contract tests pass, and the
server was exercised end-to-end on the RTX 5050 (three live agent pipelines:
114.6 s, 91.3 s, 52.5 s) with the GUI served by the backend and the CLI
running against it.

## File-by-file: before → after

| File | Before | After | What changed |
|------|-------:|------:|--------------|
| `primary_node/ai_core.py` | 229 | 380 | Rewritten (see below) |
| `workstation/model_zoo.py` | 255 | 266 | Path anchoring, timeline `total_gb`, `note()` |
| `workstation/orchestrator.py` | 76 | 96 | Honest vision-only refusal |
| `workstation/paths.py` | — | 47 | **NEW** — single source of truth for filesystem locations |
| `workstation/smoke_test.py` | 159 | 159 | Timeline dump path (1 line) |
| `workstation/agents.py` | 216 | 216 | Unchanged (already correct) |
| `workstation/router.py` | 126 | 126 | Unchanged (already correct) |
| `cli.py` | 175 | 211 | Image upload flow, honest menu, ping fix |
| `frontend/script.js` | 622 | 359 | Dead code removed + detection hardened |
| `frontend/index.html` | 84 | 84 | Label/accept fixes |
| `frontend/style.css` | 154 | 154 | Unchanged |
| `vram_chart.py` | 54 | 161 | CLI args, session trim, label collision resolver |
| `README.md` | 287 | 317 | Rewritten to match reality |
| `requirements.txt` (root) | — | 13 | **NEW** (was only `primary_node/requirements.txt`) |
| `tests/test_server_contract.py` | — | 213 | **NEW** — 20 API contract tests |
| `.gitignore` / `.zcodeignore` | 18 | 18 | Cleaned, mangled `*.db` line fixed |
| `supervisor/safety.py` | 19 | — | **DELETED** (dead code, fake "sandbox") |
| `primary_node/requirements.txt` | 10 | — | **DELETED** (replaced by root file) |

## Bugs fixed

1. **Model cache written outside the repo.** `parents[2]` in `model_zoo.py`
   and `ai_core.py` resolved to the *parent* of the repo, so `models/` and
   `offload_cache/` landed outside the project (verified on disk). Fixed via
   `workstation/paths.py` (`REPO_ROOT = parents[1]`), with a legacy fallback
   that keeps using the existing out-of-repo cache so no weights re-download.
2. **README quick start failed on a fresh clone.** `pip install -r
   requirements.txt` pointed at a nonexistent root file. Root
   `requirements.txt` now exists and gains the silently-missing
   `matplotlib`, `python-multipart` (required for uploads),
   `httpx` (required by tests).
3. **CLI remote image attach was broken.** `cli.py` sent a client-local path
   as `image_path`; the server tried to open it locally. Works only when CLI
   and server share a filesystem — broken for the advertised Tailscale use
   case. The CLI now POSTs the file to `/upload_image` first and uses the
   server-issued path.
4. **Arbitrary file read via `/chat`.** `document_path`/`image_path` were
   opened from anywhere on the server filesystem (LAN-exposed, 0.0.0.0 +
   CORS `*`). `/chat` now accepts only paths inside the server-managed
   `uploads/` directory — anything else gets HTTP 400/404. Combined with
   UUID filenames + extension whitelist + 25 MB cap + proper 413/415 codes
   + 24 h stale-upload purge.
5. **Server unreachable for minutes at boot.** The 7B copilot loaded at
   module import, blocking uvicorn startup (and downloading 5+ GB on first
   run before serving). All tiers now load lazily on first use; the server
   accepts requests within seconds. Confirmed live: boot at 03:41:25, first
   model load at 03:42:20, on demand.
6. **`supervisor/safety.py` was a footgun.** Dead code whose
   `run_sandboxed()` executed arbitrary Python with full privileges behind
   a 4-string blocklist. Deleted before it could ever be wired into the
   agent loop.
7. **Vision-only hallucination.** A vision-only request with the vision
   model not downloaded let the critic "answer" an image it never saw. The
   orchestrator now refuses with a clear message.
8. **CLI `ping()` read a nonexistent `/health` field** (`default_model`) —
   always printed `?`. Fixed.
9. **Frontend pointed at the wrong server.** The first autodetect heuristic
   (same-origin) made the GUI talk to a static file server when one was
   used, producing 404/501 errors. The backend now **serves the frontend
   itself** at `/` (one terminal, no static server), and `script.js` probes
   candidates (`?server=` → same origin → `localhost:8000` →
   `127.0.0.1:8000`) for a live `/health` before committing.
10. **DB, timeline, uploads, offload paths were CWD-relative.** They landed
    wherever uvicorn was launched from. All anchored to the repo root via
    `paths.py`; `SHELL_MIND_MODELS_DIR` / `SHELL_MIND_DB` env overrides
    available.

## README claims corrected

- `coder30` marked **disabled by default**, with the bitsandbytes
  fp32-offload rationale (the GPU+DDR5 split is impractical under bnb;
  GGUF/llama.cpp is the future path). Registry, fallback wiring and smoke
  target retained for a flag-flip integration later.
- "Every load is preceded by a live VRAM measurement" scoped to reality:
  VRAM is measured and *recorded* around every load, pre-flight fit checks
  exist for the offload path, and the fallback chain is `coder30 → coder7`
  (un-routable failures purge VRAM and return a clean error).
- Swap-latency cost stated up front: ~5–15 s per model load, 1–3 min agent
  runs — the price of zero-sum orchestration on 8 GB.
- Router described as "resident between stages; parked while heavy workers
  run" (it was previously both "always-resident" and parked — contradictory).
- Audit log called *append-only*, not "immutable".
- UI label corrected from "200 MB" to the real 25 MB limit.
- New **Limitations** section and **Security note** (no auth — trusted
  network only).

## New capabilities

- **One-terminal workflow**: `uvicorn primary_node.ai_core:app` serves both
  the API and the web UI at `http://localhost:8000`.
- **Real CPU tier on GPU hosts**: selecting `cpu` mode runs the 0.5B model
  on the CPU and leaves the GPU completely free (previously the CPU choice
  silently used the GPU model).
- **VRAM timeline completeness**: copilot loads/unloads are recorded on the
  same timeline as agent-zoo swaps (`ModelZoo.note()`), and every sample
  includes `total_gb` so charts are self-describing.
- **Chart robustness**: `vram_chart.py` grew `--in/--out/--last` args, trims
  to the latest session (no more multi-hour dead axis), uses readable event
  labels, and resolves label collisions by measuring rendered boxes.
- **Contract test suite** (`python tests/test_server_contract.py`): stubs
  torch/transformers, runs GPU-less on any machine, locks in upload rules,
  path validation, status codes, RAG injection and audit logging — 20 tests.

## Frontend cleanup

- 310 lines of commented-out duplicate code removed from `script.js`
  (622 → 359 lines, zero behavior lost).
- Corrupted `localStorage` no longer bricks the UI (guarded parse + reset).
- Upload rejections surface the server's actual error (e.g. "type not
  allowed") instead of a generic alert.
- `.gif` accepted end-to-end (input filter + server whitelist).

## Verification evidence (live, RTX 5050)

From the server log after this pass:

- `GET / 200` — backend serves the GUI.
- Boot 03:41:25 → first model load 03:42:20 — lazy loading confirmed.
- Zero-sum discipline: thinker unload → 6.3 GB free; critic + router
  coexist → 2.7 GB free; every unload returns to ~0.1 GB of baseline.
- Timeline written to the repo root: `.../shell-mind/vram_timeline.json`.
- Three full pipelines completed: 114.6 s, 91.3 s, 52.5 s; router ≈ 0.3 s,
  thinker load ≈ 15–17 s, critic load ≈ 9 s.
- Audit log at `.../shell-mind/shell_mind_history.db`.

## Known optional follow-ups

- Set `HF_HUB_OFFLINE=1` once all models are cached — skips the ~10 s of
  Hugging Face HEAD requests per load and silences the unauthenticated-
  requests warning. (Or set `HF_TOKEN`.)
- `favicon.ico` 404 — cosmetic; add one if it bothers you.
- Streaming responses (SSE/WebSockets) remains future work.

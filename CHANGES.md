# Shell-Mind — Changelog & Development Timeline

This file is the single chronological record of how Shell-Mind evolved.
It merges: the original mini-project build, the October 2026 hardening
pass (analysis + fixes), the security pass, mobile/Tailscale polish, and
the models.json customization layer.

---

## Timeline (straightened)

| When | What happened |
|------|----------------|
| **Sep–early Oct 2026** | Core system built for the 3rd-semester mini-project: Zero-Sum VRAM orchestration, 3-tier engine (CPU / GPU Copilot / Agent), FastAPI server, vanilla UI, CLI, smoke tests, SQLite audit log. Team: Moinuddin, Imtiyaz, Ayaan, Himanshu (SSTC Bhilai). |
| **~Oct 7** | External code review (Z / GLM session) of the live repo. Found 10 real bugs: cache path outside repo (`parents[2]`), missing root `requirements.txt`, broken CLI remote image, arbitrary file read via `/chat`, eager model load blocking boot, dead unsafe “sandbox”, vision-only hallucination, CLI health mismatch, dual-server GUI confusion, CWD-relative paths. |
| **Oct 7–8** | Professionalization pass applied on the GPU box: `paths.py`, lazy loading, secure uploads, path validation, backend serves UI, CLI image upload, contract tests, README honesty pass. Left uncommitted initially; then verified live (boot seconds, three agent pipelines 52–115 s, VRAM returns to baseline). |
| **Oct 9** | Security pass: optional `SHELL_MIND_API_KEY`, upload storage cap, client IP in audit log, Tailscale-only bind documented. Contract suite 20 → 28 tests. |
| **Oct 10–11** | Docs fixes (`cpu05`, test counts, models.json section). Mobile UI redraw (drawer + backdrop). Rate limiting + busy 503. `setup.sh` key rotation. End-to-end success from Android over Tailscale (`gpu · 0.88G · key`, chat 200). |
| **Current** | models.json role system is the supported way to customize Hugging Face models. **No GUI model picker** (server-owner config by design for v1). |

---

## File-by-file (hardening baseline → current)

| File | Role in the system |
|------|--------------------|
| `primary_node/ai_core.py` | FastAPI: lazy tiers, secure uploads, API key, rate limit, busy lock, serves frontend |
| `workstation/paths.py` | **NEW** — all paths anchored to repo root (+ legacy cache fallback) |
| `workstation/model_zoo.py` | Load/unload, VRAM timeline, `models.json` registry + roles |
| `workstation/orchestrator.py` | Router → vision → worker → critic; honest vision refusal |
| `workstation/agents.py` | wake → work → sleep specialists (via `role_key`) |
| `workstation/router.py` | 1.5B planner → JSON plan |
| `workstation/smoke_test.py` | Hardware acceptance (load / generate / free VRAM) |
| `cli.py` | Thin client; uploads images before chat; `--key` |
| `frontend/*` | Glassmorphism UI, mobile drawer, auth prompt, short status |
| `tests/test_server_contract.py` | **NEW** — GPU-less API contract suite (~28 tests) |
| `setup.sh` | Server/client onboarding + **key rotation** |
| `models.example.json` | Template for custom HF model IDs |
| `SECURITY.md` | API key threat model and rotation |
| `vram_chart.py` | Portfolio chart from timeline |
| `supervisor/safety.py` | **DELETED** (fake sandbox / RCE footgun) |

---

## Bugs fixed (the original 10 + follow-ons)

1. Model cache written **outside** the repo (`parents[2]`) — fixed + legacy fallback  
2. README quick start failed (no root `requirements.txt`)  
3. CLI remote image broken — now uploads via `/upload_image`  
4. Arbitrary file read via `/chat` — only server-issued upload paths  
5. Server blocked for minutes at boot — lazy model load  
6. Dead unsafe `supervisor/safety.py` — deleted  
7. Vision-only hallucination — refuse if VLM missing  
8. CLI `/health` field mismatch  
9. GUI pointed at static server — backend serves UI + health probe  
10. CWD-relative DB/timeline/uploads — anchored via `paths.py`  

**Later:** API key auth, rate limit, busy 503, mobile layout, key rotation in `setup.sh`, models.json documentation.

---

## Product framing

Shell-Mind is **not** a hosted service with separate “our servers” and
“customers.” A user clones the repo and runs the backend themselves. The
HTTP API + web UI + CLI are how *that same* process is used from localhost
or from other personal/team devices (often via Tailscale). Zero-sum VRAM
orchestration is the core claim: a full multi-agent pipeline on an 8 GB
card; larger hardware uses larger models through `models.json`.

## Customization decision (models)

**What we ship in v1**

- Server owner edits `models.json` (copy from `models.example.json`).
- Any Hugging Face `hf_id` can fill a pipeline **role**.
- On first use, weights download into the local HF cache under `models/`.
- Missing custom models fall back to built-in defaults so chat never hard-crashes.
- Phone/GUI users **do not** pick models — they only chat. That keeps 8 GB VRAM and multi-GB downloads under the server owner’s control.

**What we deliberately did *not* build yet**

- In-GUI model picker / “paste HF ID and download with progress”
- Reason: multi-GB downloads inside a chat request are a bad UX and easy to OOM the card.

That GUI remains **future work**, not a missing bug.

---

## Verification evidence (live, RTX 5050)

- Boot in seconds; first model load on demand (~16 s for 7B copilot).  
- Zero-sum: unload returns free VRAM to within ~0.1 GB of baseline.  
- Agent pipelines completed in ~1–2 minutes with stage timings.  
- Android client over Tailscale: auth key, mobile drawer, `POST /chat 200`.  
- Contract tests run without GPU.

---

## Known optional follow-ups

- `HF_HUB_OFFLINE=1` after all models are cached (skips HF HEAD noise).  
- `favicon.ico` (cosmetic 404).  
- Streaming (SSE/WebSockets).  
- Optional Settings UI for models.json (future).  
- GGUF backend for `coder30`.

# Shell-Mind — Changelog

Repo: https://github.com/momoinuddin-ali/shell-mind  
Hardware target: NVIDIA ~8 GB VRAM (RTX 5050 / 4060 class), fully local.

This file is the **product history**. Attribution follows **git authors** on each
milestone. Pair review is assumed but not invented where git has a single author.
External audit reports (Z AI) are summarized here; full PDFs may live outside the repo
or under `docs/audits/`.

## Contributors (git authors on `main` / feature branches)

| Name | GitHub | Primary ownership |
|------|--------|-------------------|
| **Mo Moinuddin Ali** | [momoinuddin-ali](https://github.com/momoinuddin-ali) | Engine & product: multi-agent / zero-sum VRAM core, `ai_core` product layer, model zoo, orchestrator, agents, router, smoke tests, v1.0–v1.2 architecture, Wave 0–3 audit remediation, vision `see()` fix, Waves A/B (R1–R4 + contract expansion), streaming **GEN_LOCK single-releaser** fix |
| **Md Imtiyaz** | [imtiyaz-dev432](https://github.com/imtiyaz-dev432) | Frontend foundation & updates; **v1.2.1** N1–N9 + initial CI; **SSE streaming** (`/chat/stream`, `TextIteratorStreamer`, UI stream client) on `v1.1-professional` |

---

## Timeline (high level)

| Period | Tag / milestone | Lead | What landed |
|--------|-----------------|------|-------------|
| 2026-08-24 → 09-06 | **v1.0** | Mo; frontend seed Imtiyaz | Multi-agent engine, CLI, VRAM timeline, first web UI |
| 2026-09-15 → 09-17 | hygiene | Mo; UI Imtiyaz | Untrack venv/db/timeline; frontend updates |
| 2026-09-27 | product merge | Mo | `ai_core` product layer + engine wiring |
| 2026-10-07 → 10-08 | **v1.1** (`3b62f7f`) | Mo | Hardening: lazy tiers, secure uploads, backend-served UI, anchored paths, contract tests |
| 2026-10-25 | **v1.2** (`e0cdcdb`, `f526b5c`) | Mo | Wave 0–3 audit remediation; 28/28 contract; smoke PASS on RTX 5050; merge to `main` |
| 2026-10-26 | **v1.2.1** (`dea677a`) | **Imtiyaz** (code + CI); Mo verified N1 live | N1–N9 residuals + GitHub Actions CI |
| 2026-10-26 | vision fix (`bd69d42`) | Mo | Qwen3-VL `see()` processor path; CHANGES dual attribution |
| 2026-10-26/27 | **v1.2.2** (`a96c376`) | Mo | Wave A: R1–R4, opaque upload tokens, keyword net |
| 2026-10-27 | **v1.2.3** (`04b7ce6`) | Mo | Wave B: 37 contract checks; `requirements-ci.txt` |
| 2026-10-27 | streaming (branch `v1.1-professional`) | **Imtiyaz** | SSE `/chat/stream` for cpu/gpu; UI stream + `/chat` fallback |
| 2026-10-27 | stream lock protocol | Mo (fix on top of Imtiyaz stream) | Single-releaser `GEN_LOCK` — closes dual-release race under early disconnect |

---

## v1.0 — Foundation (Aug–early Sep 2026)

**Lead:** Mo Moinuddin Ali · **Frontend seed:** Md Imtiyaz (`32f7ebf` add frontend)

**Intent:** Local multi-tier workstation: router + specialists + critic under sequential VRAM pressure.

Notable commits:

- `b8bda68` ready — **Mo Moinuddin Ali**
- `32f7ebf` add frontend — **Md Imtiyaz**
- `346c4ea` 3 modes (flash / reason-coder / agents) — **Mo Moinuddin Ali**
- `5a5eea6` engine green: 3/3 acceptance, cache unified — **Mo Moinuddin Ali**
- `14c8963` multi-agent orchestrator, VRAM park, CLI — **Mo Moinuddin Ali**
- `25c37c7` pipeline + GUI history + VRAM visualization — **Mo Moinuddin Ali**
- `ac4b8a5` / `c67f1f5` finalize v1.0 release architecture — **Mo Moinuddin Ali**
- `e5aa49c` harden model cleanup and VRAM reporting — **Mo Moinuddin Ali**
- `0eaf036` gitignore runtime artifacts — **Mo Moinuddin Ali**

**Known at the time:** ambitious architecture; security and honesty of claims still immature (later audits).

---

## v1.1 — Hardening (`3b62f7f`, 2026-10-08)

**Author:** Mo Moinuddin Ali

**Commit subject:** *hardening pass — lazy tiers, secure uploads, backend-served UI, anchored paths, contract tests*

Themes:

- Lazy model load (server accepts connections before multi-GB weights)
- Upload whitelist, size caps, server-issued paths only for `/chat`
- Backend serves `frontend/` (no separate static server)
- Paths anchored to repo root (`paths.py`)
- First GPU-less contract test suite
- README honesty pass (coder30 disabled reason, swap latency, limitations)

Also: README / vram_chart updates (`a6eac34`, `6d36b61`) — **Mo Moinuddin Ali**.

---

## External audit — v1.0 report → Wave 0–3 (→ v1.2)

**Source:** Z AI *Shell-Mind v1.0 Independent Audit* (37 findings: 3 Critical · 8 High · 13 Medium · 13 Low).  
**Implementation of Waves 0–3:** Mo Moinuddin Ali (`e0cdcdb` / merge `f526b5c`).

### Criticals (all fixed in v1.2)

| ID | Issue | Resolution |
|----|--------|------------|
| **C1** | Synopsis claimed concurrent model execution | SYNOPSIS + README: sequential zero-sum; correction table |
| **C2** | Smoke coexistence check never actually ran | Unconditional router+critic block in `smoke_test.py`; feeds exit code |
| **C3** | `models.json` underscore keys became real registry entries | `load_registry` skips `_` keys; example file documents convention |

### Highs (closed or partial → residuals in v1.2.1)

| ID | Issue | v1.2 status |
|----|--------|-------------|
| H1 | CLI hard-coded port / http-only | Fixed — URL normalize + setup.sh full URL |
| H2 | `/health` showed config not effective roles | Fixed+ — `roles_effective`, auth-gated telemetry |
| H3 | CORS `*` with no API key | Fixed — localhost-only when key unset |
| H4 | Unbounded `/chat` body | Partial — 1 MB middleware (regressed uploads → **N1**) |
| H5 | localStorage no quota handling | Partial — prune path; trim field bug → **N2** |
| H6 | Mid-request multi-GB download | Partial — copilot/vision/code guarded; router/critic → **N3** |
| H7 | PyPDF2 | Fixed in code; prose drift → **N6** |
| H8 | Image silently dropped | Partial in agent; copilot path → **N4** |

### Wave delivery (v1.2 — Mo Moinuddin Ali)

- Wave 0: C2 coexistence, C3 underscore skip  
- Wave 1: security Highs, pypdf, vision override, OOM guards, CORS  
- Wave 2: health auth, rate-limit refund, dynamic RAM budget, chart trim, mode labels  
- Wave 3: mobile/IME/branding polish, CLI Windows/ASCII, security headers, audit rotation  

**Verification (Mo Moinuddin Ali, RTX 5050):** contract **28/28**; smoke **PASS** including router+critic coexistence.

---

## v1.2 — Verified workstation (`e0cdcdb` + merge `f526b5c`, 2026-10-25)

**Author:** Mo Moinuddin Ali

Ship surface: root `requirements.txt`, `setup.sh`, `models.example.json`, `SECURITY.md`, `SYNOPSIS.md`, `LICENSE`; no unsafe `supervisor/`; honest README + optional API key + Tailscale.

---

## External re-audit — v1.2 → v1.2.1

**Source:** Z AI *Shell-Mind v1.2 Patch Verification & Re-Audit*  
**Primary implementer:** Md Imtiyaz (`dea677a`). **Live N1 verification:** Mo Moinuddin Ali (JARVISfedora).

| ID | Severity | Fix |
|----|----------|-----|
| **N1** | High | Path-aware body limit: `/upload*` ≤ 26 MB; `/chat` ≤ 1 MB |
| **N2** | Medium | `persistThreads` trims `m.text` |
| **N3** | Medium | Pre-flight `has_model` for router + critic |
| **N4** | Medium | Image attach only in Agent mode; honest refusal in copilot |
| **N5** | Low | `chmod 0600` on key rotation in `setup.sh` |
| **N6** | Low | Docs PyPDF2 → pypdf |
| **N7** | Low | Dead `.webp` branches removed |
| **N8** | Low | `allow_credentials=False` |
| **N9** | Low | `?server=` validated + OVERRIDE marker |
| **CI** | — | `.github/workflows/test.yml` on push/PR |

**Live checks (2026-10-26, Mo):** contract 28/28; ~20 MB upload → **415** content sniff (N1 path-aware cap working).  
Also: `7181d48` remove empty `.github/a` — Mo.

Path echo was **deferred** to v1.3.0 at this stage (later closed early in Wave A as opaque UUID tokens).

---

## Third re-audit → Waves A & B (Mo Moinuddin Ali)

Z v1.2.1 third pass: **0 Critical / 0 High**, 13 smaller items. Independent review agreed on R1/R2 and keyword-net residual.

### Wave A — `a96c376` / **v1.2.2**

| ID | Fix |
|----|-----|
| **R1** | Reject `Transfer-Encoding: chunked`; require `Content-Length` on protected POSTs |
| **R2** | Mixed vision + uncached VL → honest refusal |
| **R3** | Skip API-key on `OPTIONS`; CORSMiddleware registered last |
| **PE** | Opaque UUID filename tokens (no absolute path echo) |
| **R4** | Per-entry `try` in `models.json` overlay |
| **KW** | Drop bare `\bfix\b|\bbug\b|\berror\b|\bdebug\b` from force-code net |

### Wave B — `04b7ce6` / **v1.2.3**

| Item | Detail |
|------|--------|
| Contract suite | **37** checks (was 28): R1, opaque tokens, C3 underscores |
| `requirements-ci.txt` | CI without CUDA/torch wheels |
| Workflow | Installs `requirements-ci.txt`; 10 min timeout |

**Live:** `python tests/test_server_contract.py` → **37 passed, 0 failed**.

---

## Streaming — branch `v1.1-professional` (Md Imtiyaz)

**Feature:** `POST /chat/stream` — SSE token stream for **cpu/gpu** copilots only (agent → 400). UI tries stream first, falls back to `/chat`.

Preserves: rate limit, `GEN_LOCK`, path validation, audit log, Wave A/B middleware markers on the branch tip (branch was **ahead of main by 2**, behind 0 — contains v1.2.3 lineage + stream).

### Known issue found on review (merge blocker until fixed)

**Dual `GEN_LOCK.release` race** under early client disconnect:

1. Worker thread starts generating.  
2. Defensive cleanup could release the lock while the worker was still running.  
3. Worker `finally` released again → could unlock another request’s hold (Python `Lock` is not thread-owned).

**Status:** Fixed in the single-releaser patch (`worker_dispatched` before `thread.start()`, idempotent `_release_once()`, defensive release **only** if never dispatched). **Apply that `ai_core.py` on the stream branch before treating merge as production-safe.**

After the lock fix:

| Check | Result |
|-------|--------|
| Wave A/B markers intact | PASS |
| `/chat/stream` in `_PROTECTED_PATHS` | PASS |
| `anyio.to_thread.run_sync(_ensure_copilot)` | PASS |
| `streamer.end()` in worker `finally` | PASS |
| Single GEN_LOCK releaser after dispatch | PASS (with patch) |

**Intentional tradeoff:** after client disconnect mid-stream, GPU generation may continue until the worker finishes (lock held) — preferred over dual-unlock corruption.

---

## Accepted limitations (documented, not bugs)

- Plaintext audit SQLite at rest  
- Single `GEN_LOCK` (one generation at a time)  
- No server-side chat memory (`localStorage` threads)  
- Vision OCR quality under 4-bit 8B on dense diagrams  
- Self-host / team Tailscale — not multi-tenant SaaS  
- Stream continues GPU work after client disconnect until worker ends  

---

## Multi-clone / API key model

- Four people who each clone + `./run-server.sh` → four isolated processes, keys, DBs.  
- Four clients against **one** host → one key, one audit DB, one queue.  
- Key rotation: new `.env` value + restart; old key dies immediately; **DB kept**.

---

## Commit index (selected, newest first)

```
04b7ce6  Mo        test(ci): Wave B contract checks; slim CI deps     ← v1.2.3
a96c376  Mo        fix: R1–R4, opaque tokens, keyword net               ← v1.2.2
bd69d42  Mo        fix(vision): Qwen3-VL see() path
7181d48  Mo        chore: remove accidental empty .github/a
dea677a  Imtiyaz   fix N1–N9 + CI pipeline                              ← v1.2.1
f526b5c  Mo        Merge v1.1-professional → main as v1.2
e0cdcdb  Mo        Shell-Mind v1.2 verified workstation
3b62f7f  Mo        v1.1 hardening pass
32f7ebf  Imtiyaz   add frontend
```

Streaming commits live on **`v1.1-professional`** (Imtiyaz); lock-protocol fix should land on that branch (or main after merge) as Mo.

Full history: `git log --oneline --date=short --pretty=format:'%ad %h %an %s'`

---

## How we treat audits

1. External report → findings table with severity.  
2. Waves / N-fixes / R-fixes → code + contract tests.  
3. This file → bridge between git history and viva/demo narrative.

---

## Next

- [ ] Land stream **GEN_LOCK** single-releaser on the stream branch; re-run contract tests  
- [ ] Merge `v1.1-professional` → `main` (fast-forward once lock fix is on the branch)  
- [ ] Tag **v1.3.1** (stream + lock protocol) when green  
- [ ] Wave C / roadmap: agent streaming, GGUF/coder30, smaller VL, vector RAG  

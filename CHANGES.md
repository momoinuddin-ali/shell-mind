# Shell-Mind — Changelog

Repo: https://github.com/momoinuddin-ali/shell-mind  
Hardware target: NVIDIA ~8 GB VRAM (RTX 5050 / 4060 class), fully local.

This file is the **product history**. Commit SHAs are from `main` as of 2026-10-27.
External audit reports (Z AI) are summarized here; the full PDFs are project artifacts, not required in-tree.

## Contributors (git authors on `main`)

| Name | GitHub | Primary ownership (from commit history) |
|------|--------|-------------------------------------------|
| **Mo Moinuddin Ali** | [momoinuddin-ali](https://github.com/momoinuddin-ali) | Engine & product lead: multi-agent / zero-sum VRAM core, `ai_core`, model zoo, orchestrator, agents, router, smoke tests, v1.0–v1.2 architecture, Wave 0–3 audit remediation, vision `see()` fix, Waves A/B third-audit residuals, repo maintenance |
| **Md Imtiyaz** | [imtiyaz-dev432](https://github.com/imtiyaz-dev432) | Frontend foundation, UI updates, **v1.2.1** residual fixes (N1–N9), initial GitHub Actions CI, related README touch-ups |

---

## Timeline (high level)

| Period | Tag / milestone | Lead author(s) | What landed |
|--------|-----------------|----------------|-------------|
| 2026-08-24 → 09-06 | **v1.0** | Mo; frontend seed Imtiyaz | Multi-agent engine, CLI, VRAM timeline, first web UI |
| 2026-10-07 → 10-08 | **v1.1** (`3b62f7f`) | Mo | Hardening: lazy tiers, secure uploads, backend-served UI, anchored paths, contract tests |
| 2026-10-25 | **v1.2** (`e0cdcdb`) | Mo | Wave 0–3 audit remediation; 28/28 contract; smoke PASS on RTX 5050; merge to `main` |
| 2026-10-26 | **v1.2.1** (`dea677a`) | Imtiyaz (fixes + CI) | N1–N9 residuals + GitHub Actions CI |
| 2026-10-26 | vision fix | Mo | Qwen3-VL `see()` processor path |
| 2026-10-26/27 | **v1.2.2** (`a96c376`) | Mo | Wave A: R1–R4, opaque upload tokens, keyword net |
| 2026-10-27 | **v1.2.3** (`04b7ce6`) | Mo | Wave B: 37 contract checks; `requirements-ci.txt` (no CUDA in CI) |
| Future | **v1.3.x / Wave C** | — | Streaming UX, GGUF/coder30, optional smaller VL — roadmap, not open defects |

---

## v1.0 — Foundation (Aug–early Sep 2026)

**Lead:** Mo Moinuddin Ali · **Frontend seed:** Md Imtiyaz

**Intent:** Local multi-tier workstation: router + specialists + critic under sequential VRAM pressure.

Notable commits:
- `b8bda68` ready — **Mo Moinuddin Ali**  
- `32f7ebf` add frontend — **Md Imtiyaz**  
- `346c4ea` 3 modes (flash / reason-coder / agents) — **Mo Moinuddin Ali**  
- `14c8963` multi-agent orchestrator, VRAM park, CLI — **Mo Moinuddin Ali**  
- `25c37c7` pipeline + GUI history + VRAM visualization — **Mo Moinuddin Ali**  

---

## External audit — v1.0 report → Wave 0–3 (→ v1.2)

**Source:** Z AI *Shell-Mind v1.0 Independent Audit* (37 findings: 3 Critical · 8 High · 13 Medium · 13 Low).  
**Implementation of Waves 0–3:** Mo Moinuddin Ali.

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

---

## External re-audit — v1.2 verification report → v1.2.1

**Source:** Z AI *Shell-Mind v1.2 Patch Verification & Re-Audit*  
**Implementation:** Md Imtiyaz.

### N-findings closed in v1.2.1
| ID | Severity | Fix |
|----|----------|-----|
| **N1** | High | Path-aware body limit: `/upload*` ≤ 26 MB; `/chat` ≤ 1 MB |
| **N2** | Medium | `persistThreads` trims `m.text` (not dead `m.content`) |
| **N3** | Medium | Pre-flight `has_model` for router + critic |
| **N4** | Medium | Image attach only in Agent mode; honest refusal in copilot |
| **N5** | Low | `chmod 0600` on key rotation in `setup.sh` |
| **N6** | Low | Docs PyPDF2 → pypdf |
| **N7** | Low | Dead `.webp` branches removed |
| **N8** | Low | `allow_credentials=False` |
| **N9** | Low | `?server=` validated (http/https only) + OVERRIDE marker |
| **CI** | — | `.github/workflows/test.yml` — contract suite + AST parse on push/PR |

---

## Third re-audit (Z v1.2.1 report) → Waves A & B

Z reported **0 Critical / 0 High**, 13 smaller items. Independent review agreed on R1/R2 and noted keyword-net residual.

### Wave A — `a96c376` / tag **v1.2.2** (Mo Moinuddin Ali)
| ID | Fix |
|----|-----|
| **R1** | Reject `Transfer-Encoding: chunked`; require `Content-Length` on protected POSTs; keep path-aware 26 MB / 1 MB caps |
| **R2** | Mixed vision + uncached VL → **honest refusal** (no silent text-only) |
| **R3** | Skip API-key on `OPTIONS`; register CORSMiddleware **last** (outermost) |
| **PE** | Upload responses return **UUID filename only**; `_validated_upload` resolves under `uploads/` (legacy absolute paths still accepted if under uploads) |
| **R4** | Per-entry `try` in `models.json` so one bad field does not wipe the overlay |
| **KW** | Drop bare `\bfix\b|\bbug\b|\berror\b|\bdebug\b` from router force-code net |

### Wave B — `04b7ce6` / tag **v1.2.3** (Mo Moinuddin Ali)
| Item | Detail |
|------|--------|
| Contract suite | **37** checks (was 28): R1 413/411, opaque token 400/404, upload basename, C3 underscore absence |
| `requirements-ci.txt` | fastapi/uvicorn/httpx/pypdf/pillow only — CI does not download CUDA wheels |
| `.github/workflows/test.yml` | Installs `requirements-ci.txt`; 10 min timeout |

**Live verification (JARVISfedora):** `python tests/test_server_contract.py` → **37 passed, 0 failed**.

---

## Accepted limitations (documented, not tracked as bugs)

- Plaintext audit SQLite at rest  
- Single `GEN_LOCK` (one generation at a time)  
- No server-side chat memory (threads in `localStorage`)  
- Vision OCR quality under 4-bit 8B on dense diagrams  
- Personal / team self-host model — not multi-tenant SaaS  

---

## Multi-clone / API key model (product)

- Four people who **each** `git clone` + `./run-server.sh` → four isolated processes, keys, and DBs.  
- Four clients against **one** Tailscale host → one key, one audit DB, one queue.  
- Key rotation: new value in `.env` + restart; old key invalid immediately; **audit history is kept**. Clients update key in UI/CLI.
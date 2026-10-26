# Shell-Mind — Changelog

Repo: https://github.com/momoinuddin-ali/shell-mind  
Hardware target: NVIDIA ~8 GB VRAM (RTX 5050 / 4060 class), fully local.

This file is the **product history**. Commit SHAs are from `main` as of 2026-10-26.
External audit reports (Z AI) are summarized here; the full PDFs are project artifacts, not required in-tree.

## Contributors (git authors on `main`)

| Name | GitHub | Primary ownership (from commit history) |
|------|--------|-------------------------------------------|
| **Mo Moinuddin Ali** | [momoinuddin-ali](https://github.com/momoinuddin-ali) | Engine & product lead: multi-agent / zero-sum VRAM core, `ai_core`, model zoo, orchestrator, agents, router, smoke tests, v1.0–v1.2 architecture, Wave 0–3 audit remediation, contract suite direction, README/SYNOPSIS/SECURITY framing, vision `see()` fix, repo maintenance |
| **Md Imtiyaz** | [imtiyaz-dev432](https://github.com/imtiyaz-dev432) | Frontend foundation, UI updates, **v1.2.1** residual fixes (N1–N9), GitHub Actions CI, related README touch-ups |

Attribution below follows **who authored the commits** on each milestone. Pair programming / review is assumed inside a milestone but is not invented where git has a single author.

---

## Timeline (high level)

| Period | Tag / milestone | Lead author(s) | What landed |
|--------|-----------------|----------------|-------------|
| 2026-08-24 → 09-06 | **v1.0** | Mo Moinuddin Ali; frontend seed **Md Imtiyaz** | Multi-agent engine, CLI, VRAM timeline, first release architecture; initial web UI |
| 2026-09-15 → 09-17 | hygiene | Mo Moinuddin Ali; UI **Md Imtiyaz** | Untrack venv/db/timeline; frontend updates |
| 2026-09-27 | product merge | Mo Moinuddin Ali | `ai_core` product layer + engine wiring |
| 2026-10-07 → 10-08 | **v1.1** (`3b62f7f`) | Mo Moinuddin Ali | Hardening: lazy tiers, secure uploads, backend-served UI, anchored paths, contract tests |
| 2026-10-25 | **v1.2** (`e0cdcdb`, `f526b5c`) | Mo Moinuddin Ali | Wave 0–3 audit remediation; 28/28 contract; smoke PASS on RTX 5050; merge to `main` |
| 2026-10-26 | **v1.2.1** (`dea677a`…) | **Md Imtiyaz** (fixes + CI); README follow-up | N1–N9 residuals + GitHub Actions CI; path-echo deferred |
| 2026-10-26 | vision fix + this changelog | Mo Moinuddin Ali | `agents.see()` Qwen3-VL processor path; expanded CHANGES timeline |

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

This is the first “product layer” that a stranger could clone without immediately shooting themselves in the foot.

Also in this era: README / vram_chart updates (`a6eac34`, `6d36b61`) — **Mo Moinuddin Ali**.

---

## External audit — v1.0 report → Wave 0–3 (→ v1.2)

**Source:** Z AI *Shell-Mind v1.0 Independent Audit* (37 findings: 3 Critical · 8 High · 13 Medium · 13 Low).  
**Implementation of Waves 0–3:** Mo Moinuddin Ali (commits `e0cdcdb` / merge `f526b5c`).

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

### Wave delivery (v1.2 commit `e0cdcdb` — Mo Moinuddin Ali)

- Wave 0: C2 coexistence, C3 underscore skip  
- Wave 1: security Highs, pypdf, vision override, OOM guards, CORS  
- Wave 2: health auth, rate-limit refund, dynamic RAM budget, chart trim, mode labels  
- Wave 3: mobile/IME/branding polish, CLI Windows/ASCII, security headers, audit rotation  

**Verification (hardware, Mo Moinuddin Ali’s RTX 5050):**

- `python tests/test_server_contract.py` → **28/28**  
- `python -m workstation.smoke_test` → **PASS** including router+critic coexistence (~2.8 GB free)

---

## v1.2 — Verified workstation (`e0cdcdb` + merge `f526b5c`, 2026-10-25)

**Author:** Mo Moinuddin Ali  

Merge message: *Merge v1.1-professional: Shell-Mind v1.2 as main*

Ship surface:

- Root `requirements.txt`, `setup.sh`, `models.example.json`, `SECURITY.md`, `SYNOPSIS.md`, `LICENSE`
- No `supervisor/` (unsafe sandbox removed earlier)
- Contract suite + honest README / security model (optional API key + Tailscale)

---

## External re-audit — v1.2 verification report → v1.2.1

**Source:** Z AI *Shell-Mind v1.2 Patch Verification & Re-Audit*  
Headline: all 3 Criticals dead; ~84% of original defect budget retired; **1 new High (N1)** + residuals.

### N-findings closed in v1.2.1

**Primary author:** Md Imtiyaz (`dea677a` — *fix various problems and add CI pipeline*; `3c00865` README).  
**Verification / N1 live 20 MB upload / contract re-run:** Mo Moinuddin Ali (on JARVISfedora).

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

**Live checks (2026-10-26, Mo Moinuddin Ali):**

- Contract: **28/28**  
- ~20 MB upload with API key → **415** “not a PDF” (proves N1: body not rejected at 1 MB)

Also: `7181d48` remove accidental empty `.github/a` — **Mo Moinuddin Ali**.

### Deferred to v1.3.0

- **Path echo:** `/upload` still returns absolute server paths — plan opaque UUID tokens.

---

## Vision path fix (2026-10-26, post-tag)

**Author:** Mo Moinuddin Ali  

**Symptom:** Agent + image loaded Qwen3-VL-8B, then crashed:

```text
AttributeError: 'str' object has no attribute 'items'
```

in `workstation/agents.py` `see()` — `apply_chat_template(..., return_dict=True)` returned a string on this stack.

**Fix:** template → text, then `processor(text=[...], images=[...], return_tensors="pt")`; modest thumbnail (1024); decode new tokens only when possible.

**Note:** Dense architecture diagrams may still mis-OCR labels under 4-bit 8B VL; structure is usually right. Image attach remains **Agent-mode only** by N4 design (Md Imtiyaz).

---

## Commit index (selected, newest first)

```
7181d48  Mo Moinuddin Ali   chore: remove accidental empty .github/a
3c00865  Md Imtiyaz         update readme
dea677a  Md Imtiyaz         fix various problems and add CI pipeline     ← v1.2.1 body
f526b5c  Mo Moinuddin Ali   Merge v1.1-professional: Shell-Mind v1.2 as main
e0cdcdb  Mo Moinuddin Ali   Shell-Mind v1.2: verified zero-sum workstation
3b62f7f  Mo Moinuddin Ali   v1.1: hardening pass
eaa55a8  Mo Moinuddin Ali   ai_core product layer + engine
84df74a  Md Imtiyaz         updated-frontend
32f7ebf  Md Imtiyaz         add frontend
ac4b8a5  Mo Moinuddin Ali   feat: finalize Shell-Mind v1.0 release architecture
25c37c7  Mo Moinuddin Ali   multi-agent pipeline, GUI history, VRAM viz
14c8963  Mo Moinuddin Ali   orchestrator + VRAM park + CLI
b8bda68  Mo Moinuddin Ali   ready
```

Full history:

```bash
git log --oneline --date=short --pretty=format:'%ad %h %an %s'
```

---

## How we treat audits

1. **External report** (v1.0 audit, v1.2 re-audit) → findings table with severity.  
2. **Waves / N-fixes** → code + contract tests (Waves: Mo Moinuddin Ali; N1–N9/CI: Md Imtiyaz).  
3. **This file** → human-readable bridge between git history and viva/demo narrative.  
4. Full PDF reports can live outside the repo or under `docs/audits/` if the team wants them versioned.

---

## Next

- **v1.3.0** — opaque upload tokens (path echo)  
- Optional — smaller VL model for 8 GB headroom; llama.cpp path for 30B coder (documented, not enabled)

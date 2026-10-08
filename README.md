# ⚡ Shell-Mind

**Zero-Sum VRAM Orchestrated Multi-Agent Local AI Workstation**

Shell-Mind is a fully local, multi-tier AI system designed to run complex software-engineering and multi-agent workflows on a strict **8 GB VRAM** budget (NVIDIA RTX 5050 / 4060 / 3060 class).

Unlike single-shot chatbot wrappers, Shell-Mind treats GPU memory as a scarce resource. It dynamically loads and unloads specialized models so that only the models required for the current stage of a request occupy VRAM at any time.

```
User
 │
 ├── Web Interface (frontend/)
 └── Terminal Client (cli.py)
          │
          ▼
   FastAPI Server (primary_node/ai_core.py)
          │
    ┌─────┴─────┬──────────────┐
    │           │              │
 File Uploads  Doc Context   CPU / GPU Copilot
    │           │              │
    └─────┬─────┘              │
          │                    │
          ▼                    │
   Agent Engine                │
   (workstation/orchestrator.py)│
          │                    │
   ┌──────┼──────┬──────┐      │
   │      │      │      │      │
 Router Vision Coder Critic    │
   │      │      │      │      │
   └──────┴──────┴──────┘      │
          │                    │
          ▼                    ▼
   Model Zoo + Audit Log (SQLite)
          │
          ▼
   Local Quantized Weights (4-bit NF4)
```

---

## Core Idea — Zero-Sum VRAM Orchestration

On an 8 GB card you cannot keep a 7–8 B model, a vision model, and a critic resident at the same time. Shell-Mind therefore enforces a **zero-sum** contract:

| Stage              | What lives in VRAM                          | What is parked / unloaded      |
|--------------------|---------------------------------------------|-------------------------------|
| Router planning    | 1.5 B router only                           | everything else               |
| Vision             | 8 B VLM                                     | router parked                 |
| Code / Reasoning   | 7 B coder or 8 B thinker                    | router parked                 |
| Critic             | 4 B critic + 1.5 B router (they coexist)    | workers unloaded              |
| GPU Copilot mode   | single 7 B instruct model                   | agent models unloaded         |
| CPU Lite mode      | 0.5 B model on CPU                          | GPU free                      |

VRAM is measured live around every load (`torch.cuda.mem_get_info()`) and recorded to a timeline. Load failures (OOM, broken quantization path) **purge** VRAM and fall back along a registered chain (`coder30 → coder7`); workers without a registered fallback fail gracefully — the request gets a clean error, VRAM is purged, and the server keeps running.

**The measured price of this contract:** each model swap costs roughly 5–15 s of load time on the RTX 5050, so a full agent run typically takes 1–3 minutes. That is the trade-off that makes a 6-model pipeline fit on an 8 GB card at all — swap latency instead of OOM.

---

## Three-Tier Compute Engine

1. **CPU Lite (Tier 1)**
   Qwen2.5-0.5B-Instruct on CPU (fp32, ~1 GB RAM). Used automatically when no GPU is present, or on demand — selecting `cpu` mode on a GPU machine keeps the GPU completely free.

2. **GPU Copilot (Tier 2)**
   A single 7 B instruct model (Qwen2.5-Coder-7B-Instruct, 4-bit NF4) holds the GPU. Standard chat, coding help, and document-context questions.

3. **Agent Workstation (Tier 3)**
   Full multi-agent pipeline for hard requests:

   ```
   Router (1.5 B)
        ↓
   [optional Vision Specialist]
        ↓
   ONE specialist worker
        • Code   → Qwen2.5-Coder-7B (30 B MoE behind a flag, see registry)
        • Reasoning → Qwen3-8B
        • Vision-only → summary becomes the draft
        ↓
   Final Critic (4 B)
        ↓
   Answer returned to user
   ```

All tiers load **lazily on first use** — the server starts serving `/health` within seconds; the first prompt of each tier pays the model-load cost.

---

## Key Features

| Feature | Implementation |
|---------|----------------|
| **Zero-Sum VRAM** | Live `torch.cuda.mem_get_info()` around every load, forced unload + `gc` + `empty_cache`, every swap recorded on a timeline |
| **Graceful degradation** | OOM / quant failures → purge → fallback chain (`coder30 → coder7`) → continue; un-routable requests (e.g. vision-only without the vision model) refuse honestly instead of guessing |
| **RAG Lite** | PDF: first 3 pages; TXT/CSV: first 3 000 chars — injected into the prompt, no vector DB required |
| **Vision** | Qwen3-VL-8B processes screenshots / images; output becomes compact context for the text workers |
| **Audit logging** | Every prompt, mode, attached file and response appended to `shell_mind_history.db` (SQLite) |
| **Hardened uploads** | Extension whitelist + 25 MB cap + UUID filenames; `/chat` only opens files the server itself issued |
| **Smoke tests** | `python -m workstation.smoke_test` verifies load → generate → unload → VRAM actually freed |
| **VRAM timeline** | Pipeline dumps `vram_timeline.json`; `vram_chart.py` produces a portfolio-ready chart |
| **Decoupled clients** | Vanilla HTML/CSS/JS glassmorphism UI + independent terminal CLI (uploads images itself, works cross-machine) |
| **Thread history** | Client-side `localStorage` threads; server-side append-only SQLite log for academic review. Requests themselves are stateless — there is no server-side conversation memory (yet) |

---

## Model Registry

All models are 4-bit NF4 (bitsandbytes) except vision towers (bf16).

| Key       | Hugging Face ID                        | Role     | Approx. VRAM | Notes                                                     |
|-----------|----------------------------------------|----------|--------------|-----------------------------------------------------------|
| `router`  | Qwen/Qwen2.5-1.5B-Instruct             | Router   | ~1.2 GB      | Resident between stages; parked while heavy workers run    |
| `coder7`  | Qwen/Qwen2.5-Coder-7B-Instruct         | Coder    | ~5.2 GB      | Production coder                                           |
| `coder30` | Qwen/Qwen3-Coder-30B-A3B-Instruct      | Coder    | —            | **Disabled by default** — see note below                   |
| `thinker` | Qwen/Qwen3-8B                          | Reasoner | ~5.5 GB      | Step-by-step thinking                                      |
| `critic`  | Qwen/Qwen3-4B-Instruct-2507            | Critic   | ~3.0 GB      | Coexists with router                                       |
| `vision`  | Qwen/Qwen3-VL-8B-Instruct              | Vision   | ~6.0 GB      | Parks router while active                                  |
| `cpu`     | Qwen/Qwen2.5-0.5B-Instruct             | Copilot  | 0 GB (CPU)   | CPU Lite tier, fp32 on CPU                                 |

**Why `coder30` is disabled:** bitsandbytes keeps CPU-offloaded MoE experts in fp32 (~75 GB of RAM for this model), so the planned GPU+DDR5 split is impractical with the bnb backend. The 7 B model is the production coder until the GGUF/llama.cpp backend lands (see Future Work). The registry entry, fallback wiring and smoke-test target remain so the integration is a flag-flip once the backend exists.

---

## Architecture (Component View)

```
shell-mind/
├── primary_node/
│   └── ai_core.py          # FastAPI server: tiers, uploads, RAG-lite, audit log
├── workstation/
│   ├── model_zoo.py        # Loading layer, VRAM accounting, fallback chain
│   ├── router.py           # 1.5 B planner → strict JSON plan
│   ├── orchestrator.py     # State machine: plan → vision → worker → critic
│   ├── agents.py           # see / code / think / critique (wake → work → sleep)
│   ├── paths.py            # Single source of truth for all filesystem locations
│   └── smoke_test.py       # Hardware acceptance tests
├── frontend/
│   ├── index.html
│   ├── style.css           # Dark glassmorphism UI
│   └── script.js           # Threads, attachments, neural loader
├── cli.py                  # Thin terminal client (never loads models)
├── vram_chart.py           # Portfolio chart from vram_timeline.json
├── requirements.txt
└── README.md
```

All runtime artifacts (`models/`, `uploads/`, `offload_cache/`, the audit DB, the timeline) are anchored to the repo root via `workstation/paths.py`, so the server behaves the same regardless of where it is launched from. `SHELL_MIND_MODELS_DIR` and `SHELL_MIND_DB` environment variables override the default locations.

---

## Quick Start

### Requirements

- Python 3.10+
- NVIDIA GPU with ≥ 8 GB VRAM (or CPU-only fallback)
- CUDA 12+ / PyTorch with CUDA
- ~100 GB free SSD (model weights)

### 1. Clone & environment

```bash
git clone https://github.com/momoinuddin-ali/shell-mind.git
cd shell-mind
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Start the server (one terminal does everything)

From the repo root, **single worker** (the tier engine assumes one process owns the GPU):

```bash
uvicorn primary_node.ai_core:app --host 0.0.0.0 --port 8000
```

The server is ready in seconds — models load lazily on the first prompt of each tier. On first boot it creates `shell_mind_history.db` and the `uploads/` directory.

### 3. Open the web UI

The backend serves the UI itself — open **http://localhost:8000** and you're done. No second terminal, no static file server.

Alternatively, hosting `frontend/` with any static server also works: the page probes candidates for a live `/health` (same origin → `localhost:8000` → `127.0.0.1:8000`), or set it explicitly with `?server=http://<host>:8000`.

### 4. Or use the terminal client

```bash
python cli.py                                  # interactive
python cli.py --mode agent "fix this traceback..."
python cli.py --mode agent --image shot.png "what is wrong here?"
```

`--image` uploads the file to the server first, so the CLI works from any machine with network access to the server (e.g. a teammate over Tailscale).

---

## API Surface

| Method | Endpoint          | Purpose                                      |
|--------|-------------------|----------------------------------------------|
| GET    | `/health`         | Status, current tier, GPU flag, free VRAM    |
| POST   | `/chat`           | Main inference (`mode`: `cpu` / `gpu` / `agent`) |
| POST   | `/upload`         | Store a document (PDF/TXT/CSV) for RAG-Lite context |
| POST   | `/upload_image`   | Store an image for the vision specialist     |

Example request:

```json
{
  "prompt": "Write a bash one-liner that finds the 10 largest files",
  "mode": "agent",
  "document_path": null,
  "image_path": null
}
```

**Upload rules.** Uploads are capped at 25 MB and restricted to `.pdf .txt .csv .jpg .jpeg .png .gif`; the server stores them under UUID names in `uploads/` and returns the server-side path. `/chat` accepts **only** those server-issued paths — arbitrary filesystem paths are rejected with HTTP 400. Stale uploads are purged after 24 h. Rejections return proper status codes: `413` (too large), `415` (bad type), `400`/`404` (bad/expired path), `422` (invalid mode).

**Security note.** The server binds `0.0.0.0` by design (LAN / Tailscale access) and has **no authentication** — run it on a trusted network only. Path validation prevents `/chat` from reading arbitrary files, but anyone who can reach the port can use the models.

---

## Verification & Evaluation

```bash
# Fast smoke test (router + critic + coder7)
python -m workstation.smoke_test

# Full model set
python -m workstation.smoke_test all

# After any agent run, generate the VRAM chart
python vram_chart.py                  # full timeline
python vram_chart.py --last 22        # zoom on the last 22 samples
```

The smoke test asserts that each model can load, generate, unload, and actually free VRAM (within a 1.5 GB CUDA-context tolerance), plus a router+critic coexistence check — the core architecture claim.

---

## Hardware & Software Stack

**Minimum hardware**

- CPU: multi-core x86_64 (i7 / Ryzen 7 class)
- RAM: 16 GB DDR4/DDR5
- GPU: 8 GB VRAM (RTX 3060 / 4060 / 5050)
- Storage: 100 GB SSD (NVMe preferred)

**Software**

- Python 3.10+, FastAPI, Uvicorn
- PyTorch (CUDA 12+), Hugging Face Transformers, bitsandbytes
- SQLite3
- Vanilla HTML5 / CSS3 / ES6 (no framework)

---

## Applications

- **Local code copilot** — free, privacy-preserving, offline assistant for developers
- **VRAM-constrained agent research** — demonstrates multi-agent workflows on consumer GPUs
- **Document-aware Q&A** — PDF/TXT/CSV context injection without a heavy vector store
- **Academic auditing** — append-only SQLite log of every interaction for project evaluation

---

## Limitations & Engineering Constraints

Stated honestly, because they shaped the design:

- **Sequential swap latency** — zero-sum orchestration costs 5–15 s per model load; agent runs take minutes, not seconds. No streaming yet (planned).
- **No server-side conversation memory** — each request is independent; threads live in the client's `localStorage`.
- **Single user / single worker** — one GPU owner, one uvicorn worker; requests serialize on a generation lock.
- **30 B MoE integration parked** — disabled behind `CODER30_ENABLED` pending a GGUF backend (bitsandbytes fp32-offload makes the GPU+RAM split impractical).
- **Trusted-network security model** — no auth; hardening is path validation + upload limits only.

---

## Future Work

- [ ] GGUF / llama.cpp backend for true CPU offload of MoE experts (unlocks `coder30`)
- [ ] Streaming responses via WebSockets or Server-Sent Events
- [ ] Full vector RAG (Chroma / FAISS) for larger document collections
- [ ] Server-side conversation memory across turns and sessions
- [ ] Function-calling / web-search tool agents

---

## Team

| Name                 | Role                          | Roll No. |
|----------------------|-------------------------------|----------|
| Mo Moinuddin Ali     | Systems & Orchestration       | 63       |
| Md Imtiyaz           | Backend & Model Zoo           | 61       |
| Mohammad Ayaan       | Frontend & CLI                | 64       |
| Himanshu Verma       | Frontend & CLI                | 23       |

**Institution:** Shri Shankaracharya Technical Campus, Bhilai
**Department:** Computer Science & Engineering (AI & ML)
**Guide:** Dr. Jaspal Bagga, HOD (AIML)
**Session:** September – October 2026 (3rd Semester Mini-Project)

---

## License

This project is released for academic and educational use.
See the repository for the exact license terms.

---

**Shell-Mind** — complex multi-agent AI, zero cloud, 8 GB VRAM.

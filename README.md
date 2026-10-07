# ⚡ Shell-Mind

**Zero-Sum VRAM Orchestrated Multi-Agent Local AI Workstation**

Shell-Mind is a fully local, multi-tier AI system designed to run complex software-engineering and multi-agent workflows on a strict **8 GB VRAM** budget (NVIDIA RTX 5050 / 4060 / 3060 class).

Unlike single-shot chatbot wrappers, Shell-Mind treats GPU memory as a scarce resource. It dynamically loads and unloads specialized models so that only the models required for the current stage of a request occupy VRAM at any time.

```
User
 │
 ├── Web Interface (script.js)
 └── Terminal Client (cli.py)
          │
          ▼
   FastAPI Server (ai_core.py)
          │
    ┌─────┴─────┬──────────────┐
    │           │              │
 File Uploads  PDF Context   CPU / GPU Copilot
    │           │              │
    └─────┬─────┘              │
          │                    │
          ▼                    │
   Agent Engine                │
   (orchestrator.py)           │
          │                    │
   ┌──────┼──────┬──────┐      │
   │      │      │      │      │
 Router Vision Coder Critic    │
   │      │      │      │      │
   └──────┴──────┴──────┘      │
          │                    │
          ▼                    ▼
   Model Zoo + Interaction History (SQLite)
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

Every load is preceded by a live VRAM measurement. On any `OutOfMemory` or quantisation failure the system **purges**, falls back along a registered chain (e.g. 30 B MoE → 7 B), and continues without crashing the server.

---

## Three-Tier Compute Engine

1. **CPU Lite (Tier 1)**  
   Qwen2.5-0.5B-Instruct on CPU. Instant responses when no GPU is available or for the lightest queries.

2. **GPU Copilot (Tier 2)**  
   A single 7 B instruct model (Qwen2.5-Coder-7B-Instruct, 4-bit NF4) stays resident. Standard chat, coding help, and document-context questions.

3. **Agent Workstation (Tier 3)**  
   Full multi-agent pipeline for hard requests:

   ```
   Router (1.5 B)
        ↓
   [optional Vision Specialist]
        ↓
   ONE specialist worker
        • Code   → Qwen2.5-Coder-7B (or 30 B MoE when enabled)
        • Reasoning → Qwen3-8B
        • Vision-only → summary becomes the draft
        ↓
   Final Critic (4 B)
        ↓
   Answer returned to user
   ```

---

## Key Features

| Feature | Implementation |
|---------|----------------|
| **Zero-Sum VRAM** | Live `torch.cuda.mem_get_info()` before every load, forced unload + `gc` + `empty_cache` |
| **Graceful degradation** | OOM / quant failures → purge → fallback chain → continue |
| **RAG Lite** | PyPDF2 extracts first 3 pages (≤ 3 000 chars) and injects them into the prompt — no vector DB required |
| **Vision** | Qwen3-VL-8B processes screenshots / images; output becomes compact context for the text workers |
| **Audit logging** | Every prompt, mode, attached file and response written to `shell_mind_history.db` (SQLite) |
| **Smoke tests** | `python -m workstation.smoke_test` verifies load → generate → unload → VRAM actually freed |
| **VRAM timeline** | Pipeline dumps `vram_timeline.json`; `vram_chart.py` produces a portfolio-ready chart |
| **Decoupled clients** | Vanilla HTML/CSS/JS glassmorphism UI + independent terminal CLI |
| **Thread history** | Client-side `localStorage` threads; server-side immutable SQLite log for academic review |

---

## Model Registry

All models are 4-bit NF4 (bitsandbytes) except vision towers (bf16).

| Key       | Hugging Face ID                        | Role     | Approx. VRAM | Notes                          |
|-----------|----------------------------------------|----------|--------------|--------------------------------|
| `router`  | Qwen/Qwen2.5-1.5B-Instruct             | Router   | ~1.2 GB      | Always-resident planner        |
| `coder7`  | Qwen/Qwen2.5-Coder-7B-Instruct         | Coder    | ~5.2 GB      | Production coder               |
| `coder30` | Qwen/Qwen3-Coder-30B-A3B-Instruct      | Coder    | ~6 GB + RAM  | MoE, GPU+DDR5 split (optional) |
| `thinker` | Qwen/Qwen3-8B                          | Reasoner | ~5.5 GB      | Step-by-step thinking          |
| `critic`  | Qwen/Qwen3-4B-Instruct-2507            | Critic   | ~3.0 GB      | Coexists with router           |
| `vision`  | Qwen/Qwen3-VL-8B-Instruct              | Vision   | ~6.0 GB      | Parks router while active      |

---

## Architecture (Component View)

```
primary_node/
├── ai_core.py          # FastAPI entry point, tier switching, PDF lite, SQLite log
└── ...

workstation/
├── model_zoo.py        # Loading layer, VRAM accounting, fallback chain
├── router.py           # 1.5 B planner → strict JSON plan
├── orchestrator.py     # State machine: plan → vision → worker → critic
├── agents.py           # see / code / think / critique (wake → work → sleep)
└── smoke_test.py       # Hardware acceptance tests

frontend/
├── index.html
├── style.css           # Dark glassmorphism UI
└── script.js           # Threads, attachments, neural loader

cli/
└── cli.py              # Thin terminal client (never loads models)

scripts/
└── vram_chart.py       # Portfolio chart from vram_timeline.json
```

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

### 2. Start the FastAPI engine

```bash
uvicorn primary_node.ai_core:app --host 0.0.0.0 --port 8000
```

On first boot the server creates `shell_mind_history.db` and begins serving.

### 3. Open the web UI

Serve the frontend folder with any static server, or open `index.html` directly while the backend is running at `http://localhost:8000`.

### 4. Or use the terminal client

```bash
python cli.py                                  # interactive
python cli.py --mode agent "fix this traceback..."
python cli.py --mode agent --image shot.png "what is wrong here?"
```

---

## API Surface

| Method | Endpoint          | Purpose                                      |
|--------|-------------------|----------------------------------------------|
| GET    | `/health`         | Status, current tier, free VRAM              |
| POST   | `/chat`           | Main inference (`mode`: `cpu` / `gpu` / `agent`) |
| POST   | `/upload`         | Store PDF for RAG-Lite context               |
| POST   | `/upload_image`   | Store image for vision specialist            |

Example request:

```json
{
  "prompt": "Write a bash one-liner that finds the 10 largest files",
  "mode": "agent",
  "document_path": null,
  "image_path": null
}
```

---

## Verification & Evaluation

```bash
# Fast smoke test (router + critic + coder7)
python -m workstation.smoke_test

# Full model set
python -m workstation.smoke_test all

# After any agent run, generate the VRAM chart
python scripts/vram_chart.py
```

The smoke test asserts that each model can load, generate, unload, and actually free VRAM (within a 1.5 GB CUDA-context tolerance).

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
- **Document-aware Q&A** — PDF context injection without a heavy vector store
- **Academic auditing** — immutable SQLite log of every interaction for project evaluation

---

## Future Work

- [ ] GGUF / llama.cpp backend for true CPU offload of MoE experts
- [ ] Full vector RAG (Chroma / FAISS) for larger document collections
- [ ] Streaming responses via WebSockets or Server-Sent Events
- [ ] Function-calling / web-search tool agents
- [ ] Persistent research memory across sessions

---

## Team

| Name                 | Role                          | Roll No. |
|----------------------|-------------------------------|----------|
| Mo Moinuddin Ali     | Lead / Systems & Orchestration| 63       |
| Md Imtiyaz           | Backend & Model Zoo           | 61       |
| Mohammad Ayaan       | Agents & Router               | 64       |
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

# SHELL-MIND v1.0 — Revised Mini-Project Synopsis Text
**Use this text on the official synopsis form. It replaces the concurrent/Streamlit wording.**

---

**Department of Computer Science & Engineering**  
**Mini Project Synopsis**  
**Semester:** 3rd (Session: September – October 2026)

**Students (Roll No.):**  
Md Imtiyaz (61) · Mo Moinuddin Ali (63) · Mohammad Ayaan (64) · Himanshu Verma (23)

**Project Title:**  
SHELL-MIND v1.0: Zero-Sum VRAM Orchestrated Multi-Agent Local AI System Architecture

---

## Synopsis of Project

SHELL-MIND v1.0 is an intelligent, privacy-first local AI platform designed to execute complex software-engineering and multi-agent workflows under tight hardware constraints. The system addresses the challenge of running multiple large language models in an **8 GB VRAM** environment without out-of-memory failures.

It features a **FastAPI** REST server backend integrated with **SQLite** for append-only interaction audit logging and lightweight RAG-Lite document context ingestion (PDF/TXT/CSV).

The core pipeline uses **4-bit NF4 quantized** Qwen-series models managed by aggressive dynamic memory management (evict, purge, and agent-level VRAM unloading). A pipeline of Router, Coder, Thinker, Critic, and Vision specialists executes **sequentially under zero-sum VRAM orchestration**: only the models required for the current stage occupy GPU memory; heavy workers park the router; the critic is sized to coexist with the router. Models do **not** all reside in VRAM at the same time.

The frontend is a dependency-free custom web stack (HTML5, CSS3, ES6) with glassmorphism aesthetics, client-side thread history via localStorage, optional think-block parsing, and neural-network-style loading feedback. A separate terminal CLI and optional Tailscale binding support use from other personal devices without exposing the service to the public internet.

---

## Hardware & Software Requirements

### Minimum hardware

- **CPU:** Multi-core x86_64 (Intel Core i7 or AMD Ryzen 7 class) for concurrent local server threads.
- **System memory:** 16 GB DDR4/DDR5 RAM for OS processes and data pipelines.
- **GPU:** Dedicated NVIDIA GPU with a strict **8 GB VRAM** minimum (e.g. RTX 3060, 4060, or 5050). This is the hard threshold for running 7B and 8B parameter models under 4-bit NF4 quantization with zero-sum orchestration.
- **Storage:** About **60 GB** free SSD for the enabled models Hugging Face cache (about **120 GB** if the optional disabled 30B coder weights are also fetched). NVMe preferred to reduce load latency when swapping weights into GPU memory.

### Software stack

- **OS:** Linux (Ubuntu/Fedora) or Windows 11 with WSL2 for native PyTorch compatibility.
- **Backend:** Python 3.10+, FastAPI, Uvicorn.
- **AI engine:** PyTorch (CUDA 12+), Hugging Face Transformers, bitsandbytes (dynamic NF4 quantization).
- **Database:** SQLite3 for append-only interaction auditing.
- **Presentation:** Dependency-free custom web stack (HTML5, CSS3, ES6 JavaScript) — not Streamlit.

---

## Application of Project

- **Local code copilot and reasoning assistant** — free, privacy-focused, offline assistant for developers.
- **VRAM-constrained agentic workflows** — demonstrates multi-agent pipelines (routing, coding, reasoning, vision, criticism) on consumer GPUs without cloud GPUs.
- **Document processing and context retrieval** — injects limited PDF/TXT/CSV context without overflowing the KV cache (RAG-Lite).

---

## Future work

- GGML/GGUF backends (e.g. llama.cpp) to offload model layers to system RAM and unlock larger coders.
- Expansion of RAG (e.g. Chroma/FAISS) for larger document collections.
- Real-time streaming via WebSockets or Server-Sent Events (SSE).
- Optional function-calling / web-search agents for dynamic information retrieval.
- Optional calibrated non-generative router backends for structured planning.

---

**Guide:** Dr. Jaspal Bagga, HOD (AIML)  
**Institution:** Shri Shankaracharya Technical Campus, Bhilai

---

### Changelog vs previous synopsis (for your records)

| Old claim | Corrected claim |
|-----------|-----------------|
| Models safely execute concurrently | Execute **sequentially under zero-sum VRAM orchestration** |
| Streamlit-style UI | Custom HTML/CSS/JS (not Streamlit) |
| SQLite conversation history | Append-only **interaction audit log** |
| 100 GB SSD | ~60 GB enabled / ~120 GB with optional 30B cache |
| coupmn / G&MIL typos | purge / GGML |

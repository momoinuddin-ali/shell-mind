# ⚡ Shell-Mind: Local Multi-Agent AI Workstation

Shell-Mind is a fully local, multi-tier artificial intelligence workstation designed to run entirely on an 8GB VRAM constraint (NVIDIA RTX 5050). It features a custom hardware-aware orchestrator, a multi-agent pipeline, and a decoupled web interface.

## 🚀 Core Architecture

Unlike standard single-shot wrappers, Shell-Mind implements a **Zero-Sum VRAM Orchestration** system. It aggressively manages GPU memory by dynamically loading and unloading specialized models based on the task, ensuring the system never exceeds hardware limits.

### The 3-Tier Compute Engine
1. **CPU Lite (Tier 1):** Utilizes a 0.5B model for ultra-fast, lightweight tasks.
2. **GPU Copilot (Tier 2):** Keeps a 7B Instruct model resident in memory for standard queries.
3. **Agent Workstation (Tier 3):** Parks the resident model and unleashes a multi-agent workflow for complex reasoning.

### The Multi-Agent Pipeline (Tier 3)
When complex tasks are requested, the pipeline executes the following workflow:
* **Router:** Analyzes the prompt and determines the required specialist (Code, Reasoning, or Vision).
* **Workers (7B Coder / 8B Thinker / 8B Vision):** Loads the specific domain expert into VRAM, generates a draft, and unloads.
* **Critic (4B):** Reviews the Worker's draft, catches logic or syntax errors, and polishes the final response before returning it to the user.

## ✨ Key Features

* **Graceful Degradation:** A custom error-handling system that catches PyTorch `OutOfMemory` (OOM) exceptions, purges corrupted VRAM, and safely falls back without crashing the server.
* **Document Context Injection ("RAG Lite"):** Uses `PyPDF2` to extract text from uploaded PDFs and injects targeted context directly into the prompt stream, bypassing the need for heavy vector databases.
* **Vision Capabilities:** Supports image uploads, processing them through a dedicated Vision-Language Model (VLM) for multimodal analysis.
* **Persistent Audit Logging:** Integrates a local SQLite relational database (`shell_mind_history.db`) to record all prompts, execution modes, attached files, and AI responses for academic auditing.
* **Vanilla Glassmorphism UI:** A lightweight, dependency-free HTML/CSS/JS frontend featuring CSS flexbox layouts, active thread history via `localStorage`, and animated neural network feedback.

## 🛠️ Tech Stack
* **Backend:** Python, FastAPI, PyTorch, Hugging Face `transformers`
* **Models:** Qwen 2.5 architecture (0.5B, 1.5B, 4B Critic, 7B Coder, 8B Thinker, Vision)
* **Optimization:** 4-bit NF4 Quantization (`bitsandbytes`)
* **Frontend:** Vanilla HTML, CSS3, JavaScript
* **Database:** SQLite3

## 🚦 Running the Application

This architecture is decoupled. The backend and frontend must be started separately.

**1. Start the FastAPI Engine**
Ensure your virtual environment is active, then launch the backend server:
```bash
uvicorn primary_node.ai_core:app --host 0.0.0.0 --port 8000
```
**3. Database Auditing**
Upon the first boot, the backend automatically generates an SQLite database file (`shell_mind_history.db`) in the root directory. You can open this file using any standard SQLite viewer (like DB Browser for SQLite) to audit the execution modes, prompts, file attachments, and AI outputs of every session.

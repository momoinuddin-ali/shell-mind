# Shell Mind

A local AI orchestration server built to run multi-agent workflows entirely on consumer hardware (specifically targeting an 8GB VRAM footprint).

This is a 3rd-semester computer science mini-project. The goal was to move beyond basic API wrappers and build a hardware-aware system that handles model offloading, memory limits, and multi-agent routing natively.

## What It Does
Shell Mind acts as a backend for local AI tasks, accessible via a Web GUI or a native Terminal CLI. All models and cache data are stored on an external SSD to keep the host machine clean.

To prevent Out-Of-Memory (OOM) crashes on an 8GB GPU, the system dynamically loads and unloads models based on the task.

## Core Features
*   **3-Tier Execution:** 
    *   **CPU Mode:** Fast fallback for non-GPU environments.
    *   **GPU Copilot:** Standard single-model mode for quick coding and chat.
    *   **Agent Workstation:** A multi-model pipeline where tasks are split among specialists.
*   **VRAM Management:** Uses a "Resident Router + Hot-Swapped Worker" approach. A small router model stays in memory to classify tasks, while larger specialist models (Code, Vision, Reasoning) are swapped in and out of the GPU as needed.
*   **Unified Interface:** Includes a FastAPI backend, a web frontend, and a command-line interface.

## Tech Stack
*   **Backend:** Python, FastAPI, Uvicorn
*   **ML Infrastructure:** PyTorch, Hugging Face `transformers`, `bitsandbytes` (4-bit quantization)
*   **Models:** Qwen Family (Qwen 2.5 / Qwen 3 covering Router, Critic, Coder, and Vision specialists)

## The Team
Built by computer science students focusing on local LLM deployment and systems engineering:
*   Moinuddin Ali
*   MD. Imtiyaz
*   Mohammad Ayaan
*   Himanshu Varma

---
*Developed as a 3rd-Semester Mini-Project.*

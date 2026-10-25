"""
cli.py — terminal client for the Shell-Mind server.

The CLI never loads models — it is the thin client of the 3-tier
architecture and runs on any machine with network access to the server.

Usage:
  python cli.py                                             # interactive chat
  python cli.py "explain this traceback: ValueError: ..."   # one-shot (GPU copilot)
  python cli.py --mode agent "fix this: ValueError: invalid literal for int()"
  python cli.py --mode agent --image shot.png "what is wrong in this screenshot?"

Interactive commands: /mode, /image, /doc, /help, exit, quit, clear
"""

import argparse
import os
import sys
from pathlib import Path

import requests


def _load_env() -> None:
    """Tiny .env loader: KEY=VALUE lines, '#' comments. No dependency.

    Lets `setup.sh`-generated configuration (server address, API key)
    work with zero extra steps — real environment variables still win.
    """
    env_file = Path(__file__).resolve().parent / ".env"
    if not env_file.exists():
        return
    try:
        lines = env_file.read_text().splitlines()
    except OSError:
        return
    for line in lines:
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())


_load_env()


def _ui(s: str) -> str:
    """ASCII-safe glyphs on legacy Windows consoles (L11)."""
    if sys.platform != "win32":
        return s
    return (
        s.replace("✅", "[OK]")
         .replace("⚠️", "[!]")
         .replace("⏱", "[TIME]")
         .replace("⚡", "*")
    )


DEFAULT_LOCAL = "http://localhost:8000"
# Agent pipelines load several models sequentially -> minutes, not seconds.
TIMEOUTS = {"agent": 600, "gpu": 180, "cpu": 180}


def _auth_headers(api_key: str | None) -> dict:
    return {"X-API-Key": api_key} if api_key else {}


def _normalize_server_url(raw: str) -> str:
    """Accept host, host:port, or full URL; preserve scheme; default port 8000."""
    from urllib.parse import urlparse
    raw = (raw or "").strip().replace("%", "").replace(" ", "")
    if not raw:
        return DEFAULT_LOCAL
    if "://" not in raw:
        raw = "http://" + raw
    parsed = urlparse(raw)
    scheme = parsed.scheme or "http"
    host = parsed.hostname or "localhost"
    port = parsed.port or 8000
    return f"{scheme}://{host}:{port}"


def get_server_choice(explicit: str | None = None):
    if explicit:
        return _normalize_server_url(explicit)
    env = os.getenv("SHELL_MIND_SERVER", "")
    print("\n=== Shell-Mind ===")
    print("1) Remote server (e.g. a GPU machine over Tailscale)")
    print("2) Local server on this machine (http://localhost:8000)")
    choice = input("Choose [1/2]: ").strip()

    if choice == "1":
        print("\nEnter the server address (host, host:port, or full URL)")
        if env:
            print(f"Press Enter to use saved: {env}")
        raw = input("Remote URL: ").strip() or env
        return _normalize_server_url(raw)

    print("\nNote: option 2 connects to a server running on THIS machine.")
    print("If it is not running yet, start it in another terminal:")
    print("   uvicorn primary_node.ai_core:app --host 0.0.0.0 --port 8000")
    return DEFAULT_LOCAL



def ping(server_url: str) -> None:
    """Confirm the server is alive before the first prompt."""
    try:
        info = requests.get(f"{server_url}/health", timeout=5).json()
        vram = info.get("free_vram_gb")
        vram_s = f" | {vram} GB VRAM free" if vram is not None else ""
        print(_ui(f"✅ Server online [{info.get('tier', '?')} tier{vram_s}]"))
    except Exception:
        print(_ui("⚠️  Server not responding yet — start it in another terminal with:"))
        print("   uvicorn primary_node.ai_core:app --host 0.0.0.0 --port 8000")


def upload_image(server_url: str, image_path: Path,
                 api_key: str | None = None) -> str | None:
    """Upload a local image to the server and return the server-side path.

    The server never opens client-local paths, so the image must be
    transferred first — this is what makes `--image` work from a
    different machine than the server.
    """
    try:
        with open(image_path, "rb") as fh:
            r = requests.post(f"{server_url}/upload_image",
                              files={"file": (image_path.name, fh)},
                              headers=_auth_headers(api_key),
                              timeout=300)
        if r.status_code == 401:
            print("[Error] Server rejected the API key (401). Get the correct "
                  "key from the server owner and pass it with --key.\n")
            return None
        if r.status_code == 200:
            server_path = r.json().get("image_path")
            if server_path:
                return server_path
            print("[Error] Server accepted the upload but returned no path.\n")
        else:
            print(f"[Error] Upload rejected (HTTP {r.status_code}): "
                  f"{r.text[:200]}\n")
    except requests.RequestException as exc:
        print(f"[Error] Image upload failed: {exc}\n")
    except OSError as exc:
        print(f"[Error] Cannot read '{image_path}': {exc}\n")
    return None


def upload_document(server_url: str, doc_path: Path,
                    api_key: str | None = None) -> str | None:
    """Upload a local PDF/TXT/CSV for RAG-Lite; return server-side path."""
    try:
        with open(doc_path, "rb") as fh:
            r = requests.post(
                f"{server_url}/upload",
                files={"file": (doc_path.name, fh)},
                headers=_auth_headers(api_key),
                timeout=300,
            )
        if r.status_code == 401:
            print("[Error] Server rejected the API key (401).\n")
            return None
        if r.status_code == 200:
            server_path = r.json().get("document_path")
            if server_path:
                return server_path
            print("[Error] Server accepted the upload but returned no path.\n")
        else:
            print(f"[Error] Upload rejected (HTTP {r.status_code}): "
                  f"{r.text[:200]}\n")
    except requests.RequestException as exc:
        print(f"[Error] Document upload failed: {exc}\n")
    except OSError as exc:
        print(f"[Error] Cannot read '{doc_path}': {exc}\n")
    return None


def print_reply(reply: dict) -> None:
    print(_ui(f"ai> {reply.get('answer', '')}\n"))
    stages = reply.get("stages")
    if stages:
        stage_s = " · ".join(f"{name} {t}s" for name, t in stages)
        print(_ui(f"   ⏱ {stage_s} | total {reply.get('total_s', '?')}s\n"))


def chat_with_server(server_url: str, prompt_text: str, mode: str = "gpu",
                     image_path: Path | None = None,
                     document_path: Path | None = None,
                     api_key: str | None = None) -> None:
    payload = {"prompt": prompt_text, "mode": mode}
    if image_path:
        server_path = upload_image(server_url, image_path, api_key)
        if not server_path:
            print("[Error] Prompt not sent — the image could not be uploaded.\n")
            return
        payload["image_path"] = server_path
    if document_path:
        server_doc = upload_document(server_url, document_path, api_key)
        if not server_doc:
            print("[Error] Prompt not sent — the document could not be uploaded.\n")
            return
        payload["document_path"] = server_doc
    try:
        r = requests.post(f"{server_url}/chat", json=payload,
                          headers=_auth_headers(api_key),
                          timeout=TIMEOUTS.get(mode, 180))
        if r.status_code == 200:
            print_reply(r.json())
        elif r.status_code == 401:
            print("[Error] Server rejected the API key (401). Get the correct "
                  "key from the server owner and pass it with --key.\n")
        else:
            print(f"[Error] Server returned status {r.status_code}: {r.text[:200]}\n")
    except requests.Timeout:
        print(f"[Error] Timed out after {TIMEOUTS.get(mode, 180)}s in {mode} mode "
              f"(model may still be working — check the server terminal).\n")
    except requests.RequestException:
        print(f"[Error] Server not reachable at {server_url}.")
        print("-> Did you forget to start 'uvicorn primary_node.ai_core:app' in another terminal?\n")


def main() -> None:
    ap = argparse.ArgumentParser(description="SHELL MIND terminal client")
    ap.add_argument("prompt", nargs="*",
                    help="one-shot prompt (omit for interactive chat)")
    ap.add_argument("--mode", choices=["agent", "gpu", "cpu"], default="gpu",
                    help="compute tier (default: gpu copilot)")
    ap.add_argument("--image", type=Path, default=None,
                    help="image/screenshot — uploaded then cleared after one shot")
    ap.add_argument("--doc", type=Path, default=None,
                    help="PDF/TXT/CSV for RAG-Lite — uploaded for this request")
    ap.add_argument("--server", "-s", default=os.getenv("SHELL_MIND_SERVER"),
                    help="server URL (skips interactive chooser); env SHELL_MIND_SERVER")
    ap.add_argument("--key", default=os.getenv("SHELL_MIND_API_KEY"),
                    help="API key (defaults to SHELL_MIND_API_KEY)")
    args = ap.parse_args()

    # L12: non-interactive (piped / CI) or explicit --server / env → no prompt
    if args.server:
        server_url = get_server_choice(args.server)
    elif not sys.stdin.isatty():
        server_url = _normalize_server_url(
            os.getenv("SHELL_MIND_SERVER") or DEFAULT_LOCAL
        )
    else:
        server_url = get_server_choice(None)
    print(f"\nConnected to: {server_url}")
    ping(server_url)
    print()

    mode = args.mode
    image = args.image
    document = args.doc
    api_key = args.key
    if image and not image.exists():
        print(f"[Error] Image not found: {image}\n")
        sys.exit(1)
    if document and not document.exists():
        print(f"[Error] Document not found: {document}\n")
        sys.exit(1)

    # --- ONE-SHOT COMMAND MODE ---
    if args.prompt:
        prompt_text = " ".join(args.prompt)
        print(_ui(f"you> {prompt_text}"))
        chat_with_server(server_url, prompt_text, mode, image, document, api_key)
        return

    # --- INTERACTIVE CHAT LOOP ---
    print("Interactive mode. Commands: /mode /image /doc /help, exit, quit, clear\n")
    while True:
        try:
            prompt = input(_ui("you> ")).strip()
            if not prompt:
                continue
            low = prompt.lower()

            if low in ("exit", "quit"):
                break
            if low == "clear":
                os.system("cls" if os.name == "nt" else "clear")
                continue

            if low.startswith("/mode"):
                parts = prompt.split()
                if len(parts) > 1 and parts[1].lower() in ("agent", "gpu", "cpu"):
                    mode = parts[1].lower()
                    print(f"   [mode set to {mode}]\n")
                else:
                    print(f"   current mode: {mode} | usage: /mode agent|gpu|cpu\n")
                continue

            if low.startswith("/image"):
                parts = prompt.split(maxsplit=1)
                if len(parts) > 1 and parts[1].lower() not in ("none", "clear"):
                    img = Path(parts[1].strip().strip("'\""))
                    if img.exists():
                        image = img
                        print(f"   [image attached: {img} — uploaded with your next message]\n")
                    else:
                        print(f"   [image not found: {img}]\n")
                else:
                    image = None
                    print("   [image cleared]\n")
                continue

            if low.startswith("/doc"):
                parts = prompt.split(maxsplit=1)
                if len(parts) > 1 and parts[1].lower() not in ("none", "clear"):
                    d = Path(parts[1].strip().strip("'\""))
                    if d.exists():
                        document = d
                        print(f"   [document attached: {d} — uploaded with your next message]\n")
                    else:
                        print(f"   [document not found: {d}]\n")
                else:
                    document = None
                    print("   [document cleared]\n")
                continue

            if low == "/help":
                print("   /mode agent|gpu|cpu   switch compute tier")
                print("   /image <path>|none    attach a screenshot (one message only)")
                print("   /doc <path>|none      attach PDF/TXT/CSV for RAG-Lite")
                print("   exit | quit | clear\n")
                continue

            chat_with_server(server_url, prompt, mode, image, document, api_key)
            # Match web UI: attachments apply to one message only
            image = None
            document = None

        except (KeyboardInterrupt, EOFError):
            print("\nExiting Shell-Mind...")
            break



if __name__ == "__main__":
    main()
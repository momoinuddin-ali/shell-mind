"""
cli.py — terminal client for the Shell-Mind server.

The CLI never loads models — it is the thin client of the 3-tier
architecture and runs on any machine with network access to the server.

Usage:
  python cli.py                                             # interactive chat
  python cli.py "explain this traceback: ValueError: ..."   # one-shot (GPU copilot)
  python cli.py --mode agent "fix this: ValueError: invalid literal for int()"
  python cli.py --mode agent --image shot.png "what is wrong in this screenshot?"

Interactive commands: /mode, /image, /help, exit, quit, clear
"""

import argparse
import os
import sys
from pathlib import Path

import requests

DEFAULT_LOCAL = "http://localhost:8000"
# Agent pipelines load several models sequentially -> minutes, not seconds.
TIMEOUTS = {"agent": 600, "gpu": 180, "cpu": 180}


def get_server_choice():
    print("\n=== Shell-Mind ===")
    print("1) Remote server (e.g. a GPU machine over Tailscale)")
    print("2) Local server on this machine (http://localhost:8000)")
    choice = input("Choose [1/2]: ").strip()

    if choice == "1":
        default_remote = os.getenv("SHELL_MIND_SERVER", "")
        print("\nEnter the server address (e.g. 100.109.148.4)")
        if default_remote:
            print(f"Press Enter to use saved: {default_remote}")

        # Clean up accidental spaces or % signs
        raw_ip = input("Remote URL: ").strip().replace("%", "").replace(" ", "") or default_remote

        # Strip the protocol first so we don't accidentally split the 'http://'
        if raw_ip.startswith("http://"):
            raw_ip = raw_ip[7:]
        elif raw_ip.startswith("https://"):
            raw_ip = raw_ip[8:]

        # Now safely drop any typed ports and slashes
        raw_ip = raw_ip.split(":")[0].rstrip("/")

        return f"http://{raw_ip}:8000"

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
        print(f"✅ Server online [{info.get('tier', '?')} tier{vram_s}]")
    except Exception:
        print("⚠️  Server not responding yet — start it in another terminal with:")
        print("   uvicorn primary_node.ai_core:app --host 0.0.0.0 --port 8000")


def upload_image(server_url: str, image_path: Path) -> str | None:
    """Upload a local image to the server and return the server-side path.

    The server never opens client-local paths, so the image must be
    transferred first — this is what makes `--image` work from a
    different machine than the server.
    """
    try:
        with open(image_path, "rb") as fh:
            r = requests.post(f"{server_url}/upload_image",
                              files={"file": (image_path.name, fh)},
                              timeout=300)
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


def print_reply(reply: dict) -> None:
    print(f"ai> {reply.get('answer', '')}\n")
    stages = reply.get("stages")
    if stages:
        stage_s = " · ".join(f"{name} {t}s" for name, t in stages)
        print(f"   ⏱ {stage_s} | total {reply.get('total_s', '?')}s\n")


def chat_with_server(server_url: str, prompt_text: str,
                     mode: str = "gpu", image_path: Path | None = None) -> None:
    payload = {"prompt": prompt_text, "mode": mode}
    if image_path:
        server_path = upload_image(server_url, image_path)
        if not server_path:
            print("[Error] Prompt not sent — the image could not be uploaded.\n")
            return
        payload["image_path"] = server_path
    try:
        r = requests.post(f"{server_url}/chat", json=payload,
                          timeout=TIMEOUTS.get(mode, 180))
        if r.status_code == 200:
            print_reply(r.json())
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
                    help="image/screenshot path — uploaded to the server and routed to the agent vision expert")
    args = ap.parse_args()

    server_url = get_server_choice()
    print(f"\nConnected to: {server_url}")
    ping(server_url)
    print()

    mode = args.mode
    image = args.image
    if image and not image.exists():
        print(f"[Error] Image not found: {image}\n")
        sys.exit(1)

    # --- ONE-SHOT COMMAND MODE ---
    if args.prompt:
        prompt_text = " ".join(args.prompt)
        print(f"you> {prompt_text}")
        chat_with_server(server_url, prompt_text, mode, image)
        return

    # --- INTERACTIVE CHAT LOOP ---
    print("Interactive mode. Commands: /mode /image /help, exit, quit, clear\n")
    while True:
        try:
            prompt = input("you> ").strip()
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

            if low == "/help":
                print("   /mode agent|gpu|cpu   switch compute tier")
                print("   /image <path>|none    attach a screenshot (uploaded with the next message)")
                print("   exit | quit | clear\n")
                continue

            chat_with_server(server_url, prompt, mode, image)

        except (KeyboardInterrupt, EOFError):
            print("\nExiting Shell-Mind...")
            break


if __name__ == "__main__":
    main()

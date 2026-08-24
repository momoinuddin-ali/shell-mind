import requests
import subprocess
import sys
from supervisor.safety import is_safe, log_action

SERVER = "http://localhost:8000"

def ask_ai(prompt, persona):
    try:
        r = requests.post(f"{SERVER}/chat",
            json={"prompt": prompt, "persona": persona, "max_tokens": 400},
            stream=True, timeout=120
        )
        for chunk in r.iter_content(decode_unicode=True):
            if chunk:
                print(chunk, end="", flush=True)
        print()
    except Exception as e:
        print(f"[Server not running? Start uvicorn first] {e}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python shell_mind_cli.py explain 'ls -la'")
        sys.exit(0)
    cmd = sys.argv[1]
    if cmd == "explain":
        user_cmd = " ".join(sys.argv[2:])
        if not is_safe(user_cmd):
            print(f"BLOCKED by supervisor: {user_cmd}")
            log_action(f"explain {user_cmd}", user_cmd, blocked=True)
            sys.exit(1)
        ask_ai(f"Explain this linux command in simple terms: {user_cmd}", "You are a Linux expert. Explain commands simply.")
        log_action(f"explain {user_cmd}", user_cmd, blocked=False)
    elif cmd == "write":
        task = " ".join(sys.argv[2:])
        ask_ai(f"Write a linux shell command for: {task}. Give command only plus one line explanation.", "You are a helpful shell assistant.")
import os, sys, requests

DEFAULT_LOCAL = "http://localhost:8000"

def get_server_choice():
    print("\n=== Shell-Mind ===")
    print("1) Use Moin's Omen as Remote Server (Long Distance - Fast, 8B)")
    print("2) Use Local Small Model (True Offline - Works on No dGPU)")
    choice = input("Choose [1/2]: ").strip()
    if choice == "1":
        # Ask for IP
        default_remote = os.getenv("SHELL_MIND_SERVER", "")
        print(f"\nEnter Moin's Tailscale IP (e.g. 100.x.x.x:8000)")
        if default_remote: print(f"Press Enter to use saved: {default_remote}")
        ip = input("Remote URL: ").strip() or default_remote
        if not ip.startswith("http"): ip = f"http://{ip}"
        if ":8000" not in ip: ip = ip.rstrip("/") + ":8000"
        return ip
    else:
        print("\nStarting local CPU model... Make sure you ran: uvicorn primary_node.ai_core:app --host 0.0.0.0 --port 8000")
        return DEFAULT_LOCAL

SERVER_URL = get_server_choice()
print(f"\nConnected to: {SERVER_URL}\n")

while True:
    prompt = input("you> ").strip()
    if not prompt: continue
    if prompt in ["exit","quit"]: break
    try:
        r = requests.post(f"{SERVER_URL}/chat", json={"prompt": prompt}, stream=True, timeout=120)
        print("ai> ", end="")
        for chunk in r.iter_content(decode_unicode=True):
            if chunk: print(chunk, end="", flush=True)
        print("\n")
    except Exception as e:
        print(f"[Error] Server not reachable at {SERVER_URL}. Is Moin's laptop ON? {e}")
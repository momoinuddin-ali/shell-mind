import os, sys, requests

DEFAULT_LOCAL = "http://localhost:8000"

def get_server_choice():
    print("\n=== Shell-Mind ===")
    print("1) Use Moin's Omen as Remote Server (Long Distance - Fast, 8B)")
    print("2) Use Local Small Model (True Offline - Works on No dGPU)")
    choice = input("Choose [1/2]: ").strip()
    
    if choice == "1":
        default_remote = os.getenv("SHELL_MIND_SERVER", "")
        print(f"\nEnter Moin's Tailscale IP (e.g. 100.109.148.4)")
        if default_remote: print(f"Press Enter to use saved: {default_remote}")
        
        # Get input and clean up accidental spaces or % signs
        raw_ip = input("Remote URL: ").strip().replace("%", "").replace(" ", "") or default_remote
        
        # Strip protocol first so we don't accidentally split the 'http://'
        if raw_ip.startswith("http://"):
            raw_ip = raw_ip[7:]
        elif raw_ip.startswith("https://"):
            raw_ip = raw_ip[8:]
            
        # Now safely remove any typed ports and slashes
        raw_ip = raw_ip.split(":")[0].rstrip("/")
        
        ip = f"http://{raw_ip}:8000"
        return ip
    else:
        print("\nStarting local CPU model...")
        return DEFAULT_LOCAL

SERVER_URL = get_server_choice()
print(f"\nConnected to: {SERVER_URL}\n")

def chat_with_server(prompt_text):
    try:
        # We send mode="gpu" to match our updated ai_core.py requirements
        r = requests.post(f"{SERVER_URL}/chat", json={"prompt": prompt_text, "mode": "gpu"}, stream=False, timeout=120)
        if r.status_code == 200:
            print(f"ai> {r.json().get('answer', '')}\n")
        else:
            print(f"[Error] Server returned status {r.status_code}")
    except Exception as e:
        print(f"[Error] Server not reachable at {SERVER_URL}.")
        print("-> Did you forget to start 'uvicorn primary_node.ai_core:app' in another terminal?\n")

# --- ONE-SHOT COMMAND FEATURE ---
# This allows: python shell_mind_cli.py explain "ls -la"
if len(sys.argv) > 1:
    one_shot_prompt = " ".join(sys.argv[1:])
    print(f"you> {one_shot_prompt}")
    chat_with_server(one_shot_prompt)
else:
    # --- INTERACTIVE CHAT LOOP ---
    while True:
        try:
            prompt = input("you> ").strip()
            if not prompt: continue
            if prompt in ["exit", "quit", "clear"]: 
                if prompt == "clear":
                    os.system('cls' if os.name == 'nt' else 'clear')
                    continue
                break
            chat_with_server(prompt)
        except KeyboardInterrupt:
            print("\nExiting Shell-Mind...")
            break
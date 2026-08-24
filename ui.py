import gradio as gr, requests, os
SERVER = os.getenv("SHELL_MIND_SERVER","http://localhost:8000")

def chat_fn(prompt):
    try:
        r = requests.post(f"{SERVER}/chat", json={"prompt":prompt}, stream=False, timeout=120)
        return r.text
    except Exception as e:
        return f"Server {SERVER} not reachable: {e}"

gr.Interface(fn=chat_fn, inputs="text", outputs="text", title="Shell-Mind - Offline AI", description=f"Connected to {SERVER} | Choose remote Omen or local 0.5B").launch(server_name="0.0.0.0", server_port=7860)
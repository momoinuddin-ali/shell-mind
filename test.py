import requests

print("Sending order to the Waiter...")

# 1. We package our question exactly how the Waiter expects it
payload = {"prompt": "Explain what a Linux kernel is in one short sentence."}

# 2. We send it to the local door (Port 8000)
response = requests.post("http://127.0.0.1:8000/chat", json=payload)

# 3. Print the AI's reply to the screen!
print("\n🤖 DeepSeek Replies:\n", response.json()["answer"])

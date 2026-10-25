# Shell-Mind — Security guide

## Threat model (honest)

Shell-Mind is **self-hosted**: you clone it and run the backend on your own
GPU machine (or a company box). There is no Shell-Mind cloud. The browser
and CLI are frontends to *your* process.

Anyone who can reach that HTTP port **and** present a valid API key can use
your models and stress the GPU within the rate limit.

They **cannot** (with current hardening):

- read arbitrary files on the server (`/chat` only opens paths the server issued under `uploads/`)
- execute uploaded files (parsed by PyPDF2 / PIL only)
- see other users' chats as a service feature (audit DB is local SQLite on the server disk)

---

## Defenses (use all three on shared networks)

1. **Tailscale-only bind**
   ```bash
   uvicorn primary_node.ai_core:app --host $(tailscale ip -4) --port 8000
   # or: ./run-server.sh after ./setup.sh (option 1)
   ```
   LAN strangers never see the port.

2. **API key** — `SHELL_MIND_API_KEY` in `.env`  
   Required on `/chat`, `/upload`, `/upload_image`. `/health` stays open.

3. **Rate limit** — defaults in `.env` from `setup.sh`
   ```bash
   SHELL_MIND_RATE_LIMIT=20    # requests per window per IP
   SHELL_MIND_RATE_WINDOW=60   # seconds
   ```
   Over limit → HTTP **429**. Concurrent work → HTTP **503** ("server busy").

---

## API key: how it works

- One valid key only: the value in the **running process** environment.
- Compared with `secrets.compare_digest` (constant-time).
- **No key history, no secondary key, no grace period.**

### If the key leaks

Anyone with the key + network path can run prompts and uploads until you rotate.

### How to dispose of a key and create a new one

```bash
./setup.sh
# choose 3) Rotate API key
# then restart: Ctrl+C → ./run-server.sh
```

Or manually: put a new value in `.env`, restart the server.

**The moment the process restarts with the new value, the old key returns HTTP 401.**  
Holding a copy of the old key does nothing.

### On every client after rotation

| Client | Action |
|--------|--------|
| Web UI | **Clear All Data** (forgets `localStorage` key) **or** enter the new key when the 401 prompt appears |
| CLI | Update `.env` / `--key` / re-run `./setup.sh` as client |

### Does rotation fully protect you?

| Situation | Result |
|-----------|--------|
| Rotated + restarted; attacker has **old** key | **Blocked** (401) |
| Attacker has the **new** key | Not blocked — treat the key like a password |
| Attacker is on your Tailscale account | Remove the device in the [admin console](https://login.tailscale.com/admin/machines) |
| Bound to `0.0.0.0` with **no** key on open Wi-Fi | They never needed a key |

**Rotation kills the leaked secret. It does not revoke network access.**

---

## Lost phone / laptop

1. Remove the device from Tailscale admin → it cannot reach the server.
2. Rotate the API key → any cached key on that device dies.
3. Optional: check `shell_mind_history.db` for unexpected client IPs.

---

## Checklist

- [ ] `./setup.sh` as Server (Tailscale IP + key + rate limits)
- [ ] Share URL + key only with people you trust
- [ ] On hostel/college Wi-Fi: never `0.0.0.0` without a key
- [ ] Lost device → Tailscale remove **and** rotate key
- [ ] `models.json` and `.env` stay gitignored

See also: README security note, `CHANGES.md` timeline.

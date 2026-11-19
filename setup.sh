#!/usr/bin/env bash
# Shell-Mind onboarding — server (GPU box) or client (everything else).
# Generates .env + run-server.sh (both gitignored) with YOUR Tailscale IP
# and a fresh API key. Re-run any time to rotate the key.
set -euo pipefail

echo "=== Shell-Mind setup ==="
echo "1) Server  — this machine has the GPU and runs the models"
echo "2) Client  — this device just talks to a server"
echo "3) Rotate API key (server only — kills the old key immediately)"
read -rp "Choose [1/2/3]: " ROLE

rotate_key() {
  command -v python3 >/dev/null 2>&1 || { echo "python3 required"; exit 1; }
  NEW_KEY="$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')"
  if [ -f .env ]; then
    # Replace existing key or append
    if grep -q '^SHELL_MIND_API_KEY=' .env 2>/dev/null; then
      # portable in-place edit
      python3 -c "
from pathlib import Path
p = Path('.env')
lines = []
for line in p.read_text().splitlines():
    if line.startswith('SHELL_MIND_API_KEY='):
        lines.append('SHELL_MIND_API_KEY=$NEW_KEY')
    else:
        lines.append(line)
p.write_text('\n'.join(lines) + '\n')
"
    else
      printf 'SHELL_MIND_API_KEY=%s\n' "$NEW_KEY" >> .env
    fi
  else
    printf 'SHELL_MIND_API_KEY=%s\n' "$NEW_KEY" > .env
  fi
  chmod 0600 .env
  echo
  echo "✅ New API key written to .env"
  echo "   Key: $NEW_KEY"
  echo
  echo "IMPORTANT — the OLD key is now dead:"
  echo "  1. Restart the server (Ctrl+C, then ./run-server.sh)"
  echo "  2. On every client: open the UI → Clear All Data (forgets the old key)"
  echo "     or re-run this setup as Client and enter the new key"
  echo "  3. Anyone still holding the old key gets HTTP 401 immediately"
}

if [ "$ROLE" = "3" ]; then
  rotate_key
  exit 0
fi

if [ "$ROLE" = "1" ]; then
  command -v tailscale >/dev/null 2>&1 || {
    echo "Tailscale not installed — https://tailscale.com/download"; exit 1; }
  TS_IP="$(tailscale ip -4 2>/dev/null || true)"
  [ -z "$TS_IP" ] && { echo "Tailscale not connected — run 'sudo tailscale up' first."; exit 1; }

  # Fresh key every setup run (or keep existing if user prefers)
  if [ -f .env ] && grep -q '^SHELL_MIND_API_KEY=' .env 2>/dev/null; then
    read -rp "Existing API key found. Keep it [K] or generate a new one [N]? " KEEP
    if [ "${KEEP,,}" = "n" ]; then
      API_KEY="$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')"
    else
      API_KEY="$(grep '^SHELL_MIND_API_KEY=' .env | cut -d= -f2-)"
    fi
  else
    API_KEY="$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')"
  fi

  # Merge into .env without wiping unrelated keys (HF_HUB_OFFLINE, etc.) — M2
  export _SM_API_KEY="$API_KEY"
  python3 -c '
from pathlib import Path
import os
p = Path(".env")
data = {}
if p.exists():
    for line in p.read_text().splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, _, v = s.partition("=")
        data[k.strip()] = v.strip()
data["SHELL_MIND_API_KEY"] = os.environ["_SM_API_KEY"]
data.setdefault("SHELL_MIND_RATE_LIMIT", "20")
data.setdefault("SHELL_MIND_RATE_WINDOW", "60")
p.write_text("\n".join(f"{k}={v}" for k, v in data.items()) + "\n")
p.chmod(0o600)
'

  cat > run-server.sh <<EOF
#!/usr/bin/env bash
set -euo pipefail
cd "\$(dirname "\$0")"
set -a; source .env; set +a
echo "Tailnet-only: http://$TS_IP:8000"
echo "  (use this URL in the browser — not localhost — so the API key prompt works from other devices)"
echo "Auth: ON  |  Rate limit: \${SHELL_MIND_RATE_LIMIT:-20} req / \${SHELL_MIND_RATE_WINDOW:-60}s"
exec uvicorn primary_node.ai_core:app --host $TS_IP --port 8000
EOF
  chmod +x run-server.sh

  echo
  echo "✅ Server ready"
  echo "   Start:       ./run-server.sh"
  echo "   Share URL:   http://$TS_IP:8000"
  echo "   Share key:   $API_KEY"
  echo
  echo "   Models: copy models.example.json → models.json and edit HF IDs"
  echo "   Rotate:  ./setup.sh  → choose 3"
else
  # Client
  if command -v tailscale >/dev/null 2>&1 && tailscale status >/dev/null 2>&1; then
    echo "✅ Tailscale connected"
  else
    echo "⚠ Tailscale not detected — make sure the app/VPN is on before connecting."
  fi
  read -rp "Server URL or tailnet IP (e.g. http://100.x.y.z:8000 or 100.x.y.z): " SRV
  read -rp "API key from the server owner (Enter if auth is off): " KEY
  export _SM_SRV="$SRV"
  export _SM_KEY="$KEY"
  python3 -c '
from pathlib import Path
import os
p = Path(".env")
data = {}
if p.exists():
    for line in p.read_text().splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, _, v = s.partition("=")
        data[k.strip()] = v.strip()
raw = (os.environ.get("_SM_SRV") or "").strip()
if "://" not in raw:
    raw = "http://" + raw
from urllib.parse import urlparse as _up
_p = _up(raw)
_host = _p.hostname or "localhost"
_port = _p.port or 8000
if ":" in _host and not _host.startswith("["):
    _host = "[" + _host + "]"
data["SHELL_MIND_SERVER"] = f"{_p.scheme or 'http'}://{_host}:{_port}"
if os.environ.get("_SM_KEY"):
    data["SHELL_MIND_API_KEY"] = os.environ["_SM_KEY"]
p.write_text("\n".join(f"{k}={v}" for k, v in data.items()) + "\n")
p.chmod(0o600)
'
  # Normalize the pasted server value the same way the .env writer does —
  # the probe must use the URL the user actually typed (scheme/port and
  # all), not a hardcoded http://host:8000.
  SRV_URL="$(printf '%s' "$SRV" | python3 -c '
import sys
from urllib.parse import urlparse
raw = sys.stdin.read().strip()
if "://" not in raw:
    raw = "http://" + raw
p = urlparse(raw)
host = p.hostname or "localhost"
if ":" in host and not host.startswith("["):
    host = "[" + host + "]"
port = p.port or 8000
print((p.scheme or "http") + "://" + host + ":" + str(port))
')"
  echo
  if curl -fsS ${KEY:+-H "X-API-Key: $KEY"} "$SRV_URL/health" >/dev/null 2>&1; then
    echo "✅ Server reachable — run: python cli.py"
    echo "   Browser:  $SRV_URL"
  else
    echo "⚠ Not reachable yet — is the server running, and is your device on the tailnet?"
  fi
fi

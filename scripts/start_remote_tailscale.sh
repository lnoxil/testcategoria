#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PORT="${PORT:-5000}"
HOST="${HOST:-0.0.0.0}"

if [[ ! -d .venv ]]; then
  python -m venv .venv
fi

source .venv/bin/activate
pip install -r requirements.txt >/dev/null

TAILSCALE_IP=""
if command -v tailscale >/dev/null 2>&1; then
  TAILSCALE_IP="$(tailscale ip -4 2>/dev/null | head -n1 || true)"
fi

echo "[info] Starting Flask on http://${HOST}:${PORT}"
if [[ -n "$TAILSCALE_IP" ]]; then
  echo "[info] Open from your phone (Tailscale connected): http://${TAILSCALE_IP}:${PORT}"
else
  echo "[warn] Tailscale CLI not found or disconnected. Install/login to Tailscale on PC and phone."
fi

USE_HTTPS=0 HOST="$HOST" PORT="$PORT" python app.py

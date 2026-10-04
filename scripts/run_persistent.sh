#!/usr/bin/env bash
# Keep app_service.py running; restart after 5 s if it dies (Linux/macOS equivalent of PERSISTENCE_SERVICE.bat).
cd "$(dirname "$0")/.."
if [ -f venv/bin/activate ]; then . venv/bin/activate; fi
while true; do
  echo "[$(date)] Starting app service..."
  python app_service.py
  echo "[$(date)] WARNING: service stopped. Restarting in 5 s..."
  sleep 5
done

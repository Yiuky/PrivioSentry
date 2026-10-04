#!/usr/bin/env bash
# Start the Gatekeeper (on/off control panel + reverse proxy for the app).
set -euo pipefail
cd "$(dirname "$0")/.."
if [ -f venv/bin/activate ]; then . venv/bin/activate; fi
exec python gatekeeper.py

#!/usr/bin/env bash
# Start the web app (FastAPI). Honors APP_HOST / APP_PORT / API_TOKEN from .env.
set -euo pipefail
cd "$(dirname "$0")/.."
if [ -f venv/bin/activate ]; then . venv/bin/activate; fi
exec python app_service.py

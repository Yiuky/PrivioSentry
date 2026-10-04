# syntax=docker/dockerfile:1
FROM python:3.12-slim

LABEL org.opencontainers.image.title="PRIVIO SENTRY - SENTRY Redact" \
      org.opencontainers.image.description="Local AI Privacy Infrastructure: AI-assisted document redaction with human review" \
      org.opencontainers.image.licenses="AGPL-3.0-or-later (source code; see NOTICE for third-party components and TRADEMARKS.md for the name/logos)"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# Tesseract (+ Portuguese and English data) and the shared libs OpenCV (ultralytics) needs.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        tesseract-ocr tesseract-ocr-por tesseract-ocr-eng libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Unprivileged user
RUN useradd --create-home --uid 10001 sentry
WORKDIR /app

COPY requirements.txt .
# CPU-only PyTorch keeps the image small (remove the first line to use the default/GPU wheels).
RUN pip install --extra-index-url https://download.pytorch.org/whl/cpu torch torchvision \
    && pip install -r requirements.txt

COPY . .
RUN mkdir -p /app/output /app/WEB_INPUT /app/documentos_finais /app/state \
    && chown -R sentry:sentry /app
USER sentry

# Inside a container the app must listen on all interfaces; publish the port to localhost only
# (see docker-compose.yml) and set API_TOKEN if you expose it further.
ENV APP_HOST=0.0.0.0 \
    APP_PORT=8001 \
    PRIVIO_TASKS_FILE=/app/state/tasks.json \
    YOLO_MODEL_PATH=models/signature_stamp_detector.pt

EXPOSE 8001
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
    CMD python -c "import urllib.request,os;urllib.request.urlopen('http://127.0.0.1:%s/' % os.environ.get('APP_PORT','8001'))" || exit 1

CMD ["python", "app_service.py"]

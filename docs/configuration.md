# Configuration

All settings are environment variables, normally set in a `.env` file at the repository root (loaded with `python-dotenv`). Copy [`.env.example`](../.env.example) to `.env`. Every variable is optional; the **default** is the value used by the code when the variable is unset. This list was produced from the code (`os.getenv` calls); if you add a variable, update this file and `.env.example`.

## Web service

| Variable | Default | Read in | Description |
|---|---|---|---|
| `APP_HOST` | `127.0.0.1` | `app_service.py`, `gatekeeper.py` | Interface to bind. Use `0.0.0.0` only together with `API_TOKEN` and HTTPS in front. |
| `APP_PORT` | `8001` | `app_service.py`, `gatekeeper.py` | Port of the app; the gatekeeper proxies to it. |
| `API_TOKEN` | *(empty = no auth)* | `app_service.py` | When set, every route requires it: header `X-API-Token`, cookie `api_token` or `?token=` (the query-string form can leak in logs/history; prefer the header/cookie). |
| `MAX_UPLOAD_MB` | `500` | `app_service.py` | Maximum upload size. |
| `PRIVIO_INPUT_DIR` | `./WEB_INPUT` | `app_service.py` | Where uploaded PDFs are stored. |
| `PRIVIO_OUTPUT_DIR` | `./output` | `app_service.py`, `utils/session.py` | Per-task artifacts: page images, OCR results, crops, logs, redaction metadata (**contain personal data**). |
| `PRIVIO_FINAL_DIR` | `./documentos_finais` | `app_service.py`, `utils/session.py` | Final redacted PDFs. |
| `PRIVIO_TASKS_FILE` | `./tasks.json` | `app_service.py` | Task state (JSON, written atomically). |
| `GATEKEEPER_PORT` | `8000` | `gatekeeper.py` | Port of the optional on/off panel / reverse proxy. |
| `GATEKEEPER_STATE_FILE` | `./.gatekeeper_state` | `gatekeeper.py` | Where the gatekeeper remembers whether the app should be running. |

## PDF rendering and OCR (Tesseract)

| Variable | Default | Description |
|---|---|---|
| `BASE_DPI` | `1000` | DPI used to render each page for OCR. High values help small text but need lots of RAM and time; 300-600 is a reasonable start on modest machines. |
| `TESSERACT_PATH` | *(system PATH)* | Full path to the `tesseract` executable if it is not on `PATH` (typical on Windows). |
| `TESSERACT_LANG` | `por` | Tesseract language(s), e.g. `por+eng`. The traineddata must be installed. |
| `TESSDATA_PREFIX` | *(Tesseract default)* | Folder with `*.traineddata`. Read by Tesseract itself, not by the code. On Debian/Ubuntu install `tesseract-ocr-por`; the original working copy kept a 16 MB `tessdata/` folder, which is not part of the public repository. |
| `TESSERACT_STD_PSM` | `3` | Page segmentation mode for the full-page pass. |
| `TESSERACT_SPARSE_PSM` | *(empty = skip)* | PSM for the second ("sparse") full-page pass, e.g. `11`; it finds disconnected fragments such as noisy digits. |
| `TESSERACT_CROP_PSM` | `6` | PSM for small crops (signature crops, verification). |

## Local LLM (Ollama)

| Variable | Default | Description |
|---|---|---|
| `OLLAMA_API_URL` | `http://localhost:11434` | Base URL of the Ollama server (`/api/chat` is appended). In Docker use `http://host.docker.internal:11434`. |
| `OLLAMA_MODEL` | `llama3` | Text model name. |
| `OLLAMA_VISION_MODEL` | `gemma4:e4b` | Vision model used for address discovery and handwritten-CPF audits. Must be a multimodal model you have pulled. |
| `OLLAMA_TEXT_TIMEOUT` | `300` | Seconds before a text request is considered failed (the pipeline then fails closed / flags the page). |
| `OLLAMA_VISION_TIMEOUT` | `600` | Same for vision requests. |
| `AI_IMAGE_RESOLUTION` | `2048` | Maximum image side (px) sent to the vision model (it is reduced further on retries). |
| `AI_CONTEXT_WINDOW` | `32768` | `num_ctx` passed to Ollama (tokens). Affects VRAM use. |

## YOLO signature detector

| Variable | Default | Description |
|---|---|---|
| `YOLO_MODEL_PATH` | `models/signature_stamp_detector.pt` | Path to the detector. If the file is missing the YOLO phase is skipped with a warning (CPFs near signatures then rely on OCR only). |
| `YOLO_CROP_PADDING` | `50` | Pixels of context added around each detected signature before auditing the crop with the vision model. |

## Post-redaction verification

| Variable | Default | Description |
|---|---|---|
| `VERIFY_OCR` | `1` | `1` = OCR the final PDF pages without native text and cross-check the original; `0` disables the OCR part (not recommended: native-text check only). |
| `VERIFY_DPI` | `300` | DPI of the verification OCR. Higher is more sensitive but slower. |

## Output quality and data retention

Both are read in `utils/session.py` and `app_service.py`.

| Variable | Default | Description |
|---|---|---|
| `FINAL_IMAGE_WIDTH` | `1240` | Width (px) of pages in the final rasterized PDF. |
| `FINAL_JPEG_QUALITY` | `75` | JPEG quality (1-95; out-of-range values fall back to the default) of those pages. |
| `RETENTION_DAYS` | `0` (disabled) | At startup, delete tasks (and all their artifacts) older than N days; `0`/unset keeps everything. `POST /purge/{id}` removes the original page images of one task on demand. Always delete `output/` when you are done: it contains page images and OCR text with personal data. |

## Logging

| Variable | Default | Description |
|---|---|---|
| `DEBUG_LEVEL` | `INFO` | Python logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`). `DEBUG` can be verbose; never share logs from real documents. |

## Internal

`OMP_NUM_THREADS` and `MKL_NUM_THREADS` are set to `4` by `main.py` to bound CPU usage. `main.py` also accepts `--input` / `--output` on the command line.

## Docker

The image sets `APP_HOST=0.0.0.0`, `PRIVIO_TASKS_FILE=/app/state/tasks.json` and `YOLO_MODEL_PATH`; `docker-compose.yml` publishes the port on `127.0.0.1` only and sets `OLLAMA_API_URL` to the host. Do not copy a Windows `.env` (with `TESSERACT_PATH=C:\...`) into a container: remove such lines.

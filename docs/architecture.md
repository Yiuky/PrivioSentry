# Architecture

> **PRIVIO SENTRY** (Local AI Privacy Infrastructure) · current product: **SENTRY Redact**. This page describes what exists today. Internal module/class names (for example `SentryApp`) and some environment variables still carry the earlier working name "Tarjador"; they are being renamed separately.

## Process layout

```
Browser ─► gatekeeper.py (:8000, optional) ──proxy──► app_service.py (:8001, FastAPI)
              start/stop + watchdog                      │  POST /internal/update/{id}   (progress, shared secret)
                                                         └─ multiprocessing.Process per task ─► main.SentryApp
                                                                  ├─ utils/ocr_engine.py     (Tesseract, word-level "grounding map")
                                                                  ├─ utils/yolo_engine.py    (signature detector, Ultralytics)
                                                                  ├─ utils/ai_client.py      (Ollama /api/chat, vision + text)
                                                                  ├─ utils/address_redactor.py (address discovery + matching)
                                                                  ├─ utils/session.py       (folders, logging, PDF reconstruction/native redaction)
                                                                  └─ utils/verifier.py      (post-redaction verification)
```

* **`gatekeeper.py`** (optional): control panel on `:8000` that starts/stops `app_service.py` as a subprocess, runs a watchdog that restarts it after repeated failed health checks, remembers the desired state, and reverse-proxies other requests to the app. Shows `templates/gatekeeper.html` when the app is down.
* **`app_service.py`**: FastAPI API + HTML UI. State of tasks is kept in memory and persisted atomically to `tasks.json`. Each upload/reprocess/finalize starts a worker process; workers report progress to the service over HTTP with a per-run shared secret. A multiprocessing lock serializes LLM calls across workers. Concurrent operations on the same task return `409`.
* **`main.py`** (`SentryApp`): the pipeline, also usable as a CLI (`python main.py --input ... --output ...`).
* **Web editor** (`templates/index.html`): a self-contained HTML/JS page (DOM overlay boxes on top of the page images) to inspect, add, move, delete and approve redaction boxes. It is **local-first by construction**: no external fonts, scripts or icon libraries (the Markdown help is rendered by a small built-in renderer, not a CDN library) and the favicon/logo are inlined. It follows the PRIVIO SENTRY design tokens (`docs/brand/design-tokens.json`), keeps all UI strings in an `I18N` object (pt-BR default, en-US available) and states permanently that AI detection is probabilistic. The **LOCAL PROCESSING** badge describes the architecture (OCR/models run on the operator's machine); it does not technically enforce a network state.

## Pipeline phases (`SentryApp.run`)

| # | Phase | What happens |
|---|---|---|
| 0 | Render | PDF pages to PNG at `BASE_DPI`. |
| 1 | OCR | Tesseract with word coordinates (page in two overlapping halves; fallback to a lower scale when Tesseract fails). Standard PSM plus an optional sparse PSM pass. |
| 2 | CPF discovery | Digits are re-assembled across words/lines, dates/times excluded, 14-digit CNPJs spared, 11-digit windows validated with the CPF check digits; boxes are computed per character. |
| 3 | YOLO | Detects signatures; crops with padding. |
| 4 | Crop micro-audit | OCR (PSM 6) on each crop, mapping coordinates back to the page. |
| 5 | Address discovery | Vision LLM reads each page and returns addresses classified as personal/professional/secondary. If the AI call fails, the page is added to `failed_pages` and flagged for review (fail closed). |
| 6 | Address redaction | Only *personal* addresses: deterministic token matching against OCR words, with a list of "immune" words (street, district, ZIP labels...). |
| 7 | Signature audit | Draws current redactions on each signature crop and asks the vision LLM if a CPF is still visible; if yes or if the AI fails, the whole crop is redacted. |
| 8 | Export | Writes `redactions_metadata.json` (used by the editor) and the final PDF, either by **native redaction** of the original (`apply_redactions`, removes text and burns pixels) or by rasterized pages. Reconstruction fails closed (missing/errored page = no PDF). |
| 9 | Verification | See below. |

## Verification and states

`utils/verifier.py` (a) re-reads the final PDF (native text + OCR of pages with images/without text) and (b) **cross-checks coverage**: independent OCR of the *original* at `VERIFY_DPI` and checks that every valid CPF found lies inside some redaction box. Findings, AI failures and unverifiable pages become **alerts** per page.

Task states (free-form status text plus a progress percentage): `Iniciando...`/`Processando`/phase messages while running, `Concluído` (no pending alerts), **`Requer revisão`** (alerts exist: human review is mandatory), an error status, and `Interrompido` (the process died; set on startup for orphaned tasks).

## Folder layout of a task (`output/<name>/`)

`00_original_images/`, `01_ocr_results/`, `02_signature_crops/`, `04_*`, `05_final_export/{cpf_only,address_only,combined}`, `07_addresses_crops_ia/`, `08_*`, `99_ia_interactions/` (prompts/responses of the LLM), `process_log.log`. **All of it can contain personal data.** Final PDFs go to `documentos_finais/`.

## HTTP API (app_service)

`GET /` UI · `GET /readme` · `POST /upload` · `GET /tasks` · `POST /reprocess/{id}` · `GET /logs/{id}` · `POST /process-all` · `DELETE /delete-all` · `GET /previews/{id}/{page}` · `GET /metadata/{id}` · `POST /update-redactions/{id}` · `POST /reprocess-metadata/{id}` · `POST /finalize-native/{id}` · `POST /finalize/{id}` (legacy raster) · `GET /download/{id}` · `DELETE /task/{id}` · `POST /purge/{id}` (remove unredacted page images after approval) · `POST /internal/update/{id}` (workers only). Task ids are UUIDs and validated.

## Other directories

* `scripts/` helper launchers and manual experiments; `experimental/agent_loop/` an unfinished LLM-agent approach (not used by the pipeline).
* `models/` the sanitized detector and its model card; `examples/` synthetic sample generator.

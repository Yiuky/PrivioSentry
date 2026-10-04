<p align="center">
  <img src="assets/concept-mark.svg" alt="PRIVIO SENTRY logo (concept mark)" width="96" height="96">
</p>

# PRIVIO SENTRY

**Local AI Privacy Infrastructure** · current product: **SENTRY Redact**

> **Protect data before it is exposed.** &nbsp;·&nbsp; Detect. Review. Protect.

[Português (Brasil)](README.md) | **English**

> The Portuguese README is the primary one; this English version is kept in sync. Most technical documents under [docs/](docs/) are written in Portuguese (Brazil).

PRIVIO SENTRY is a local-first project for detecting and protecting personal, sensitive and confidential information in documents. Its first and only released capability, **SENTRY Redact**, is a pipeline that finds **CPF numbers** and **personal (residential) addresses** in PDF files and prepares redactions for a person to review. OCR, detection and the language/vision models run on your machine; the application does not send document content to third-party clouds.

> A **personal, independent** project by Joberth Firmino Gambati ([@Yiuky](https://github.com/Yiuky)): it is not an official product of any institution and does not speak for one.

> **Status: early stage.** SENTRY Redact is usable but young: it covers a narrow scope (CPF and personal addresses), has been measured only on synthetic data, and has no audit trail yet. Expect breaking changes.

> **Trademark:** the code is AGPL-3.0-or-later, but the names and logos are not covered by that license. See [TRADEMARKS.md](TRADEMARKS.md).

<p align="center">
  <img src="docs/img/editor.png" alt="SENTRY Redact editor with suggested redactions over the CPF and residential address of a fictional form" width="94%" />
</p>

## Principle

> **AI suggests. The policy constrains. The human confirms. The system records.**

* The models only **suggest** *potential* detections; every suggestion appears as an editable region that a person can accept, move, resize or remove.
* Automatic processing produces only a *preliminary* PDF with the AI suggestions; the version meant for use comes from the reviewer checking the boxes and clicking **Apply protection** in the editor. When the pipeline is unsure (an AI call failed, a CPF found in the original is not covered, a page could not be verified) it **fails closed**: the document is marked **"Requer revisão" (Needs review)** instead of "Concluído" (Completed), with per-page alerts.
* "The policy constrains" and "the system records" are the design direction: today the policy is fixed (CPF + personal addresses) and the only record is the task log. A configurable policy engine and an audit trail are **planned, not implemented** (see [Vision](#vision-future-not-implemented)).

## Read this first: it assists, it does not guarantee

**This tool does NOT guarantee complete anonymization.** AI detection is probabilistic. OCR errors, handwriting, poor scans, unusual layouts and model mistakes can leave personal data visible, and it can also redact more than necessary.

* Every output **must be reviewed by a person** before publication or sharing.
* "Concluído" means *no pending alert was detected by the automatic checks*, not that the document is guaranteed clean.
* Only **CPF** and **personal addresses** are targeted. Names, phone numbers, e-mails, RG, bank data, photos, QR codes, metadata, etc. are **not** redacted. See [docs/limitations.md](docs/limitations.md) and [docs/threat-model-lgpd.md](docs/threat-model-lgpd.md).
* Never use real documents to report bugs or in tests; see [SECURITY.md](SECURITY.md).

## LGPD positioning

PRIVIO SENTRY is a **technical control that can support privacy and security practices**, including those related to Brazil's data-protection law (**LGPD**, Lei 13.709/2018). It is **not** an "LGPD compliance" engine, it is not legal advice, and using it does not by itself make any document or process compliant: that depends on purpose, legal basis, necessity, governance, data lifecycle and roles. Local processing is an architectural choice, not a legal conclusion; actual guarantees depend on your deployment (network configuration, logging, temporary files, model behavior). The UI label **LOCAL PROCESSING** describes where processing happens; it does not claim the machine is offline.

The LGPD separates *personal data* from *sensitive personal data* (health, biometric, genetic...). Today only CPF numbers and residential addresses (personal data) are targeted. See [docs/brand/LGPD_PRODUCT_POSITIONING.md](docs/brand/LGPD_PRODUCT_POSITIONING.md) and the official sources: [LGPD](https://www.planalto.gov.br/ccivil_03/_ato2015-2018/2018/lei/l13709.htm), [ANPD](https://www.gov.br/anpd/pt-br).

## What SENTRY Redact does today

1. Renders each PDF page to an image and runs **Tesseract OCR** (with word coordinates).
2. Finds **CPFs** (validated with the check digits; CNPJs are spared; dates/times are excluded) using two OCR passes.
3. Detects **signatures** with a **YOLO** model, crops them and audits the crops (OCR + a **vision LLM** served by [Ollama](https://ollama.com)) for handwritten/hard-to-OCR CPFs.
4. Asks the vision LLM to discover **addresses** on each page and classify them (personal / professional / secondary); only *personal* addresses are redacted, via a deterministic match against the OCR words.
5. Produces a final PDF (native-text redaction of the original, or rasterized pages) plus a JSON of redaction boxes.
6. Runs a **post-redaction verification**: re-reads the output and cross-checks the *original* (OCR at higher DPI) to make sure every CPF found is covered by a redaction.
7. Optionally, a **local decision model** ([Laya](https://huggingface.co/convaiinnovations/laya), Apache-2.0, CPU-friendly) gives a calibrated second opinion on addresses and **learns from reviewer corrections**; a new profile only goes live after passing a quality gate, and it never removes a redaction. Off by default; see [docs/decisions.md](docs/decisions.md) (Portuguese).
8. Provides a **web editor** to add, move, delete and approve redactions before generating the final PDF.

## Requirements

* Python **3.10 – 3.12**
* **Tesseract OCR** 5.x with the Portuguese data (`por`)
* **Ollama** with a text/vision-capable model (any local VLM; e.g. `ollama pull qwen2.5vl:7b`)
* RAM/VRAM suitable for the model you choose (the default render DPI is high; reduce `BASE_DPI` on small machines)
* The YOLO signature detector `models/signature_stamp_detector.pt` (included, see [models/MODEL_CARD.md](models/MODEL_CARD.md))

## Installation

### Linux (Debian/Ubuntu)

```bash
sudo apt-get install -y tesseract-ocr tesseract-ocr-por tesseract-ocr-eng libgl1
git clone https://github.com/Yiuky/PrivioSentry.git && cd PrivioSentry
python3 -m venv venv && . venv/bin/activate
pip install --extra-index-url https://download.pytorch.org/whl/cpu torch torchvision   # CPU-only PyTorch (optional, smaller)
pip install -r requirements.txt
cp .env.example .env     # then edit
```

### Windows

1. Install Tesseract (e.g. the UB-Mannheim build) and tick the **Portuguese** language data. Note the path of `tesseract.exe`.
2. Install Python 3.10–3.12 and Ollama.
3. In PowerShell:

```powershell
git clone https://github.com/Yiuky/PrivioSentry.git; cd PrivioSentry
python -m venv venv; .\venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env   # set TESSERACT_PATH=C:\Program Files\Tesseract-OCR\tesseract.exe
```

### Ollama models

```bash
ollama serve                       # if it is not already running
ollama pull <your-vision-model>    # e.g. qwen2.5vl:7b
```

Set `OLLAMA_MODEL` and `OLLAMA_VISION_MODEL` in `.env` to the model name(s). For a custom GGUF see [scripts/ollama/Modelfile.example](scripts/ollama/Modelfile.example).

### Docker (optional)

```bash
docker compose up --build        # app on http://127.0.0.1:8001 ; Ollama must run on the host
```

See the licensing caveat about distributing images in [docs/licensing.md](docs/licensing.md).

## Configuration

Copy `.env.example` to `.env`. All variables are documented in [docs/configuration.md](docs/configuration.md). The most relevant ones: `TESSERACT_PATH`, `OLLAMA_API_URL`, `OLLAMA_MODEL`, `OLLAMA_VISION_MODEL`, `YOLO_MODEL_PATH`, `BASE_DPI`, `APP_HOST`, `API_TOKEN`, `VERIFY_OCR`.

## Usage

### Web app (with editor)

```bash
python app_service.py          # http://127.0.0.1:8001   (or scripts/run_app.sh | scripts/run_app.bat)
# optional on/off control panel + reverse proxy on :8000:
python gatekeeper.py           # http://127.0.0.1:8000/gatekeeper
```

Upload PDFs, wait for processing, then open the editor: pages flagged for review are highlighted. Adjust the boxes and click **Apply protection (native mode)**. The interface is in Portuguese (pt-BR) by default with an English (en-US) selector, works without internet access to external assets, and supports `N`/`P` (next/previous page) and `Esc` shortcuts. The server listens on `127.0.0.1` by default; to expose it on a network set `APP_HOST=0.0.0.0` **and** `API_TOKEN`, and put it behind HTTPS.

### Command line (batch)

```bash
python main.py --input path/to/file_or_folder --output path/to/results
```

Exit codes: `0` all documents completed, `3` at least one document **needs review**, `1` error. Try it with the synthetic sample:

```bash
python examples/make_sample_pdf.py            # writes examples/sample_input.pdf (fictional data)
python main.py --input examples/sample_input.pdf --output out
```

## Architecture (short)

```
Browser ─► gatekeeper.py (:8000, optional) ─proxy─► app_service.py (:8001, FastAPI)
                                                       └─ one worker process per task ─► main.py (SentryApp)
                                                              OCR (Tesseract) · YOLO · Ollama LLM · verifier
```

Details: [docs/architecture.md](docs/architecture.md).

## Vision (future, not implemented)

The long-term direction is a local privacy-processing layer for documents, APIs, AI systems and workflows. **Only SENTRY Redact exists today.** The modules below are a roadmap to guide design, with no committed dates and no promise that they will ship:

| Module (vision) | Intended role |
|---|---|
| SENTRY Detect | Detect and classify candidate sensitive information (taxonomy: personal data, sensitive personal data, secrets, financial, custom) |
| SENTRY Mask / Transform | Replacement/masking and pseudonymization as explicit, policy-controlled operations |
| SENTRY Gateway | Privacy boundary for traffic to external AI/APIs |
| SENTRY Audit | Evidence (hashes, model/policy provenance) without storing raw sensitive values |

Brand, design and UX guidelines live in [docs/brand/](docs/brand/) (including the product notice).

## Limitations

* Only CPF and personal addresses; no names, phones, e-mails, faces, etc.
* Recall of the detection and of the verification was only measured on synthetic data (see [docs/benchmarks.md](docs/benchmarks.md) when available); real-world scans can be worse.
* Handwriting and low-quality scans are the weakest point. The signature detector has modest accuracy (see model card).
* Address redaction depends on an LLM classification and on fuzzy matching: it can over- or under-redact.
* Processing a large PDF is slow (high DPI OCR + LLM calls + verification).

Full list: [docs/limitations.md](docs/limitations.md).

## Privacy & security

Processing is local. Artifacts of every task (page images, OCR output, crops) are stored under `output/` and contain **personal data**; delete them when no longer needed (see retention options in [docs/configuration.md](docs/configuration.md)). Report vulnerabilities privately: [SECURITY.md](SECURITY.md).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) and the [Code of Conduct](CODE_OF_CONDUCT.md). Run `pytest` and `ruff check .` before opening a PR. **Never commit real personal data.**

## Support the project

PRIVIO SENTRY is free and open source, built in spare time. If it saved you time, you can buy the developer a
coffee via Pix (Brazil): see [the donation section of the Portuguese README](README.md#-doe-um-café-para-o-dev).

## License

Source code: [GNU AGPL-3.0-or-later](LICENSE). If you distribute a modified version, or offer one to users over a network, you must provide its source under the same license. Dependencies and the YOLO weights are covered in [NOTICE](NOTICE) and [docs/licensing.md](docs/licensing.md).

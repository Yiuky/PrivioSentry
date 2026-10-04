# Limitations

Be explicit about what this tool cannot do. Always combine it with human review. PRIVIO SENTRY / SENTRY Redact is in an **early stage**: the AI **suggests**, a person **confirms**.

## Scope of redaction
* **Only CPF numbers and personal (residential) addresses** are targeted. Not redacted: names, RG and other IDs, phone numbers, e-mails, bank/financial data, license plates, photographs/faces, QR codes/barcodes, signatures themselves (only CPFs near them), dates of birth, PDF metadata/attachments/annotations/bookmarks (inspect these separately).
* Names of people are deliberately **not** redacted (a business rule of the original use case), which can make an individual identifiable even without CPF/address.

## Detection quality
* **OCR dependent:** low resolution, skew, stains, stamps over text, columns, and handwriting reduce recall. A single misread digit can make a CPF fail its check digits and escape detection; the verifier mitigates (but does not eliminate) this by re-OCRing the original at a different DPI and flagging inconsistencies.
* **Handwriting / signatures:** the YOLO detector is small (single class, modest metrics, see [models/MODEL_CARD.md](../models/MODEL_CARD.md)); CPFs written by hand rely on the vision LLM, whose quality depends on the model you run.
* **Addresses:** discovery and personal/professional classification are done by an LLM, then matched to OCR words by token. It can **under-redact** (address missed or misclassified as professional) and **over-redact** (tokens that also occur elsewhere on the page).
* **LLM nondeterminism:** results can vary between runs and models. Failures/timeouts are flagged for review, but a confidently wrong answer is not detectable.
* Measured recall/precision exist only for **synthetic** documents (see `docs/benchmarks.md` when present). Real-world accuracy is unknown and likely lower.
* Only Portuguese (Brazilian) documents/formats were considered (CPF/CNPJ rules, address vocabulary).

## Performance
* High-DPI OCR, LLM calls and the verification pass make large PDFs slow (hundreds of pages can take hours); memory use grows with `BASE_DPI`.
* One worker process per task; LLM calls are serialized by a lock, so concurrency gains are limited.

## Output
* **Native mode** edits the original PDF in place of rasterizing; hidden layers, embedded files, form fields or annotations may still carry data.
* **Raster mode** reduces resolution (default ~150 DPI-equivalent width 1240 px) and removes selectable text.
* The final PDF is as good as the boxes: manual review in the editor is part of the workflow, not an optional extra.

## Platform / operations
* The **LOCAL PROCESSING** label in the UI describes the architecture, not an enforced network state: the application does not block outbound traffic, and `OLLAMA_API_URL` can point to a remote server. The UI never claims "no network access".
* Not a legal-compliance tool: it can support privacy and security practices, including LGPD-aligned ones, but it does not by itself establish compliance (see [threat-model-lgpd.md](threat-model-lgpd.md)).
* No built-in user accounts, TLS or audit trail; protection relies on loopback binding, an optional shared `API_TOKEN` and the host's security.
* Intermediate artifacts keep personal data until deleted.
* Primarily developed and tested on Windows; Linux support is exercised by CI (Tesseract installed via apt) but less field-tested.
* Licensing caveats of the AGPL dependencies: [licensing.md](licensing.md).

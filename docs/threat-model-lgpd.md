# Threat model and LGPD notes

> Engineering notes, not legal advice. Consult your data-protection officer (DPO/encarregado) and legal counsel.
>
> **Positioning.** PRIVIO SENTRY is a technical control that can *support* privacy and security practices, including LGPD-aligned ones. It does not make a document "LGPD compliant": compliance depends on purpose, legal basis, necessity, governance, data lifecycle and roles. Principle: **AI suggests. The policy constrains. The human confirms. The system records.** (The audit record is not implemented yet; see the vision in [brand/LGPD_PRODUCT_POSITIONING.md](brand/LGPD_PRODUCT_POSITIONING.md) and [brand/SECURITY_AND_PRIVACY.md](brand/SECURITY_AND_PRIVACY.md).)

## Purpose and assets
The tool helps remove **personal data (CPF, residential addresses)** from PDFs before they are published or shared, in the context of Brazil's **LGPD** (Lei 13.709/2018). Assets to protect:

1. The **original documents** (contain personal data).
2. **Intermediate artifacts** (`output/`, `WEB_INPUT/`, logs, `99_ia_interactions/`): page images, OCR text, crops, LLM prompts/responses.
3. The **redacted output** (must not leak what was meant to be removed).

## Design choices that reduce risk
* **Local processing:** OCR, detection and LLMs run on the operator's machine (Tesseract, Ultralytics, Ollama). No document content is sent to third-party APIs. (Ollama itself must be pointed at a local/trusted server: `OLLAMA_API_URL`.)
* **Fail closed + human in the loop:** uncertain results make the document **"Requer revisão"**; the editor lets a person adjust every box before generating the final PDF.
* **Independent verification:** the final PDF is re-read and CPFs found in the original are checked against the redaction boxes.
* **Hardened service:** loopback bind by default, optional token, upload validation (PDF magic bytes, size limit), UUID-validated routes, HTML escaping in the UI.

## Threats and residual risks

| Threat | Mitigation | Residual risk |
|---|---|---|
| Personal data left visible (OCR/LLM miss) | dual OCR passes, YOLO + vision audit, verification, mandatory review | **Real**; recall is not 100%. Review is the control. |
| Over-redaction hides needed information | editor, manual review | Operational cost |
| Data remains in PDF structure (hidden text, metadata, attachments) | native redaction removes text under boxes; raster mode flattens | Metadata/attachments/annotations are **not** cleaned: inspect separately |
| Leakage through artifacts/logs | files stay local; logs avoid full CPFs (improvements in progress: see CHANGELOG) | `output/` contains page images of the originals: delete after use; disk encryption recommended |
| Unauthorized access to the web UI | loopback default; `API_TOKEN`; no multi-user model | If exposed on a network without HTTPS + token, anyone can read documents |
| Malicious PDF/upload (parser exploits, path traversal, huge files) | sanitized names, magic-bytes check, size limit, run unprivileged (Docker user) | PDF/OCR parsers are large attack surfaces: keep dependencies updated, isolate the host |
| Prompt injection via document text into the vision LLM | LLM output is only used to *add* redactions (JSON of addresses); failures fail closed | A document could try to suppress detection (e.g. "ignore addresses"): human review required |
| Model/weights leakage of training data | weights are sanitized (no paths/metadata); detector is a small single-class model | Cannot be mathematically excluded (see model card) |
| Supply chain | pinned requirements, Dependabot, CI | Standard supply-chain risk |

## LGPD considerations (non-exhaustive)
* Redaction/anonymization under LGPD (art. 12) requires that data **cannot be re-identified by reasonable means**; a visual blackout with remaining names, context or metadata may still allow re-identification. Evaluate this case by case.
* The LGPD distinguishes *personal data* from *sensitive personal data* (health, biometric, genetic, etc.). This tool currently targets only CPF numbers and residential addresses (personal data); it does not detect sensitive categories.
* Keep a **retention policy** for artifacts (delete `output/`; see `RETENTION_DAYS` in [configuration.md](configuration.md)).
* The operator remains the **controller/operator** of the data and is responsible for the legal basis, records of processing and incident handling. This project provides no warranty (see LICENSE, section 7).

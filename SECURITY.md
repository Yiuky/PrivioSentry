# Security Policy / Política de Segurança

## Reporting a vulnerability / Como relatar

**Please do not open a public issue** for security problems.

* Use GitHub's private vulnerability reporting: <https://github.com/Yiuky/privio-sentry/security/advisories/new>.
* If that is unavailable, open a public issue that says only "security contact request" (no details) and a maintainer will arrange a private channel.

Include: affected version/commit, steps to reproduce, impact, and a proposed fix if you have one. **Do not attach real documents or real personal data**; use fictional/synthetic samples. We aim to acknowledge reports within 7 days and to publish a fix or mitigation within 90 days. We will credit reporters who wish it.

*PT-BR:* não abra issue pública. Use o relato privado de vulnerabilidades do GitHub (<https://github.com/Yiuky/privio-sentry/security/advisories/new>). Se indisponível, abra uma issue pública dizendo apenas "pedido de contato de segurança" (sem detalhes). Não anexe documentos nem dados pessoais reais.

## Scope / Escopo

In scope:
* The web service (`app_service.py`, `gatekeeper.py`, `templates/`): authentication bypass, path traversal, file-upload handling, XSS, SSRF, request forgery, unsafe defaults.
* The pipeline when it **leaks data it was supposed to redact** in a way attributable to a bug (for example a CPF reported as covered but still present in the output file, hidden text/metadata that survives redaction, or PII written to logs).
* Supply chain issues in this repository (CI, Docker, dependencies).

Out of scope:
* The general limits of OCR/LLM accuracy described in [docs/limitations.md](docs/limitations.md) (a missed CPF on a poor scan is a quality issue: open a normal issue with a *synthetic* reproduction).
* Vulnerabilities in third-party software (Tesseract, Ollama, PyMuPDF, Ultralytics...): report them upstream.
* Attacks that require an already-compromised host or administrator access.

## Data warning / Aviso sobre dados

* This tool **does not guarantee anonymization**. Always review the output; see [README.md](README.md) and [docs/threat-model-lgpd.md](docs/threat-model-lgpd.md).
* Intermediate artifacts (`output/`, `WEB_INPUT/`, `documentos_finais/`) contain **personal data** (page images, OCR text, crops). Protect them with disk encryption and file permissions, and delete them when not needed.
* By default the service listens only on `127.0.0.1`. If you expose it, set `API_TOKEN` and use HTTPS (a reverse proxy); there is no built-in TLS or multi-user access control.
* If you ever committed a real document, `.env` or credentials, treat them as leaked: rotate secrets and rewrite history before publishing.

## Supported versions

Only the latest release/`main` receives security fixes.

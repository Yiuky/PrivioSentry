# Contributing / Contribuindo

Thank you for helping! / Obrigado por contribuir!

## Golden rules / Regras de ouro

1. **No real personal data. Ever.** No real CPFs, names, addresses, PDFs, screenshots or logs from real processes in code, tests, fixtures, issues or PRs. Use the synthetic generator (`python examples/make_sample_pdf.py`) or fictional values. The pre-publication audit (`python scripts/audit_public_tree.py`) must pass.
2. **Fail closed.** When in doubt the pipeline must flag the document for human review rather than report success. Any change that could cause *under-redaction* needs a test that proves it does not.
3. **Local-first.** Do not add network calls that send document content outside the user's machine.
4. Do not weaken the review/verification steps or the wording that tells users the tool does not guarantee anonymization.

*PT-BR:* nunca inclua dados pessoais reais; a pipeline deve falhar fechado; tudo roda localmente; não enfraqueça a verificação nem o aviso de que a ferramenta não garante anonimização.

## UI copy and brand rules

The interface and docs follow [docs/brand/](docs/brand/) (brand, design and UX guidelines). In short:

* **Never** claim "LGPD compliant", "100% secure", "guaranteed" or "no network access". Use "LGPD-aligned protection policy", "potential", "detected", "suggested", "review", "Protection complete", "Processed locally". The UI label is exactly `LOCAL PROCESSING`.
* The AI **suggests** and the human **confirms**; keep the permanent notice that AI detection is probabilistic.
* The UI must stay **local-first**: no CDN scripts, fonts or images, no external requests (`tests/ui/test_ui_brand.py` enforces this and the copy rules). User-facing strings live in the `I18N` object in `templates/index.html` (keys as in `docs/brand/UX_SPEC.md`).
* Use the design tokens (CSS custom properties in `:root`); keep text contrast at WCAG AA (4.5:1) and a visible focus state.
* The name and logos are not covered by the AGPL-3.0 license ([TRADEMARKS.md](TRADEMARKS.md)).

## Development setup

```bash
git clone https://github.com/Yiuky/privio-sentry.git && cd privio-sentry
python -m venv venv && . venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements-dev.txt
cp .env.example .env
# Tesseract with Portuguese data is needed by some tests: apt install tesseract-ocr tesseract-ocr-por
```

## Running checks

```bash
ruff check .                              # lint
pytest --ignore=tests/ui                  # unit / integration tests
pytest --ignore=tests/ui --cov=utils --cov=app_service --cov=gatekeeper --cov=main
playwright install chromium               # once
pytest tests/ui                           # browser (UI) tests
```

Tests must not need Ollama or a GPU: use fakes/stubs for the LLM and YOLO.

## Pull requests

* One focused change per PR, with tests. Explain the *why*.
* Update docs (`README*`, `docs/`, `.env.example`, `CHANGELOG.md`) when behavior or configuration changes.
* New dependencies need a justification and a license check (see [docs/licensing.md](docs/licensing.md); avoid adding more AGPL/GPL components).
* By contributing you agree that your contribution is licensed under the project license (see `LICENSE`). Sign off commits (`git commit -s`) to certify the [Developer Certificate of Origin](https://developercertificate.org/).
* Be kind: see the [Code of Conduct](CODE_OF_CONDUCT.md).

## Reporting issues

Use the issue templates. For security problems or leaks of real data, **do not open a public issue**: follow [SECURITY.md](SECURITY.md).

# Changelog

All notable changes are documented here. Format based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow [SemVer](https://semver.org/).

## [Unreleased]

### Added
- **PRIVIO SENTRY brand identity** (Local AI Privacy Infrastructure; product SENTRY Redact): `assets/` (concept mark, favicon, reference images), `docs/brand/` (brand, design, UX, security/privacy and LGPD-positioning guidelines, design tokens, brand board) and `TRADEMARKS.md` (name/logos are not covered by the AGPL-3.0 license; trademark prior-art search pending).
- Web UI re-skinned with the design tokens: PRIVIO SENTRY header and logo, `LOCAL PROCESSING` badge, permanent "AI suggests; you confirm" notice, copy rules (potential/suggested/review; "Protection complete - Processed locally"), pt-BR/en-US `I18N` with a language selector, `N`/`P`/`Esc` shortcuts, visible focus, keyboard-operable task cards.
- UI tests for identity, forbidden claims, no external requests, contrast (WCAG AA) and focus.
- Open-source preparation: AGPL-3.0-or-later `LICENSE`, `NOTICE`, bilingual README, `CONTRIBUTING`, `CODE_OF_CONDUCT`, `SECURITY`, `docs/`.
- `pyproject.toml`, `requirements*.txt`, `Dockerfile`, `docker-compose.yml`, GitHub Actions CI, issue/PR templates, Dependabot.
- Sanitized YOLO signature detector at `models/signature_stamp_detector.pt` with a model card.
- Synthetic example generator `examples/make_sample_pdf.py`.
- `scripts/audit_public_tree.py` (PII/secret audit before publishing) and Linux/macOS launch scripts.

### Changed
- Project name set to **PRIVIO SENTRY** (`privio-sentry`); `PROJECT_NAME` placeholders replaced. Repository owner set to `Yiuky`; contact channels use GitHub (no e-mail published).
- UI is now local-first: removed Google Fonts, `marked` (jsDelivr) and `lucide` (unpkg) CDN loads; the Markdown help uses a small built-in renderer that never injects file text as HTML; favicon/logo are inlined.
- README no longer says the tool helps "comply" with the LGPD; it states the LGPD-aligned positioning and the early-stage status.
- Helper scripts moved to `scripts/`; the experimental agent loop moved to `experimental/agent_loop/`; removed hard-coded user paths.
- README rewritten without over-promising: the tool assists but does not guarantee anonymization.

## [5.0.0]

### Added
- Fail-closed pipeline: new **"Requer revisão"** (needs review) state with per-page alerts.
- Post-redaction verification (`utils/verifier.py`): re-reads the output and cross-checks the original at 300 DPI.
- Security hardening of the web service: upload validation, size limit, UUID-validated routes, optional `API_TOKEN`, loopback bind by default, internal endpoint secret.
- Atomic `tasks.json` persistence, 409 on concurrent operations, shared cross-process AI lock.
- Automated tests (pytest).

### Fixed
- Task list XSS (HTML escaping of file names/status/alerts).
- Missing `/readme` and `/finalize/{id}` routes.

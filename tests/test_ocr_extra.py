# SPDX-License-Identifier: AGPL-3.0-or-later
"""Leitura extra de OCR (opcional): soma às do Tesseract, nunca substitui; falha = revisão. Sem motor real (I-08)."""
import pytest

from sentry_testkit import CPF_A, CPF_A_FMT, make_text_pdf, word
from utils import ocr_extra


def test_disabled_by_default(monkeypatch):
    monkeypatch.delenv("OCR_EXTRA_ENGINE", raising=False)
    assert not ocr_extra.enabled() and not ocr_extra.available()


def test_lines_are_split_into_words_with_proportional_boxes():
    words = ocr_extra.lines_to_words([([[100, 10], [400, 10], [400, 40], [100, 40]], "CPF 123.456")])
    assert [w["text"] for w in words] == ["CPF", "123.456"]
    assert words[0]["box"]["x"] == 100 and words[1]["box"]["x"] > words[0]["box"]["x"] + words[0]["box"]["w"]
    assert words[1]["box"]["x"] + words[1]["box"]["w"] <= 401


@pytest.fixture()
def app(tmp_path, monkeypatch):
    from main import SentryApp
    monkeypatch.setenv("BASE_DPI", "40")
    a = SentryApp(make_text_pdf(tmp_path / "doc.pdf", n_pages=2))
    a.run_phase_0()
    yield a
    a.session.close()


def _no_tesseract(monkeypatch, app):
    monkeypatch.setattr(app, "_ocr_page", lambda path: ("", [word(0, "nada", 10)], [], False))


def test_cpf_seen_only_by_the_extra_reading_is_redacted(app, monkeypatch):
    monkeypatch.setenv("OCR_EXTRA_ENGINE", "rapidocr")
    _no_tesseract(monkeypatch, app)
    monkeypatch.setattr(ocr_extra, "read", lambda path: [word(0, "CPF", 10), word(1, CPF_A_FMT, 120)])
    app.run_phase_1()
    app.run_phase_2()
    assert app.known_cpfs == [CPF_A]
    assert app.cpf_redactions[1] and app.cpf_redactions[2]


def test_extra_reading_failure_sends_page_to_review(app, monkeypatch):
    monkeypatch.setenv("OCR_EXTRA_ENGINE", "rapidocr")
    _no_tesseract(monkeypatch, app)

    def boom(path):
        raise RuntimeError("modelo ausente")
    monkeypatch.setattr(ocr_extra, "read", boom)
    app.run_phase_1()
    assert app.needs_review and all(any("Leitura extra" in r for r in app.review_pages[p]) for p in (1, 2))


def test_extra_reading_off_never_calls_the_engine(app, monkeypatch):
    monkeypatch.delenv("OCR_EXTRA_ENGINE", raising=False)
    _no_tesseract(monkeypatch, app)

    def boom(path):
        raise AssertionError("não deveria rodar")
    monkeypatch.setattr(ocr_extra, "read", boom)
    app.run_phase_1()
    assert app.grounding_maps_extra == []

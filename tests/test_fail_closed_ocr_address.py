# SPDX-License-Identifier: AGPL-3.0-or-later
"""Falha fechado: OCR que falha (B-43), tipos de endereço do LLM (B-49) e alertas que exigem revisão (B-61)."""
import os

import fitz
import pytest
import pytesseract
from PIL import Image

from main import SentryApp
from sentry_testkit import CPF_A_FMT, make_text_pdf, word
from utils.address_redactor import classify_address_type
from utils.ocr_engine import OCREngine


@pytest.fixture()
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("BASE_DPI", "50")
    a = SentryApp(make_text_pdf(tmp_path / "doc.pdf", n_pages=2))
    yield a
    a.session.close()


def _tesseract_broken(*args, **kwargs):
    raise pytesseract.TesseractNotFoundError()


# --- B-43: OCR que falha não pode virar "página sem CPF" --------------------------------------------
def test_ocr_engine_counts_critical_failures(tmp_path, monkeypatch):
    monkeypatch.setattr(pytesseract, "image_to_data", _tesseract_broken)
    img = tmp_path / "p.png"
    Image.new("RGB", (60, 80), "white").save(img)
    engine = OCREngine(tesseract_path=None)
    text, grounding = engine.get_grounding_map(str(img))
    assert grounding == [] and engine.failure_count == 2  # as duas metades falharam nas duas escalas


def test_ocr_merge_keeps_bottom_half_when_top_half_fails(tmp_path, monkeypatch):
    img = tmp_path / "p.png"
    Image.new("RGB", (60, 100), "white").save(img)
    calls = {"n": 0}
    keys = ("level", "page_num", "block_num", "par_num", "line_num", "word_num",
            "left", "top", "width", "height", "conf", "text")

    def fake_data(img_input, **kw):
        calls["n"] += 1
        if calls["n"] <= 2:  # metade de cima: falha a 100% e a 50%
            raise RuntimeError("crash")
        row = dict(zip(keys, (5, 1, 1, 1, 1, 1, 3, 4, 20, 10, 90, CPF_A_FMT)))
        return {k: [v] for k, v in row.items()}

    monkeypatch.setattr(pytesseract, "image_to_data", fake_data)
    engine = OCREngine(tesseract_path=None)
    data = engine.get_full_ocr_data(str(img))
    assert engine.failure_count == 1
    assert data["text"] == [CPF_A_FMT] and data["top"] == [4 + (100 - 55)]


class FlakyOCR(OCREngine):
    """Falha (resultado vazio + contador) nas páginas/arquivos indicados."""

    def __init__(self, fail_when):
        super().__init__(tesseract_path=None)
        self.fail_when = fail_when

    def get_grounding_map(self, img_path, psm=3):
        if self.fail_when(os.path.basename(img_path)):
            self.failure_count += 1
            return "", []
        return "[0] CPF: [1] " + CPF_A_FMT, [word(0, "CPF:", 0), word(1, CPF_A_FMT, 200, w=280)]


def test_phase1_flags_pages_where_ocr_failed(app):
    app.run_phase_0()
    app.ocr = FlakyOCR(lambda name: name.endswith("_page_2.png"))
    app.run_phase_1()
    assert set(app.review_pages) == {2}
    assert "OCR" in app.review_pages[2][0]
    assert app.final_state()["status"] == "Requer revisão"


def test_phase4_flags_crop_where_ocr_failed(app):
    app.ocr = FlakyOCR(lambda name: name == "crop.png")
    app.all_crops_metadata = [{"path": "crop.png", "page_num": 1, "origin_bbox": (0, 0, 10, 10)}]
    app.run_phase_4()
    assert "recorte" in app.review_pages[1][0]


def test_verifier_marks_page_unverified_when_ocr_fails(tmp_path):
    from utils.verifier import find_uncovered_cpfs, verify_pdf
    # página "digitalizada": só uma imagem, sem texto nativo -> só o OCR pode verificá-la
    img = tmp_path / "scan.png"
    Image.new("RGB", (100, 140), "white").save(img)
    pdf = str(tmp_path / "scan.pdf")
    with fitz.open() as doc:
        doc.new_page().insert_image(fitz.Rect(0, 0, 300, 400), filename=str(img))
        doc.save(pdf)
    broken = FlakyOCR(lambda name: True)
    leftovers, unverified = verify_pdf(pdf, ocr_engine=broken, use_ocr=True, dpi=40)
    assert leftovers == {} and unverified == [1]
    uncovered, failed = find_uncovered_cpfs(pdf, {}, broken, dpi=40)
    assert uncovered == {} and failed == [1]


# --- B-49: tipo de endereço normalizado --------------------------------------------------------------
@pytest.mark.parametrize("label, expected", [
    ("pessoal", "pessoal"), ("Pessoal", "pessoal"), (" pessoal ", "pessoal"), ("PESSOAL", "pessoal"),
    ("residencial", "pessoal"), ("Residência", "pessoal"), ("domicílio", "pessoal"),
    ("profissional", "nao_pessoal"), ("Comercial", "nao_pessoal"), ("secundário", "nao_pessoal"),
    ("", "desconhecido"), (None, "desconhecido"), ("rural?", "desconhecido"),
])
def test_classify_address_type(label, expected):
    assert classify_address_type(label) == expected


def _redactor(tmp_path, monkeypatch, response):
    app = SentryApp(make_text_pdf(tmp_path / "a.pdf"))
    img = tmp_path / "x.png"
    img.write_bytes(b"")
    monkeypatch.setattr(app.address_redactor.ai, "analyze_image", lambda path, prompt: (response, None, {}))
    app.image_paths = [str(img)]
    return app


def test_capitalized_and_synonym_personal_types_are_redacted(tmp_path, monkeypatch):
    app = _redactor(tmp_path, monkeypatch, {"addresses": [
        {"text": "Rua A 1", "type": "Pessoal"}, {"text": "Rua B 2", "type": "residencial "},
        {"text": "Av C 3", "type": "Profissional"}]})
    app.run_address_discovery()
    types = [a["type"] for a in app.address_redactor.results[1]]
    assert types == ["pessoal", "pessoal", "profissional"]
    assert not app.needs_review  # rótulos reconhecidos: sem revisão extra
    app.session.close()


def test_unknown_type_is_redacted_as_personal_and_flagged(tmp_path, monkeypatch):
    app = _redactor(tmp_path, monkeypatch, {"addresses": [{"text": "Sitio X", "type": "rural"}, "lixo"]})
    app.run_address_discovery()
    assert app.address_redactor.results[1][0]["type"] == "pessoal"
    assert app.needs_review and "não reconhecido" in app.review_pages[1][0]
    assert "fora do formato" in app.review_pages[1][0]
    app.session.close()


def test_response_without_address_list_fails_closed(tmp_path, monkeypatch):
    app = _redactor(tmp_path, monkeypatch, {"enderecos": []})
    app.run_address_discovery()
    assert 1 in app.address_redactor.failed_pages and app.needs_review
    app.session.close()


def test_refine_uses_normalized_type(app):
    redactor = app.address_redactor
    addresses = redactor._normalize_types(1, [{"text": "Rua Flores 10", "type": "Pessoal"}])
    cmap = [{"id": 0, "text": "Rua"}, {"id": 1, "text": "Flores"}, {"id": 2, "text": "10"}]
    assert redactor.refine_redaction_with_text_ai(1, "", addresses, cmap)


# --- B-61: alertas que antes não pediam revisão -------------------------------------------------------
def test_document_level_alert_requires_review(app):
    app.add_document_review("Modelo YOLO ausente: teste")
    assert app.needs_review and app.final_state()["status"] == "Requer revisão"
    assert "Modelo YOLO ausente: teste" in app.alerts

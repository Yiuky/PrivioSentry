# SPDX-License-Identifier: AGPL-3.0-or-later
"""Regiões a revisar: a verificação diz ONDE está o problema (caixas relativas 0..1), não só a página."""
import shutil

import fitz
import pytest
from PIL import Image

from main import SentryApp
from sentry_testkit import CPF_A_FMT, make_text_pdf, word
from utils.ocr_engine import OCREngine
from utils.verifier import find_uncovered_cpfs, verify_pdf


class FixedOCR(OCREngine):
    """OCR falso: sempre 'lê' um CPF numa posição conhecida da imagem recebida (em pixels)."""

    def __init__(self, rel_box):
        super().__init__(tesseract_path=None)
        self.rel_box = rel_box

    def get_grounding_map(self, img_path, psm=3):
        w, h = Image.open(img_path).size
        x0, y0, x1, y1 = self.rel_box
        return "[0] " + CPF_A_FMT, [word(0, CPF_A_FMT, x0 * w, y=y0 * h, w=(x1 - x0) * w, h=(y1 - y0) * h)]


def _scanned_pdf(tmp_path):
    img = tmp_path / "scan.png"
    Image.new("RGB", (200, 280), "white").save(img)
    pdf = str(tmp_path / "scan.pdf")
    with fitz.open() as doc:
        doc.new_page().insert_image(fitz.Rect(0, 0, 595, 842), filename=str(img))
        doc.save(pdf)
    return pdf


def test_verify_pdf_reports_relative_location_of_leftover_cpf(tmp_path):
    locations = {}
    leftovers, unverified = verify_pdf(_scanned_pdf(tmp_path), ocr_engine=FixedOCR([0.5, 0.25, 0.75, 0.3]),
                                       dpi=72, locations=locations)
    assert leftovers and not unverified
    (box,) = locations[1]
    assert box == pytest.approx([0.5, 0.25, 0.75, 0.3], abs=0.01)


def test_verify_pdf_native_text_location(tmp_path):
    pdf = str(tmp_path / "texto.pdf")
    with fitz.open() as doc:
        doc.new_page(width=600, height=800).insert_text((300, 200), f"CPF {CPF_A_FMT}")
        doc.save(pdf)
    locations = {}
    leftovers, _ = verify_pdf(pdf, use_ocr=False, locations=locations)
    assert leftovers[1] and 0.5 <= locations[1][0][0] <= 0.65 and 0.22 < locations[1][0][1] < 0.26


def test_uncovered_cpf_location(tmp_path):
    locations = {}
    uncovered, failed = find_uncovered_cpfs(_scanned_pdf(tmp_path), {}, FixedOCR([0.1, 0.8, 0.3, 0.83]), dpi=72,
                                            locations=locations)
    assert uncovered and not failed
    assert locations[1][0] == pytest.approx([0.1, 0.8, 0.3, 0.83], abs=0.01)


@pytest.fixture()
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("BASE_DPI", "50")
    a = SentryApp(make_text_pdf(tmp_path / "doc.pdf", n_pages=2))
    yield a
    a.session.close()


def test_review_marks_travel_with_the_final_state(app):
    app.add_review(2, f"CPF {CPF_A_FMT} ainda visível", [[0.1, 0.2, 0.3, 0.25]])
    app.add_review(2, f"CPF {CPF_A_FMT} ainda visível", [[0.1, 0.2, 0.3, 0.25]])  # sem duplicar
    app.add_review(1, "página sem posição")                                  # alerta só de página
    state = app.final_state()
    assert state["status"] == "Requer revisão"
    assert state["review_marks"] == [{"page": 2, "reason": app.review_marks[0]["reason"], "box": [0.1, 0.2, 0.3, 0.25]}]
    assert CPF_A_FMT not in app.review_marks[0]["reason"]                   # motivo mascarado


def test_verification_attaches_locations_to_alerts(app, monkeypatch, tmp_path):
    app.run_phase_0()
    app.ocr = FixedOCR([0.5, 0.25, 0.75, 0.3])
    monkeypatch.setenv("VERIFY_DPI", "40")
    final = f"{app.session.doc_finais_dir}/{app.session.filename}_TARJADO_FINAL.pdf"
    shutil.copy(_scanned_pdf(tmp_path), final)  # "PDF final" digitalizado com um CPF ainda legível
    app.run_verification()
    pages = {m["page"] for m in app.review_marks}
    assert 1 in pages and all(len(m["box"]) == 4 for m in app.review_marks)


def test_reprocess_clears_review_marks(monkeypatch):
    import importlib
    import app_service
    importlib.reload(app_service)
    task = {"review_marks": [{"page": 1}], "alerts": ["x"]}
    app_service.reset_task_state(task, "Reiniciando...")
    assert task["review_marks"] == [] and task["alerts"] == []

# SPDX-License-Identifier: AGPL-3.0-or-later
"""Eficiência sem perder segurança: OCR das páginas em paralelo (com falha atribuída à página certa),
texto digital do PDF como passada extra, tempos por etapa e número de workers."""
import os
import threading
import time

import fitz
import pytest

from main import SentryApp
from sentry_testkit import CPF_A, CPF_A_FMT, CPF_B_FMT, make_text_pdf, word
from utils.ocr_engine import OCREngine, ocr_workers
from utils.verifier import verify_pdf


class SlowOCR(OCREngine):
    """OCR falso: demora um pouco, conta a concorrência e falha nas páginas pedidas."""

    def __init__(self, fail_pages=(), delay=0.05):
        super().__init__(tesseract_path=None)
        self.fail_pages, self.delay = set(fail_pages), delay
        self.active = self.peak = 0
        self.calls = []
        self._guard = threading.Lock()

    def get_grounding_map(self, img_path, psm=3):
        with self._guard:
            self.active += 1
            self.peak = max(self.peak, self.active)
            self.calls.append((os.path.basename(img_path), str(psm)))
        time.sleep(self.delay)
        with self._guard:
            self.active -= 1
        page = int(os.path.splitext(os.path.basename(img_path))[0].rsplit("_", 1)[-1])
        if page in self.fail_pages:
            self._record_failure()
            return "", []
        return f"[0] {CPF_A_FMT}", [word(0, CPF_A_FMT, 100)]


@pytest.fixture()
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("BASE_DPI", "40")
    monkeypatch.setenv("OCR_WORKERS", "4")
    monkeypatch.setenv("TESSERACT_SPARSE_PSM", "11")
    a = SentryApp(make_text_pdf(tmp_path / "doc.pdf", text="pagina", n_pages=6))
    yield a
    a.session.close()


def test_phase1_runs_pages_in_parallel_and_keeps_both_passes(app):
    app.run_phase_0()
    app.ocr = SlowOCR()
    app.run_phase_1()
    assert app.ocr.peak > 1                                   # páginas em paralelo
    assert sorted(psm for _, psm in app.ocr.calls) == ["11"] * 6 + ["3"] * 6   # as DUAS passadas em todas
    assert len(app.grounding_maps) == len(app.grounding_maps_sparse) == 6      # ordem e tamanho preservados


def test_parallel_ocr_failure_is_attributed_to_the_right_page(app):
    app.run_phase_0()
    app.ocr = SlowOCR(fail_pages={2, 5})
    app.run_phase_1()
    assert sorted(app.review_pages) == [2, 5]                 # nem mais (outras páginas) nem menos


def test_native_text_is_an_extra_cpf_pass(tmp_path, monkeypatch):
    monkeypatch.setenv("BASE_DPI", "40")
    monkeypatch.delenv("TESSERACT_SPARSE_PSM", raising=False)
    pdf = str(tmp_path / "digital.pdf")
    with fitz.open() as doc:
        doc.new_page().insert_text((72, 100), f"Interessado CPF {CPF_B_FMT}")
        doc.save(pdf)
    app = SentryApp(pdf)
    app.run_phase_0()

    class BlindOCR(OCREngine):  # o OCR "não lê" nada: só o texto digital pode achar o CPF
        def get_grounding_map(self, img_path, psm=3):
            return "", []

    app.ocr = BlindOCR(tesseract_path=None)
    app.run_phase_1()
    app.run_phase_2()
    assert app.cpf_redactions[1], "o CPF do texto digital deveria ter virado tarja"
    box = app.cpf_redactions[1][0]
    assert 0 < box["x"] < app.base_dpi / 72.0 * 600            # caixa na escala de pixels da imagem
    app.session.close()


def test_timings_are_recorded_per_phase(tmp_path, monkeypatch):
    monkeypatch.setenv("BASE_DPI", "40")
    app = SentryApp(make_text_pdf(tmp_path / "t.pdf"))
    for name in ("run_phase_0", "run_phase_1", "run_phase_2", "run_policy_phase", "run_phase_3", "run_phase_4",
                 "run_address_discovery",
                 "run_phase_6", "run_signature_audit", "run_second_look", "run_phase_5", "run_verification"):
        monkeypatch.setattr(app, name, lambda: time.sleep(0.01))
    app.run()
    timings = app.final_state()["timings"]
    assert len(timings) == 12 and all(v >= 0 for v in timings.values())
    app.session.close()


@pytest.mark.parametrize("env, dpi, jobs, expected", [
    ("3", 300, 10, 3), ("3", 300, 2, 2), ("", 1000, 10, None), ("x", 300, 10, None),
])
def test_ocr_workers(monkeypatch, env, dpi, jobs, expected):
    monkeypatch.setenv("OCR_WORKERS", env)
    value = ocr_workers(dpi, jobs)
    if expected is not None:
        assert value == expected
    else:
        assert 1 <= value <= (2 if dpi > 600 else 8)


def test_parallel_verification_matches_sequential(tmp_path):
    from PIL import Image
    pdf = str(tmp_path / "scan.pdf")
    img = tmp_path / "p.png"
    Image.new("RGB", (100, 140), "white").save(img)
    with fitz.open() as doc:
        for _ in range(4):
            doc.new_page().insert_image(fitz.Rect(0, 0, 595, 842), filename=str(img))
        doc.save(pdf)

    class PageOCR(OCREngine):  # CPF só nas páginas pares; página 3 falha
        def get_grounding_map(self, img_path, psm=3):
            page = int(os.path.splitext(os.path.basename(img_path))[0].rsplit("_", 1)[-1])
            if page == 3:
                self._record_failure()
                return "", []
            return (f"[0] {CPF_A_FMT}", [word(0, CPF_A_FMT, 10)]) if page % 2 == 0 else ("", [])

    seq = verify_pdf(pdf, ocr_engine=PageOCR(tesseract_path=None), dpi=36, workers=1)
    par = verify_pdf(pdf, ocr_engine=PageOCR(tesseract_path=None), dpi=36, workers=4)
    assert seq == par
    leftovers, unverified = par
    assert set(leftovers) == {2, 4} and unverified == [3] and leftovers[2] == {CPF_A}

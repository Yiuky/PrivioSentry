# SPDX-License-Identifier: AGPL-3.0-or-later
"""Verificador: bordas adicionais (falha de OCR, progresso, paginas limpas, palavras vazias)."""
import fitz

from sentry_testkit import CPF_A_FMT, make_text_pdf
from utils.ocr_engine import OCREngine
from utils.verifier import _words_to_grounding, find_cpfs_in_words, find_uncovered_cpfs, verify_pdf


def scanned_pdf(path, n_pages=1):
    doc = fitz.open()
    for _ in range(n_pages):
        page = doc.new_page()
        pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 40, 40), False)
        pix.set_rect(pix.irect, (255, 255, 255))
        page.insert_image(fitz.Rect(50, 100, 300, 300), pixmap=pix)
    doc.save(str(path))
    doc.close()
    return str(path)


class ExplodingOCR(OCREngine):
    def __init__(self):
        super().__init__(None)

    def get_grounding_map(self, img_path, psm="6"):
        raise RuntimeError("tesseract caiu")


class EmptyOCR(OCREngine):
    def __init__(self):
        super().__init__(None)

    def get_grounding_map(self, img_path, psm="6"):
        return "", []


def test_words_to_grounding_skips_blank_words_and_clamps_size():
    g = _words_to_grounding([(0, 0, 0, 0, "  ", 0, 0, 0), (10, 10, 10, 10, "abc", 0, 0, 0)])
    assert len(g) == 1 and g[0]["id"] == 0 and g[0]["box"]["w"] == 1.0 and g[0]["box"]["h"] == 1.0


def test_find_cpfs_in_words_matches_formatted_number():
    words = [(0, 0, 50, 10, "CPF:", 0, 0, 0), (60, 0, 200, 10, CPF_A_FMT, 0, 0, 1)]
    assert find_cpfs_in_words(words) == {"52998224725"}


def test_verify_marks_page_unverified_when_ocr_fails(tmp_path):
    pdf = scanned_pdf(tmp_path / "scan.pdf", n_pages=2)
    logs = []

    class L:
        def error(self, m):
            logs.append(m)

    leftovers, unverified = verify_pdf(pdf, ocr_engine=ExplodingOCR(), use_ocr=True, logger=L())
    assert leftovers == {} and unverified == [1, 2]
    assert len(logs) == 2 and "Verificação por OCR falhou" in logs[0]
    # sem logger tambem nao levanta
    assert verify_pdf(pdf, ocr_engine=ExplodingOCR(), use_ocr=True)[1] == [1, 2]


def test_verify_scanned_page_clean_and_progress_callback(tmp_path):
    pdf = scanned_pdf(tmp_path / "scan.pdf", n_pages=2)
    seen = []
    leftovers, unverified = verify_pdf(pdf, ocr_engine=EmptyOCR(), use_ocr=True, progress=lambda d, t: seen.append((d, t)))
    assert leftovers == {} and unverified == []
    assert seen[-1] == (2, 2)


def test_verify_without_ocr_still_reads_native_text_of_scanned_page(tmp_path):
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 100), f"CPF {CPF_A_FMT}")
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 10, 10), False)
    pix.set_rect(pix.irect, (255, 255, 255))
    page.insert_image(fitz.Rect(50, 200, 100, 250), pixmap=pix)
    doc.save(str(tmp_path / "mix.pdf"))
    doc.close()
    leftovers, unverified = verify_pdf(str(tmp_path / "mix.pdf"), use_ocr=False)
    assert leftovers == {1: {"52998224725"}} and unverified == []


def test_coverage_reports_ocr_failure_and_ignores_pages_without_cpf(tmp_path):
    pdf = make_text_pdf(tmp_path / "o.pdf", n_pages=2)
    logs = []

    class L:
        def error(self, m):
            logs.append(m)

    uncovered, failed = find_uncovered_cpfs(pdf, {}, ExplodingOCR(), logger=L())
    assert uncovered == {} and failed == [1, 2] and len(logs) == 2
    seen = []
    uncovered, failed = find_uncovered_cpfs(pdf, {}, EmptyOCR(), progress=lambda d, t: seen.append(d))
    assert uncovered == {} and failed == [] and seen == [2]
    assert find_uncovered_cpfs(pdf, {}, ExplodingOCR())[1] == [1, 2]

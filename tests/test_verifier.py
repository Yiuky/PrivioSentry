# SPDX-License-Identifier: AGPL-3.0-or-later
import fitz

from utils.verifier import verify_pdf

CPF_FORMATTED = "529.982.247-25"


def make_pdf(path, text):
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 100), text, fontsize=12)
    doc.save(str(path))
    doc.close()


def test_verifier_flags_cpf_left_in_text(tmp_path):
    pdf = tmp_path / "leak.pdf"
    make_pdf(pdf, f"Proprietario CPF: {CPF_FORMATTED}")
    leftovers, unverified = verify_pdf(str(pdf), use_ocr=False)
    assert leftovers == {1: {"52998224725"}}
    assert unverified == []


def test_verifier_passes_clean_pdf(tmp_path):
    pdf = tmp_path / "clean.pdf"
    make_pdf(pdf, "Texto sem dados pessoais. Processo 7001840.2026")
    leftovers, unverified = verify_pdf(str(pdf), use_ocr=False)
    assert leftovers == {}
    assert unverified == []


def test_verifier_does_not_flag_cnpj(tmp_path):
    pdf = tmp_path / "cnpj.pdf"
    make_pdf(pdf, "Empresa CNPJ 11.444.777/0001-61")
    leftovers, _ = verify_pdf(str(pdf), use_ocr=False)
    assert leftovers == {}


def test_page_without_text_is_unverified_when_ocr_disabled(tmp_path):
    pdf = tmp_path / "blank.pdf"
    doc = fitz.open()
    doc.new_page()
    doc.save(str(pdf))
    doc.close()
    leftovers, unverified = verify_pdf(str(pdf), use_ocr=False)
    assert unverified == [1]


def test_native_redaction_removes_cpf_text_end_to_end(tmp_path, monkeypatch):
    """PDF com CPF em texto -> tarja nativa -> verificador não encontra mais o CPF."""
    monkeypatch.chdir(tmp_path)
    from utils.session import Session

    pdf = tmp_path / "doc.pdf"
    make_pdf(pdf, f"CPF: {CPF_FORMATTED}")
    with fitz.open(str(pdf)) as d:
        rect = d[0].search_for(CPF_FORMATTED)[0]
        page_w = d[0].rect.width

    session = Session(str(pdf))
    # coordenadas em "pixels de imagem" com image_width = largura da página (escala 1:1)
    box = {"x": rect.x0, "y": rect.y0, "w": rect.width, "h": rect.height, "source_width": page_w}
    out = session.apply_native_pdf_redactions({1: [box]}, output_suffix="_TARJADO_FINAL.pdf")
    assert out is not None

    leftovers, _ = verify_pdf(out, use_ocr=False)
    assert leftovers == {}
    with fitz.open(out) as d:
        assert "529" not in d[0].get_text()


def test_scanned_page_with_some_native_text_still_goes_through_ocr(tmp_path):
    """Regressão: página com imagem + poucas palavras nativas (carimbo) não pode pular o OCR."""
    pdf = tmp_path / "scan.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 40), "Processo 7002350/2023")
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 40, 40), False)
    pix.set_rect(pix.irect, (255, 255, 255))
    page.insert_image(fitz.Rect(50, 100, 300, 300), pixmap=pix)
    doc.save(str(pdf))
    doc.close()

    class FakeOCR:
        calls = 0

        def get_grounding_map(self, img_path, psm="6"):
            FakeOCR.calls += 1
            return "", [{"id": 0, "text": CPF_FORMATTED, "box": {"x": 0, "y": 0, "w": 300, "h": 30}, "conf": 90}]

        def find_cpfs_in_grounding(self, gm):
            from utils.ocr_engine import OCREngine
            return OCREngine(None).find_cpfs_in_grounding(gm)

    leftovers, unverified = verify_pdf(str(pdf), ocr_engine=FakeOCR(), use_ocr=True)
    assert FakeOCR.calls == 1
    assert leftovers == {1: {"52998224725"}}


def test_coverage_flags_cpf_without_matching_redaction(tmp_path):
    from utils.verifier import find_uncovered_cpfs
    pdf = tmp_path / "orig.pdf"
    make_pdf(pdf, f"CPF {CPF_FORMATTED}")
    with fitz.open(str(pdf)) as d:
        page_w = d[0].rect.width

    class FakeOCR:
        # OCR "enxerga" o CPF em (72..200pt, ~y 100pt) a 300 DPI
        def get_grounding_map(self, img_path, psm="6"):
            s = 300 / 72.0
            return "", [{"id": 0, "text": CPF_FORMATTED, "box": {"x": 100 * s, "y": 95 * s, "w": 80 * s, "h": 12 * s}, "conf": 90}]

        def find_cpfs_in_grounding(self, gm):
            from utils.ocr_engine import OCREngine
            return OCREngine(None).find_cpfs_in_grounding(gm)

    covering = {1: [{"x": 90, "y": 90, "w": 120, "h": 25, "source_width": page_w}]}  # em pontos, escala 1:1
    far_away = {1: [{"x": 400, "y": 400, "w": 50, "h": 20, "source_width": page_w}]}

    assert find_uncovered_cpfs(str(pdf), covering, FakeOCR())[0] == {}
    assert find_uncovered_cpfs(str(pdf), far_away, FakeOCR())[0] == {1: {"52998224725"}}
    assert find_uncovered_cpfs(str(pdf), {}, FakeOCR())[0] == {1: {"52998224725"}}

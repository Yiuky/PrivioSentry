# SPDX-License-Identifier: AGPL-3.0-or-later
import fitz

from main import SentryApp
from utils.session import Session


def make_pdf(path, n_pages=2):
    doc = fitz.open()
    for i in range(n_pages):
        doc.new_page().insert_text((72, 100), f"pagina {i + 1}")
    doc.save(str(path))
    doc.close()


def test_final_state_completed_without_review(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    pdf = tmp_path / "a.pdf"
    make_pdf(pdf)
    app = SentryApp(str(pdf))
    st = app.final_state()
    assert st["status"] == "Concluído" and st["needs_review"] is False


def test_final_state_requires_review_when_page_flagged(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    pdf = tmp_path / "a.pdf"
    make_pdf(pdf)
    app = SentryApp(str(pdf))
    app.add_review(2, "IA não analisou endereços")
    app.add_review(2, "IA não analisou endereços")  # sem duplicar
    st = app.final_state()
    assert st["status"] == "Requer revisão" and st["needs_review"] is True
    assert st["completed"] is True
    assert len(st["alerts"]) == 1 and "Pág 2" in st["alerts"][0]


def test_reconstitute_pdf_fails_closed_on_missing_page_image(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    pdf = tmp_path / "a.pdf"
    make_pdf(pdf, n_pages=2)
    session = Session(str(pdf))
    # só 1 imagem para 2 páginas
    import fitz as _f
    pix = _f.Pixmap(_f.csRGB, _f.IRect(0, 0, 50, 50), False)
    pix.set_rect(pix.irect, (255, 255, 255))
    img = tmp_path / "p1.png"
    pix.save(str(img))
    assert session.reconstitute_pdf([str(img)]) is None
    assert session.reconstitute_pdf([str(img), str(tmp_path / "missing.png")]) is None


def test_reconstitute_pdf_ok_with_all_pages(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    pdf = tmp_path / "a.pdf"
    make_pdf(pdf, n_pages=2)
    session = Session(str(pdf))
    import fitz as _f
    imgs = []
    for i in range(2):
        pix = _f.Pixmap(_f.csRGB, _f.IRect(0, 0, 50, 50), False)
        pix.set_rect(pix.irect, (255, 255, 255))
        p = tmp_path / f"p{i}.png"
        pix.save(str(p))
        imgs.append(str(p))
    out = session.reconstitute_pdf(imgs)
    assert out is not None
    with _f.open(out) as d:
        assert len(d) == 2


def test_address_redactor_records_failed_pages(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    pdf = tmp_path / "a.pdf"
    make_pdf(pdf, n_pages=1)
    app = SentryApp(str(pdf))
    img = tmp_path / "x.png"
    img.write_bytes(b"")
    monkeypatch.setattr(app.address_redactor.ai, "analyze_image",
                        lambda path, prompt: ({"error": "timeout"}, None, {}))
    app.image_paths = [str(img)]
    app.run_address_discovery()
    assert app.address_redactor.failed_pages == {1: "timeout"}
    assert app.needs_review

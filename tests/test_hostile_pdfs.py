# SPDX-License-Identifier: AGPL-3.0-or-later
"""PDFs hostis achados no teste de pressão (benchmarks/stress.py): nunca travar, nunca concluir em silêncio."""
import fitz
import pytest

from main import SentryApp
from sentry_testkit import make_text_pdf
from utils.session import effective_dpi


def _pdf(path, width, height, text="pagina"):
    d = fitz.open()
    d.new_page(width=width, height=height).insert_text((72, 72), text)
    d.save(str(path))
    d.close()
    return str(path)


def test_giant_page_lowers_dpi_for_the_whole_document(tmp_path, monkeypatch):
    monkeypatch.setenv("BASE_DPI", "300")
    giant = _pdf(tmp_path / "g.pdf", 14400, 14400)            # 200 x 200 polegadas: 3.600 MP a 300 DPI
    dpi, reduced = effective_dpi(giant)
    assert reduced and 30 <= dpi < 300
    assert (14400 / 72 * dpi) ** 2 <= 150e6 * 1.01             # cabe no teto padrão
    assert effective_dpi(giant) == (dpi, True)                 # determinístico: a finalização usa o mesmo DPI
    a4 = _pdf(tmp_path / "a4.pdf", 595, 842)
    assert effective_dpi(a4) == (300, False)
    a0 = _pdf(tmp_path / "a0.pdf", 2384, 3370)                 # mapa A0 continua a 300 DPI
    assert effective_dpi(a0) == (300, False)


def test_giant_page_goes_to_review(tmp_path, monkeypatch):
    monkeypatch.setenv("BASE_DPI", "300")
    monkeypatch.setenv("MAX_PAGE_MEGAPIXELS", "4")              # deixa o teste leve: limite baixo
    app = SentryApp(_pdf(tmp_path / "big.pdf", 2384, 3370))
    app.run_phase_0()
    assert app.dpi_reduced and app.needs_review
    assert any("muito grande" in r for r in app.review_pages[0])
    app.session.close()


def test_password_protected_pdf_gives_a_clear_error(tmp_path):
    d = fitz.open()
    d.new_page().insert_text((72, 72), "x")
    path = tmp_path / "s.pdf"
    d.save(str(path), encryption=fitz.PDF_ENCRYPT_AES_256, user_pw="segredo", owner_pw="dono")
    d.close()
    app = SentryApp(str(path))
    with pytest.raises(Exception, match="senha"):
        app.run_phase_0()
    app.session.close()


def test_repaired_pdf_goes_to_review(tmp_path, monkeypatch):
    monkeypatch.setenv("BASE_DPI", "40")
    good = make_text_pdf(tmp_path / "ok.pdf", n_pages=2)
    data = open(good, "rb").read()
    broken = tmp_path / "quebrado.pdf"
    broken.write_bytes(data.replace(b"xref", b"xxxx", 1))      # tabela de referências estragada: o leitor repara
    with fitz.open(str(broken)) as doc:
        if not doc.is_repaired:
            pytest.skip("esta versão do PyMuPDF não marcou o arquivo como reparado")
    app = SentryApp(str(broken))
    app.run_phase_0()
    assert app.needs_review and any("danificado" in r for r in app.review_pages[0])
    app.session.close()


def test_verification_respects_the_reduced_dpi(tmp_path, monkeypatch):
    # Teste de pressão: com a página gigante, a verificação renderizava a 300 DPI e o processo chegou a 40 GB
    import os

    from utils import verifier
    monkeypatch.setenv("BASE_DPI", "300")
    monkeypatch.setenv("MAX_PAGE_MEGAPIXELS", "4")
    app = SentryApp(_pdf(tmp_path / "big.pdf", 2384, 3370))
    final = os.path.join(app.session.doc_finais_dir, f"{app.session.filename}_TARJADO_FINAL.pdf")
    os.makedirs(os.path.dirname(final), exist_ok=True)
    open(final, "wb").write(open(app.session.pdf_path, "rb").read())
    seen = []
    monkeypatch.setattr(verifier, "verify_pdf", lambda *a, **k: (seen.append(k["dpi"]), ({}, []))[1])
    monkeypatch.setattr(verifier, "find_uncovered_cpfs", lambda *a, **k: (seen.append(k["dpi"]), ({}, []))[1])
    app.run_verification()
    assert seen and all(d == app.base_dpi < 300 for d in seen)
    app.session.close()

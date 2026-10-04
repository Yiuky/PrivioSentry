# SPDX-License-Identifier: AGPL-3.0-or-later
import os

import fitz
import pytest
from PIL import Image

from sentry_testkit import CPF_A, CPF_A_FMT, CPF_B, make_text_pdf
import utils.transform_pdf_to_img as transform_module
from utils.transform_pdf_to_img import transform_pdf_to_img
from utils.validators import is_valid_cnpj, is_valid_cpf


# --- validators --------------------------------------------------------------------------------
@pytest.mark.parametrize("value", [CPF_A, CPF_A_FMT, CPF_B, " 529.982.247-25 ", "529 982 247 25"])
def test_valid_cpf_variants(value):
    assert is_valid_cpf(value)


@pytest.mark.parametrize("value", [
    None, "", "   ", "abc", "1234567890", "123456789012", "00000000000", "11111111111", "99999999999",
    "529.982.247-24", "52998224726", "5299822472", "529.982.247-2",
])
def test_invalid_cpf_variants(value):
    assert not is_valid_cpf(value)


def test_cpf_check_digit_ten_maps_to_zero():
    # base 000.000.006: resto 10 no 1o digito -> digito 0 (borda do modulo 11); 2o digito = 4
    assert is_valid_cpf("00000000604") is True
    assert is_valid_cpf("00000000614") is False
    assert is_valid_cpf("00000000191") is True


def test_every_single_digit_change_invalidates_cpf():
    for pos in range(11):
        digit = (int(CPF_A[pos]) + 1) % 10
        mutated = CPF_A[:pos] + str(digit) + CPF_A[pos + 1:]
        assert not is_valid_cpf(mutated), pos


@pytest.mark.parametrize("value", ["11444777000161", "11.444.777/0001-61", "00.000.000/0001-91", "11222333000181"])
def test_valid_cnpj_variants(value):
    assert is_valid_cnpj(value)


@pytest.mark.parametrize("value", [None, "", "11444777000162", "11444777000160", "00000000000000",
                                   "1144477700016", "114447770001611", "abc"])
def test_invalid_cnpj_variants(value):
    assert not is_valid_cnpj(value)


def test_cnpj_and_cpf_are_distinguished_by_length():
    assert not is_valid_cpf("11444777000161")
    assert not is_valid_cnpj(CPF_A)


# --- transform_pdf_to_img ----------------------------------------------------------------------
def test_transform_renders_every_page_at_requested_dpi(tmp_path):
    pdf = make_text_pdf(tmp_path / "meu doc.pdf", n_pages=3)
    out = tmp_path / "imgs" / "sub"           # pasta inexistente e criada
    paths = transform_pdf_to_img(pdf, str(out), dpi=72)
    assert [os.path.basename(p) for p in paths] == [f"meu doc_page_{i}.png" for i in (1, 2, 3)]
    with Image.open(paths[0]) as im:
        assert im.size == (595, 842)   # A4 a 72 DPI (zoom 1.0)
    paths150 = transform_pdf_to_img(pdf, str(out), dpi=144)
    with Image.open(paths150[0]) as im:
        assert im.size == (1190, 1684)


def test_transform_missing_pdf_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        transform_pdf_to_img(str(tmp_path / "nao.pdf"), str(tmp_path / "o"))


def test_transform_corrupt_pdf_raises(tmp_path):
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"%PDF-1.4 lixo")
    with pytest.raises(fitz.FileDataError):
        transform_pdf_to_img(str(bad), str(tmp_path / "o"))


def test_transform_retries_locked_output_then_succeeds(tmp_path, monkeypatch):
    pdf = make_text_pdf(tmp_path / "a.pdf")
    calls = {"n": 0}
    real_save = transform_module._save_png

    def flaky(pix, filename):
        calls["n"] += 1
        if calls["n"] < 3:
            raise OSError("arquivo travado")
        return real_save(pix, filename)

    monkeypatch.setattr(transform_module, "_save_png", flaky)
    monkeypatch.setattr("time.sleep", lambda s: None)
    paths = transform_pdf_to_img(pdf, str(tmp_path / "o"), dpi=36)
    assert calls["n"] == 3 and os.path.exists(paths[0])


def test_transform_gives_up_after_three_failed_saves(tmp_path, monkeypatch):
    pdf = make_text_pdf(tmp_path / "a.pdf")
    monkeypatch.setattr(transform_module, "_save_png", lambda *a, **k: (_ for _ in ()).throw(OSError("travado")))
    monkeypatch.setattr("time.sleep", lambda s: None)
    with pytest.raises(OSError):
        transform_pdf_to_img(pdf, str(tmp_path / "o"), dpi=36)


def test_transform_module_main_usage(tmp_path, monkeypatch, capsys):
    import runpy
    import sys
    monkeypatch.setattr(sys, "argv", ["transform_pdf_to_img.py"])
    runpy.run_module("utils.transform_pdf_to_img", run_name="__main__")
    assert "Usage" in capsys.readouterr().out
    pdf = make_text_pdf(tmp_path / "a.pdf")
    monkeypatch.setattr(sys, "argv", ["transform_pdf_to_img.py", pdf])
    runpy.run_module("utils.transform_pdf_to_img", run_name="__main__")
    assert "Success" in capsys.readouterr().out
    monkeypatch.setattr(sys, "argv", ["transform_pdf_to_img.py", str(tmp_path / "nada.pdf")])
    runpy.run_module("utils.transform_pdf_to_img", run_name="__main__")
    assert "Error" in capsys.readouterr().out

# SPDX-License-Identifier: AGPL-3.0-or-later
from utils.validators import is_valid_cpf, is_valid_cnpj
from utils.ocr_engine import OCREngine
from utils.session import Session

VALID_CPF = "52998224725"          # CPF válido (dígitos verificadores corretos)
VALID_CNPJ = "11444777000161"      # CNPJ válido


def word(i, text, x, y=100, w=None, h=30):
    return {"id": i, "text": text, "box": {"x": x, "y": y, "w": w or 20 * len(text), "h": h}, "conf": 90}


def make_engine():
    return OCREngine(tesseract_path=None)


def test_valid_cpf_formats():
    assert is_valid_cpf("529.982.247-25")
    assert is_valid_cpf(VALID_CPF)
    assert not is_valid_cpf("529.982.247-26")
    assert not is_valid_cpf("111.111.111-11")
    assert not is_valid_cpf("")


def test_valid_cnpj():
    assert is_valid_cnpj(VALID_CNPJ)
    assert not is_valid_cnpj("11444777000162")


def test_formatted_cpf_in_single_word_is_found():
    gm = [word(0, "CPF:", 0), word(1, "529.982.247-25", 200)]
    cmds, found = make_engine().find_cpfs_in_grounding(gm)
    assert found == {VALID_CPF}
    assert set(cmds) == {1}


def test_cpf_split_across_two_words_is_found():
    gm = [word(0, "529.982", 0), word(1, "247-25", 160)]
    cmds, found = make_engine().find_cpfs_in_grounding(gm)
    assert found == {VALID_CPF}
    assert set(cmds) == {0, 1}


def test_cnpj_is_not_redacted():
    gm = [word(0, "11.444.777/0001-61", 0)]
    cmds, found = make_engine().find_cpfs_in_grounding(gm)
    assert found == set()
    assert cmds == {}


def test_date_is_not_a_cpf():
    gm = [word(0, "12/03/2024", 0)]
    cmds, found = make_engine().find_cpfs_in_grounding(gm)
    assert found == set()


def test_digits_on_different_lines_are_not_joined():
    gm = [word(0, "52998", 0, y=100), word(1, "224725", 0, y=900)]
    cmds, found = make_engine().find_cpfs_in_grounding(gm)
    assert found == set()


def test_get_redaction_boxes_covers_only_cpf_chars(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    session = Session(str(pdf))
    gm = [word(0, "529.982.247-25", 1000, y=500, w=1400, h=100)]
    cmds, _ = make_engine().find_cpfs_in_grounding(gm)
    boxes = session.get_redaction_boxes(gm, cmds, padding=10)
    assert len(boxes) == 1
    b = boxes[0]
    assert b["x"] <= 1000 and b["x"] + b["w"] >= 1000 + 1400 - 1
    assert b["y"] == 490 and b["h"] == 120

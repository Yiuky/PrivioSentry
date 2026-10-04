# SPDX-License-Identifier: AGPL-3.0-or-later
import logging

import pytesseract
from PIL import Image, ImageDraw, ImageFont

from sentry_testkit import CPF_A, CPF_A_FMT, CPF_B, CPF_B_FMT, make_blank_image, word
from utils.ocr_engine import OCREngine

VALID_CNPJ_FMT = "11.444.777/0001-61"


def engine(**kw):
    return OCREngine(tesseract_path=None, **kw)


def make_data(words, level=5, block=1, line=1, left=0, top=0, width=50, height=20, conf=90):
    """Dicionario no formato de pytesseract.image_to_data."""
    n = len(words)
    return {
        "level": [level] * n, "block_num": [block] * n, "line_num": [line] * n, "par_num": [1] * n,
        "word_num": list(range(1, n + 1)), "left": [left] * n, "top": [top] * n, "width": [width] * n,
        "height": [height] * n, "conf": [conf] * n, "text": list(words), "page_num": [1] * n,
    }


# --- inicializacao / fallback ------------------------------------------------------------------
def test_init_sets_tesseract_cmd(monkeypatch):
    monkeypatch.setattr(pytesseract.pytesseract, "tesseract_cmd", "tesseract")
    OCREngine(tesseract_path="/x/tesseract")
    assert pytesseract.pytesseract.tesseract_cmd == "/x/tesseract"


def test_fallback_to_half_size_rescales_coordinates(monkeypatch, caplog):
    sizes = []

    def fake_image_to_data(img, lang, config, output_type):
        sizes.append(img.size)
        if len(sizes) == 1:
            raise RuntimeError("crash em tamanho cheio")
        d = make_data(["abc"], left=10, top=20, width=30, height=40)
        return d

    monkeypatch.setattr(pytesseract, "image_to_data", fake_image_to_data)
    logger = logging.getLogger("t_ocr")
    img = Image.new("RGB", (400, 200))
    with caplog.at_level(logging.WARNING, logger="t_ocr"):
        data = OCREngine(None, logger=logger).image_to_data(img, psm=6)
    assert sizes == [(400, 200), (200, 100)]
    # coordenadas do resultado a 50% voltam para a escala original (/0.5)
    assert (data["left"][0], data["top"][0], data["width"][0], data["height"][0]) == (20, 40, 60, 80)
    assert "TESSERACT FALLBACK" in caplog.text


def test_fallback_gives_up_with_empty_result(monkeypatch, caplog):
    monkeypatch.setattr(pytesseract, "image_to_data", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
    monkeypatch.setattr(pytesseract, "image_to_string", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("y")))
    eng = OCREngine(None, logger=logging.getLogger("t_ocr2"))
    img = Image.new("RGB", (100, 100))
    assert eng.image_to_data(img) == {"text": []}
    assert eng.image_to_string(img) == ""


def test_image_to_string_strips_and_passes_psm(monkeypatch):
    seen = {}

    def fake(img, lang, config):
        seen["config"], seen["lang"] = config, lang
        return "  texto \n"

    monkeypatch.setattr(pytesseract, "image_to_string", fake)
    assert OCREngine(None, lang="eng").image_to_string(Image.new("RGB", (10, 10)), psm=11) == "texto"
    assert seen == {"config": "--psm 11", "lang": "eng"}


# --- metades / merge ---------------------------------------------------------------------------
def test_full_ocr_merges_bottom_half_with_offsets(tmp_path, monkeypatch):
    img_path = make_blank_image(tmp_path / "p.png", size=(1000, 2000))  # 55% de 2000 = 1100
    calls = []

    def fake_image_to_data(img, psm=3):
        calls.append(img.size)
        if len(calls) == 1:   # metade superior
            d = make_data(["", "topo"], level=5, block=3, top=100)
            d["level"][0] = 1  # cabecalho de pagina
            return d
        d = make_data(["", "base"], level=5, block=2, top=50)
        d["level"][0] = 1
        return d

    eng = engine()
    monkeypatch.setattr(eng, "image_to_data", fake_image_to_data)
    data = eng.get_full_ocr_data(str(img_path), psm=6)
    assert calls == [(1000, 1100), (1000, 1100)]
    assert data["text"] == ["", "topo", "", "base"]
    # nivel >= 2: top somado ao deslocamento (2000 - 1100 = 900); nivel 1 nao e deslocado
    assert data["top"] == [100, 100, 50, 50 + 900]
    # block_num da metade inferior e somado ao maior bloco da superior (3)
    assert data["block_num"] == [3, 3, 2 + 3, 2 + 3]


def test_full_ocr_merge_handles_empty_top_result(tmp_path, monkeypatch):
    img_path = make_blank_image(tmp_path / "p.png", size=(100, 200))
    eng = engine()
    results = iter([{"text": []}, {"text": []}])
    monkeypatch.setattr(eng, "image_to_data", lambda img, psm=3: next(results))
    assert eng.get_full_ocr_data(str(img_path))["text"] == []


def test_extract_page_text_keeps_only_words(tmp_path, monkeypatch):
    img_path = make_blank_image(tmp_path / "p.png", size=(100, 200))
    eng = engine()
    top = make_data(["a", "  ", "b"])
    top["level"][2] = 4
    bottom = make_data(["c"])
    seq = iter([top, bottom])
    monkeypatch.setattr(eng, "image_to_data", lambda img, psm=3: next(seq))
    assert eng.extract_page_text(str(img_path)) == "a c"


# --- grounding map -----------------------------------------------------------------------------
def test_grounding_map_layout_blocks_lines_and_ids(tmp_path, monkeypatch):
    img_path = make_blank_image(tmp_path / "p.png", size=(100, 200))
    eng = engine()
    data = make_data(["Rua", "das", "   ", "Flores", "Casa", "7"])
    data["block_num"] = [1, 1, 1, 1, 2, 2]
    data["line_num"] = [1, 1, 1, 2, 1, 1]
    data["level"][1] = 4          # nao e palavra: ignorada
    monkeypatch.setattr(eng, "get_full_ocr_data", lambda p, psm=3: data)
    text, gm = eng.get_grounding_map(str(img_path), psm=3)
    assert [w["text"] for w in gm] == ["Rua", "Flores", "Casa", "7"]
    assert [w["id"] for w in gm] == [0, 1, 2, 3]
    assert text.split("\n") == ["[0] Rua", "[1] Flores", "", "[2] Casa [3] 7"]
    assert gm[0]["box"] == {"x": 0, "y": 0, "w": 50, "h": 20}


def test_grounding_map_empty_page(tmp_path, monkeypatch):
    img_path = make_blank_image(tmp_path / "p.png", size=(100, 200))
    eng = engine()
    monkeypatch.setattr(eng, "get_full_ocr_data", lambda p, psm=3: make_data([]))
    assert eng.get_grounding_map(str(img_path)) == ("", [])


# --- deteccao de CPF ---------------------------------------------------------------------------
def test_empty_and_short_maps():
    assert engine().find_cpfs_in_grounding([]) == ({}, set())
    assert engine().find_cpfs_in_grounding([word(0, "12345", 0)]) == ({}, set())


def test_two_cpfs_back_to_back_are_both_found():
    gm = [word(0, CPF_A_FMT, 0), word(1, CPF_B_FMT, 400)]
    _, found = engine().find_cpfs_in_grounding(gm)
    assert found == {CPF_A, CPF_B}


def test_cpf_adjacent_to_cnpj_is_found_but_cnpj_digits_are_not_redacted():
    gm = [word(0, VALID_CNPJ_FMT, 0, w=360), word(1, "CPF", 380), word(2, CPF_A_FMT, 480)]
    cmds, found = engine().find_cpfs_in_grounding(gm)
    assert found == {CPF_A} and set(cmds) == {2}


def test_time_pattern_does_not_create_cpf():
    gm = [word(0, "12:34:56", 0), word(1, "78901", 200)]
    assert engine().find_cpfs_in_grounding(gm)[1] == set()


def test_far_apart_words_on_same_line_are_not_joined():
    gm = [word(0, "52998", 0, w=100, h=30), word(1, "224725", 2000, w=120, h=30)]
    assert engine().find_cpfs_in_grounding(gm)[1] == set()


def test_cpf_with_ocr_noise_characters_still_found():
    gm = [word(0, "(529.982.247-25)", 0)]
    cmds, found = engine().find_cpfs_in_grounding(gm)
    assert found == {CPF_A}
    # os parenteses nao entram na tarja: so os indices dos digitos
    assert min(cmds[0]) == 1 and max(cmds[0]) == len("(529.982.247-25)") - 2


def test_invalid_check_digit_is_not_found():
    gm = [word(0, "529.982.247-26", 0)]
    assert engine().find_cpfs_in_grounding(gm) == ({}, set())


def test_date_and_valid_cpf_digits_mix_is_ignored_when_only_date_ids():
    gm = [word(0, "01/02/2003", 0), word(1, "04/05/2006", 300)]
    assert engine().find_cpfs_in_grounding(gm)[1] == set()


# --- endereco legado ---------------------------------------------------------------------------
def test_find_address_in_grounding_ignores_labels():
    gm = [word(0, "Rua", 0), word(1, "Palmeiras", 100), word(2, "Bairro:", 300), word(3, "Centro,", 450)]
    boxes = engine().find_address_in_grounding(gm, "Rua Palmeiras, Bairro Centro")
    assert [b["x"] for b in boxes] == [100, 450]
    assert engine().find_address_in_grounding(gm, "  ") == []


# --- Tesseract REAL ----------------------------------------------------------------------------
def draw_text_image(path, lines, size=(1500, 420), font_size=64):
    img = Image.new("L", size, 255)
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default(size=font_size)
    y = 30
    for line in lines:
        draw.text((40, y), line, font=font, fill=0)
        y += font_size + 40
    img.save(str(path))
    return str(path)


def test_real_tesseract_grounding_map_finds_cpf_and_skips_decoys(tmp_path, real_ocr):
    path = draw_text_image(tmp_path / "cpf.png", [f"CPF: {CPF_A_FMT}", f"CNPJ {VALID_CNPJ_FMT}", "Emitido 12/03/2024"])
    text, gm = real_ocr.get_grounding_map(path, psm=6)
    assert gm and text.startswith("[0]")
    assert all(set(w["box"]) == {"x", "y", "w", "h"} for w in gm)
    cmds, found = real_ocr.find_cpfs_in_grounding(gm)
    assert found == {CPF_A}
    boxes_words = [gm[i] for i in cmds]
    assert all(w["box"]["y"] < 150 for w in boxes_words)  # so a 1a linha (CPF), nao CNPJ/data


def test_real_tesseract_image_to_string(tmp_path, real_ocr):
    path = draw_text_image(tmp_path / "t.png", ["Texto simples"])
    assert real_ocr.image_to_string(Image.open(path), psm=6).lower().startswith("texto")

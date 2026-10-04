# SPDX-License-Identifier: AGPL-3.0-or-later
import json
import os

import fitz
import numpy as np
import pytest
from PIL import Image

from sentry_testkit import (CPF_A, CPF_A_FMT, CPF_B, FULL_CPF_RE, make_blank_image, make_text_pdf,
                              text_files_under, word)
from utils.session import DEFAULT_FINAL_IMAGE_WIDTH, DEFAULT_FINAL_JPEG_QUALITY, Session, _env_int


@pytest.fixture()
def session(tmp_path):
    pdf = make_text_pdf(tmp_path / "doc.pdf", n_pages=2)
    s = Session(pdf)
    yield s
    s.close()


def noisy_image(path, size=(2000, 2800), seed=1):
    arr = np.random.default_rng(seed).integers(0, 256, (size[1], size[0], 3), dtype=np.uint8)
    Image.fromarray(arr).save(str(path))
    return str(path)


# --- diretorios / ambiente ---------------------------------------------------------------------
def test_dirs_come_from_env_and_explicit_arguments(tmp_path, monkeypatch):
    pdf = make_text_pdf(tmp_path / "a.pdf")
    s = Session(pdf)
    assert s.output_dir == os.path.join(str(tmp_path / "state" / "output"), "a")
    assert s.doc_finais_dir == str(tmp_path / "state" / "final")
    s.close()
    s2 = Session(pdf, output_dir=str(tmp_path / "o2"), final_dir=str(tmp_path / "f2"))
    assert os.path.isdir(tmp_path / "o2" / "a" / "00_original_images")
    assert os.path.isdir(tmp_path / "f2")
    s2.close()


def test_defaults_are_relative_to_cwd_when_no_env(tmp_path, monkeypatch):
    monkeypatch.delenv("PRIVIO_OUTPUT_DIR")
    monkeypatch.delenv("PRIVIO_FINAL_DIR")
    pdf = make_text_pdf(tmp_path / "b.pdf")
    s = Session(pdf)
    assert s.output_dir == os.path.join("output", "b")
    assert s.doc_finais_dir == "documentos_finais"
    assert (tmp_path / "output" / "b").is_dir()
    s.close()


@pytest.mark.parametrize("raw,expected", [
    (None, 7), ("", 7), ("abc", 7), ("0", 7), ("-3", 7), ("5", 5), (" 9 ", 9), ("500", 7),
])
def test_env_int_validation(monkeypatch, raw, expected):
    if raw is None:
        monkeypatch.delenv("X_TEST_INT", raising=False)
    else:
        monkeypatch.setenv("X_TEST_INT", raw)
    assert _env_int("X_TEST_INT", 7, 1, 100) == expected


# --- logs sem PII ------------------------------------------------------------------------------
def test_session_log_masks_cpf_in_file_and_console(session, capsys):
    session.logger.info(f"CPF encontrado {CPF_A_FMT} e {CPF_A}")
    for h in session.logger.handlers:
        h.flush()
    log = open(os.path.join(session.output_dir, "process_log.log"), encoding="utf-8").read()
    assert not FULL_CPF_RE.search(log)
    assert "***.***.247-25" in log
    assert not FULL_CPF_RE.search(capsys.readouterr().out)


def test_recreating_session_closes_old_handlers(tmp_path):
    pdf = make_text_pdf(tmp_path / "dup.pdf")
    s1 = Session(pdf)
    old_handlers = list(s1.logger.handlers)
    s2 = Session(pdf)
    assert all(h not in s2.logger.handlers for h in old_handlers)
    assert len(s2.logger.handlers) == 2
    s2.close()
    assert s2.logger.handlers == []


def test_close_releases_log_file_so_folder_can_be_deleted(tmp_path):
    import shutil
    pdf = make_text_pdf(tmp_path / "del.pdf")
    s = Session(pdf)
    s.logger.info("x")
    s.close()
    shutil.rmtree(s.output_dir)  # no Windows falharia com o FileHandler aberto
    assert not os.path.exists(s.output_dir)


def test_save_detected_cpfs_stores_only_masks(session):
    session.save_detected_cpfs({CPF_A, CPF_B})
    content = open(os.path.join(session.output_dir, "detected_cpfs.txt"), encoding="utf-8").read()
    assert content.splitlines() == sorted(["***.***.247-25", "***.***.777-35"])
    assert not FULL_CPF_RE.search(content)


def test_save_ai_interaction_masks_every_text_artifact(session):
    session.save_ai_interaction(
        phase_key="Signature_Audit", prefix="p1",
        prompt=f"Os CPFs da memoria sao [{CPF_A_FMT}, {CPF_B}]",
        response={"unredacted_cpfs": [CPF_A_FMT]},
        metrics={"nota": f"cpf {CPF_B}"}, data={"visto": CPF_A}, img_bytes=b"\xff\xd8fake")
    d = session.dirs["99_ia_interactions"]
    assert sorted(os.listdir(d)) == ["p1_data.json", "p1_prompt.txt", "p1_response.txt", "p1_source.jpg"]
    for name in os.listdir(d):
        if name.endswith((".txt", ".json")):
            assert not FULL_CPF_RE.search(open(os.path.join(d, name), encoding="utf-8").read()), name
    assert json.load(open(os.path.join(d, "p1_data.json"), encoding="utf-8"))["phase"] == "Signature_Audit"


def test_save_ai_interaction_without_metrics_or_image(session):
    session.save_ai_interaction("fase", "p2", "prompt", {"ok": 1})
    d = session.dirs["99_ia_interactions"]
    assert not os.path.exists(os.path.join(d, "p2_source.jpg"))
    assert "METRICS" not in open(os.path.join(d, "p2_response.txt"), encoding="utf-8").read()


def test_export_ocr_masks_text_and_json(session):
    gm = [word(0, CPF_A_FMT, 0)]
    session.export_ocr(1, f"[0] {CPF_A_FMT}", gm)
    d = session.dirs["01_ocr"]
    for name in ("page_1.txt", "page_1.json"):
        assert not FULL_CPF_RE.search(open(os.path.join(d, name), encoding="utf-8").read())


def test_export_micro_audit_masks_detected_cpfs(session, tmp_path):
    crop = make_blank_image(tmp_path / "crop.jpg", size=(300, 100))
    gm = [word(0, CPF_A_FMT, 10, y=10, w=200, h=20)]
    points = session.export_micro_audit_results("crop.jpg", crop, gm, (100, 200, 400, 300), {CPF_A})
    assert points[0]["global_box"] == {"x": 110, "y": 210, "w": 200, "h": 20}
    meta = open(os.path.join(session.dirs["04_micro_audit"], "meta_crop.json"), encoding="utf-8").read()
    assert not FULL_CPF_RE.search(meta)
    assert os.path.exists(os.path.join(session.dirs["04_micro_audit"], "viz_crop.jpg"))


def test_export_grounding_viz_and_yolo_results(session, tmp_path):
    img = make_blank_image(tmp_path / "pg.png", size=(500, 700))
    session.export_grounding_viz(1, img, [word(0, "abc", 10, y=10, w=50, h=20)])
    assert os.path.exists(os.path.join(session.dirs["01_ocr"], "page_1_grounding.jpg"))
    session.export_yolo_results(1, img, [])  # sem candidatos: nada gerado
    assert not os.path.exists(os.path.join(session.dirs["02_signatures"], "page_1_yolo.json"))
    session.export_yolo_results(1, img, [{"label": "signature", "conf": 0.91234, "bbox": [10, 20, 110, 80]}])
    data = json.load(open(os.path.join(session.dirs["02_signatures"], "page_1_yolo.json"), encoding="utf-8"))
    assert data[0]["label"] == "signature" and data[0]["conf"] == 0.9123
    assert data[0]["bbox_normalized"] == [round(20 / 700 * 1000, 2), round(10 / 500 * 1000, 2),
                                          round(80 / 700 * 1000, 2), round(110 / 500 * 1000, 2)]


# --- caixas de tarja ---------------------------------------------------------------------------
def test_get_redaction_boxes_substring_padding_and_zero_length(session):
    gm = [word(0, "CPF:529.982", 100, y=50, w=1100, h=40), word(1, "", 0, w=10)]
    # tarja so os caracteres 4..10 da palavra 0 (cada caractere = 100 px); palavra 1 vazia e ignorada
    boxes = session.get_redaction_boxes(gm, {0: {4, 10}, 1: {0}, 7: {0}}, padding=5)
    assert boxes == [{"x": 100 + 400 - 5, "y": 45, "w": 7 * 100 + 10, "h": 50}]


def test_get_redaction_boxes_clamps_negative_origin(session):
    gm = [word(0, "123", 3, y=2, w=30, h=10)]
    box = session.get_redaction_boxes(gm, {0: {0}}, padding=10)[0]
    assert box["x"] == 0 and box["y"] == 0


# --- exportacao final / qualidade ---------------------------------------------------------------
def test_final_export_defaults_1240_width_q75(session, tmp_path):
    img = noisy_image(tmp_path / "big.png")
    out = session.apply_final_redactions(1, img, [], dir_key="05_combined")
    with Image.open(out) as im:
        assert im.width == DEFAULT_FINAL_IMAGE_WIDTH == 1240
        assert im.height == int(2800 * 1240 / 2000)
        assert im.format == "JPEG"
    assert DEFAULT_FINAL_JPEG_QUALITY == 75
    assert out.endswith(os.path.join("combined", "page_1_REDACTED.jpg"))


def test_final_width_is_configurable_and_never_upscales(session, tmp_path, monkeypatch):
    img = noisy_image(tmp_path / "big.png")
    monkeypatch.setenv("FINAL_IMAGE_WIDTH", "800")
    with Image.open(session.apply_final_redactions(1, img, [])) as im:
        assert im.width == 800
    monkeypatch.setenv("FINAL_IMAGE_WIDTH", "5000")  # maior que a imagem: mantem o tamanho
    with Image.open(session.apply_final_redactions(1, img, [])) as im:
        assert im.width == 2000


def test_final_jpeg_quality_is_configurable(session, tmp_path, monkeypatch):
    img = noisy_image(tmp_path / "big.png")
    monkeypatch.setenv("FINAL_JPEG_QUALITY", "20")
    low = os.path.getsize(session.apply_final_redactions(1, img, [], suffix="_LOW"))
    monkeypatch.setenv("FINAL_JPEG_QUALITY", "95")
    high = os.path.getsize(session.apply_final_redactions(1, img, [], suffix="_HIGH"))
    monkeypatch.delenv("FINAL_JPEG_QUALITY")
    default = os.path.getsize(session.apply_final_redactions(1, img, [], suffix="_DEF"))
    assert low < default < high


@pytest.mark.parametrize("bad_width,bad_quality", [("abc", "xyz"), ("0", "0"), ("-5", "200"), ("", "")])
def test_invalid_quality_settings_fall_back_to_defaults(session, tmp_path, monkeypatch, bad_width, bad_quality):
    img = noisy_image(tmp_path / "big.png")
    ref = os.path.getsize(session.apply_final_redactions(1, img, [], suffix="_REF"))
    monkeypatch.setenv("FINAL_IMAGE_WIDTH", bad_width)
    monkeypatch.setenv("FINAL_JPEG_QUALITY", bad_quality)
    out = session.apply_final_redactions(1, img, [], suffix="_BAD")
    with Image.open(out) as im:
        assert im.width == 1240
    assert os.path.getsize(out) == ref


def test_final_redaction_paints_black_box_raw_coordinates(session, tmp_path):
    img = make_blank_image(tmp_path / "w.png", size=(1000, 1000))
    out = session.apply_final_redactions(1, img, [{"x": 100, "y": 100, "w": 200, "h": 100}])
    with Image.open(out) as im:
        assert im.getpixel((200, 150)) == (0, 0, 0) or sum(im.getpixel((200, 150))) < 30
        assert sum(im.getpixel((600, 600))) > 700


def test_final_redaction_scales_boxes_by_source_width(session, tmp_path):
    """Caixa do editor (coordenadas de uma imagem de 500 px) aplicada numa imagem de 1000 px."""
    img = make_blank_image(tmp_path / "w.png", size=(1000, 1000))
    box = {"x": 50, "y": 50, "w": 100, "h": 100, "source_width": 500}
    out = session.apply_final_redactions(1, img, [box])
    with Image.open(out) as im:
        assert sum(im.getpixel((200, 200))) < 30   # (100..300) apos escala 2x
        assert sum(im.getpixel((80, 80))) > 700    # fora da tarja


# --- PDF ----------------------------------------------------------------------------------------
def test_reconstitute_pdf_rejects_empty_and_corrupt_inputs(session, tmp_path):
    assert session.reconstitute_pdf([]) is None
    bad = tmp_path / "bad.png"
    bad.write_bytes(b"not an image")
    good = make_blank_image(tmp_path / "ok.png")
    assert session.reconstitute_pdf([good, str(bad)]) is None
    # nenhum PDF parcial foi entregue
    assert not [f for f in os.listdir(session.doc_finais_dir) if f.endswith("_FINAL.pdf")]


def test_reconstitute_pdf_keeps_original_page_sizes(session, tmp_path):
    imgs = [make_blank_image(tmp_path / f"p{i}.png") for i in range(2)]
    out = session.reconstitute_pdf(imgs, output_suffix="_X.pdf")
    with fitz.open(out) as d, fitz.open(session.pdf_path) as orig:
        assert len(d) == 2
        assert d[0].rect == orig[0].rect


def test_native_redaction_uses_image_width_and_default_scale(session, tmp_path):
    with fitz.open(session.pdf_path) as d:
        page_w = d[0].rect.width
    # image_width == largura da pagina (escala 1:1), em pagina 1; pagina inexistente e ignorada
    box = {"x": 72, "y": 90, "w": 60, "h": 20, "image_width": page_w}
    out = session.apply_native_pdf_redactions({1: [box], 99: [box], 0: [box]})
    assert out and os.path.exists(out)
    with fitz.open(out) as d:
        assert "pagina 1" not in d[0].get_text()  # texto sob a tarja foi removido do conteudo
        assert "pagina 2" in d[1].get_text()


def test_native_redaction_default_assumption_is_1000_dpi(session):
    """Sem source/image_width: assume imagem a 1000 DPI -> caixa gigante em pixels vira pequena em pontos."""
    box = {"x": 1000, "y": 1250, "w": 800, "h": 300}  # ~72..130pt x 90..112pt
    out = session.apply_native_pdf_redactions({1: [box]})
    with fitz.open(out) as d:
        assert "pagina 1" not in d[0].get_text()


def test_native_redaction_missing_pdf_returns_none(tmp_path):
    s = Session(str(tmp_path / "nao_existe.pdf"))
    assert s.apply_native_pdf_redactions({1: []}) is None
    s.close()


def test_native_redaction_error_returns_none(session):
    assert session.apply_native_pdf_redactions({1: [{"x": "a", "y": 0, "w": 1, "h": 1}]}) is None


def test_no_cpf_text_artifacts_after_basic_usage(session, tmp_path):
    session.logger.info(f"x {CPF_A_FMT}")
    session.save_detected_cpfs({CPF_A})
    session.save_ai_interaction("f", "p", CPF_A_FMT, CPF_A, {"m": CPF_A})
    for path in text_files_under(session.output_dir):
        assert not FULL_CPF_RE.search(open(path, encoding="utf-8").read()), path

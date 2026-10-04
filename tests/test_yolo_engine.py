# SPDX-License-Identifier: AGPL-3.0-or-later
import logging
import os
import sys
import types

import pytest
from PIL import Image

from sentry_testkit import make_blank_image
from utils import yolo_engine
from utils.yolo_engine import DEFAULT_MODEL_PATH, YOLOEngine, resolve_model_path


class _Item:
    def __init__(self, v):
        self.v = v

    def tolist(self):
        return list(self.v)

    def item(self):
        return self.v[0] if isinstance(self.v, (list, tuple)) else self.v


class FakeBox:
    def __init__(self, xyxy, conf, cls):
        self.xyxy = [_Item(xyxy)]
        self.conf = [_Item(conf)]
        self.cls = [_Item(cls)]


class FakeModel:
    names = {0: "Signature", 1: "stamp", 2: "assinatura"}
    boxes = []
    raises = False

    def __init__(self, path):
        self.path = path
        self.calls = []

    def __call__(self, img_path, conf, verbose):
        self.calls.append((img_path, conf))
        if FakeModel.raises:
            raise RuntimeError("falha CUDA")
        return [types.SimpleNamespace(boxes=FakeModel.boxes)]


@pytest.fixture()
def fake_ultralytics(monkeypatch):
    FakeModel.boxes = []
    FakeModel.raises = False
    monkeypatch.setitem(sys.modules, "ultralytics", types.SimpleNamespace(YOLO=FakeModel))
    return FakeModel


@pytest.fixture()
def model_file(tmp_path):
    p = tmp_path / "m.pt"
    p.write_bytes(b"weights")
    return str(p)


def test_default_model_path_is_models_dir_signature_detector():
    assert DEFAULT_MODEL_PATH.endswith(os.path.join("models", "signature_stamp_detector.pt"))
    assert resolve_model_path(None) == DEFAULT_MODEL_PATH
    assert resolve_model_path("") == DEFAULT_MODEL_PATH


def test_resolve_relative_path_prefers_cwd_then_repo_root(tmp_path):
    (tmp_path / "meu.pt").write_bytes(b"x")
    assert resolve_model_path("meu.pt") == "meu.pt"  # existe no cwd (tmp_path)
    assert resolve_model_path("models/outro.pt") == os.path.join(yolo_engine.REPO_ROOT, "models/outro.pt")
    absolute = str(tmp_path / "abs.pt")
    assert resolve_model_path(absolute) == absolute


def test_missing_model_degrades_with_clear_warning(tmp_path, caplog):
    logger = logging.getLogger("t_yolo")
    with caplog.at_level(logging.WARNING, logger="t_yolo"):
        eng = YOLOEngine(model_path=str(tmp_path / "nao_existe.pt"), logger=logger)
    assert eng.model is None
    assert "YOLO model not found" in caplog.text and "models" in caplog.text and "YOLO_MODEL_PATH" in caplog.text
    assert eng.get_candidates(str(tmp_path / "x.png")) == ([], [])


def test_engine_without_arguments_uses_default_path_and_tolerates_absent_file():
    if os.path.exists(DEFAULT_MODEL_PATH):
        pytest.skip("modelo padrao presente nesta maquina")
    eng = YOLOEngine()
    assert eng.model is None


def test_loads_model_lazily_and_exposes_names(fake_ultralytics, model_file):
    eng = YOLOEngine(model_file, logging.getLogger("t_yolo2"))
    assert isinstance(eng.model, FakeModel) and eng.model.path == model_file
    assert eng.names[0] == "Signature"


def test_candidates_and_signature_crops(fake_ultralytics, model_file, tmp_path, monkeypatch):
    monkeypatch.setenv("YOLO_CROP_PADDING", "30")
    img = make_blank_image(tmp_path / "page.png", size=(1000, 800))
    crops = tmp_path / "crops"
    crops.mkdir()
    FakeModel.boxes = [
        FakeBox([100, 200, 300, 260], 0.9, 0),       # assinatura -> recorte com padding 30
        FakeBox([10, 10, 60, 40], 0.5, 1),           # carimbo -> so candidato, sem recorte
        FakeBox([950, 780, 990, 799], 0.7, 2),       # 'assinatura' encostada na borda -> padding limitado
        FakeBox([1, 1, 2, 2], 0.3, 99),              # classe desconhecida
    ]
    eng = YOLOEngine(model_file, logging.getLogger("t_yolo3"))
    candidates, meta = eng.get_candidates(img, conf_threshold=0.4, crop_dir=str(crops), page_num=3)
    assert [c["label"] for c in candidates] == ["signature", "stamp", "assinatura", "unknown"]
    assert candidates[0]["conf"] == pytest.approx(0.9) and candidates[0]["cls"] == 0
    assert eng.model.calls == [(img, 0.4)]
    assert eng.last_error is None
    assert len(meta) == 2
    assert meta[0]["origin_bbox"] == (70, 170, 330, 290) and meta[0]["page_num"] == 3
    assert meta[0]["tight_bbox"] == [100, 200, 300, 260]
    assert meta[1]["origin_bbox"] == (920, 750, 1000, 800)  # clamp nas bordas da imagem
    assert sorted(os.listdir(crops)) == ["page_3_yolo_sig_1.jpg", "page_3_yolo_sig_3.jpg"]
    with Image.open(meta[0]["path"]) as crop:
        assert crop.size == (260, 120)


def test_without_crop_dir_no_crops_are_written(fake_ultralytics, model_file, tmp_path):
    img = make_blank_image(tmp_path / "page.png", size=(300, 300))
    FakeModel.boxes = [FakeBox([10, 10, 50, 50], 0.9, 0)]
    eng = YOLOEngine(model_file, logging.getLogger("t_yolo4"))
    candidates, meta = eng.get_candidates(img)
    assert len(candidates) == 1 and meta == []


def test_inference_failure_is_reported_not_silent(fake_ultralytics, model_file, tmp_path, caplog):
    img = make_blank_image(tmp_path / "page.png")
    eng = YOLOEngine(model_file, logging.getLogger("t_yolo5"))
    FakeModel.raises = True
    with caplog.at_level(logging.ERROR, logger="t_yolo5"):
        assert eng.get_candidates(img) == ([], [])
    assert eng.last_error == "falha CUDA" and "YOLO inference failed" in caplog.text
    FakeModel.raises = False
    FakeModel.boxes = []
    eng.get_candidates(img)
    assert eng.last_error is None  # reseta a cada chamada


def test_default_model_must_match_its_sha256(fake_ultralytics, tmp_path, monkeypatch):
    bad = tmp_path / "signature_stamp_detector.pt"
    bad.write_bytes(b"pickle malicioso")
    monkeypatch.setattr(yolo_engine, "DEFAULT_MODEL_PATH", str(bad))
    eng = YOLOEngine(str(bad), logging.getLogger("t_yolo_sha"))
    assert eng.model is None and "recusado" in eng.integrity_error


def test_custom_model_checked_when_sha256_given(fake_ultralytics, model_file, monkeypatch):
    monkeypatch.setenv("YOLO_MODEL_SHA256", "0" * 64)
    assert YOLOEngine(model_file, logging.getLogger("t_yolo_sha2")).model is None
    monkeypatch.setenv("YOLO_MODEL_SHA256", yolo_engine.file_sha256(model_file))
    assert YOLOEngine(model_file, logging.getLogger("t_yolo_sha3")).model is not None


def test_repository_model_matches_pinned_hash():
    if not os.path.exists(DEFAULT_MODEL_PATH):
        pytest.skip("modelo padrao ausente")
    assert yolo_engine.file_sha256(DEFAULT_MODEL_PATH) == yolo_engine.DEFAULT_MODEL_SHA256

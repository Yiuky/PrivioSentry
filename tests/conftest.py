# SPDX-License-Identifier: AGPL-3.0-or-later
import os
import sys

import dotenv
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# O .env do desenvolvedor NAO pode influenciar os testes: neutraliza load_dotenv (main.py/app_service.py o
# chamam no import) e aproveita apenas a localizacao do Tesseract/tessdata, se existir.
_dev_env = dotenv.dotenv_values(os.path.join(ROOT, ".env"))
for _key in ("TESSERACT_PATH", "TESSDATA_PREFIX"):
    if _dev_env.get(_key):
        os.environ.setdefault(_key, _dev_env[_key])
dotenv.load_dotenv = lambda *args, **kwargs: False

# Variaveis que alteram o comportamento do pipeline: cada teste parte de um ambiente limpo e previsivel
# (o .env do desenvolvedor e carregado por main.py no import e NAO deve vazar para os testes).
_ENV_TO_CLEAR = (
    "API_TOKEN", "RETENTION_DAYS", "FINAL_IMAGE_WIDTH", "FINAL_JPEG_QUALITY", "YOLO_MODEL_PATH",
    "TESSERACT_SPARSE_PSM", "TESSERACT_STD_PSM", "TESSERACT_CROP_PSM", "VERIFY_OCR", "VERIFY_DPI",
    "BASE_DPI", "DEBUG_LEVEL", "YOLO_CROP_PADDING", "PRIVIO_TASKS_FILE", "PRIVIO_INPUT_DIR",
    "PRIVIO_OUTPUT_DIR", "PRIVIO_FINAL_DIR", "GATEKEEPER_STATE_FILE", "GATEKEEPER_PORT", "APP_PORT",
    "APP_HOST", "MAX_UPLOAD_MB", "AI_IMAGE_RESOLUTION", "AI_CONTEXT_WINDOW", "OLLAMA_TEXT_TIMEOUT",
    "OLLAMA_VISION_TIMEOUT",
)


@pytest.fixture(autouse=True)
def isolated_environment(request, tmp_path, monkeypatch):
    """Isola cada teste: cwd e diretorios de estado em tmp_path (nunca toca output/, WEB_INPUT/ ou tasks.json
    reais) e ambiente limpo. Nao se aplica a tests/ui (outro dono)."""
    if f"{os.sep}ui{os.sep}" in str(request.fspath):
        yield
        return
    for name in _ENV_TO_CLEAR:
        monkeypatch.delenv(name, raising=False)
    # O TestClient usa o Host "testserver"; a proteção de Host (utils/net_guard.py) o aceita só nos testes.
    monkeypatch.setenv("ALLOWED_HOSTS", "testserver")
    (tmp_path / "state").mkdir(exist_ok=True)
    monkeypatch.setenv("PRIVIO_TASKS_FILE", str(tmp_path / "state" / "tasks.json"))
    monkeypatch.setenv("PRIVIO_INPUT_DIR", str(tmp_path / "state" / "in"))
    monkeypatch.setenv("PRIVIO_OUTPUT_DIR", str(tmp_path / "state" / "output"))
    monkeypatch.setenv("PRIVIO_FINAL_DIR", str(tmp_path / "state" / "final"))
    monkeypatch.setenv("GATEKEEPER_STATE_FILE", str(tmp_path / "state" / "gatekeeper_state"))
    monkeypatch.setenv("TESSERACT_SPARSE_PSM", "")
    monkeypatch.chdir(tmp_path)
    yield


@pytest.fixture(scope="session")
def ocr_config():
    """(caminho_tesseract, idioma) ou skip se o Tesseract nao estiver disponivel."""
    from benchmarks.env import get_ocr_config
    cfg = get_ocr_config()
    if not cfg:
        pytest.skip("Tesseract nao encontrado (defina TESSERACT_PATH)")
    return cfg


@pytest.fixture()
def real_ocr(ocr_config):
    from utils.ocr_engine import OCREngine
    path, lang = ocr_config
    return OCREngine(tesseract_path=path, lang=lang)

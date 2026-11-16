# SPDX-License-Identifier: AGPL-3.0-or-later
"""Administração mais fácil: valor EM USO de cada item (lido pelas funções do pipeline), painel /admin/status só com
fatos e contagens, e contagem da fila por situação. Sem Tesseract, YOLO nem rede de verdade (I-08)."""
import importlib
import json
import os

import pytest

pytest.importorskip("fastapi")

from utils import admin_status, settings  # noqa: E402

KEYS = [f["key"] for f in settings.FIELDS]


@pytest.fixture()
def clean_env(monkeypatch):
    for key in KEYS + ["OLLAMA_API_URL", "OLLAMA_VISION_MODEL", "OLLAMA_MODEL", "OLLAMA_VISION_TIMEOUT"]:
        monkeypatch.delenv(key, raising=False)
    return monkeypatch


@pytest.fixture()
def svc(monkeypatch):
    import app_service
    importlib.reload(app_service)
    monkeypatch.setattr(app_service, "start_worker", lambda tid, **kw: None)
    monkeypatch.setattr(admin_status, "tesseract", lambda: {"encontrado": True, "versao": "5.0.0", "do_path": True})
    monkeypatch.setattr(admin_status, "yolo", lambda: {"pacote": True, "modelo": True})
    from fastapi.testclient import TestClient
    return TestClient(app_service.app), app_service


def by_key(state):
    return {f["key"]: f for f in state["campos"]}


# ------------------------------------------------------------------ valor em uso
def test_in_use_values_come_from_the_pipeline_readers(clean_env):
    from utils import doc_templates, ratelimit, second_look, session, verifier
    from utils.detect import profiles
    eff = settings.effective()
    assert eff["DOC_TEMPLATES"] == ("1" if doc_templates.enabled() else "0") == "1"   # ligado por padrão
    assert eff["VERIFY_OCR"] == "1" and eff["SECOND_LOOK"] == ("1" if second_look.enabled() else "0") == "0"
    assert eff["BASE_DPI"] == str(session.render_dpi()) and eff["VERIFY_DPI"] == str(verifier.verify_dpi())
    assert eff["POLICY_PROFILE"] == profiles.active_profile_id()
    assert eff["DOC_TEMPLATE_INSPECTION"] == doc_templates.inspection_mode()
    assert eff["AI_LIMIT_RETRY_MINUTES"] == "60" == settings._num(ratelimit.retry_minutes())
    assert eff["SECOND_LOOK_MODEL"] == second_look.model()


def test_in_use_values_follow_the_legacy_ollama_variables(clean_env):
    # o .env antigo (OLLAMA_*) define o modelo e o servidor: a tela não pode mostrar um "padrão" que não é o usado
    clean_env.setenv("OLLAMA_API_URL", "http://10.0.0.5:11434")
    clean_env.setenv("OLLAMA_VISION_MODEL", "modelo-do-env")
    clean_env.setenv("OLLAMA_VISION_TIMEOUT", "900")
    eff = settings.effective()
    assert eff["AI_BASE_URL"] == "http://10.0.0.5:11434" and eff["AI_VISION_MODEL"] == "modelo-do-env"
    assert eff["AI_VISION_TIMEOUT"] == "900" and eff["SECOND_LOOK_MODEL"] == "modelo-do-env"


@pytest.mark.parametrize("url, expected", [("https://api.openai.com/v1", "12"), ("http://localhost:11434", "0")])
def test_requests_per_minute_in_use_depends_on_the_destination(clean_env, url, expected):
    from utils import egress
    clean_env.setattr(egress, "is_external", lambda u: "openai" in u)
    clean_env.setenv("AI_PROVIDER", "openai")
    clean_env.setenv("AI_BASE_URL", url)
    assert settings.effective()["AI_REQUESTS_PER_MINUTE"] == expected


def test_switched_off_values_are_shown_as_off(clean_env):
    clean_env.setenv("DOC_TEMPLATES", "0")
    clean_env.setenv("VERIFY_OCR", "0")
    eff = settings.effective()
    assert eff["DOC_TEMPLATES"] == "0" and eff["VERIFY_OCR"] == "0"                 # contra-teste


def test_empty_value_in_env_counts_as_not_set(clean_env):
    clean_env.setenv("AI_BASE_URL", "")
    item = by_key(settings.describe())["AI_BASE_URL"]
    assert item["origem"] == "padrao" and item["efetivo"]


def test_choices_have_readable_labels_and_secrets_have_no_value(clean_env):
    items = by_key(settings.describe())
    assert items["POLICY_PROFILE"]["labels"]["cpf_endereco"] == "Só CPF e endereço residencial"
    assert items["AI_LIMIT_ACTION"]["labels"]["pendente"].startswith("Deixar pendente")
    assert items["AI_API_KEY"]["efetivo"] is None and items["AI_API_KEY"]["valor"] is None
    assert not any(f["advanced"] for f in settings.FIELDS if f["key"] == "AI_ALLOW_EXTERNAL")   # nunca escondido


def test_restart_items_show_the_value_the_service_started_with(svc, monkeypatch):
    c, mod = svc
    items = by_key(c.get("/admin/settings").json())
    assert items["MAX_PARALLEL_TASKS"]["efetivo"] == str(mod.MAX_PARALLEL_TASKS)
    assert items["MAX_UPLOAD_MB"]["efetivo"] == str(mod.MAX_UPLOAD_BYTES // (1024 * 1024))


# ------------------------------------------------------------------ painel
def test_status_has_only_facts_and_counts(svc):
    c, mod = svc
    mod.tasks.update({
        "a": {"file": "contrato_fulano_segredo.pdf", "input_path": "x", "completed": True, "needs_review": True,
              "alerts": ["Página 1: CPF 529.982.247-25 sem tarja"]},
        "b": {"file": "b.pdf", "input_path": "x", "pendente": True, "pendente_ate": 4102444800},
        "c": {"file": "c.pdf", "input_path": "x", "completed": True, "finalizado": True},
        "d": {"file": "d.pdf", "input_path": "x", "completed": True},
        "e": {"file": "e.pdf", "input_path": "x", "error": True, "status": "Erro: falhou"},
    })
    r = c.get("/admin/status")
    assert r.status_code == 200
    body = r.json()
    q = body["fila"]
    assert (q["requer_revisao"], q["pendente"], q["aprovado"], q["preliminar"], q["erro"], q["total"]) == (1, 1, 1, 1, 1, 5)
    assert q["proxima_tentativa"] == 4102444800
    text = r.text
    assert "fulano" not in text and "529.982" not in text and "sem tarja" not in text and "falhou" not in text
    assert {x["id"] for x in body["verificacoes"]} >= {"ocr", "yolo", "ia_principal", "saida", "verificacao"}


def test_status_flags_what_needs_attention(svc, monkeypatch):
    c, _ = svc
    monkeypatch.setattr(admin_status, "tesseract", lambda: {"encontrado": False, "versao": None, "do_path": True})
    monkeypatch.setattr(admin_status, "yolo", lambda: {"pacote": False, "modelo": True})
    monkeypatch.setenv("VERIFY_OCR", "0")
    levels = {x["id"]: x["nivel"] for x in c.get("/admin/status").json()["verificacoes"]}
    assert levels["ocr"] == "erro" and levels["yolo"] == "erro" and levels["verificacao"] == "aviso"


def test_status_says_all_ok_when_everything_is_there(svc, monkeypatch):
    c, _ = svc
    monkeypatch.delenv("VERIFY_OCR", raising=False)
    levels = {x["id"]: x["nivel"] for x in c.get("/admin/status").json()["verificacoes"]}
    assert levels["ocr"] == levels["yolo"] == levels["verificacao"] == "ok"                 # contra-teste


def test_external_server_without_permission_is_an_error_in_the_panel(svc, monkeypatch):
    from utils import egress
    c, _ = svc
    monkeypatch.setattr(egress, "is_external", lambda url: "nuvem" in url)
    monkeypatch.setenv("AI_PROVIDER", "openai")
    monkeypatch.setenv("AI_BASE_URL", "https://api.nuvem.example/v1")
    monkeypatch.setenv("AI_ALLOW_EXTERNAL", "0")
    item = next(x for x in c.get("/admin/status").json()["verificacoes"] if x["id"] == "ia_principal")
    assert item["nivel"] == "erro" and item["dados"]["bloqueado"]


def test_status_follows_the_admin_switch(svc, monkeypatch):
    c, _ = svc
    monkeypatch.setenv("ADMIN_ENABLED", "0")
    assert c.get("/admin/status").status_code == 404


def test_status_needs_the_token(monkeypatch):
    monkeypatch.setenv("API_TOKEN", "t0k3n")
    import app_service
    importlib.reload(app_service)
    from fastapi.testclient import TestClient
    assert TestClient(app_service.app).get("/admin/status").status_code == 401


def test_tesseract_check_survives_a_missing_or_broken_executable(monkeypatch, tmp_path):
    monkeypatch.setenv("TESSERACT_PATH", str(tmp_path / "nao_existe.exe"))
    assert admin_status.tesseract()["encontrado"] is False
    fake = tmp_path / "tesseract.exe"
    fake.write_bytes(b"x")
    monkeypatch.setenv("TESSERACT_PATH", str(fake))
    monkeypatch.setattr(admin_status, "_tesseract_version", lambda exe: None)       # não executa
    admin_status._cache.clear()
    assert admin_status.tesseract()["encontrado"] is False


def test_disk_usage_counts_files_and_is_cached(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "f.bin").write_bytes(b"x" * 1000)
    admin_status._cache.clear()
    first = admin_status.disk([str(tmp_path)])
    (tmp_path / "a" / "g.bin").write_bytes(b"y" * 10)
    assert first == {"bytes": 1000, "arquivos": 1, "parcial": False}
    assert admin_status.disk([str(tmp_path)]) == first                              # cache de 1 minuto
    admin_status._cache.clear()
    assert admin_status.disk([str(tmp_path)])["arquivos"] == 2


def test_saving_one_item_does_not_write_the_others(clean_env):
    settings.save({"BASE_DPI": "250"})
    with open(settings.path(), encoding="utf-8") as fh:
        saved = json.load(fh)["values"]
    assert saved == {"BASE_DPI": "250"} and os.getenv("VERIFY_OCR") is None

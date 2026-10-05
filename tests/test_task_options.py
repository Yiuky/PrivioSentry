# SPDX-License-Identifier: AGPL-3.0-or-later
"""Opções por documento (utils/task_options.py e app_service): validação no servidor, padrões, aplicação isolada."""
import importlib
import os
import uuid

import pytest

from utils import task_options

pytest.importorskip("fastapi")

PDF = b"%PDF-1.4\n%fake\n"


@pytest.fixture()
def installed(monkeypatch):
    """Controla o que 'está instalado' (gliner/rapidocr) sem instalar nada."""
    state = {"gliner": True, "rapidocr": True}
    monkeypatch.setattr(task_options, "_installed", lambda pkg: state.get(pkg, False))
    return state


# --- resolve: testes ---------------------------------------------------------------------------------
def test_resolve_full_choice(installed):
    opts = task_options.resolve("lgpd_publicacao", "sim", "1")
    assert opts == {"perfil": "lgpd_publicacao", "nomes": True, "baixa_qualidade": True,
                    "segundo_olhar": True, "leitura_extra": True}


def test_resolve_without_fields_uses_env_defaults(installed, monkeypatch):
    monkeypatch.setenv("POLICY_PROFILE", "gdpr")
    monkeypatch.setenv("NER_ENGINE", "gliner")
    opts = task_options.resolve()
    assert opts["perfil"] == "gdpr" and opts["nomes"] is True and opts["baixa_qualidade"] is False


def test_low_quality_without_rapidocr_still_turns_on_second_look(installed):
    installed["rapidocr"] = False
    opts = task_options.resolve("cpf_endereco", "0", "1")
    assert opts["segundo_olhar"] is True and opts["leitura_extra"] is False


# --- resolve: contratestes ---------------------------------------------------------------------------
@pytest.mark.parametrize("perfil, nomes, low, msg", [
    ("inexistente", None, None, "Perfil desconhecido"),
    ("cpf_endereco", "1", None, "não procura nomes"),       # nomes num perfil que não procura nomes
    ("lgpd_publicacao", "talvez", None, "Valor inválido"),
    ("lgpd_publicacao", None, "x", "Valor inválido"),
])
def test_resolve_rejects_inconsistent_choices(installed, perfil, nomes, low, msg):
    with pytest.raises(task_options.OptionsError, match=msg):
        task_options.resolve(perfil, nomes, low)


def test_resolve_rejects_names_when_detector_is_not_installed(installed):
    installed["gliner"] = False
    with pytest.raises(task_options.OptionsError, match="detector de nomes instalado"):
        task_options.resolve("lgpd_publicacao", "1", "0")


def test_catalog_explains_what_is_missing(installed):
    installed.update(gliner=False, rapidocr=False)
    cat = task_options.catalog()
    assert {p["id"] for p in cat["perfis"]} == {"cpf_endereco", "lgpd_publicacao", "lgpd_interno", "gdpr", "saude_hipaa"}
    assert cat["disponivel"] == {"nomes": False, "leitura_extra": False, "segundo_olhar": True}
    assert "pip install" in cat["motivos"]["nomes"] and "segundo olhar" in cat["motivos"]["leitura_extra"]
    assert {p["id"]: p["pede_nomes"] for p in cat["perfis"]}["cpf_endereco"] is False


# --- aplicação no processo da tarefa ------------------------------------------------------------------
def test_apply_sets_only_this_process_variables():
    env = {"POLICY_PROFILE": "cpf_endereco", "OUTRA": "x"}
    task_options.apply_to_environment({"perfil": "gdpr", "nomes": True, "segundo_olhar": True,
                                       "leitura_extra": False}, env)
    assert env == {"POLICY_PROFILE": "gdpr", "NER_ENGINE": "gliner", "SECOND_LOOK": "1", "OCR_EXTRA_ENGINE": "",
                   "OUTRA": "x"}
    untouched = {"POLICY_PROFILE": "cpf_endereco"}
    assert task_options.apply_to_environment(None, untouched) == {} and untouched == {"POLICY_PROFILE": "cpf_endereco"}


def test_worker_applies_options_before_building_the_pipeline(monkeypatch):
    import app_service
    seen = {}

    class FakeApp:
        def __init__(self, *a, **k):
            seen["perfil"] = os.environ.get("POLICY_PROFILE")
            seen["second"] = os.environ.get("SECOND_LOOK")

        def run(self, **k):
            pass

        def final_state(self):
            return {}
    monkeypatch.setattr(app_service, "SentryApp", FakeApp)
    monkeypatch.setattr(app_service.httpx, "Client", lambda **k: type("C", (), {
        "__enter__": lambda s: s, "__exit__": lambda s, *a: None, "post": lambda s, *a, **kw: None})())
    # o worker grava as opções no ambiente (no app, é o processo da tarefa): o monkeypatch restaura depois,
    # senão vazariam para os testes seguintes
    for name in ("POLICY_PROFILE", "NER_ENGINE", "SECOND_LOOK", "OCR_EXTRA_ENGINE"):
        monkeypatch.setenv(name, "")
    monkeypatch.setenv("POLICY_PROFILE", "cpf_endereco")
    app_service.redaction_worker("t", "x.pdf", options={"perfil": "saude_hipaa", "nomes": False,
                                                        "segundo_olhar": True, "leitura_extra": False})
    assert seen == {"perfil": "saude_hipaa", "second": "1"}


# --- API ---------------------------------------------------------------------------------------------
@pytest.fixture()
def client(monkeypatch, installed):
    import app_service
    importlib.reload(app_service)
    started = []
    monkeypatch.setattr(app_service, "start_worker", lambda tid, **kw: started.append(tid))
    from fastapi.testclient import TestClient
    c = TestClient(app_service.app)
    c.mod, c.started = app_service, started
    return c


def test_options_route(client):
    data = client.get("/options").json()
    assert data["padrao"]["perfil"] == "cpf_endereco" and len(data["perfis"]) == 5


def test_upload_stores_options_and_starts_worker(client):
    r = client.post("/upload", files={"file": ("a.pdf", PDF, "application/pdf")},
                    data={"perfil": "lgpd_publicacao", "nomes": "1", "baixa_qualidade": "1"})
    assert r.status_code == 200
    tid = r.json()["task_id"]
    assert client.mod.tasks[tid]["options"]["perfil"] == "lgpd_publicacao" and client.started == [tid]


def test_upload_without_options_keeps_working_like_before(client):
    r = client.post("/upload", files={"file": ("a.pdf", PDF, "application/pdf")})
    assert r.status_code == 200
    assert client.mod.tasks[r.json()["task_id"]]["options"]["perfil"] == "cpf_endereco"


@pytest.mark.parametrize("data", [{"perfil": "hack"}, {"perfil": "cpf_endereco", "nomes": "1"},
                                  {"baixa_qualidade": "<script>"}])
def test_upload_rejects_bad_options_and_creates_nothing(client, data):
    r = client.post("/upload", files={"file": ("a.pdf", PDF, "application/pdf")}, data=data)
    assert r.status_code == 400 and client.mod.tasks == {} and client.started == []
    assert os.listdir(client.mod.INPUT_DIR) == [] if os.path.isdir(client.mod.INPUT_DIR) else True


def test_reprocess_keeps_the_options(client, monkeypatch):
    r = client.post("/upload", files={"file": ("a.pdf", PDF, "application/pdf")}, data={"perfil": "gdpr"})
    tid = r.json()["task_id"]
    client.mod.tasks[tid]["completed"] = True
    assert client.post(f"/reprocess/{tid}").status_code == 200
    assert client.mod.tasks[tid]["options"]["perfil"] == "gdpr"


def test_start_worker_passes_the_task_options_to_the_process(monkeypatch):
    import app_service
    importlib.reload(app_service)
    created = []

    class FakeProc:
        def __init__(self, target, args):
            created.append(args)

        def start(self):
            pass

        def is_alive(self):
            return True
    monkeypatch.setattr(app_service.multiprocessing, "Process", FakeProc)
    tid = str(uuid.uuid4())
    inp = os.path.join(app_service.INPUT_DIR, "o.pdf")
    os.makedirs(app_service.INPUT_DIR, exist_ok=True)
    open(inp, "wb").write(PDF)
    app_service.tasks[tid] = {"input_path": inp, "status": "x", "options": {"perfil": "gdpr"}}
    app_service.start_worker(tid)
    assert created[0][-1] == {"perfil": "gdpr"}

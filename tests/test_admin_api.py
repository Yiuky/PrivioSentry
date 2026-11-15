# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tela Admin (utils/settings.py + /admin/*), modo só-API e rotas para clientes da API e agentes."""
import importlib
import json
import os

import pytest

pytest.importorskip("fastapi")

from test_ai_backends import openai_chat  # noqa: E402
from test_ai_client import FakeOllama  # noqa: E402
from utils import egress, settings  # noqa: E402

PDF = b"%PDF-1.4\n%fake\n"


@pytest.fixture()
def svc(monkeypatch):
    import app_service
    importlib.reload(app_service)
    monkeypatch.setattr(app_service, "start_worker", lambda tid, **kw: None)
    from fastapi.testclient import TestClient
    return TestClient(app_service.app), app_service


def upload(c):
    r = c.post("/upload", files={"file": ("doc.pdf", PDF)})
    assert r.status_code == 200, r.text
    return r.json()["task_id"]


def field(state, key):
    return next(f for f in state["campos"] if f["key"] == key)


# ------------------------------------------------------------------ configuração
def test_saved_values_reach_the_environment_and_reset_restores_env(monkeypatch):
    monkeypatch.setenv("AI_VISION_MODEL", "do-env")
    settings.save({"AI_VISION_MODEL": "do-admin", "BASE_DPI": "300"})
    assert os.environ["AI_VISION_MODEL"] == "do-admin" and os.environ["BASE_DPI"] == "300"
    settings.save({"AI_VISION_MODEL": None})
    assert os.environ["AI_VISION_MODEL"] == "do-env"                       # voltou ao .env/ambiente


def test_secret_is_write_only_and_blank_keeps_it(svc):
    c, _ = svc
    r = c.post("/admin/settings", json={"values": {"AI_API_KEY": "sk-segredo-123"}})
    assert r.status_code == 200 and "sk-segredo-123" not in r.text
    key = field(r.json(), "AI_API_KEY")
    assert key["definido"] is True and key["valor"] is None
    c.post("/admin/settings", json={"values": {"AI_API_KEY": ""}})          # campo em branco = manter
    assert os.environ["AI_API_KEY"] == "sk-segredo-123"
    assert "sk-segredo-123" not in c.get("/admin/settings").text
    assert "sk-segredo-123" not in c.get("/health/ai").text
    assert "sk-segredo-123" not in c.get("/api/info").text


def test_invalid_values_are_rejected_and_nothing_is_saved(svc):
    c, _ = svc
    for bad in ({"BASE_DPI": "9999"}, {"AI_BASE_URL": "file:///etc/passwd"}, {"POLICY_PROFILE": "inventado"},
                {"API_TOKEN": "x"}, {"APP_HOST": "0.0.0.0"}, {"AI_VISION_MODEL": "a\nb"}):
        r = c.post("/admin/settings", json={"values": bad})
        assert r.status_code == 400, bad
    assert not os.path.exists(settings.path())


def test_restart_items_are_flagged(svc):
    c, _ = svc
    state = c.post("/admin/settings", json={"values": {"MAX_PARALLEL_TASKS": "4"}}).json()
    assert field(state, "MAX_PARALLEL_TASKS")["pendente_reinicio"] is True
    assert field(state, "BASE_DPI")["pendente_reinicio"] is False


def test_external_consent_is_recorded_and_cleared(svc):
    c, _ = svc
    state = c.post("/admin/settings", json={"values": {"AI_ALLOW_EXTERNAL": "sim"}}).json()
    assert state["externo_liberado_em"] and state["ia"]["externo_permitido"] is True
    state = c.post("/admin/settings", json={"values": {"AI_ALLOW_EXTERNAL": "0"}}).json()
    assert state["externo_liberado_em"] is None and state["ia"]["externo_permitido"] is False


def test_settings_file_is_ignored_by_git_and_docker():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for name in (".gitignore", ".dockerignore"):
        with open(os.path.join(root, name), encoding="utf-8") as fh:
            assert "privio_settings.json" in fh.read().split(), name


def test_admin_can_be_switched_off(svc, monkeypatch):
    c, _ = svc
    monkeypatch.setenv("ADMIN_ENABLED", "0")
    assert c.get("/admin").status_code == 404
    assert c.get("/admin/settings").status_code == 404
    assert c.post("/admin/settings", json={"values": {"BASE_DPI": "300"}}).status_code == 404


def test_admin_writes_from_another_site_are_refused(svc):
    c, _ = svc
    r = c.post("/admin/settings", json={"values": {"AI_BASE_URL": "https://atacante.example"}},
               headers={"Origin": "https://atacante.example"})
    assert r.status_code == 403 and not os.path.exists(settings.path())


def test_admin_page_is_served(svc):
    c, _ = svc
    r = c.get("/admin")
    assert r.status_code == 200 and "Administração" in r.text


# ------------------------------------------------------------------ teste da IA
def test_ai_test_reports_ok_without_echoing_the_server_body(svc, monkeypatch):
    c, _ = svc
    srv = FakeOllama([openai_chat('{"ok": true, "eco": "nao-devolver"}')])
    try:
        c.post("/admin/settings", json={"values": {"AI_PROVIDER": "openai", "AI_BASE_URL": srv.url + "/v1",
                                                   "AI_VISION_MODEL": "m"}})
        r = c.post("/admin/ai/test")
        assert r.status_code == 200 and r.json()["ok"] is True and "nao-devolver" not in r.text
        assert "Responda" in json.dumps(srv.requests[0])                   # só o pedido curto, sem documento
    finally:
        srv.stop()


def test_ai_test_for_missing_reserve_is_404(svc):
    c, _ = svc
    assert c.post("/admin/ai/test?papel=reserva").status_code == 404


# ------------------------------------------------------------------ API e modo só-API
def test_api_only_mode_has_no_portal(svc, monkeypatch):
    c, _ = svc
    monkeypatch.setenv("PORTAL_ENABLED", "0")
    r = c.get("/")
    assert r.json()["portal"] is False and c.get("/admin").status_code == 404
    assert c.get("/api/info").json()["portal"] is False


def test_no_cdn_docs_but_openapi_is_local(svc):
    c, _ = svc
    assert c.get("/docs").status_code == 404 and c.get("/redoc").status_code == 404
    spec = c.get("/openapi.json").json()
    assert "/tasks/{task_id}" in spec["paths"] and "/admin/settings" in spec["paths"]


def test_healthz_needs_no_token_but_everything_else_does(monkeypatch):
    monkeypatch.setenv("API_TOKEN", "t0k3n")
    import app_service
    importlib.reload(app_service)
    from fastapi.testclient import TestClient
    c = TestClient(app_service.app)
    assert c.get("/healthz").json() == {"ok": True}
    assert c.get("/api/info").status_code == 401
    assert c.get("/api/info", headers={"X-API-Token": "t0k3n"}).json()["token_exigido"] is True


def test_single_task_route_hides_server_paths(svc):
    c, mod = svc
    tid = upload(c)
    data = c.get(f"/tasks/{tid}").json()
    assert data["task_id"] == tid and "input_path" not in data and data["pdf_disponivel"] is False
    assert c.get("/tasks/nao-e-uuid").status_code == 404


def test_final_download_requires_reviewer_approval(svc):
    c, mod = svc
    tid = upload(c)
    os.makedirs(mod.FINAL_DIR, exist_ok=True)
    with open(mod.final_pdf_path(mod.tasks[tid]), "wb") as fh:
        fh.write(PDF)
    mod.tasks[tid].update(completed=True, needs_review=False, finalizado=False)
    assert c.get(f"/download/{tid}").status_code == 200                    # portal: comportamento de antes
    assert c.get(f"/download/{tid}?final=true").status_code == 409         # preliminar: agente não recebe
    mod.tasks[tid].update(finalizado=True, needs_review=True)
    assert c.get(f"/download/{tid}?final=true").status_code == 409         # aprovado mas com pendência
    mod.tasks[tid].update(needs_review=False)
    assert c.get(f"/download/{tid}?final=true").status_code == 200


def test_reprocess_clears_approval_and_external_mark(svc, monkeypatch):
    c, mod = svc
    tid = upload(c)
    mod.tasks[tid].update(finalizado=True, ia_externa=["api.exemplo"], completed=True)
    monkeypatch.setattr(mod, "is_running", lambda t: False)
    assert c.post(f"/reprocess/{tid}").status_code == 200
    assert mod.tasks[tid]["finalizado"] is False and "ia_externa" not in mod.tasks[tid]


def test_api_info_lists_external_ai_only_when_allowed(svc, monkeypatch):
    c, _ = svc
    monkeypatch.setattr(egress, "is_external", lambda url: "nuvem" in url)
    monkeypatch.setenv("AI_PROVIDER", "openai")
    monkeypatch.setenv("AI_BASE_URL", "https://api.nuvem.example/v1")
    assert c.get("/api/info").json()["ia_externa"] == []                   # bloqueada: nada sai
    monkeypatch.setenv("AI_ALLOW_EXTERNAL", "1")
    assert c.get("/api/info").json()["ia_externa"] == ["api.nuvem.example"]


def test_final_state_names_external_ai_used(monkeypatch, tmp_path):
    from main import SentryApp
    monkeypatch.setattr(egress, "_sent", {"api.nuvem.example"})
    app = SentryApp.__new__(SentryApp)
    app.review_pages, app.alerts, app.review_marks, app.timings = {}, [], [], {}
    app.policy_profile, app.pii_summary = "cpf_endereco", {}
    app.pii_found = lambda: []
    assert app.final_state()["ia_externa"] == ["api.nuvem.example"]


def test_changing_the_server_drops_its_key_and_the_external_permission(svc, monkeypatch):
    """A chave de um provedor nunca segue para outro host, e destino novo exige nova confirmação (I-04, I-12)."""
    c, _ = svc
    c.post("/admin/settings", json={"values": {"AI_PROVIDER": "openai", "AI_BASE_URL": "https://api.a.example/v1",
                                               "AI_API_KEY": "sk-do-provedor-a", "AI_ALLOW_EXTERNAL": "1"}})
    assert os.environ["AI_API_KEY"] == "sk-do-provedor-a" and os.environ["AI_ALLOW_EXTERNAL"] == "1"
    c.post("/admin/settings", json={"values": {"AI_VISION_MODEL": "outro-modelo"}})      # mesmo host: mantém
    assert os.environ["AI_API_KEY"] == "sk-do-provedor-a"
    c.post("/admin/settings", json={"values": {"AI_BASE_URL": "https://api.a.example/v2"}})  # mesmo host
    assert os.environ["AI_API_KEY"] == "sk-do-provedor-a" and os.environ["AI_ALLOW_EXTERNAL"] == "1"
    state = c.post("/admin/settings", json={"values": {"AI_BASE_URL": "https://atacante.example/v1"}}).json()
    assert os.environ["AI_API_KEY"] == "" and os.environ["AI_ALLOW_EXTERNAL"] == "0"
    assert field(state, "AI_API_KEY")["definido"] is False


def test_a_key_from_env_is_also_dropped_when_the_server_changes(svc, monkeypatch):
    c, _ = svc
    monkeypatch.setenv("AI_BASE_URL", "https://api.a.example/v1")
    monkeypatch.setenv("AI_API_KEY", "sk-do-env")
    c.post("/admin/settings", json={"values": {"AI_BASE_URL": "http://localhost:1234/v1"}})
    assert os.environ["AI_API_KEY"] == ""


def test_switching_provider_with_key_and_permission_in_one_save_keeps_them(svc):
    c, _ = svc
    c.post("/admin/settings", json={"values": {"AI_BASE_URL": "https://api.b.example/v1", "AI_API_KEY": "sk-b",
                                               "AI_ALLOW_EXTERNAL": "1"}})
    assert os.environ["AI_API_KEY"] == "sk-b" and os.environ["AI_ALLOW_EXTERNAL"] == "1"


def test_unwritable_settings_file_is_a_clear_error(svc, monkeypatch):
    c, _ = svc

    def boom(data):
        raise PermissionError("negado")
    monkeypatch.setattr(settings, "_write", boom)
    r = c.post("/admin/settings", json={"values": {"BASE_DPI": "300"}})
    assert r.status_code == 500 and "privio_settings" in r.json()["detail"]


def test_cli_applies_admin_settings(monkeypatch, tmp_path):
    import main
    settings.save({"BASE_DPI": "250"})
    monkeypatch.delenv("BASE_DPI", raising=False)
    assert main.cli(["--input", str(tmp_path / "vazio")]) == 1                # sem PDFs: só confere o ambiente
    assert os.environ["BASE_DPI"] == "250"


def test_example_token_from_the_k8s_template_is_refused(monkeypatch):
    monkeypatch.setenv("API_TOKEN", "troque-por-um-token-longo-e-aleatorio")
    import app_service
    with pytest.raises(SystemExit):
        importlib.reload(app_service)
    monkeypatch.setenv("API_TOKEN", "")
    importlib.reload(app_service)


def test_agent_model_falls_back_to_the_main_vision_model(monkeypatch):
    from utils import second_look
    monkeypatch.setenv("AI_VISION_MODEL", "modelo-principal")
    assert second_look.model() == "modelo-principal"
    monkeypatch.setenv("SECOND_LOOK_BASE_URL", "http://outro:1234/v1")       # outro servidor: não supõe o modelo
    assert second_look.model() == "gemma4:e4b"
    monkeypatch.setenv("SECOND_LOOK_MODEL", "agente")
    assert second_look.model() == "agente"

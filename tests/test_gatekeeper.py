# SPDX-License-Identifier: AGPL-3.0-or-later
"""Gatekeeper (proxy + watchdog) com TestClient e subprocesso/HTTP falsos."""
import asyncio
import importlib
import json
import logging
import sys

import httpx
import pytest

pytest.importorskip("fastapi")

REAL_ASYNC_CLIENT = httpx.AsyncClient


@pytest.fixture()
def gk(monkeypatch, tmp_path):
    import gatekeeper
    importlib.reload(gatekeeper)
    monkeypatch.setattr(gatekeeper.time, "sleep", lambda s: None)
    monkeypatch.setattr(gatekeeper, "kill_port_owner", lambda port: None)
    return gatekeeper


class FakeProcess:
    instances = []

    def __init__(self, cmd, **kwargs):
        self.cmd, self.kwargs = cmd, kwargs
        self.pid = 4242
        self.exit_code = None
        self.terminated = False
        FakeProcess.instances.append(self)

    def poll(self):
        return self.exit_code

    def terminate(self):
        self.terminated = True


@pytest.fixture()
def fake_popen(gk, monkeypatch):
    FakeProcess.instances = []
    monkeypatch.setattr(gk.subprocess, "Popen", FakeProcess)
    return FakeProcess


def mock_upstream(monkeypatch, gk, handler):
    """Faz o gatekeeper falar com um 'app_service' falso via httpx.MockTransport."""
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(gk.httpx, "AsyncClient", lambda **kw: REAL_ASYNC_CLIENT(transport=transport, **kw))


# --- configuracao por ambiente e estado persistido ----------------------------------------------
def test_ports_and_state_file_come_from_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_PORT", "9101")
    monkeypatch.setenv("GATEKEEPER_PORT", "9100")
    import gatekeeper
    importlib.reload(gatekeeper)
    assert gatekeeper.state.app_port == 9101 and gatekeeper.state.gatekeeper_ports == [9100]
    assert gatekeeper.state.state_file == str(tmp_path / "state" / "gatekeeper_state")


def test_state_roundtrip_and_restore_on_import(monkeypatch, tmp_path):
    import gatekeeper
    importlib.reload(gatekeeper)
    gatekeeper.state.should_run = True
    (tmp_path / "state").mkdir(exist_ok=True)
    gatekeeper.state.save_state()
    assert json.load(open(gatekeeper.state.state_file)) == {"should_run": True}
    importlib.reload(gatekeeper)       # novo import le o estado salvo (restaura apos reinicio)
    assert gatekeeper.state.should_run is True


def test_state_load_corrupt_and_save_failure_are_logged(gk, caplog, tmp_path):
    (tmp_path / "state").mkdir(exist_ok=True)
    open(gk.state.state_file, "w").write("{ruim")
    gk.state.should_run = False
    with caplog.at_level(logging.ERROR, logger="Gatekeeper"):
        gk.state.load_state()
    assert gk.state.should_run is False and "Erro ao carregar estado" in caplog.text
    gk.state.state_file = str(tmp_path / "pasta_inexistente" / "x" / "state")
    with caplog.at_level(logging.ERROR, logger="Gatekeeper"):
        gk.state.save_state()
    assert "Erro ao salvar estado" in caplog.text


def test_win_error_filter_hides_harmless_resets(gk):
    flt = gk.WinErrorFilter()
    mk = lambda msg: logging.LogRecord("x", logging.ERROR, __file__, 1, msg, None, None)
    assert flt.filter(mk("normal")) is True
    assert flt.filter(mk("[WinError 10054] reset")) is False
    assert flt.filter(mk("ConnectionResetError")) is False


# --- processo -----------------------------------------------------------------------------------
def test_start_spawns_app_service_once_and_persists_intent(gk, fake_popen):
    gk.manage_process("start")
    assert gk.state.should_run is True and gk.state.app_running is True
    assert json.load(open(gk.state.state_file)) == {"should_run": True}
    assert len(fake_popen.instances) == 1
    cmd = fake_popen.instances[0].cmd
    assert cmd[0] == sys.executable and cmd[1].endswith("app_service.py")
    gk.manage_process("start")       # ja rodando: nao duplica
    assert len(fake_popen.instances) == 1
    fake_popen.instances[0].exit_code = 1   # morreu: novo start sobe outro
    gk.manage_process("start")
    assert len(fake_popen.instances) == 2


def test_start_creates_new_process_group_only_on_windows(gk, fake_popen, monkeypatch):
    monkeypatch.setattr(gk, "IS_WINDOWS", False)
    gk.manage_process("start")
    assert fake_popen.instances[0].kwargs["creationflags"] == 0


def test_stop_on_posix_terminates_process(gk, fake_popen, monkeypatch):
    monkeypatch.setattr(gk, "IS_WINDOWS", False)
    gk.manage_process("start")
    gk.manage_process("stop")
    assert fake_popen.instances[0].terminated
    assert gk.state.process is None and gk.state.app_running is False and gk.state.should_run is False
    assert json.load(open(gk.state.state_file)) == {"should_run": False}


def test_stop_on_windows_uses_taskkill_tree(gk, fake_popen, monkeypatch):
    calls = []
    monkeypatch.setattr(gk, "IS_WINDOWS", True)
    # a constante só existe no Windows; no CI (Linux) o start simulado precisa dela
    monkeypatch.setattr(gk.subprocess, "CREATE_NEW_PROCESS_GROUP", 0x200, raising=False)
    monkeypatch.setattr(gk.subprocess, "call", lambda cmd: calls.append(cmd))
    gk.manage_process("start")
    gk.manage_process("stop")
    assert calls == [["taskkill", "/F", "/T", "/PID", "4242"]]


def test_stop_without_process_only_updates_intent(gk):
    gk.state.should_run = True
    gk.manage_process("stop")
    assert gk.state.should_run is False


def test_manage_process_swallows_spawn_errors(gk, monkeypatch, caplog):
    def boom(*a, **k):
        raise OSError("sem permissao")

    monkeypatch.setattr(gk.subprocess, "Popen", boom)
    with caplog.at_level(logging.ERROR, logger="Gatekeeper"):
        gk.manage_process("start")
    assert "Erro ao gerenciar processo" in caplog.text


def test_kill_port_owner_parses_netstat_on_windows(monkeypatch):
    import gatekeeper
    importlib.reload(gatekeeper)
    killed = []
    monkeypatch.setattr(gatekeeper, "IS_WINDOWS", True)
    monkeypatch.setattr(gatekeeper.subprocess, "check_output",
                        lambda cmd, shell, text: "  TCP    127.0.0.1:8001    0.0.0.0:0    LISTENING    777\n"
                                                 "  TCP    127.0.0.1:18001   0.0.0.0:0    LISTENING    888\n")
    monkeypatch.setattr(gatekeeper.subprocess, "call", lambda cmd: killed.append(cmd[-1]))
    gatekeeper.kill_port_owner(8001)
    assert "777" in killed
    monkeypatch.setattr(gatekeeper.subprocess, "check_output", lambda *a, **k: (_ for _ in ()).throw(OSError("x")))
    gatekeeper.kill_port_owner(8001)   # sem processo na porta: silencioso
    monkeypatch.setattr(gatekeeper, "IS_WINDOWS", False)
    gatekeeper.kill_port_owner(8001)   # nao faz nada fora do Windows


# --- check_app_alive ---------------------------------------------------------------------------
@pytest.mark.parametrize("status,alive", [(200, True), (401, True), (500, False), (404, False)])
def test_check_app_alive_by_status(gk, monkeypatch, status, alive):
    mock_upstream(monkeypatch, gk, lambda req: httpx.Response(status))
    assert asyncio.run(gk.check_app_alive()) is alive


def test_check_app_alive_false_when_unreachable(gk, monkeypatch):
    def refuse(request):
        raise httpx.ConnectError("recusada")

    mock_upstream(monkeypatch, gk, refuse)
    assert asyncio.run(gk.check_app_alive()) is False


def test_check_app_alive_targets_configured_port(gk, monkeypatch):
    seen = []
    gk.state.app_port = 9555
    mock_upstream(monkeypatch, gk, lambda req: seen.append(str(req.url)) or httpx.Response(200))
    asyncio.run(gk.check_app_alive())
    assert seen == ["http://127.0.0.1:9555/tasks"]


# --- watchdog ----------------------------------------------------------------------------------
def run_watchdog(gk, monkeypatch, iterations):
    """Executa N voltas do loop do watchdog (sleep falso cancela ao final)."""
    count = {"n": 0}

    async def fake_sleep(seconds):
        count["n"] += 1
        if count["n"] >= iterations:
            raise asyncio.CancelledError()

    monkeypatch.setattr(gk.asyncio, "sleep", fake_sleep)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(gk.watchdog_task())


def test_watchdog_idle_when_user_does_not_want_service(gk, monkeypatch):
    started = []
    monkeypatch.setattr(gk, "manage_process", lambda a: started.append(a))
    gk.state.should_run = False
    run_watchdog(gk, monkeypatch, 2)
    assert started == []


def test_watchdog_restarts_dead_process(gk, monkeypatch):
    started = []
    monkeypatch.setattr(gk, "manage_process", lambda a: started.append(a))

    async def alive():
        return True

    monkeypatch.setattr(gk, "check_app_alive", alive)
    gk.state.should_run = True
    gk.state.process = None
    run_watchdog(gk, monkeypatch, 1)
    assert started == ["start"]


def test_watchdog_forces_restart_after_three_failed_health_checks(gk, monkeypatch):
    started = []
    monkeypatch.setattr(gk, "manage_process", lambda a: started.append(a))

    async def dead():
        return False

    monkeypatch.setattr(gk, "check_app_alive", dead)
    gk.state.should_run = True
    gk.state.process = FakeProcess(["x"])          # processo existe (poll() None) mas HTTP nao responde
    run_watchdog(gk, monkeypatch, 4)
    assert started == ["start"]                    # reinicia na 3a falha consecutiva; 4a volta a contar


def test_watchdog_healthy_resets_failures_and_marks_running(gk, monkeypatch):
    started = []
    monkeypatch.setattr(gk, "manage_process", lambda a: started.append(a))
    answers = iter([False, False, True, False, False])

    async def flaky():
        return next(answers)

    monkeypatch.setattr(gk, "check_app_alive", flaky)
    gk.state.should_run = True
    gk.state.app_running = False
    gk.state.process = FakeProcess(["x"])
    run_watchdog(gk, monkeypatch, 5)
    assert started == []                           # nunca chegou a 3 falhas seguidas
    assert gk.state.app_running is True


def test_watchdog_survives_unexpected_errors(gk, monkeypatch, caplog):
    async def boom():
        raise RuntimeError("inesperado")

    monkeypatch.setattr(gk, "check_app_alive", boom)
    gk.state.should_run = True
    gk.state.process = FakeProcess(["x"])
    with caplog.at_level(logging.ERROR, logger="Gatekeeper"):
        run_watchdog(gk, monkeypatch, 2)
    assert "Erro no loop do Watchdog" in caplog.text


def test_startup_event_launches_watchdog_and_restores_service(gk, monkeypatch):
    calls = []

    async def fake_watchdog():
        calls.append("watchdog")

    monkeypatch.setattr(gk, "watchdog_task", fake_watchdog)
    monkeypatch.setattr(gk, "manage_process", lambda a: calls.append(a))

    async def go():
        await gk.startup_event()
        await asyncio.sleep(0)

    gk.state.should_run = True
    asyncio.run(go())
    assert calls == ["start", "watchdog"] or calls == ["watchdog", "start"]
    calls.clear()
    gk.state.should_run = False
    asyncio.run(go())
    assert calls == ["watchdog"]


# --- HTTP: API de gestao e proxy ----------------------------------------------------------------
@pytest.fixture()
def client(gk):
    from fastapi.testclient import TestClient
    return TestClient(gk.app)    # sem 'with': nao dispara o startup (watchdog)


def test_management_pages_and_unknown_api_are_served_locally(client):
    for path in ("/gatekeeper", "/manage"):
        r = client.get(path)
        assert r.status_code == 200 and "html" in r.headers["content-type"]
    assert client.get("/api/inexistente").status_code == 404


def test_status_reflects_app_health_and_clears_dead_process(client, gk, monkeypatch):
    dead = FakeProcess(["x"])
    dead.exit_code = 3
    gk.state.process = dead
    mock_upstream(monkeypatch, gk, lambda req: httpx.Response(200))
    r = client.get("/api/status")
    assert r.json() == {"app_running": True, "should_run": gk.state.should_run}
    assert gk.state.process is None


def test_toggle_start_and_stop(client, gk, fake_popen, monkeypatch):
    monkeypatch.setattr(gk, "IS_WINDOWS", False)
    r = client.post("/api/toggle", json={"action": "start"})
    assert r.json() == {"status": "ok", "app_running": True}
    assert gk.state.should_run is True
    r = client.post("/api/toggle", json={"action": "stop"})
    assert r.json() == {"status": "ok", "app_running": False}
    assert fake_popen.instances[0].terminated


def test_toggle_with_invalid_body_returns_500(client):
    r = client.post("/api/toggle", content=b"nao-json", headers={"content-type": "application/json"})
    assert r.status_code == 500 and r.json()["status"] == "error"


def test_proxy_forwards_request_and_response(client, gk, monkeypatch):
    seen = []

    def upstream(request):
        seen.append((request.method, request.url.path, request.url.query, request.content,
                     request.headers.get("x-api-token"), request.headers.get("host")))
        if request.url.path == "/tasks":
            return httpx.Response(200, json={})
        return httpx.Response(201, json={"ok": True}, headers={"X-Extra": "1"})

    mock_upstream(monkeypatch, gk, upstream)
    r = client.post("/upload?force=1", content=b"corpo", headers={"X-API-Token": "tok"})
    assert r.status_code == 201 and r.json() == {"ok": True} and r.headers["x-extra"] == "1"
    method, path, query, body, token, host = seen[-1]
    # regressao: a query string chegava como "b'force=1'" (bytes interpolado em f-string)
    assert (method, path, query, body, token) == ("POST", "/upload", b"force=1", b"corpo", "tok")
    assert host != "testserver"       # host original removido; o do upstream e recalculado
    assert gk.state.app_running is True


def test_proxy_passes_through_401_when_api_token_is_required(client, gk, monkeypatch):
    def upstream(request):
        return httpx.Response(401, json={"detail": "Não autorizado"})

    mock_upstream(monkeypatch, gk, upstream)
    r = client.get("/tasks")
    assert r.status_code == 401 and r.json()["detail"] == "Não autorizado"


def test_proxy_strips_stale_encoding_headers(client, gk, monkeypatch):
    """Regressao: corpo ja descompactado + 'content-encoding: gzip' repassado quebrava o cliente."""
    import gzip
    payload = json.dumps({"a": "b" * 500}).encode()

    def upstream(request):
        if request.url.path == "/tasks":
            return httpx.Response(200, json={})
        return httpx.Response(200, content=gzip.compress(payload),
                              headers={"content-encoding": "gzip", "content-type": "application/json"})

    mock_upstream(monkeypatch, gk, upstream)
    r = client.get("/dados")
    assert r.status_code == 200 and r.json() == {"a": "b" * 500}
    assert "content-encoding" not in r.headers


def test_proxy_shows_management_page_when_app_is_down(client, gk, monkeypatch):
    mock_upstream(monkeypatch, gk, lambda req: httpx.Response(500))
    r = client.get("/")
    assert r.status_code == 200 and "html" in r.headers["content-type"]
    assert gk.state.app_running is False
    r = client.get("/qualquer/rota")
    assert r.status_code == 200 and gk.state.app_running is False


def test_proxy_falls_back_when_request_fails_midway(client, gk, monkeypatch):
    state = {"n": 0}

    def upstream(request):
        state["n"] += 1
        if state["n"] == 1:               # health check ok
            return httpx.Response(200, json={})
        raise httpx.ReadTimeout("lento")  # a requisicao proxied falha

    mock_upstream(monkeypatch, gk, upstream)
    r = client.get("/tasks-lento")
    assert r.status_code == 200 and "html" in r.headers["content-type"]
    assert gk.state.app_running is False


def test_root_proxies_when_alive(client, gk, monkeypatch):
    mock_upstream(monkeypatch, gk, lambda req: httpx.Response(200, text="<html>app</html>",
                                                              headers={"content-type": "text/html"}))
    assert client.get("/").text == "<html>app</html>"


def test_template_error_returns_plain_500(gk, monkeypatch):
    monkeypatch.setattr(gk.templates, "TemplateResponse", lambda **k: (_ for _ in ()).throw(RuntimeError("tpl")))
    r = gk.safe_template_response(object(), "gatekeeper.html")
    assert r.status_code == 500 and b"Template gatekeeper.html falhou" in r.body


# --- servidor -----------------------------------------------------------------------------------
def test_run_gatekeeper_configures_uvicorn_and_logs_failures(gk, monkeypatch, caplog):
    seen = {}

    class FakeServer:
        def __init__(self, config):
            seen["config"] = config

        def run(self):
            seen["ran"] = True

    monkeypatch.setattr(gk.uvicorn, "Server", FakeServer)
    monkeypatch.setenv("APP_HOST", "0.0.0.0")
    gk.run_gatekeeper(8123)
    assert seen["ran"] and seen["config"].port == 8123 and seen["config"].host == "0.0.0.0"

    class Broken:
        def __init__(self, config):
            raise OSError("porta ocupada")

    monkeypatch.setattr(gk.uvicorn, "Server", Broken)
    with caplog.at_level(logging.ERROR, logger="Gatekeeper"):
        gk.run_gatekeeper(8123)
    assert "Erro ao iniciar servidor na porta 8123" in caplog.text

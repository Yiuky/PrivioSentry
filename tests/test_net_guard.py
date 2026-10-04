# SPDX-License-Identifier: AGPL-3.0-or-later
"""B-40: proteção contra DNS rebinding (Host) e CSRF (Origin) no app e no gatekeeper."""
import importlib

import pytest

pytest.importorskip("fastapi")

from utils.net_guard import allowed_hosts, check_request  # noqa: E402


@pytest.fixture()
def loopback_only(monkeypatch):
    monkeypatch.delenv("ALLOWED_HOSTS", raising=False)
    monkeypatch.delenv("APP_HOST", raising=False)


# --- regras -------------------------------------------------------------------------------------
def test_loopback_hosts_are_accepted(loopback_only):
    for host in ("127.0.0.1:8001", "localhost:8001", "[::1]:8001", "LOCALHOST"):
        assert check_request("GET", {"host": host}, token_enabled=False) is None


def test_foreign_host_is_rejected_dns_rebinding(loopback_only):
    assert check_request("GET", {"host": "evil.example:8001"}, token_enabled=False)[0] == 421
    assert check_request("GET", {}, token_enabled=False)[0] == 421


def test_cross_site_writes_are_rejected(loopback_only):
    base = {"host": "127.0.0.1:8001"}
    assert check_request("POST", {**base, "origin": "https://evil.example"}, False)[0] == 403
    assert check_request("DELETE", {**base, "origin": "null"}, False)[0] == 403
    assert check_request("POST", {**base, "sec-fetch-site": "cross-site"}, False)[0] == 403


def test_same_origin_and_originless_writes_are_accepted(loopback_only):
    base = {"host": "127.0.0.1:8001"}
    assert check_request("POST", {**base, "origin": "http://127.0.0.1:8001"}, False) is None
    assert check_request("POST", {**base, "origin": "http://localhost:8000"}, False) is None  # via gatekeeper
    assert check_request("POST", base, False) is None  # curl/scripts locais não mandam Origin
    assert check_request("GET", {**base, "origin": "https://evil.example"}, False) is None  # leitura: CORS barra


def test_app_host_and_allowed_hosts_extend_the_list(monkeypatch):
    monkeypatch.setenv("APP_HOST", "Sentry.Local")
    monkeypatch.setenv("ALLOWED_HOSTS", "intranet.example, 10.0.0.5")
    assert {"sentry.local", "intranet.example", "10.0.0.5", "127.0.0.1"} <= allowed_hosts()
    monkeypatch.setenv("APP_HOST", "0.0.0.0")
    assert "0.0.0.0" not in allowed_hosts()


def test_wildcard_disables_the_check(monkeypatch):
    monkeypatch.setenv("ALLOWED_HOSTS", "*")
    assert check_request("POST", {"host": "qualquer", "origin": "https://x.example"}, False) is None


def test_token_mode_skips_host_check(loopback_only):
    assert check_request("GET", {"host": "10.0.0.5:8001"}, token_enabled=True) is None


# --- integração ---------------------------------------------------------------------------------
@pytest.fixture()
def svc(monkeypatch, loopback_only):
    import app_service
    importlib.reload(app_service)
    monkeypatch.setattr(app_service, "start_worker", lambda tid, **kw: None)
    from fastapi.testclient import TestClient
    return TestClient(app_service.app, base_url="http://127.0.0.1:8001")


def test_service_rejects_rebinding_host(svc):
    assert svc.get("/tasks").status_code == 200
    r = svc.get("/tasks", headers={"host": "attacker.example"})
    assert r.status_code == 421


def test_service_rejects_cross_site_upload_but_accepts_same_origin(svc):
    files = {"file": ("doc.pdf", b"%PDF-1.4\n%fake\n")}
    r = svc.post("/upload", files=files, headers={"origin": "https://evil.example"})
    assert r.status_code == 403
    r = svc.post("/upload", files=files, headers={"origin": "http://127.0.0.1:8001"})
    assert r.status_code == 200


def test_internal_route_is_not_blocked_by_the_guard(svc):
    # /internal/ continua protegido pelo segredo interno (403 por segredo, não 421 por Host)
    r = svc.post("/internal/update/x", json={}, headers={"host": "attacker.example"})
    assert r.status_code == 403 and "Segredo" in r.json()["detail"]


def test_gatekeeper_toggle_rejects_cross_site(monkeypatch, loopback_only, tmp_path):
    monkeypatch.setenv("GATEKEEPER_STATE_FILE", str(tmp_path / "state"))
    import gatekeeper
    importlib.reload(gatekeeper)
    from fastapi.testclient import TestClient
    client = TestClient(gatekeeper.app, base_url="http://127.0.0.1:8000")
    r = client.post("/api/toggle", json={"action": "stop"}, headers={"origin": "https://evil.example"})
    assert r.status_code == 403
    assert client.get("/gatekeeper", headers={"host": "attacker.example"}).status_code == 421

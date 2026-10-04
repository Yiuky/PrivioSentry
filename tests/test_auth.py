# SPDX-License-Identifier: AGPL-3.0-or-later
"""B-41/B-42: sessão no lugar do token cru, mascaramento de segredos em logs e painel do gatekeeper."""
import importlib
import logging
import time

import pytest

pytest.importorskip("fastapi")

from fastapi import FastAPI, Request  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from utils.auth import TokenAuth  # noqa: E402
from utils.pii import ArgsMaskingFilter, CpfMaskingFilter, install_access_log_masking, mask_secrets  # noqa: E402


def _app(token="segredo"):
    app = FastAPI()
    auth = TokenAuth("sessao_teste")

    @app.middleware("http")
    async def guard(request: Request, call_next):
        denied = auth.check(request, token)
        return denied if denied is not None else await call_next(request)

    @app.get("/x")
    def x():
        return {"ok": True}

    @app.post("/x")
    def x_post():
        return {"ok": True}

    return app, auth


def test_query_token_redirects_without_token_and_sets_random_session():
    app, _ = _app()
    c = TestClient(app, base_url="http://127.0.0.1")
    r = c.get("/x?token=segredo", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/x"
    cookie = r.headers["set-cookie"]
    assert "segredo" not in cookie and "sessao_teste=" in cookie
    assert "secure" not in cookie.lower()          # HTTP puro: sem Secure (senão o navegador descartaria)
    assert c.get("/x").status_code == 200


def test_secure_cookie_behind_https_proxy():
    app, _ = _app()
    r = TestClient(app).get("/x?token=segredo", headers={"x-forwarded-proto": "https"}, follow_redirects=False)
    assert "secure" in r.headers["set-cookie"].lower()


def test_wrong_token_post_with_query_token_and_raw_token_cookie_are_rejected():
    app, _ = _app()
    c = TestClient(app)
    assert c.get("/x?token=errado", follow_redirects=False).status_code == 401
    assert c.post("/x?token=segredo").status_code == 401           # token na URL só para abrir sessão (GET)
    assert c.get("/x", cookies={"sessao_teste": "segredo"}).status_code == 401   # cookie com o token cru não vale
    assert c.get("/x", headers={"X-API-Token": "segredo"}).status_code == 200    # scripts: cabeçalho


def test_sessions_expire(monkeypatch):
    monkeypatch.setenv("SESSION_TTL_HOURS", "0.1")
    app, auth = _app()
    c = TestClient(app)
    c.get("/x?token=segredo")
    assert c.get("/x").status_code == 200
    now = time.time()
    monkeypatch.setattr(time, "time", lambda: now + 3600)
    assert c.get("/x").status_code == 401


def test_without_token_everything_is_open():
    app, _ = _app(token="")
    assert TestClient(app).get("/x?token=qualquer").status_code == 200


def test_mask_secrets_and_access_log_filter():
    assert mask_secrets("GET /tasks?token=abc&x=1") == "GET /tasks?token=***&x=1"
    assert mask_secrets("?API_TOKEN=z") == "?API_TOKEN=***"
    install_access_log_masking()
    filters = logging.getLogger("uvicorn.access").filters
    assert any(isinstance(f, ArgsMaskingFilter) for f in filters)
    assert not any(isinstance(f, CpfMaskingFilter) for f in filters)
    record = logging.LogRecord("uvicorn.access", logging.INFO, __file__, 1, '%s "GET %s"', ("127.0.0.1", "/?token=s3"), None)
    ArgsMaskingFilter().filter(record)
    assert "s3" not in record.getMessage() and "token=***" in record.getMessage()


def test_uvicorn_access_formatter_still_works_with_masking():
    # Regressão da 5.3.0: o filtro achatava record.args e o AccessFormatter do uvicorn quebrava a cada requisição
    from uvicorn.logging import AccessFormatter
    record = logging.LogRecord("uvicorn.access", logging.INFO, __file__, 1, '%s - "%s %s HTTP/%s" %d',
                               ("127.0.0.1:5000", "GET", "/tasks?token=s3cr3t", "1.1", 200), None)
    ArgsMaskingFilter().filter(record)
    line = AccessFormatter('%(client_addr)s - "%(request_line)s" %(status_code)s', use_colors=False).format(record)
    assert "s3cr3t" not in line and "token=***" in line and "200" in line


def test_gatekeeper_panel_requires_token_when_set(monkeypatch, tmp_path):
    monkeypatch.setenv("GATEKEEPER_STATE_FILE", str(tmp_path / "state"))
    monkeypatch.setenv("API_TOKEN", "segredo")
    import gatekeeper
    importlib.reload(gatekeeper)
    c = TestClient(gatekeeper.app, base_url="http://127.0.0.1:8000")
    assert c.get("/api/status").status_code == 401
    assert c.post("/api/toggle", json={"action": "stop"}).status_code == 401
    assert c.get("/api/status", headers={"X-API-Token": "segredo"}).status_code == 200
    r = c.get("/gatekeeper?token=segredo", follow_redirects=False)
    assert r.status_code == 303 and "privio_gk_session=" in r.headers["set-cookie"]
    assert c.get("/api/status").status_code == 200

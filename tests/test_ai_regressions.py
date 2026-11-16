"""Regressões achadas na varredura de bugs: IA, trava de saída e Administração. Tudo simulado (I-08)."""
import logging

import pytest

from sentry_testkit import word
from utils import address_redactor as ar
from utils import egress, second_look
from utils import settings as admin_settings

ADDR = "Rua das Flores, 123, Apto 45, Jardim Primavera, Cuiabá-MT, CEP 78550-352"


class _Session:
    def save_ai_interaction(self, **k):
        pass


def _refine(ocr_text):
    ocr = ocr_text.split()
    r = ar.AddressRedactor.__new__(ar.AddressRedactor)
    r.session, r.logger, r.unlocated = _Session(), logging.getLogger("x"), {}
    ids = r.refine_redaction_with_text_ai(1, "", [{"text": ADDR, "type": "pessoal"}],
                                          [word(i, t, 50 * i) for i, t in enumerate(ocr)])
    return ids, r


@pytest.mark.parametrize("ocr", [
    "Endereço: Rua das Flores, 123 Apto 45 Complemento: casa dos fundos Bairro: Jardim Primavera Cidade: Cuiabá-MT "
    "CEP: 78550-352",
    "Residente na Rua das Flores, 123, Apto 45, Testemunha Joana Lima Jardim Primavera, Cuiabá-MT, CEP 78550-352",
])
def test_address_found_only_in_part_asks_for_review(ocr):
    ids, r = _refine(ocr)
    assert ids and r.partial[1] == [ADDR] and r.unlocated[1] == []


def test_address_found_whole_is_not_flagged():
    ids, r = _refine("Residente na Rua das Flores, 123, Apto 45, Jardim Primavera, Cuiabá-MT, CEP 78550-352")
    assert ids and r.partial[1] == []                                     # contra-teste


@pytest.mark.parametrize("url, host", [
    ("http://nuvem.example\\@localhost:11434", "nuvem.example"),          # o cliente HTTP vai para nuvem.example
    ("http://localhost:11434", "localhost"),
    ("localhost:1234/v1", "localhost"),
    ("https://user:pw@10.0.0.5/v1", "10.0.0.5"),
])
def test_host_is_the_one_the_http_client_really_connects_to(url, host):
    assert egress.host_of(url) == host


def test_odd_url_cannot_pass_as_local(monkeypatch):
    monkeypatch.setattr(egress.socket, "getaddrinfo", lambda *a, **k: [(0, 0, 0, "", ("8.8.8.8", 0))])
    egress._host_is_external.cache_clear()
    monkeypatch.delenv("AI_ALLOW_EXTERNAL", raising=False)
    with pytest.raises(egress.ExternalBlocked):
        egress.check("http://nuvem.example\\@localhost:11434")


def test_redirect_is_refused_and_never_followed(monkeypatch):
    from utils import ai_client
    seen = []

    class R:
        status_code = 307
        text = ""
        headers = {"location": "https://nuvem.example/v1/chat/completions"}

    def fake_post(url, **kw):
        seen.append(kw.get("allow_redirects"))
        return R()
    monkeypatch.setattr(ai_client.requests, "post", fake_post)
    backend = ai_client.OpenAICompatBackend("http://localhost:1234/v1", "m", "m")
    with pytest.raises(RuntimeError, match="redirecion"):
        backend.chat("s", "p", None, 5, False)
    assert seen == [False]


def test_credentials_in_url_never_shown():
    from utils import ai_client
    b = ai_client.OpenAICompatBackend("https://user:SEGREDO@10.0.0.7/v1", "m", "m")
    assert "SEGREDO" not in str(b.describe()) and "SEGREDO" not in b.key(True)


# --- Administração ------------------------------------------------------------------------------
@pytest.mark.parametrize("key, value", [("MAX_PARALLEL_TASKS", "2.5"), ("MAX_UPLOAD_MB", "2.5"),
                                        ("VERIFY_DPI", "300.5"), ("BASE_DPI", "nan"), ("BASE_DPI", "inf")])
def test_admin_rejects_numbers_that_would_break_startup(key, value):
    with pytest.raises(admin_settings.SettingsError):
        admin_settings.save({key: value})


def test_admin_keeps_decimals_where_they_make_sense():
    admin_settings.save({"AI_REQUESTS_PER_MINUTE": "7.5", "MAX_PARALLEL_TASKS": "3"})   # contra-teste


@pytest.mark.parametrize("url", ["http://nuvem.example\\@localhost:11434", "https://user:pw@10.0.0.5/v1",
                                 "http://local host:1234/v1"])
def test_admin_rejects_misleading_urls(url):
    with pytest.raises(admin_settings.SettingsError):
        admin_settings.save({"AI_BASE_URL": url})


def test_second_look_key_does_not_follow_the_main_server_to_another_host(monkeypatch):
    monkeypatch.setenv("AI_BASE_URL", "https://provedor-a.example/v1")
    monkeypatch.setenv("SECOND_LOOK_API_KEY", "CHAVE-DO-A")
    admin_settings.save({"AI_BASE_URL": "https://provedor-b.example/v1"})
    import os
    assert not os.environ.get("SECOND_LOOK_API_KEY")


def test_service_survives_a_bad_number_already_saved(monkeypatch):
    import importlib

    import app_service
    monkeypatch.setenv("MAX_PARALLEL_TASKS", "2.5")
    monkeypatch.setenv("MAX_UPLOAD_MB", "abc")
    importlib.reload(app_service)                                         # antes: ValueError, o serviço não subia
    assert app_service.MAX_PARALLEL_TASKS == 2 and app_service.MAX_UPLOAD_BYTES == 500 * 1024 * 1024


# --- agente -------------------------------------------------------------------------------------
class _R:
    status_code = 200

    def __init__(self, body):
        self.body = body

    def json(self):
        return self.body


@pytest.mark.parametrize("body", [[1, 2], {"choices": [{"message": {"tool_calls": [
    {"id": "1", "function": {"name": "ler_pagina", "arguments": '{"inicio": "um"}'}}]}}]},
    {"choices": [{"message": {"tool_calls": [{"id": "1", "function": {"name": "ler_pagina", "arguments": [1]}}]}}]}])
def test_malformed_agent_answer_fails_the_page_not_the_document(monkeypatch, body):
    monkeypatch.setenv("AI_PROVIDER", "openai")
    monkeypatch.setenv("AI_BASE_URL", "http://localhost:1234/v1")
    monkeypatch.setenv("SECOND_LOOK_MAX_TURNS", "2")
    items, info = second_look.run_agent("texto", ["cpf"], post=lambda *a, **k: _R(body))
    assert items is None and info["erro"]                                 # sem exceção: a página vai para revisão


def test_locate_covers_every_occurrence():
    g = [word(i, t, 100 * i) for i, t in enumerate(["Fulano", "Exemplo", "e", "Fulano", "Exemplo"])]
    assert set(second_look.locate("Fulano Exemplo", g)) == {0, 1, 3, 4}

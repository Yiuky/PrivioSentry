# SPDX-License-Identifier: AGPL-3.0-or-later
"""IA externa só com liberação explícita (AI_ALLOW_EXTERNAL=1); bloqueada = página em revisão (I-02, I-04).

Contra testes: servidor local/da intranet continua funcionando sem liberação; liberado, a chamada sai e a tarefa
registra o destino (a interface não diz "Processado localmente")."""
import time

import pytest
from PIL import Image

from test_ai_backends import openai_chat
from test_ai_client import FakeOllama
from utils import ai_client, egress, second_look


@pytest.fixture(autouse=True)
def clean_egress(monkeypatch):
    monkeypatch.setattr(egress, "_sent", set())
    monkeypatch.setattr(time, "sleep", lambda s: None)
    egress._host_is_external.cache_clear()
    yield
    egress._host_is_external.cache_clear()


@pytest.fixture()
def fake_cloud(monkeypatch):
    """Servidor falso local tratado como se fosse um provedor na nuvem (sem rede: I-08)."""
    srv = FakeOllama([openai_chat('{"addresses": []}')])
    monkeypatch.setattr(egress, "is_external", lambda url: True)
    monkeypatch.setenv("AI_PROVIDER", "openai")
    monkeypatch.setenv("AI_BASE_URL", srv.url + "/v1")
    monkeypatch.setenv("AI_VISION_MODEL", "modelo-da-nuvem")
    monkeypatch.setenv("AI_API_KEY", "chave-de-teste")
    yield srv
    srv.stop()


def page(tmp_path):
    p = tmp_path / "p.png"
    Image.new("RGB", (200, 100), (255, 255, 255)).save(p)
    return str(p)


@pytest.mark.parametrize("url,external", [
    ("http://localhost:11434", False), ("http://127.0.0.1:1234/v1", False), ("http://192.168.0.10:8000", False),
    ("http://10.1.2.3/v1", False), ("http://[::1]:11434", False), ("http://servidor-ia:11434", False),
    ("http://ia.intranet/v1", False), ("http://gpu.local:1234", False), ("http://x.localhost", False),
    ("http://8.8.8.8/v1", True), ("", True),
])
def test_classification_without_dns(url, external):
    assert egress.is_external(url) is external


def test_name_resolving_only_to_private_ips_is_local(monkeypatch):
    monkeypatch.setattr(egress.socket, "getaddrinfo", lambda h, p: [(0, 0, 0, "", ("10.0.0.5", 0))])
    assert egress.is_external("https://ia.minhaorg.br/v1") is False


def test_public_or_unresolvable_names_are_external(monkeypatch):
    monkeypatch.setattr(egress.socket, "getaddrinfo", lambda h, p: [(0, 0, 0, "", ("104.18.1.1", 0))])
    assert egress.is_external("https://api.provedor.example/v1") is True
    egress._host_is_external.cache_clear()

    def fail(h, p):
        raise OSError("sem DNS")
    monkeypatch.setattr(egress.socket, "getaddrinfo", fail)
    assert egress.is_external("https://api.outro.example/v1") is True     # na dúvida, externo


def test_external_ai_is_blocked_by_default_and_nothing_is_sent(fake_cloud, tmp_path):
    resp, img_bytes, _ = ai_client.AIClient().analyze_image(page(tmp_path), "p")
    assert "error" in resp and resp.get("egress_blocked") and "AI_ALLOW_EXTERNAL" in resp["error"]
    assert fake_cloud.requests == [] and img_bytes is None                 # a imagem nem saiu
    assert egress.sent() == []


def test_blocked_external_ai_sends_the_page_to_review(fake_cloud, tmp_path, monkeypatch):
    import logging

    from utils.address_redactor import AddressRedactor
    from utils.session import Session
    session = Session(str(tmp_path / "doc.pdf"), str(tmp_path / "out"))
    redactor = AddressRedactor(session, logging.getLogger("teste"))
    redactor.run_discovery([page(tmp_path)], page_texts=["Rua Fictícia, 10"])
    assert 1 in redactor.failed_pages and "bloqueado" in redactor.failed_pages[1]   # falha fechado: revisão


def test_allowed_external_ai_is_called_and_recorded(fake_cloud, tmp_path, monkeypatch):
    monkeypatch.setenv("AI_ALLOW_EXTERNAL", "1")
    resp, _, _ = ai_client.AIClient().analyze_image(page(tmp_path), "p")
    assert resp == {"addresses": []} and len(fake_cloud.requests) == 1
    assert egress.sent() == [egress.host_of(fake_cloud.url)]


def test_local_server_needs_no_permission(tmp_path, monkeypatch):
    srv = FakeOllama([openai_chat('{"addresses": []}')])
    try:
        monkeypatch.setenv("AI_PROVIDER", "openai")
        monkeypatch.setenv("AI_BASE_URL", srv.url + "/v1")
        monkeypatch.setenv("AI_VISION_MODEL", "local")
        resp, _, _ = ai_client.AIClient().analyze_image(page(tmp_path), "p")
        assert resp == {"addresses": []} and egress.sent() == []
    finally:
        srv.stop()


def test_local_primary_with_external_reserve_blocked_still_fails_closed(tmp_path, monkeypatch):
    """Principal local caiu; a reserva é externa e não liberada: nada sai e o resultado é erro (revisão)."""
    local = FakeOllama([(500, "erro", 0)])
    cloud = FakeOllama([openai_chat('{"addresses": []}')])
    try:
        monkeypatch.setattr(egress, "is_external", lambda url: url.startswith(cloud.url))
        monkeypatch.setenv("AI_PROVIDER", "openai")
        monkeypatch.setenv("AI_BASE_URL", local.url + "/v1")
        monkeypatch.setenv("AI_VISION_MODEL", "local")
        monkeypatch.setenv("AI_SECONDARY_PROVIDER", "openai")
        monkeypatch.setenv("AI_SECONDARY_BASE_URL", cloud.url + "/v1")
        monkeypatch.setenv("AI_SECONDARY_VISION_MODEL", "nuvem")
        resp, _, _ = ai_client.AIClient().analyze_image(page(tmp_path), "p")
        assert "error" in resp and cloud.requests == []
    finally:
        local.stop()
        cloud.stop()


def test_second_look_text_is_not_sent_to_a_blocked_external_server(monkeypatch):
    calls = []
    monkeypatch.setattr(egress, "is_external", lambda url: True)
    monkeypatch.setenv("AI_PROVIDER", "openai")
    monkeypatch.setenv("AI_BASE_URL", "https://nuvem.example/v1")
    items, info = second_look.run_agent("CPF 000", ["cpf"], post=lambda *a, **k: calls.append(1))
    assert items is None and "bloqueado" in info["erro"] and calls == []    # main.py manda a página para revisão


def test_second_look_reuses_the_main_api_key(monkeypatch):
    seen = {}

    class R:
        status_code = 200

        def json(self):
            return {"choices": [{"message": {"content": '{"achados": []}'}}]}

    def post(url, headers=None, **kw):
        seen.update(headers or {})
        return R()
    monkeypatch.setenv("AI_PROVIDER", "openai")
    monkeypatch.setenv("AI_BASE_URL", "http://localhost:1234/v1")
    monkeypatch.setenv("AI_API_KEY", "chave-principal")
    items, _ = second_look.run_agent("texto", ["cpf"], post=post)
    assert items == [] and seen["Authorization"] == "Bearer chave-principal"


def test_reasoning_models_get_the_new_token_parameter(tmp_path, monkeypatch):
    """Modelos que recusam max_tokens/temperature: repete uma vez no formato novo."""
    srv = FakeOllama([(400, {"error": {"message": "Unsupported parameter: 'max_tokens'. Use "
                                                  "'max_completion_tokens' instead."}}, 0),
                      openai_chat('{"addresses": []}')])
    try:
        monkeypatch.setenv("AI_PROVIDER", "openai")
        monkeypatch.setenv("AI_BASE_URL", srv.url + "/v1")
        monkeypatch.setenv("AI_VISION_MODEL", "m")
        resp, _, _ = ai_client.AIClient().analyze_image(page(tmp_path), "p")
        assert resp == {"addresses": []}
        retry = srv.requests[1]
        assert "max_completion_tokens" in retry and "max_tokens" not in retry and "temperature" not in retry
    finally:
        srv.stop()


def test_external_servers_are_never_asked_to_unload(monkeypatch):
    calls = []
    monkeypatch.setattr(ai_client.requests, "get", lambda *a, **k: calls.append(a))
    monkeypatch.setattr(ai_client.requests, "post", lambda *a, **k: calls.append(a))
    ai_client.OpenAICompatBackend("https://api.openai.com/v1", "m", "m", "k").reset()
    ai_client.OllamaBackend("https://8.8.8.8", "m", "m").reset()
    assert calls == []


def test_anthropic_gets_its_auth_headers_and_key_stays_out_of_health(monkeypatch):
    b = ai_client.OpenAICompatBackend("https://api.anthropic.com/v1", "m", "m", "sk-teste")
    h = b._headers()
    assert h["x-api-key"] == "sk-teste" and h["anthropic-version"]
    assert "sk-teste" not in str(b.describe())


# ------------------------------------------------------------------ achados com um provedor real (Gemini, 2026-11)
def test_agent_type_name_as_shown_in_the_prompt_is_accepted():
    """O modelo devolveu o tipo com o nome do pedido ("endereço residencial de pessoa"): antes era descartado."""
    assert second_look.type_id_for("endereço residencial de pessoa") == "endereco_residencial"
    assert second_look.type_id_for("CNS (cartão SUS)") == "cns"
    assert second_look.type_id_for("tipo inventado") is None


def test_agent_prompt_lists_type_ids_and_running_text():
    task = second_look._task(["cpf", "endereco_residencial"])
    assert "endereco_residencial (" in task and "texto corrido" in task and "█" in task


class R429:
    status_code = 429
    headers = {}
    text = '[{"error": {"code": 429, "details": [{"retryDelay": "33s"}]}}]'


def test_rate_limit_wait_comes_from_the_provider():
    assert second_look._retry_wait(R429()) == 33.0
    r = R429()
    r.headers = {"retry-after": "500"}
    assert second_look._retry_wait(r) == 60.0                 # teto


def test_agent_retries_after_rate_limit(monkeypatch):
    waits, answers = [], [R429(), R429()]

    class OK:
        status_code = 200

        def json(self):
            return {"choices": [{"message": {"content": '{"achados": []}'}}]}
    monkeypatch.setattr(second_look.time, "sleep", waits.append)
    monkeypatch.setenv("AI_PROVIDER", "openai")
    monkeypatch.setenv("AI_BASE_URL", "http://localhost:1234/v1")
    items, info = second_look.run_agent("texto", ["cpf"], post=lambda *a, **k: answers.pop(0) if answers else OK())
    assert items == [] and waits == [33.0, 33.0]


def test_agent_gives_up_after_repeated_rate_limit(monkeypatch):
    monkeypatch.setattr(second_look.time, "sleep", lambda s: None)
    monkeypatch.setenv("AI_PROVIDER", "openai")
    monkeypatch.setenv("AI_BASE_URL", "http://localhost:1234/v1")
    items, info = second_look.run_agent("texto", ["cpf"], post=lambda *a, **k: R429())
    assert items is None and "429" in info["erro"]          # vira revisão no pipeline (falha fechado)

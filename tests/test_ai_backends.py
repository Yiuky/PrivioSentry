# SPDX-License-Identifier: AGPL-3.0-or-later
"""Qualquer servidor de IA (Ollama ou API da OpenAI), IA reserva, disjuntor e teste de saúde pela API.

Servidores FALSOS locais (sem rede externa, sem modelo: I-08)."""
import json
import time

import pytest
from PIL import Image

from test_ai_client import FakeOllama
from utils import ai_client


def openai_chat(content):
    return (200, {"choices": [{"message": {"role": "assistant", "content": content}}],
                  "usage": {"prompt_tokens": 7, "completion_tokens": 3}}, 0)


def ollama_chat(content):
    return (200, {"message": {"role": "assistant", "content": content}}, 0)


@pytest.fixture()
def servers(monkeypatch):
    made = []
    monkeypatch.setattr(time, "sleep", lambda s: None)

    def make(script):
        s = FakeOllama(script)
        made.append(s)
        return s
    yield make
    for s in made:
        s.stop()


def image(tmp_path):
    p = tmp_path / "p.png"
    Image.new("RGB", (300, 200), (255, 255, 255)).save(p)
    return str(p)


def test_openai_compatible_server_lm_studio_vllm_or_corporate(servers, monkeypatch, tmp_path):
    srv = servers([openai_chat('{"addresses": []}')])
    monkeypatch.setenv("AI_PROVIDER", "openai")
    monkeypatch.setenv("AI_BASE_URL", srv.url + "/v1")
    monkeypatch.setenv("AI_VISION_MODEL", "qwen3.5-9b")
    monkeypatch.setenv("AI_API_KEY", "segredo-da-organizacao")
    resp, img_bytes, metrics = ai_client.AIClient().analyze_image(image(tmp_path), "p")
    assert resp == {"addresses": []} and metrics["output_tokens"] == 3 and img_bytes
    body = srv.requests[0]
    assert body["model"] == "qwen3.5-9b"
    parts = body["messages"][1]["content"]
    assert parts[0] == {"type": "text", "text": "p"} and parts[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")


def test_api_key_never_appears_in_health(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "openai")
    monkeypatch.setenv("AI_API_KEY", "segredo-da-organizacao")
    assert "segredo" not in json.dumps(ai_client.AIClient().health())


def test_secondary_takes_over_when_primary_is_down(servers, monkeypatch, tmp_path):
    reserva = servers([openai_chat('{"addresses": [{"text": "Rua A, 1", "type": "pessoal"}]}')])
    monkeypatch.setenv("AI_BASE_URL", "http://127.0.0.1:9")            # principal fora do ar
    monkeypatch.setenv("AI_SECONDARY_PROVIDER", "openai")
    monkeypatch.setenv("AI_SECONDARY_BASE_URL", reserva.url + "/v1")
    monkeypatch.setenv("AI_SECONDARY_VISION_MODEL", "gemma")
    resp, _, metrics = ai_client.AIClient().analyze_image(image(tmp_path), "p")
    assert resp["addresses"][0]["text"] == "Rua A, 1" and resp["_backend"] == "reserva"
    assert metrics["backend"] == "reserva"


def test_invalid_answer_from_primary_is_checked_by_the_secondary(servers, monkeypatch, tmp_path):
    principal = servers([ollama_chat("não sei responder em JSON")])
    reserva = servers([openai_chat('{"addresses": []}')])
    monkeypatch.setenv("AI_BASE_URL", principal.url)
    monkeypatch.setenv("AI_SECONDARY_PROVIDER", "openai")
    monkeypatch.setenv("AI_SECONDARY_BASE_URL", reserva.url + "/v1")
    resp, _, _ = ai_client.AIClient().analyze_image(image(tmp_path), "p")
    assert resp == {"addresses": [], "_backend": "reserva"}


def test_breaker_switches_off_a_failing_server_and_skips_it(servers, monkeypatch, tmp_path):
    srv = servers([(500, "sem memória", 0)])
    monkeypatch.setenv("AI_BASE_URL", srv.url)
    monkeypatch.setenv("AI_BREAKER_FAILURES", "3")
    monkeypatch.setenv("AI_BREAKER_COOLDOWN", "600")
    client = ai_client.AIClient()
    first, _, _ = client.analyze_image(image(tmp_path), "p")
    assert "error" in first and len(srv.requests) == 3                # 3 falhas: desligou
    assert any(o[1] == "/api/generate" for o in srv.other)            # e descarregou o modelo (API do Ollama)
    t0 = time.perf_counter()
    second, _, _ = ai_client.AIClient().analyze_image(image(tmp_path), "p")   # outra instância (outra tarefa)
    assert second.get("breaker_open") and len(srv.requests) == 3       # nem tentou: estado compartilhado
    assert time.perf_counter() - t0 < 1


def test_after_cooldown_a_health_probe_decides(servers, monkeypatch, tmp_path):
    srv = servers([(500, "x", 0), (500, "x", 0), (500, "x", 0), ollama_chat('{"ok": 1}')])
    monkeypatch.setenv("AI_BASE_URL", srv.url)
    monkeypatch.setenv("AI_VISION_MODEL", "m")
    monkeypatch.setenv("AI_BREAKER_FAILURES", "3")
    monkeypatch.setenv("AI_BREAKER_COOLDOWN", "0.01")
    client = ai_client.AIClient()
    client.analyze_image(image(tmp_path), "p")
    real_sleep = time.perf_counter() + 0.05
    while time.perf_counter() < real_sleep:
        pass
    resp, _, _ = client.analyze_image(image(tmp_path), "p")
    assert resp == {"ok": 1}
    assert ("GET", "/api/tags") in srv.other                           # teste de saúde pela API antes de voltar


def test_probe_reports_a_model_that_does_not_exist(servers, monkeypatch):
    srv = servers([ollama_chat("{}")])
    b = ai_client.OllamaBackend(srv.url, "x", "modelo-inexistente")
    # o servidor falso lista zero modelos: lista vazia não reprova (servidores que não listam)
    assert b.probe() == (True, "ok")
    monkeypatch.setattr(ai_client.requests, "get", lambda *a, **k: type("R", (), {
        "status_code": 200, "json": lambda self: {"models": [{"name": "outro"}]}})())
    ok, why = b.probe()
    assert not ok and "não existe" in why


def test_lm_studio_unload_uses_its_rest_api(monkeypatch):
    calls = []

    class R:
        status_code = 200

        def json(self):
            return {"models": [{"key": "qwen", "loaded_instances": [{"id": "qwen:1"}]}]}

    monkeypatch.setattr(ai_client.requests, "get", lambda url, **k: (calls.append(("GET", url)), R())[1])
    monkeypatch.setattr(ai_client.requests, "post", lambda url, **k: calls.append(("POST", url, k.get("json"))))
    ai_client.OpenAICompatBackend("http://h:1234/v1", "qwen", "qwen").reset()
    assert ("POST", "http://h:1234/api/v1/models/unload", {"instance_id": "qwen:1"}) in calls


# --- verificação cruzada (address_redactor) ------------------------------------------------------------
def test_cross_check_unites_answers_and_never_reduces_protection():
    from utils.address_redactor import merge_cross_check
    a = {"addresses": [{"text": "Rua A, 10", "type": "pessoal"}, {"text": "Av. B, 5", "type": "profissional"}]}
    b = {"addresses": [{"text": "Av.  B, 5", "type": "pessoal"}, {"text": "Rua C, 7", "type": "pessoal"}]}
    merged, note = merge_cross_check(a, b)
    kinds = {x["text"].replace("  ", " "): x["type"] for x in merged["addresses"]}
    assert kinds == {"Rua A, 10": "pessoal", "Av. B, 5": "pessoal", "Rua C, 7": "pessoal"}
    assert "discordaram" in note and "1 endereço(s) apontado(s) só pela IA verificadora" in note


def test_cross_check_with_one_side_failing_goes_to_review():
    from utils.address_redactor import merge_cross_check
    ok = {"addresses": [{"text": "Rua A, 10", "type": "pessoal"}]}
    assert merge_cross_check(ok, {"error": "x"}) == (ok, "verificação cruzada: a IA reserva não respondeu")
    assert merge_cross_check({"error": "x"}, ok)[1] == "verificação cruzada: só a IA reserva respondeu"
    merged, note = merge_cross_check(ok, {"addresses": [{"text": "Rua A, 10", "type": "pessoal"}]})
    assert merged == ok and note == ""                                   # concordaram: nada a revisar
    more = {"addresses": ok["addresses"] + [{"text": "Rua B, 2", "type": "pessoal"}]}
    assert merge_cross_check(more, ok)[1] == ""                          # principal viu mais: normal, sem revisão


def test_discovery_calls_the_secondary_when_cross_check_is_on(tmp_path, monkeypatch):
    from main import SentryApp
    from sentry_testkit import make_text_pdf
    monkeypatch.setenv("AI_CROSS_CHECK", "1")
    monkeypatch.setenv("AI_SECONDARY_PROVIDER", "openai")
    app = SentryApp(make_text_pdf(tmp_path / "a.pdf"))
    red = app.address_redactor
    seen = []

    def fake(path, prompt, only=None):
        seen.append(only)
        if only == "reserva":
            return {"addresses": [{"text": "Rua Z, 9", "type": "pessoal"}]}, b"", {}
        return {"addresses": []}, b"", {}
    monkeypatch.setattr(red.ai, "analyze_image", fake)
    red.run_discovery([image(tmp_path)], page_texts=["x"])
    assert seen == [None, "reserva"]
    assert [a["text"] for a in red.results[1]] == ["Rua Z, 9"] and "só pela IA verificadora" in red.review_notes[1]
    app.session.close()

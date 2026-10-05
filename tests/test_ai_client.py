# SPDX-License-Identifier: AGPL-3.0-or-later
import base64
import io
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from PIL import Image

from utils import ai_client
from utils.ai_client import OllamaClient, _env_float


class FakeOllama:
    """Servidor /api/chat falso. `script` = lista de respostas consumidas em ordem (a ultima se repete):
    (status, corpo_str_ou_dict, atraso_s)."""

    def __init__(self, script):
        self.script = list(script)
        self.requests = []        # só as chamadas de chat (/api/chat ou /chat/completions)
        self.other = []           # o resto (descarregar modelo, listar modelos)
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                outer.other.append(("GET", self.path))
                payload = b'{"models": [], "data": []}'
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length) or b"{}")
                if not self.path.endswith(("/api/chat", "/chat/completions")):
                    outer.other.append(("POST", self.path, body))
                    self.send_response(200)
                    self.send_header("Content-Length", "2")
                    self.end_headers()
                    self.wfile.write(b"{}")
                    return
                outer.requests.append(body)
                idx = min(len(outer.requests) - 1, len(outer.script) - 1)
                status, body, delay = outer.script[idx]
                if delay:
                    threading.Event().wait(delay)
                if isinstance(body, (dict, list)):
                    body = json.dumps(body)
                payload = body.encode("utf-8")
                try:
                    self.send_response(status)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                except (BrokenPipeError, ConnectionResetError, OSError):
                    pass  # cliente desistiu (timeout)

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=lambda: self.server.serve_forever(poll_interval=0.01), daemon=True)
        self.thread.start()

    @property
    def url(self):
        return f"http://127.0.0.1:{self.server.server_address[1]}"

    def stop(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture()
def ollama(monkeypatch):
    monkeypatch.setenv("AI_BREAKER_FAILURES", "100")  # estes testes medem as 3 tentativas; o disjuntor tem os seus
    servers = []

    def make(script):
        srv = FakeOllama(script)
        servers.append(srv)
        monkeypatch.setenv("OLLAMA_API_URL", srv.url + "/")  # barra final deve ser tolerada
        return srv

    monkeypatch.setattr(time, "sleep", lambda s: None)  # sem esperas de retry
    yield make
    for s in servers:
        s.stop()


def chat(content, **extra):
    body = {"message": {"role": "assistant", "content": content}}
    body.update(extra)
    return (200, body, 0)


def make_image(path, size=(3000, 2000)):
    Image.new("RGB", size, (200, 200, 200)).save(str(path))
    return str(path)


# --- _clean_json_response ----------------------------------------------------------------------
@pytest.mark.parametrize("raw,expected", [
    ('{"a": 1}', {"a": 1}),
    ('```json\n{"a": 2}\n```', {"a": 2}),
    ('texto antes {"a": 3} texto depois', {"a": 3}),
])
def test_clean_json_response_extracts_object(ollama, raw, expected):
    ollama([chat("x")])
    assert OllamaClient()._clean_json_response(raw) == expected


def test_clean_json_response_reports_malformed_and_missing(ollama):
    ollama([chat("x")])
    client = OllamaClient()
    bad = client._clean_json_response('{"a": 1,, }')
    assert "JSON malformado" in bad["error"] and "raw_fragment" in bad
    none = client._clean_json_response("sem json aqui")
    assert "Nenhum JSON" in none["error"]


def test_env_float_parsing(monkeypatch):
    monkeypatch.setenv("T_X", "2.5")
    assert _env_float("T_X", 9) == 2.5
    monkeypatch.setenv("T_X", "abc")
    assert _env_float("T_X", 9) == 9.0
    monkeypatch.setenv("T_X", "-1")
    assert _env_float("T_X", 9) == 9.0
    monkeypatch.delenv("T_X")
    assert _env_float("T_X", 9) == 9.0


def test_client_reads_models_and_url_from_env(ollama, monkeypatch):
    srv = ollama([chat("{}")])
    monkeypatch.setenv("OLLAMA_MODEL", "m-text")
    monkeypatch.setenv("OLLAMA_VISION_MODEL", "m-vision")
    c = OllamaClient()
    assert c.url == srv.url + "/api/chat"
    assert (c.model, c.vision_model) == ("m-text", "m-vision")


# --- analyze_text ------------------------------------------------------------------------------
def test_analyze_text_success_with_metrics(ollama):
    srv = ollama([chat('{"addresses": []}', total_duration=2_000_000_000, prompt_eval_count=11, eval_count=5)])
    result, metrics = OllamaClient().analyze_text("oi")
    assert result == {"addresses": []}
    assert metrics["input_tokens"] == 11 and metrics["output_tokens"] == 5
    assert metrics["total_duration_sec"] == 2.0
    payload = srv.requests[0]
    assert payload["stream"] is False and payload["messages"][1]["content"] == "oi"


def test_analyze_text_non_chat_json_is_returned_as_is(ollama):
    ollama([(200, {"foo": "bar"}, 0)])
    result, _ = OllamaClient().analyze_text("oi")
    assert result == {"foo": "bar"}


def test_analyze_text_retries_on_server_error_then_succeeds(ollama):
    srv = ollama([(500, {"error": "oom"}, 0), (503, "indisponivel", 0), chat('{"ok": true}')])
    result, _ = OllamaClient().analyze_text("oi")
    assert result == {"ok": True}
    assert len(srv.requests) == 3


def test_analyze_text_fails_after_three_attempts(ollama):
    srv = ollama([(500, "falha", 0)])
    result, metrics = OllamaClient().analyze_text("oi")
    assert "Falha após 3 tentativas" in result["error"] and metrics == {}
    assert len(srv.requests) == 3


def test_analyze_text_timeout(ollama, monkeypatch):
    monkeypatch.setenv("OLLAMA_TEXT_TIMEOUT", "0.2")
    srv = ollama([chat('{"ok": 1}') [:2] + (1.0,)])
    result, _ = OllamaClient().analyze_text("oi")
    assert "Falha após 3 tentativas" in result["error"]
    assert len(srv.requests) == 3


def test_analyze_text_json_list_body_is_retried_and_fails(ollama):
    srv = ollama([(200, [1, 2, 3], 0)])
    result, _ = OllamaClient().analyze_text("oi")
    assert "error" in result and len(srv.requests) == 3


def test_analyze_text_connection_refused(ollama, monkeypatch):
    import requests

    def refuse(*args, **kwargs):
        raise requests.ConnectionError("recusada")

    monkeypatch.setattr(ai_client.requests, "post", refuse)
    result, _ = OllamaClient().analyze_text("oi")
    assert "Falha após 3 tentativas" in result["error"] and "recusada" in result["error"]


# --- analyze_image -----------------------------------------------------------------------------
def sent_image_size(payload):
    raw = base64.b64decode(payload["messages"][1]["images"][0])
    with Image.open(io.BytesIO(raw)) as im:
        return im.size


def test_analyze_image_success_returns_parsed_json_bytes_metrics(ollama, tmp_path, monkeypatch):
    monkeypatch.setenv("AI_IMAGE_RESOLUTION", "1024")
    srv = ollama([chat('```json\n{"addresses": [{"text": "Rua X", "type": "pessoal"}]}\n```', eval_count=3)])
    response, img_bytes, metrics = OllamaClient().analyze_image(make_image(tmp_path / "a.png"), "prompt")
    assert response["addresses"][0]["type"] == "pessoal"
    assert img_bytes[:2] == b"\xff\xd8" and metrics["output_tokens"] == 3
    assert max(sent_image_size(srv.requests[0])) == 1024


def test_analyze_image_reduces_resolution_on_each_retry(ollama, tmp_path, monkeypatch):
    """Regressao: erro 5xx (ex.: Ollama sem VRAM) deve disparar o retry com imagem menor."""
    monkeypatch.setenv("AI_IMAGE_RESOLUTION", "1536")
    srv = ollama([(500, {"error": "out of memory"}, 0), (500, "x", 0), chat('{"ok": 1}')])
    response, img_bytes, _ = OllamaClient().analyze_image(make_image(tmp_path / "a.png"), "p")
    assert response == {"ok": 1}
    sizes = [max(sent_image_size(r)) for r in srv.requests]
    assert sizes == [1536, 1024, 512]


def test_analyze_image_empty_message_is_error(ollama, tmp_path):
    ollama([chat("")])
    response, img_bytes, _ = OllamaClient().analyze_image(make_image(tmp_path / "a.png", (400, 300)), "p")
    assert response["error"] == "A IA retornou uma mensagem vazia"
    assert img_bytes  # bytes enviados continuam disponiveis para auditoria


def test_analyze_image_non_json_200_is_error_not_crash(ollama, tmp_path):
    ollama([(200, "<html>proxy</html>", 0)])
    response, _, _ = OllamaClient().analyze_image(make_image(tmp_path / "a.png", (400, 300)), "p")
    assert "error" in response


def test_analyze_image_malformed_model_json_is_error(ollama, tmp_path):
    ollama([chat('{"addresses": [oops')])
    response, _, _ = OllamaClient().analyze_image(make_image(tmp_path / "a.png", (400, 300)), "p")
    assert "error" in response  # o chamador trata como falha da IA (fail-closed)


def test_analyze_image_all_attempts_fail(ollama, tmp_path):
    srv = ollama([(500, "x", 0)])
    response, img_bytes, metrics = OllamaClient().analyze_image(make_image(tmp_path / "a.png", (400, 300)), "p")
    assert "Falha crítica" in response["error"] and img_bytes is None and metrics == {}
    assert len(srv.requests) == 3


def test_analyze_image_timeout(ollama, tmp_path, monkeypatch):
    monkeypatch.setenv("OLLAMA_VISION_TIMEOUT", "0.2")
    srv = ollama([chat('{"ok": 1}')[:2] + (1.0,)])
    response, img_bytes, _ = OllamaClient().analyze_image(make_image(tmp_path / "a.png", (400, 300)), "p")
    assert "Falha crítica" in response["error"] and img_bytes is None
    assert len(srv.requests) == 3


def test_requests_are_serialized_by_the_shared_lock(ollama, tmp_path):
    """O lock global enfileira chamadas simultaneas (um modelo local por vez)."""
    ollama([chat('{"ok": 1}')[:2] + (0.15,)])
    results = []

    def call():
        results.append(OllamaClient().analyze_text("x")[0])

    threads = [threading.Thread(target=call) for _ in range(3)]
    start = time.perf_counter()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert time.perf_counter() - start >= 0.4  # 3 x 0.15s sequenciais
    assert results == [{"ok": 1}] * 3
    assert ai_client.ollama_lock.locked() is False

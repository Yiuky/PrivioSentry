# SPDX-License-Identifier: AGPL-3.0-or-later
"""Servidor MCP local (sentry_mcp.py) contra o app_service de verdade (TestClient, sem rede: I-08).

O agente envia, acompanha e baixa; nunca aprova, edita nem apaga; nunca recebe texto do documento (I-02, I-07)."""
import importlib
import io
import json
import os

import pytest

pytest.importorskip("fastapi")

import sentry_mcp  # noqa: E402

PDF = b"%PDF-1.4\n%fake\n"


@pytest.fixture()
def env(monkeypatch, tmp_path):
    import app_service
    importlib.reload(app_service)
    started = []
    monkeypatch.setattr(app_service, "start_worker", lambda tid, **kw: started.append(tid))
    from fastapi.testclient import TestClient
    client = sentry_mcp.Sentry(base_url="http://127.0.0.1:8001", token="", http=TestClient(app_service.app))
    pdf = tmp_path / "contrato ficticio.pdf"
    pdf.write_bytes(PDF)
    return client, app_service, str(pdf), started


def rpc(client, method, params=None, mid=1):
    return sentry_mcp.handle(client, {"jsonrpc": "2.0", "id": mid, "method": method, "params": params or {}})


def call(client, name, **args):
    out = rpc(client, "tools/call", {"name": name, "arguments": args})["result"]
    return out, (out.get("structuredContent") if not out["isError"] else out["content"][0]["text"])


def test_handshake_and_tool_list(env):
    client = env[0]
    init = rpc(client, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {}})["result"]
    assert init["protocolVersion"] == "2025-06-18" and init["capabilities"]["tools"]
    assert "revis" in init["instructions"]
    assert sentry_mcp.handle(client, {"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    names = {t["name"] for t in rpc(client, "tools/list")["result"]["tools"]}
    assert "sentry_submit_pdf" in names and "sentry_download_final" in names
    # contra teste: nada que aprove, edite tarjas, apague ou purgue
    assert not any(w in n for n in names for w in ("finaliz", "approve", "aprov", "delete", "apag", "purge",
                                                   "update", "redaction"))
    assert rpc(client, "nao/existe")["error"]["code"] == -32601


def test_unknown_protocol_version_gets_ours(env):
    assert rpc(env[0], "initialize", {"protocolVersion": "1999-01-01"})["result"]["protocolVersion"] \
        == sentry_mcp.SUPPORTED_VERSIONS[-1]


def test_submit_and_follow_a_document(env):
    client, mod, pdf, started = env
    out, data = call(client, "sentry_submit_pdf", caminho=pdf, perfil="cpf_endereco", baixa_qualidade=False)
    assert not out["isError"], data
    tid = data["task_id"]
    assert started == [tid] and data["revisar_em"].endswith(f"/?task={tid}")
    assert mod.tasks[tid]["options"]["perfil"] == "cpf_endereco"
    _, doc = call(client, "sentry_document", task_id=tid)
    assert doc["arquivo"] == "contrato ficticio.pdf" and doc["concluido"] is False
    _, docs = call(client, "sentry_list_documents")
    assert [d["task_id"] for d in docs["documentos"]] == [tid]


def test_agent_never_sees_document_text_or_alert_reasons(env):
    client, mod, pdf, _ = env
    _, data = call(client, "sentry_submit_pdf", caminho=pdf)
    tid = data["task_id"]
    mod.tasks[tid].update(completed=True, needs_review=True, status="Requer revisão",
                          alerts=["Pág 2: endereço Rua Fictícia das Flores, 123 não localizado"],
                          review_marks=[{"page": 3, "reason": "Rua Fictícia das Flores", "box": [0, 0, 1, 1]}],
                          pii_summary={"cpf": 2})
    out, doc = call(client, "sentry_document", task_id=tid)
    text = json.dumps(out)
    assert "Fictícia" not in text and "Flores" not in text and "input_path" not in text
    assert doc["paginas_a_revisar"] == [2, 3] and doc["alertas"] == 1 and doc["tipos_encontrados"] == {"cpf": 2}


def test_download_is_refused_until_a_reviewer_approves(env, tmp_path):
    client, mod, pdf, _ = env
    _, data = call(client, "sentry_submit_pdf", caminho=pdf)
    tid = data["task_id"]
    os.makedirs(mod.FINAL_DIR, exist_ok=True)
    with open(mod.final_pdf_path(mod.tasks[tid]), "wb") as fh:
        fh.write(b"%PDF-protegido")
    mod.tasks[tid].update(completed=True, needs_review=False, finalizado=False)   # PDF preliminar
    out, msg = call(client, "sentry_download_final", task_id=tid, destino=str(tmp_path))
    assert out["isError"] and "409" in msg and f"?task={tid}" in msg
    assert not list(tmp_path.glob("*_PROTEGIDO.pdf"))
    mod.tasks[tid].update(finalizado=True)                                        # revisor aplicou a proteção
    out, saved = call(client, "sentry_download_final", task_id=tid, destino=str(tmp_path))
    assert not out["isError"] and saved["arquivo"].endswith("contrato ficticio_PROTEGIDO.pdf")
    assert open(saved["arquivo"], "rb").read() == b"%PDF-protegido"
    out, msg = call(client, "sentry_download_final", task_id=tid, destino=saved["arquivo"])
    assert out["isError"] and "sobrescrever" in msg                               # não apaga arquivo existente


def test_wait_returns_when_done_or_on_timeout(env):
    client, mod, pdf, _ = env
    _, data = call(client, "sentry_submit_pdf", caminho=pdf)
    tid = data["task_id"]
    client.sleep = lambda s: mod.tasks[tid].update(completed=True)
    assert client.sentry_wait(tid, timeout_s=60)["concluido"] is True
    mod.tasks[tid].update(completed=False)
    clock = iter([0, 1000, 2000])
    client.clock = lambda: next(clock)
    client.sleep = lambda s: None
    assert client.sentry_wait(tid, timeout_s=5)["tempo_esgotado"] is True


def test_bad_inputs_are_tool_errors_not_crashes(env, tmp_path):
    client = env[0]
    out, msg = call(client, "sentry_submit_pdf", caminho=str(tmp_path / "nao-existe.pdf"))
    assert out["isError"] and "PDF" in msg
    out, msg = call(client, "sentry_document", task_id="nao-e-uuid")
    assert out["isError"] and "task_id" in msg
    out, msg = call(client, "sentry_document", task_id="0b0e8f4e-4c1e-4c43-9a43-0e2f0f4d8a11")
    assert out["isError"] and "404" in msg
    out, msg = call(client, "sentry_document", task_id="0b0e8f4e-4c1e-4c43-9a43-0e2f0f4d8a11", extra=1)
    assert out["isError"] and "Argumentos" in msg


def test_service_down_gives_a_clear_message():
    client = sentry_mcp.Sentry(base_url="http://127.0.0.1:9", token="")
    out, msg = call(client, "sentry_status")
    assert out["isError"] and "fora do ar" in msg


def test_token_is_sent_as_header():
    client = sentry_mcp.Sentry(base_url="http://127.0.0.1:9", token="segredo")
    assert client.http.headers["X-API-Token"] == "segredo"


def test_stdio_loop_speaks_line_delimited_json(env):
    client = env[0]
    lines = [json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}),
             json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}), "nao é json",
             json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                         "params": {"name": "sentry_status", "arguments": {}}})]
    out = io.StringIO()
    sentry_mcp.serve(io.StringIO("\n".join(lines) + "\n"), out, client)
    replies = [json.loads(x) for x in out.getvalue().splitlines()]
    assert [r.get("id") for r in replies] == [1, None, 2]
    assert replies[1]["error"]["code"] == -32700
    assert replies[2]["result"]["structuredContent"]["servico"] == "PRIVIO SENTRY"


def test_status_is_a_fixed_word_never_the_raw_error_text(env):
    client, mod, pdf, _ = env
    _, data = call(client, "sentry_submit_pdf", caminho=pdf)
    tid = data["task_id"]
    mod.tasks[tid].update(status="Erro: falha em C:/servidor/WEB_INPUT/x.pdf", error=True)
    out, doc = call(client, "sentry_document", task_id=tid)
    assert doc["situacao"] == "erro" and "WEB_INPUT" not in json.dumps(out)
    mod.tasks[tid].update(error=False, completed=True, needs_review=True)
    assert call(client, "sentry_document", task_id=tid)[1]["situacao"] == "requer_revisao"


def test_real_stdio_process_keeps_accented_paths(tmp_path):
    """Processo de verdade, bytes UTF-8 no stdin (como um cliente MCP no Windows): "João" chega inteiro."""
    import subprocess
    import sys
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    missing = str(tmp_path / "João e Conceição.pdf")
    msg = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
           "params": {"name": "sentry_submit_pdf", "arguments": {"caminho": missing}}}
    proc = subprocess.run([sys.executable, os.path.join(root, "sentry_mcp.py")],
                          input=(json.dumps(msg, ensure_ascii=False) + "\n").encode("utf-8"),
                          capture_output=True, timeout=60, env=dict(os.environ, PYTHONIOENCODING=""))
    reply = json.loads(proc.stdout.decode("utf-8").splitlines()[0])
    assert reply["result"]["isError"] and "João e Conceição.pdf" in reply["result"]["content"][0]["text"]


# ------------------------------------------------------------------ regressões da varredura de bugs
class StubHTTP:
    """Cliente HTTP falso: registra os pedidos e devolve sempre a mesma resposta."""
    def __init__(self, response):
        self.response, self.calls = response, []

    def request(self, method, path, **kw):
        self.calls.append((method, path))
        return self.response


def stub(content=b"%PDF-1.4 ficticio", status=200):
    import httpx
    http = StubHTTP(httpx.Response(status, content=content))
    return sentry_mcp.Sentry(base_url="http://127.0.0.1:8001", token="", http=http), http


@pytest.mark.parametrize("tool,extra", [("sentry_document", {}), ("sentry_wait", {"timeout_s": 5}),
                                        ("sentry_download_final", {"destino": "x.pdf"})])
@pytest.mark.parametrize("bad", ["../previews/0b0e8f4e-4c1e-4c43-9a43-0e2f0f4d8a11/1",
                                 "../tasks/0b0e8f4e-4c1e-4c43-9a43-0e2f0f4d8a11", "../logs/x", "../metadata/x",
                                 "0b0e8f4e-4c1e-4c43-9a43-0e2f0f4d8a11?final=false",
                                 "0b0e8f4e-4c1e-4c43-9a43-0e2f0f4d8a11\n", 123, None])
def test_task_id_must_be_a_uuid_before_any_request(tmp_path, tool, extra, bad):
    client, http = stub()
    args = dict(extra, task_id=bad)
    if "destino" in args:
        args["destino"] = str(tmp_path / "saida.pdf")
    out, msg = call(client, tool, **args)
    assert out["isError"] and "task_id" in msg and http.calls == []
    assert not list(tmp_path.glob("*.pdf*"))


def test_traversal_never_saves_the_original_page_or_task_json(env, tmp_path):
    client, mod, pdf, _ = env
    _, data = call(client, "sentry_submit_pdf", caminho=pdf)
    tid = data["task_id"]
    mod.tasks[tid].update(completed=True, needs_review=True, alerts=["Pág 2: Rua Fictícia das Flores, 123"])
    for i, trick in enumerate([f"../previews/{tid}/1", f"../tasks/{tid}", f"../metadata/{tid}", f"../logs/{tid}"]):
        out, _ = call(client, "sentry_download_final", task_id=trick, destino=str(tmp_path / f"vazou{i}.pdf"))
        assert out["isError"] and not (tmp_path / f"vazou{i}.pdf").exists()


def test_download_refuses_a_body_that_is_not_a_pdf(tmp_path):
    client, _ = stub(content=b"<html>pagina de erro do gatekeeper</html>")
    out, msg = call(client, "sentry_download_final", task_id="0b0e8f4e-4c1e-4c43-9a43-0e2f0f4d8a11",
                    destino=str(tmp_path / "x.pdf"))
    assert out["isError"] and "PDF" in msg and not list(tmp_path.glob("*.pdf*"))
    client, _ = stub()                                                                    # contra teste
    out, saved = call(client, "sentry_download_final", task_id="0b0e8f4e-4c1e-4c43-9a43-0e2f0f4d8a11",
                      destino=str(tmp_path / "x.pdf"))
    assert not out["isError"] and open(saved["arquivo"], "rb").read().startswith(b"%PDF-")


def test_malformed_input_never_kills_the_stdio_server(tmp_path):
    client, _ = stub(content=b"isto nao e json")
    tid = "0b0e8f4e-4c1e-4c43-9a43-0e2f0f4d8a11"
    blocker = tmp_path / "arquivo"
    blocker.write_text("x")
    lines = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": [1]},
             {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": "x"},
             {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
              "params": {"name": "sentry_wait", "arguments": {"task_id": tid, "timeout_s": "abc"}}},
             {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
              "params": {"name": "sentry_document", "arguments": {"task_id": tid}}},           # 200 que não é JSON
             {"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "sentry_status", "arguments": [1]}},
             {"jsonrpc": "2.0", "id": 6, "method": "tools/call",
              "params": {"name": "sentry_download_final",
                         "arguments": {"task_id": tid, "destino": str(blocker / "sub" / "x.pdf")}}},  # pasta impossível
             {"jsonrpc": "2.0", "id": 7, "method": "ping"}]
    out = io.StringIO()
    sentry_mcp.serve(io.StringIO("\n".join(json.dumps(x) for x in lines) + "\n"), out, client)
    replies = {r["id"]: r for r in map(json.loads, out.getvalue().splitlines())}
    assert replies[1]["error"]["code"] == -32602 and replies[2]["error"]["code"] == -32602
    for i in (3, 4, 5, 6):
        assert replies[i]["result"]["isError"] is True, replies[i]
    assert "isto nao e json" not in out.getvalue()
    assert replies[7]["result"] == {}


def test_unwritable_destination_is_a_tool_error(tmp_path):
    client, _ = stub()                                                                    # corpo é PDF
    blocker = tmp_path / "arquivo"
    blocker.write_text("x")
    out, msg = call(client, "sentry_download_final", task_id="0b0e8f4e-4c1e-4c43-9a43-0e2f0f4d8a11",
                    destino=str(blocker / "sub" / "x.pdf"))
    assert out["isError"] and "gravar" in msg and not list(tmp_path.rglob("*.part"))


def test_bad_service_url_is_a_tool_error():
    import httpx

    class Bad:
        def request(self, *a, **kw):
            raise httpx.InvalidURL("URL inválida")
    client = sentry_mcp.Sentry(base_url="http://127.0.0.1:8001", token="", http=Bad())
    out, msg = call(client, "sentry_status")
    assert out["isError"] and "PRIVIO_URL" in msg

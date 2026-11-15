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
    assert out["isError"] and "404" in msg
    out, msg = call(client, "sentry_document", task_id="x", extra=1)
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

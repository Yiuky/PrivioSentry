# SPDX-License-Identifier: AGPL-3.0-or-later
"""Demais rotas e helpers de app_service (sem pipeline real)."""
import importlib
import json
import os
import uuid

import pytest

pytest.importorskip("fastapi")

from sentry_testkit import CPF_A_FMT, FULL_CPF_RE  # noqa: E402

PDF = b"%PDF-1.4\n%fake\n"


@pytest.fixture()
def svc(monkeypatch):
    import app_service
    importlib.reload(app_service)
    started = []
    monkeypatch.setattr(app_service, "start_worker", lambda tid, **kw: started.append((tid, kw)))
    from fastapi.testclient import TestClient
    app_service.started = started
    return TestClient(app_service.app), app_service


def upload(c, name="doc.pdf"):
    r = c.post("/upload", files={"file": (name, PDF)})
    assert r.status_code == 200, r.text
    return r.json()["task_id"]


def out_dir(mod, tid):
    return os.path.join(mod.OUTPUT_DIR, mod.task_base(mod.tasks[tid]))


# --- basicos -----------------------------------------------------------------------------------
def test_index_and_readme(svc):
    c, mod = svc
    r = c.get("/")
    assert r.status_code == 200 and "<html" in r.text.lower()
    readme = c.get("/readme")
    assert readme.status_code in (200, 404)
    if readme.status_code == 200:
        assert isinstance(readme.json()["content"], str)


def test_readme_not_found(svc, monkeypatch, tmp_path):
    c, mod = svc
    monkeypatch.setattr(mod, "BASE_DIR", str(tmp_path / "vazio"))
    assert c.get("/readme").status_code == 404


def test_upload_starts_worker_and_lists_task(svc):
    c, mod = svc
    tid = upload(c)
    assert mod.started == [(tid, {})]
    task = c.get("/tasks").json()[tid]
    assert task["status"] == "Iniciando..." and task["completed"] is False
    assert os.path.exists(task["input_path"])
    saved = json.load(open(mod.TASKS_FILE, encoding="utf-8"))
    assert tid in saved


def test_sanitize_filename_cases(svc):
    _, mod = svc
    s = mod.sanitize_filename
    assert s("a/b\\c.pdf") == "c.pdf"
    assert s("  ..x.pdf. ") == "x.pdf"
    assert s("") == "documento.pdf" and s(None) == "documento.pdf"
    assert s("rel<at>ório?.pdf") == "rel_at_ório_.pdf"
    long = s("a" * 300 + ".pdf")
    assert len(long) <= 150 and long.endswith(".pdf")


def test_load_tasks_with_corrupt_file_starts_empty(monkeypatch, tmp_path):
    (tmp_path / "state").mkdir(exist_ok=True)
    (tmp_path / "state" / "tasks.json").write_text("{corrompido", encoding="utf-8")
    import app_service
    importlib.reload(app_service)
    assert app_service.tasks == {}


def test_save_tasks_failure_is_logged_not_raised(svc, monkeypatch):
    _, mod = svc
    monkeypatch.setattr(mod.os, "replace", lambda *a: (_ for _ in ()).throw(OSError("disco")))
    mod.save_tasks()


# --- token / internal --------------------------------------------------------------------------
def test_token_via_query_sets_cookie_and_internal_is_exempt(svc, monkeypatch):
    c, mod = svc
    monkeypatch.setattr(mod, "API_TOKEN", "segredo")
    assert c.get("/tasks").status_code == 401
    r = c.get("/tasks?token=segredo")
    assert r.status_code == 200 and "api_token" in r.headers.get("set-cookie", "")
    assert c.get("/tasks").status_code == 200   # cookie reaproveitado pelo cliente
    assert c.post("/internal/update/x", json={}).status_code == 403   # exige segredo interno, nao token


def test_internal_update_merges_alerts_and_ignores_unknown_task(svc):
    c, mod = svc
    tid = upload(c)
    h = {"X-Internal-Secret": mod.INTERNAL_SECRET}
    c.post(f"/internal/update/{tid}", json={"status": "OCR", "percentage": 20, "alerts": ["a"]}, headers=h)
    assert mod.tasks[tid]["alerts"] == ["a"] and mod.tasks[tid]["percentage"] == 20
    assert c.post(f"/internal/update/{uuid.uuid4()}", json={"status": "x"}, headers=h).status_code == 200


# --- reprocessar / logs / process-all ---------------------------------------------------------
def test_reprocess_resets_state_and_starts_worker(svc):
    c, mod = svc
    tid = upload(c)
    mod.tasks[tid].update(status="Erro: x", error=True, alerts=["x"], needs_review=True, percentage=50)
    mod.started.clear()
    assert c.post(f"/reprocess/{tid}").json() == {"status": "restarted"}
    t = mod.tasks[tid]
    assert (t["status"], t["percentage"], t["error"], t["alerts"], t["needs_review"]) == ("Reiniciando...", 0, False, [], False)
    assert mod.started == [(tid, {})]


def test_logs_endpoint_states(svc):
    c, mod = svc
    assert c.get("/logs/not-a-uuid").json() == {"log": "Tarefa não encontrada."}
    tid = upload(c)
    assert c.get(f"/logs/{tid}").json() == {"log": "Nenhum log encontrado."}
    os.makedirs(out_dir(mod, tid))
    log = os.path.join(out_dir(mod, tid), "process_log.log")
    open(log, "w", encoding="utf-8").write("linha de log\n")
    assert c.get(f"/logs/{tid}").json() == {"log": "linha de log\n"}
    open(log, "wb").write(b"\xff\xfe\x00bin")   # nao-UTF8
    assert c.get(f"/logs/{tid}").json() == {"log": "Erro ao ler as linhas de log."}


def test_process_all_starts_waiting_and_failed_tasks_only(svc):
    c, mod = svc
    a, b, d = upload(c, "a.pdf"), upload(c, "b.pdf"), upload(c, "d.pdf")
    mod.tasks[a]["status"] = "Aguardando"
    mod.tasks[b].update(status="Erro", error=True)
    mod.tasks[d].update(status="Concluído", completed=True)
    mod.started.clear()
    r = c.post("/process-all")
    assert r.json() == {"status": "started", "count": 2}
    assert {t for t, _ in mod.started} == {a, b}
    assert mod.tasks[b]["error"] is False


# --- previews / metadados / editor -------------------------------------------------------------
def test_preview_404_and_original_image(svc):
    c, mod = svc
    tid = upload(c)
    assert c.get(f"/previews/{tid}/1").status_code == 404
    d = os.path.join(out_dir(mod, tid), "00_original_images")
    os.makedirs(d)
    base = mod.task_base(mod.tasks[tid])
    open(os.path.join(d, f"{base}_page_2.png"), "wb").write(b"PNG2")
    assert c.get(f"/previews/{tid}/2").content == b"PNG2"
    assert c.get("/previews/not-a-uuid/1").status_code == 404


def test_metadata_prefers_manual_over_ai_and_survives_corruption(svc):
    c, mod = svc
    tid = upload(c)
    assert c.get(f"/metadata/{tid}").json() == {"redactions": []}
    d = out_dir(mod, tid)
    os.makedirs(d)
    open(os.path.join(d, "redactions_metadata.json"), "w").write(json.dumps([{"page": 1, "src": "ai"}]))
    assert c.get(f"/metadata/{tid}").json()["redactions"][0]["src"] == "ai"
    manual = [{"page": 1, "src": "manual"}]
    assert c.post(f"/update-redactions/{tid}", json=manual).json() == {"status": "success"}
    assert c.get(f"/metadata/{tid}").json()["redactions"] == manual
    open(os.path.join(d, "manual_redactions.json"), "w").write("{quebrado")
    assert c.get(f"/metadata/{tid}").json()["redactions"][0]["src"] == "ai"   # cai para o da IA
    assert c.post(f"/reprocess-metadata/{tid}").json() == {"status": "success"}
    assert not os.path.exists(os.path.join(d, "manual_redactions.json"))
    assert c.post(f"/reprocess-metadata/{tid}").status_code == 200   # sem arquivo: idempotente


def test_update_redactions_write_failure_is_500(svc, monkeypatch):
    c, mod = svc
    tid = upload(c)   # sem pasta de saida -> falha ao abrir arquivo
    r = c.post(f"/update-redactions/{tid}", json=[])
    assert r.status_code == 500


def test_finalize_native_and_legacy_start_worker_with_current_redactions(svc):
    c, mod = svc
    tid = upload(c)
    d = out_dir(mod, tid)
    os.makedirs(d)
    open(os.path.join(d, "manual_redactions.json"), "w").write(json.dumps([{"page": 1}]))
    mod.started.clear()
    assert c.post(f"/finalize-native/{tid}").json() == {"status": "started"}
    assert mod.tasks[tid]["status"] == "Gerando PDF Nativo..." and mod.tasks[tid]["percentage"] == 90
    assert c.post(f"/finalize/{tid}").json() == {"status": "started"}
    assert mod.tasks[tid]["status"] == "Gerando PDF Final..."
    assert mod.started == [(tid, {"manual_redactions": [{"page": 1}], "native_mode": True}),
                           (tid, {"manual_redactions": [{"page": 1}], "native_mode": False})]


# --- download ----------------------------------------------------------------------------------
def test_download_states_and_headers(svc):
    c, mod = svc
    tid = upload(c, "Relatório ção.pdf")
    assert c.get(f"/download/{tid}").status_code == 202           # ainda processando
    mod.tasks[tid]["completed"] = True
    assert c.get(f"/download/{tid}").status_code == 404           # concluida sem arquivo
    final = mod.final_pdf_path(mod.tasks[tid])
    open(final, "wb").write(PDF)
    r = c.get(f"/download/{tid}")
    assert r.status_code == 200 and r.content == PDF and r.headers["content-type"] == "application/pdf"
    assert r.headers["content-disposition"].startswith("attachment; filename*=UTF-8''")
    assert "TARJADO.pdf" in r.headers["content-disposition"] and "no-store" in r.headers["cache-control"]
    assert c.get(f"/download/{tid}?inline=true").headers["content-disposition"].startswith("inline;")


# --- worker ------------------------------------------------------------------------------------
class FakeHttpClient:
    posts = []

    def __init__(self, *a, **k):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def post(self, url, json=None, headers=None):
        FakeHttpClient.posts.append((url, json, headers))


def test_redaction_worker_reports_progress_and_final_state(svc, monkeypatch):
    _, mod = svc
    FakeHttpClient.posts = []
    monkeypatch.setattr(mod.httpx, "Client", FakeHttpClient)
    seen = {}

    class FakeApp:
        def __init__(self, path, output_dir=None, final_dir=None):
            seen.update(path=path, output_dir=output_dir, final_dir=final_dir)

        def run(self, progress_callback, manual_redactions, native_mode):
            progress_callback({"status": "meio", "percentage": 50})
            seen["mr"], seen["native"] = manual_redactions, native_mode

        def final_state(self):
            return {"status": "Concluído", "percentage": 100, "completed": True}

    monkeypatch.setattr(mod, "SentryApp", FakeApp)
    lock = object()
    mod.redaction_worker("tid", "x.pdf", [1], True, 1234, "seg", ai_lock=lock)
    import utils.ai_client as ai_client
    assert ai_client.ollama_lock is lock
    assert seen["output_dir"] == mod.OUTPUT_DIR and seen["final_dir"] == mod.FINAL_DIR
    assert seen["mr"] == [1] and seen["native"] is True
    urls = [p[0] for p in FakeHttpClient.posts]
    assert urls == ["http://127.0.0.1:1234/internal/update/tid"] * 2
    assert FakeHttpClient.posts[0][2] == {"X-Internal-Secret": "seg"}
    assert FakeHttpClient.posts[-1][1]["status"] == "Concluído"
    import threading
    ai_client.ollama_lock = threading.Lock()


def test_redaction_worker_reports_failure_without_pii(svc, monkeypatch):
    _, mod = svc
    FakeHttpClient.posts = []
    monkeypatch.setattr(mod.httpx, "Client", FakeHttpClient)

    class Boom:
        def __init__(self, *a, **k):
            raise RuntimeError("falha ao abrir")

    monkeypatch.setattr(mod, "SentryApp", Boom)
    mod.redaction_worker("tid", "x.pdf")
    payload = FakeHttpClient.posts[-1][1]
    assert payload["status"].startswith("Erro:") and payload["error"] is True


def test_redaction_worker_survives_unreachable_service(svc, monkeypatch, capsys):
    _, mod = svc

    class Down(FakeHttpClient):
        def post(self, *a, **k):
            raise ConnectionError("servico fora")

    monkeypatch.setattr(mod.httpx, "Client", Down)
    monkeypatch.setattr(mod, "SentryApp", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
    mod.redaction_worker("tid", "x.pdf")   # nao levanta
    assert "Erro ao reportar progresso" in capsys.readouterr().out


# --- start_worker real (processo falso) --------------------------------------------------------
def test_start_worker_spawns_process_once_and_rejects_duplicates(monkeypatch):
    import app_service
    importlib.reload(app_service)
    mod = app_service
    from fastapi import HTTPException
    tid = str(uuid.uuid4())
    inp = os.path.join(mod.INPUT_DIR, "x.pdf")
    open(inp, "wb").write(PDF)
    mod.tasks[tid] = {"input_path": inp, "status": "x"}
    created = []

    class FakeProc:
        alive = True

        def __init__(self, target, args):
            created.append((target, args))

        def start(self):
            pass

        def is_alive(self):
            return FakeProc.alive

    monkeypatch.setattr(mod.multiprocessing, "Process", FakeProc)
    mod.start_worker(tid, manual_redactions=[1], native_mode=True)
    target, args = created[0]
    assert target is mod.redaction_worker
    assert args[:4] == (tid, inp, [1], True) and args[4] == mod.APP_PORT and args[5] == mod.INTERNAL_SECRET
    assert mod.is_running(tid)
    with pytest.raises(HTTPException) as err:
        mod.start_worker(tid)
    assert err.value.status_code == 409
    FakeProc.alive = False
    os.remove(inp)
    with pytest.raises(HTTPException) as err:
        mod.start_worker(tid)
    assert err.value.status_code == 409 and "entrada" in err.value.detail


def test_app_logger_masks_cpf_in_service_logs(svc, caplog):
    """O log do app (root) passa pelo filtro de mascaramento instalado em app_service."""
    import io
    import logging
    _, mod = svc
    stream = io.StringIO()
    root = logging.getLogger()
    handler = logging.StreamHandler(stream)
    root.addHandler(handler)
    try:
        from utils.pii import install_log_masking
        install_log_masking()
        mod.app_logger.error(f"Erro com {CPF_A_FMT}")
        assert not FULL_CPF_RE.search(stream.getvalue())
    finally:
        root.removeHandler(handler)

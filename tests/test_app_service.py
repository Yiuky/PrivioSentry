# SPDX-License-Identifier: AGPL-3.0-or-later
import json
import os

import pytest

pytest.importorskip("fastapi")


@pytest.fixture()
def client(tmp_path, monkeypatch):
    # isola estado: tasks.json e WEB_INPUT temporários; nunca dispara o pipeline real
    monkeypatch.setenv("PRIVIO_TASKS_FILE", str(tmp_path / "tasks.json"))
    monkeypatch.setenv("PRIVIO_INPUT_DIR", str(tmp_path / "in"))
    monkeypatch.delenv("API_TOKEN", raising=False)
    import importlib
    import app_service
    importlib.reload(app_service)
    monkeypatch.setattr(app_service, "start_worker", lambda *a, **k: None)
    from fastapi.testclient import TestClient
    return TestClient(app_service.app), app_service


PDF = b"%PDF-1.4\n%fake\n"


def test_upload_rejects_non_pdf_extension(client):
    c, _ = client
    r = c.post("/upload", files={"file": ("x.txt", PDF)})
    assert r.status_code == 400


def test_upload_rejects_fake_pdf_content(client):
    c, _ = client
    r = c.post("/upload", files={"file": ("x.pdf", b"MZ not a pdf")})
    assert r.status_code == 400


def test_upload_sanitizes_malicious_filename(client, tmp_path):
    c, mod = client
    r = c.post("/upload", files={"file": (r"..\..\evil<img onerror=1>.pdf", PDF)})
    assert r.status_code == 200
    task = mod.tasks[r.json()["task_id"]]
    assert "/" not in task["file"] and "\\" not in task["file"] and "<" not in task["file"]
    # arquivo gravado dentro do diretório de entrada
    assert os.path.dirname(os.path.abspath(task["input_path"])) == os.path.abspath(mod.INPUT_DIR)


def test_upload_size_limit(client, monkeypatch):
    c, mod = client
    monkeypatch.setattr(mod, "MAX_UPLOAD_BYTES", 10)
    r = c.post("/upload", files={"file": ("big.pdf", PDF + b"x" * 100)})
    assert r.status_code == 413


def test_invalid_task_id_is_404(client):
    c, _ = client
    for bad in ["not-a-uuid", "..%5C..%5Cx", "00000000-0000-0000-0000-000000000000"]:
        assert c.get(f"/metadata/{bad}").status_code == 404
        assert c.post(f"/reprocess/{bad}").status_code == 404


def test_duplicate_run_returns_409(client, monkeypatch):
    c, mod = client
    r = c.post("/upload", files={"file": ("a.pdf", PDF)})
    tid = r.json()["task_id"]
    monkeypatch.setattr(mod, "is_running", lambda t: True)
    assert c.post(f"/reprocess/{tid}").status_code == 409
    assert c.post(f"/finalize-native/{tid}").status_code == 409
    assert c.delete(f"/task/{tid}").status_code == 409


def test_internal_update_requires_secret(client):
    c, mod = client
    tid = c.post("/upload", files={"file": ("a.pdf", PDF)}).json()["task_id"]
    assert c.post(f"/internal/update/{tid}", json={"status": "x"}).status_code == 403
    ok = c.post(f"/internal/update/{tid}", json={"status": "x"}, headers={"X-Internal-Secret": mod.INTERNAL_SECRET})
    assert ok.status_code == 200
    assert mod.tasks[tid]["status"] == "x"


def test_api_token_enforced_when_set(client, monkeypatch):
    c, mod = client
    monkeypatch.setattr(mod, "API_TOKEN", "segredo")
    assert c.get("/tasks").status_code == 401
    assert c.get("/tasks", headers={"X-API-Token": "errado"}).status_code == 401
    assert c.get("/tasks", headers={"X-API-Token": "segredo"}).status_code == 200


def test_tasks_file_written_atomically_and_interrupted_reconciled(tmp_path, monkeypatch):
    tasks_file = tmp_path / "tasks.json"
    tasks_file.write_text(json.dumps({"a" * 8 + "-aaaa-aaaa-aaaa-" + "a" * 12: {
        "status": "OCR", "completed": False, "error": False, "input_path": "x.pdf"}}), encoding="utf-8")
    monkeypatch.setenv("PRIVIO_TASKS_FILE", str(tasks_file))
    monkeypatch.setenv("PRIVIO_INPUT_DIR", str(tmp_path / "in"))
    import importlib
    import app_service
    importlib.reload(app_service)
    t = next(iter(app_service.tasks.values()))
    assert t["status"] == "Interrompido" and t["error"] is True
    assert not os.path.exists(str(tasks_file) + ".tmp")
    assert json.loads(tasks_file.read_text(encoding="utf-8"))  # JSON íntegro

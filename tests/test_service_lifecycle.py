# SPDX-License-Identifier: AGPL-3.0-or-later
"""Retencao/limpeza (delete, purge, RETENTION_DAYS) e bug do reimport pelos workers."""
import importlib
import json
import multiprocessing
import os
import uuid
from datetime import datetime, timedelta

import pytest

pytest.importorskip("fastapi")


def load_service(monkeypatch=None):
    import app_service
    importlib.reload(app_service)
    return app_service


@pytest.fixture()
def svc(monkeypatch):
    mod = load_service()
    started = []
    monkeypatch.setattr(mod, "start_worker", lambda tid, **kw: started.append((tid, kw)))
    from fastapi.testclient import TestClient
    client = TestClient(mod.app)
    mod.started = started
    return client, mod


def make_task(mod, name="a.pdf", *, final=True, completed=True, created_at=None, needs_review=False):
    """Cria uma tarefa com TODOS os artefatos que o pipeline gera (arquivos ficticios)."""
    tid = str(uuid.uuid4())
    input_path = os.path.join(mod.INPUT_DIR, f"{tid}_{name}")
    with open(input_path, "wb") as f:
        f.write(b"%PDF-1.4 original")
    base = f"{tid}_{os.path.splitext(name)[0]}"
    out = os.path.join(mod.OUTPUT_DIR, base)
    files = [
        "00_original_images/p1.png", "01_ocr_results/page_1.txt", "02_signature_crops/c.jpg",
        "04_signatures_crops_ia/x.jpg", "04_signatures_crops_tarjados/y.jpg", "04_micro_audit_results/m.json",
        "06_final_enhanced/e.jpg", "07_addresses_crops_ia/page_1_addresses.json", "08_addresses_crops_tarjados/z.jpg",
        "99_ia_interactions/p_source.jpg", "99_ia_interactions/p_prompt.txt",
        "05_final_export/cpf_only/a.jpg", "05_final_export/address_only/b.jpg",
        "05_final_export/combined/page_1_REDACTED.jpg", "05_phase_5_export/r.jpg",
        "process_log.log", "redactions_metadata.json", "manual_redactions.json", "detected_cpfs.txt",
    ]
    for rel in files:
        path = os.path.join(out, *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(b"x")
    final_pdf = os.path.join(mod.FINAL_DIR, f"{base}_TARJADO_FINAL.pdf")
    if final:
        with open(final_pdf, "wb") as f:
            f.write(b"%PDF-1.4 final")
    mod.tasks[tid] = {
        "file": name, "input_path": input_path, "created_at": created_at or datetime.now().isoformat(),
        "status": "Concluído", "percentage": 100, "completed": completed, "error": False,
        "needs_review": needs_review, "alerts": [],
    }
    mod.save_tasks()
    return tid, input_path, out, final_pdf


# --- exclusao ----------------------------------------------------------------------------------
def test_delete_task_removes_output_input_and_final_pdf(svc):
    c, mod = svc
    tid, inp, out, final = make_task(mod)
    other = make_task(mod, "b.pdf")
    r = c.delete(f"/task/{tid}")
    assert r.status_code == 200 and r.json()["status"] == "deleted"
    assert not os.path.exists(inp) and not os.path.exists(out) and not os.path.exists(final)
    assert tid not in mod.tasks and tid not in json.load(open(mod.TASKS_FILE, encoding="utf-8"))
    # outra tarefa intacta
    assert os.path.exists(other[1]) and os.path.isdir(other[2]) and os.path.exists(other[3])


def test_delete_task_tolerates_already_missing_artifacts(svc):
    c, mod = svc
    tid, inp, out, final = make_task(mod, final=False)
    os.remove(inp)
    assert c.delete(f"/task/{tid}").status_code == 200


def test_delete_never_touches_paths_outside_work_area(svc, tmp_path):
    c, mod = svc
    tid, inp, out, final = make_task(mod)
    outsider = tmp_path / "importante.pdf"
    outsider.write_bytes(b"nao apague")
    mod.tasks[tid]["input_path"] = str(outsider)   # tasks.json adulterado
    assert c.delete(f"/task/{tid}").status_code == 200
    assert outsider.exists()


def test_delete_failure_keeps_task_and_reports(svc, monkeypatch):
    c, mod = svc
    tid, inp, out, final = make_task(mod)
    monkeypatch.setattr(mod.shutil, "rmtree", lambda p: (_ for _ in ()).throw(PermissionError("em uso")))
    r = c.delete(f"/task/{tid}")
    assert r.status_code == 500 and "em uso" in json.dumps(r.json())
    assert tid in mod.tasks  # nao "esquece" a tarefa enquanto houver PII em disco


def test_delete_all_removes_everything(svc):
    c, mod = svc
    made = [make_task(mod, f"d{i}.pdf") for i in range(3)]
    assert c.delete("/delete-all").json() == {"status": "deleted_all"}
    assert mod.tasks == {}
    for _, inp, out, final in made:
        assert not os.path.exists(inp) and not os.path.exists(out) and not os.path.exists(final)
    assert json.load(open(mod.TASKS_FILE, encoding="utf-8")) == {}


def test_delete_all_blocked_while_running_and_partial_failure(svc, monkeypatch):
    c, mod = svc
    a = make_task(mod, "a.pdf")
    b = make_task(mod, "b.pdf")
    monkeypatch.setattr(mod, "is_running", lambda t: t == a[0])
    assert c.delete("/delete-all").status_code == 409
    monkeypatch.setattr(mod, "is_running", lambda t: False)
    real_rmtree = mod.shutil.rmtree

    def selective(path):
        if os.path.basename(path).startswith(a[0]):
            raise PermissionError("travado")
        return real_rmtree(path)

    monkeypatch.setattr(mod.shutil, "rmtree", selective)
    r = c.delete("/delete-all")
    assert r.status_code == 500
    assert a[0] in mod.tasks and b[0] not in mod.tasks  # so a que falhou permanece
    assert not os.path.exists(b[2])


# --- purge -------------------------------------------------------------------------------------
KEPT = ["05_final_export/combined/page_1_REDACTED.jpg", "05_phase_5_export/r.jpg", "process_log.log",
        "redactions_metadata.json", "manual_redactions.json", "detected_cpfs.txt"]
REMOVED_DIRS = ["00_original_images", "01_ocr_results", "02_signature_crops", "04_signatures_crops_ia",
                "04_signatures_crops_tarjados", "04_micro_audit_results", "06_final_enhanced",
                "07_addresses_crops_ia", "08_addresses_crops_tarjados", "99_ia_interactions",
                "05_final_export/cpf_only", "05_final_export/address_only"]


def test_purge_removes_unredacted_images_but_keeps_final_pdf_and_metadata(svc):
    c, mod = svc
    tid, inp, out, final = make_task(mod)
    r = c.post(f"/purge/{tid}")
    assert r.status_code == 200 and r.json()["status"] == "purged" and r.json()["errors"] == []
    for rel in REMOVED_DIRS:
        assert not os.path.exists(os.path.join(out, *rel.split("/"))), rel
    for rel in KEPT:
        assert os.path.exists(os.path.join(out, *rel.split("/"))), rel
    assert os.path.exists(final) and os.path.exists(inp)  # PDF final e (por padrao) o PDF de entrada
    assert mod.tasks[tid]["purged"] is True
    assert c.post(f"/purge/{tid}").status_code == 200   # idempotente


def test_purge_can_also_remove_the_uploaded_input(svc):
    c, mod = svc
    tid, inp, out, final = make_task(mod)
    assert c.post(f"/purge/{tid}?include_input=true").status_code == 200
    assert not os.path.exists(inp) and os.path.exists(final)
    assert mod.tasks[tid]["input_purged"] is True


def test_purge_preconditions(svc, monkeypatch):
    c, mod = svc
    no_final, *_ = make_task(mod, final=False)
    assert c.post(f"/purge/{no_final}").status_code == 409
    review, _, out, _ = make_task(mod, needs_review=True)
    assert c.post(f"/purge/{review}").status_code == 409
    assert os.path.isdir(os.path.join(out, "00_original_images"))
    assert c.post(f"/purge/{review}?force=true").status_code == 200
    running, *_ = make_task(mod)
    monkeypatch.setattr(mod, "is_running", lambda t: True)
    assert c.post(f"/purge/{running}").status_code == 409
    assert c.post("/purge/not-a-uuid").status_code == 404


def test_previews_fall_back_to_redacted_page_after_purge(svc):
    c, mod = svc
    tid, inp, out, final = make_task(mod)
    # antes: imagem original (nome <base>_page_1.png)
    base = os.path.basename(out)
    with open(os.path.join(out, "00_original_images", f"{base}_page_1.png"), "wb") as f:
        f.write(b"ORIGINAL")
    assert c.get(f"/previews/{tid}/1").content == b"ORIGINAL"
    c.post(f"/purge/{tid}")
    r = c.get(f"/previews/{tid}/1")
    assert r.status_code == 200 and r.content == b"x"   # combined/page_1_REDACTED.jpg (ja tarjada)


def test_after_purge_legacy_finalize_is_refused_but_native_works(svc):
    c, mod = svc
    tid, *_ = make_task(mod)
    c.post(f"/purge/{tid}")
    assert c.post(f"/finalize/{tid}").status_code == 409
    assert mod.started == []
    assert c.post(f"/finalize-native/{tid}").status_code == 200
    assert mod.started[0][1]["native_mode"] is True


def test_reprocess_clears_purged_flag_and_requires_input(svc):
    c, mod = svc
    tid, inp, out, final = make_task(mod)
    c.post(f"/purge/{tid}?include_input=true")
    before = dict(mod.tasks[tid])
    r = c.post(f"/reprocess/{tid}")
    assert r.status_code == 409 and "entrada" in r.json()["detail"]
    assert mod.tasks[tid]["status"] == before["status"]   # estado nao ficou preso em "Reiniciando..."
    open(inp, "wb").write(b"%PDF-1.4 reenviado")
    assert c.post(f"/reprocess/{tid}").status_code == 200
    assert "purged" not in mod.tasks[tid]


def test_process_all_skips_tasks_whose_input_is_gone(monkeypatch):
    mod = load_service()
    from fastapi.testclient import TestClient
    c = TestClient(mod.app)
    ok, inp_ok, *_ = make_task(mod, "ok.pdf")
    gone, inp_gone, *_ = make_task(mod, "gone.pdf")
    for t in (ok, gone):
        mod.tasks[t]["status"] = "Aguardando"
    os.remove(inp_gone)
    spawned = []

    class FakeProc:
        def __init__(self, **kw):
            spawned.append(kw["args"][0])

        def start(self):
            pass

        def is_alive(self):
            return False

    monkeypatch.setattr(mod.multiprocessing, "Process", FakeProc)
    r = c.post("/process-all")
    assert r.json() == {"status": "started", "count": 1}
    assert spawned == [ok]


# --- RETENCAO ----------------------------------------------------------------------------------
def write_tasks_file(path, entries):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(entries), encoding="utf-8")


def test_retention_sweep_on_startup_deletes_only_expired_tasks(monkeypatch, tmp_path):
    mod = load_service()
    old, old_in, old_out, old_final = make_task(mod, "velha.pdf", created_at=(datetime.now() - timedelta(days=3)).isoformat())
    new, new_in, new_out, new_final = make_task(mod, "nova.pdf", created_at=(datetime.now() - timedelta(hours=2)).isoformat())
    undated, und_in, und_out, und_final = make_task(mod, "sem_data.pdf")
    del mod.tasks[undated]["created_at"]
    mod.save_tasks()
    monkeypatch.setenv("RETENTION_DAYS", "1")
    mod = load_service()   # reinicio do servico: varredura no startup
    assert mod.RETENTION_DAYS == 1
    assert old not in mod.tasks and new in mod.tasks and undated in mod.tasks
    assert not os.path.exists(old_in) and not os.path.exists(old_out) and not os.path.exists(old_final)
    assert os.path.exists(new_in) and os.path.isdir(new_out) and os.path.exists(new_final)
    assert os.path.exists(und_in)
    assert old not in json.load(open(mod.TASKS_FILE, encoding="utf-8"))


def test_retention_disabled_by_default_and_for_invalid_values(monkeypatch):
    mod = load_service()
    tid, inp, *_ = make_task(mod, created_at=(datetime.now() - timedelta(days=400)).isoformat())
    assert mod.RETENTION_DAYS == 0 and mod.sweep_retention() == []
    monkeypatch.setenv("RETENTION_DAYS", "abc")
    mod = load_service()
    assert mod.RETENTION_DAYS == 0 and tid in mod.tasks and os.path.exists(inp)


def test_retention_keeps_task_when_artifacts_cannot_be_removed(monkeypatch):
    mod = load_service()
    tid, inp, out, final = make_task(mod, created_at=(datetime.now() - timedelta(days=5)).isoformat())
    monkeypatch.setattr(mod, "RETENTION_DAYS", 1.0)
    monkeypatch.setattr(mod.shutil, "rmtree", lambda p: (_ for _ in ()).throw(PermissionError("travado")))
    assert mod.sweep_retention() == [] and tid in mod.tasks


def test_retention_never_removes_running_task(monkeypatch):
    mod = load_service()
    tid, *_ = make_task(mod, created_at=(datetime.now() - timedelta(days=5)).isoformat())
    monkeypatch.setattr(mod, "RETENTION_DAYS", 1.0)
    monkeypatch.setattr(mod, "is_running", lambda t: True)
    assert mod.sweep_retention() == [] and tid in mod.tasks


def test_retention_fractional_days(monkeypatch):
    mod = load_service()
    tid, *_ = make_task(mod, created_at=(datetime.now() - timedelta(hours=3)).isoformat())
    monkeypatch.setattr(mod, "RETENTION_DAYS", 0.05)   # 1,2 h
    assert mod.sweep_retention() == [tid]


# --- bug: workers (spawn) reimportam o modulo e nao podem reconciliar/varrer -------------------
def test_worker_process_import_does_not_reconcile_or_sweep(monkeypatch, tmp_path):
    """Regressao: no Windows cada worker reimporta app_service; antes, isso marcava as tarefas em andamento
    como 'Interrompido' (e, com RETENTION_DAYS, apagaria tarefas) a cada novo processo."""
    tid = str(uuid.uuid4())
    old = (datetime.now() - timedelta(days=9)).isoformat()
    tasks_file = tmp_path / "state" / "tasks.json"
    write_tasks_file(tasks_file, {tid: {"status": "OCR", "completed": False, "error": False,
                                        "input_path": "x.pdf", "created_at": old}})
    monkeypatch.setenv("RETENTION_DAYS", "1")
    monkeypatch.setattr(multiprocessing.current_process(), "name", "SpawnProcess-1")
    mod = load_service()
    assert mod.tasks[tid]["status"] == "OCR" and mod.tasks[tid]["error"] is False
    assert json.loads(tasks_file.read_text(encoding="utf-8"))[tid]["status"] == "OCR"


def test_main_process_import_still_reconciles_interrupted_tasks(tmp_path):
    tid = str(uuid.uuid4())
    write_tasks_file(tmp_path / "state" / "tasks.json",
                     {tid: {"status": "OCR", "completed": False, "error": False, "input_path": "x.pdf"}})
    mod = load_service()
    assert mod.tasks[tid]["status"] == "Interrompido" and mod.tasks[tid]["error"] is True

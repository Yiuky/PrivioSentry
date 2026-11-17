"""Regressões da varredura de bugs: fila, tarefas, CSRF com token, reprocessar com rascunho e decisor.
Sem rede, sem Tesseract (I-08)."""
import importlib
import json
import os

import pytest

from main import SentryApp
from sentry_testkit import make_text_pdf, word

PDF = b"%PDF-1.4\n%fake\n"


@pytest.fixture()
def svc(monkeypatch):
    import app_service
    importlib.reload(app_service)
    monkeypatch.setattr(app_service, "start_worker", lambda tid, **kw: None)
    monkeypatch.setattr(app_service, "_ensure_dispatcher", lambda: None)
    from fastapi.testclient import TestClient
    return TestClient(app_service.app), app_service


def _upload(c, name="doc.pdf"):
    return c.post("/upload", files={"file": (name, PDF)}).json()["task_id"]


class _Dead:
    def __init__(self, code):
        self.exitcode = code

    def is_alive(self):
        return False


def test_worker_that_dies_silently_becomes_a_visible_error(svc):
    c, mod = svc
    tid = _upload(c)
    mod.procs[tid] = _Dead(1)
    assert mod.reap_dead_workers() == 1
    t = mod.tasks[tid]
    assert t["error"] and "parou inesperadamente" in t["status"] and tid not in mod.procs


@pytest.mark.parametrize("state", [{"completed": True}, {"pendente": True}, {"error": True}])
def test_reaper_leaves_finished_tasks_alone(svc, state):
    c, mod = svc
    tid = _upload(c)
    mod.tasks[tid].update(state, status="x")
    mod.procs[tid] = _Dead(0)
    assert mod.reap_dead_workers() == 0 and mod.tasks[tid]["status"] == "x"


def test_queued_task_cannot_be_reprocessed_or_finalized_without_losing_state(svc):
    c, mod = svc
    tid = _upload(c)
    mod.tasks[tid].update(status="Na fila (1º)", queued=True, alerts=["a"])
    mod.task_queue.append((tid, None, False))
    try:
        assert c.post(f"/reprocess/{tid}").status_code == 409
        assert c.post(f"/finalize-native/{tid}").status_code == 409
        assert mod.tasks[tid]["status"] == "Na fila (1º)" and mod.tasks[tid]["alerts"] == ["a"]
    finally:
        mod.task_queue.clear()



def test_queue_positions_move_up_when_a_task_starts(svc, monkeypatch):
    c, mod = svc
    ids = [_upload(c, f"d{i}.pdf") for i in range(3)]
    for pos, tid in enumerate(ids, 1):
        mod.tasks[tid].update(status=f"Na fila ({pos}º)", queued=True)
        mod.task_queue.append((tid, None, False))
    running = []
    monkeypatch.setattr(mod, "MAX_PARALLEL_TASKS", 1)
    monkeypatch.setattr(mod, "running_count", lambda: len(running))
    monkeypatch.setattr(mod, "_spawn", lambda tid, m, n: running.append(tid))
    try:
        assert mod.dispatch_queue() == 1 and running == ids[:1]
        assert [mod.tasks[t]["status"] for t in ids[1:]] == ["Na fila (1º)", "Na fila (2º)"]
    finally:
        mod.task_queue.clear()


def test_queue_positions_stay_when_nothing_starts(svc, monkeypatch):
    c, mod = svc
    tid = _upload(c)
    mod.tasks[tid].update(status="Na fila (1º)", queued=True)
    mod.task_queue.append((tid, None, False))
    monkeypatch.setattr(mod, "running_count", lambda: mod.MAX_PARALLEL_TASKS)       # sem vaga
    try:
        assert mod.dispatch_queue() == 0 and mod.tasks[tid]["status"] == "Na fila (1º)"   # contra-teste
    finally:
        mod.task_queue.clear()


def test_server_paths_never_reach_api_clients(svc):
    c, mod = svc
    tid = _upload(c)
    mod.tasks[tid]["doc_out_dir"] = os.path.join(mod.OUTPUT_DIR, "x")
    assert "doc_out_dir" not in c.get("/tasks").json()[tid] and "input_path" not in c.get(f"/tasks/{tid}").json()


def test_long_file_names_keep_the_display_name_but_short_paths(svc):
    c, mod = svc
    name = "contrato " + "muito longo " * 12 + ".pdf"
    tid = _upload(c, name)
    t = mod.tasks[tid]
    assert len(os.path.basename(t["input_path"])) <= 36 + 1 + 40 + 4 and t["file"].startswith("contrato muito")


# --- CSRF com API_TOKEN ---------------------------------------------------------------------------
@pytest.mark.parametrize("site, expected", [("same-site", 403), ("cross-site", 403), ("same-origin", None),
                                            (None, None)])
def test_token_mode_refuses_writes_from_another_origin(site, expected):
    from utils.net_guard import check_request
    headers = {"host": "localhost:8001"} | ({"sec-fetch-site": site} if site else {})
    result = check_request("POST", headers, token_enabled=True)
    assert (result[0] if result else None) == expected
    assert check_request("GET", headers, token_enabled=True) is None    # leitura segue com o token


# --- reprocessar com rascunho salvo ---------------------------------------------------------------
def test_reprocess_adds_new_suggestions_to_the_saved_draft(tmp_path):
    a = SentryApp(make_text_pdf(tmp_path / "d.pdf"), output_dir=str(tmp_path / "o"), final_dir=str(tmp_path / "f"))
    path = os.path.join(a.session.output_dir, "manual_redactions.json")
    old = {"page": 1, "coords": [10, 10, 110, 40], "label": "CPF", "image_width": 1000, "image_height": 1400}
    with open(path, "w", encoding="utf-8") as f:
        json.dump([old], f)
    same = dict(old, coords=[12, 11, 108, 39])
    new = {"page": 1, "coords": [10, 500, 400, 530], "label": "Endereço residencial", "image_width": 1000,
           "image_height": 1400}
    a._merge_into_saved_draft([same, new])
    a.session.close()
    saved = json.load(open(path, encoding="utf-8"))
    assert saved == [old, new] and a.needs_review                         # o rascunho antigo continua, o novo entra


def test_reprocess_without_new_suggestions_changes_nothing(tmp_path):
    a = SentryApp(make_text_pdf(tmp_path / "d.pdf"), output_dir=str(tmp_path / "o"), final_dir=str(tmp_path / "f"))
    path = os.path.join(a.session.output_dir, "manual_redactions.json")
    old = {"page": 1, "coords": [10, 10, 110, 40], "image_width": 1000}
    json.dump([old], open(path, "w", encoding="utf-8"))
    a._merge_into_saved_draft([dict(old)])
    a._merge_into_saved_draft([dict(old, page=1)])
    json.dump([dict(old, page="1")], open(path, "w", encoding="utf-8"))  # página como texto no rascunho
    a._merge_into_saved_draft([dict(old)])
    a.session.close()
    assert json.load(open(path, encoding="utf-8")) == [dict(old, page="1")] and not a.needs_review  # contra-teste


# --- decisor e leitura da página ------------------------------------------------------------------
def test_decider_returning_fewer_verdicts_asks_for_review(tmp_path, monkeypatch):
    from main import decisions
    a = SentryApp(make_text_pdf(tmp_path / "d.pdf"), output_dir=str(tmp_path / "o"), final_dir=str(tmp_path / "f"))
    a.address_redactor.results = {1: [{"text": "Rua A, 1", "type": "pessoal"}, {"text": "Rua B, 2", "type": "pessoal"}]}

    class Service:
        mode, thresholds = "assist", None

        def decide_many(self, texts):
            return []
    monkeypatch.setattr(decisions, "get_engine", lambda: Service())
    a.apply_address_decisions()
    a.session.close()
    assert a.needs_review


def test_name_detector_reads_the_ocr_when_the_text_layer_is_only_a_stamp(tmp_path, monkeypatch):
    from utils import detect as pii_detect
    seen = []
    monkeypatch.setattr(pii_detect.ner, "get_engine", lambda: object())
    monkeypatch.setattr(pii_detect.ner, "find_names", lambda gmap, engine: seen.append([w["text"] for w in gmap]) or {})
    a = SentryApp(make_text_pdf(tmp_path / "d.pdf"), output_dir=str(tmp_path / "o"), final_dir=str(tmp_path / "f"))
    body = [word(i, t, 50 + 150 * i) for i, t in enumerate(["Contratante:", "Fulano", "Ficticio", "de", "Tal"])]
    stamp = [word(i, t, 10 + 120 * i, y=5) for i, t in enumerate(["Assinado", "eletronicamente"])]
    a.grounding_maps, a.grounding_maps_native = [body], [stamp]
    a.grounding_maps_sparse, a.grounding_maps_extra = [[]], [[]]
    a._run_names({"nome_pessoa": pii_detect.TARJAR}, {"nome_pessoa": set()})
    a.session.close()
    assert seen and "Fulano" in seen[0]


def test_cli_collects_pdfs_whatever_the_extension_case(tmp_path):
    from main import collect_pdfs
    for name in ("a.pdf", "B.PDF", "c.Pdf", "nota.txt"):
        (tmp_path / name).write_bytes(PDF)
    assert [os.path.basename(p) for p in collect_pdfs(str(tmp_path))] == ["B.PDF", "a.pdf", "c.Pdf"]

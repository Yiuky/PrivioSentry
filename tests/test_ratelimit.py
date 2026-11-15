"""Limite de uso do provedor de IA (HTTP 429): por minuto x cota esgotada, ritmo e documento pendente.

Tudo simulado (I-08). O corpo "por minuto" tem o formato medido no plano gratuito do Gemini em 2026-11-15."""
import importlib
import os
import uuid

import pytest

from utils import ratelimit

PER_MINUTE = ('[{"error": {"code": 429, "status": "RESOURCE_EXHAUSTED", "details": [{"violations": [{"quotaId": '
              '"GenerateRequestsPerMinutePerProjectPerModel-FreeTier", "quotaValue": "15"}]}, '
              '{"retryDelay": "36s"}]}}]')
PER_DAY = PER_MINUTE.replace("PerMinute", "PerDay")


class Resp:
    status_code = 429

    def __init__(self, text="", headers=None):
        self.text, self.headers = text, headers or {}


# --- classificação -------------------------------------------------------------------------------
@pytest.mark.parametrize("resp,expected", [
    (Resp(PER_MINUTE), (36.0, False)),                                   # por minuto: espera e tenta de novo
    (Resp(PER_DAY), (36.0, True)),                                       # por dia: esperar 36 s não adianta
    (Resp("", {"retry-after": "7"}), (7.0, False)),
    (Resp("", {"retry-after": "500"}), (60.0, True)),                    # espera maior que o teto
    (Resp('{"error": {"code": "insufficient_quota"}}', {"retry-after": "2"}), (2.0, True)),  # sem crédito
    (Resp("limite"), (5.0, False)),                                      # sem indicação: espera 5 s e tenta
])
def test_parse_tells_short_from_long(resp, expected):
    assert ratelimit.parse(resp) == expected


LOCAL = "http://localhost:1234/v1"
CLOUD = "https://api.nuvem.example/v1"


@pytest.fixture()
def cloud(monkeypatch):
    from utils import egress
    monkeypatch.setattr(egress, "is_external", lambda url: "nuvem" in str(url))  # sem DNS de verdade (I-08)


def test_automatic_rate_is_on_for_external_and_off_locally(cloud, monkeypatch):
    assert ratelimit.per_minute(CLOUD) == 12 and ratelimit.per_minute(LOCAL) == 0
    monkeypatch.setenv("AI_REQUESTS_PER_MINUTE", "0")                     # desligado de propósito
    assert ratelimit.per_minute(CLOUD) == 0
    monkeypatch.setenv("AI_REQUESTS_PER_MINUTE", "30")
    assert ratelimit.per_minute(LOCAL) == 30                              # configurado vale para todos
    monkeypatch.setenv("AI_REQUESTS_PER_MINUTE", "abc")
    assert ratelimit.per_minute(LOCAL) == 12                              # inválido: lado seguro


def test_pace_spaces_requests_to_the_same_provider(cloud):
    now, slept = [100.0], []
    for _ in range(3):
        ratelimit.pace(CLOUD, slept.append, lambda: now[0])               # 3 pedidos no mesmo instante
    assert slept == [pytest.approx(5.0), pytest.approx(10.0)]             # 12/min = um a cada 5 s
    now[0] = 200.0
    assert ratelimit.pace(CLOUD, slept.append, lambda: now[0]) == 0       # já passou a vez: não espera
    assert ratelimit.pace(LOCAL, slept.append, lambda: now[0]) == 0       # contra-teste: nesta rede, sem limite


def test_pace_is_shared_between_processes_and_separate_per_provider(cloud, monkeypatch):
    monkeypatch.setenv("AI_REQUESTS_PER_MINUTE", "6")                     # um a cada 10 s
    slept = []
    ratelimit.pace(CLOUD, slept.append, lambda: 100.0)
    ratelimit.lock = __import__("threading").Lock()
    ratelimit._slots.clear()                             # "outro processo": só o arquivo em comum
    ratelimit.pace(CLOUD, slept.append, lambda: 100.0)
    ratelimit.pace("https://outra.nuvem.example/v1", slept.append, lambda: 100.0)
    assert slept == [pytest.approx(10.0)]                                 # outro provedor tem a própria vez


def test_limiter_still_limits_when_the_state_file_cannot_be_written(cloud, monkeypatch, tmp_path):
    blocker = tmp_path / "arquivo"
    blocker.write_text("x")
    monkeypatch.setenv("PRIVIO_RUNTIME_DIR", str(blocker / "sub"))        # pasta impossível: não grava
    slept = []
    for _ in range(3):
        ratelimit.pace(CLOUD, slept.append, lambda: 100.0)
    assert slept == [pytest.approx(5.0), pytest.approx(10.0)]


def test_worker_lock_shared_by_ai_and_limiter_does_not_deadlock(cloud, monkeypatch):
    """No worker, ratelimit.lock e ai_client.ollama_lock são a MESMA trava (AI_LOCK), sem reentrada."""
    import threading
    from utils import ai_client, second_look
    shared = threading.Lock()
    monkeypatch.setattr(ai_client, "ollama_lock", shared)
    monkeypatch.setattr(ratelimit, "lock", shared)
    monkeypatch.setattr(ai_client.time, "sleep", lambda s: None)
    monkeypatch.setattr(second_look.time, "sleep", lambda s: None)
    monkeypatch.setenv("AI_PROVIDER", "openai")
    monkeypatch.setenv("AI_BASE_URL", CLOUD)
    monkeypatch.setenv("AI_ALLOW_EXTERNAL", "1")
    monkeypatch.setattr("utils.ratelimit.time.sleep", lambda s: None)
    done = []

    class OK:
        status_code = 200

        def json(self):
            return {"choices": [{"message": {"content": '{"achados": []}'}}]}

    def both():
        done.append(ai_client.AIClient()._call(False, lambda b, n: ({"ok": 1}, None, {}), "f")[0])
        done.append(second_look.run_agent("texto", ["cpf"], post=lambda *a, **k: OK())[0])
    t = threading.Thread(target=both, daemon=True)
    t.start()
    t.join(10)
    assert not t.is_alive() and done == [{"ok": 1}, []] and not shared.locked()


def test_admin_restore_default_returns_to_automatic(svc, cloud):
    c, _, _, _ = svc
    assert c.post("/admin/settings", json={"values": {"AI_REQUESTS_PER_MINUTE": "30"}}).status_code == 200
    assert ratelimit.per_minute(CLOUD) == 30
    assert c.post("/admin/settings", json={"values": {"AI_REQUESTS_PER_MINUTE": None}}).status_code == 200
    assert ratelimit.per_minute(CLOUD) == 12


def test_main_client_and_agent_wait_their_turn(cloud, monkeypatch):
    from utils import ai_client, second_look
    paced = []
    monkeypatch.setattr(ratelimit, "pace", lambda url, *a, **k: paced.append(url))
    monkeypatch.setenv("AI_PROVIDER", "openai")
    monkeypatch.setenv("AI_BASE_URL", LOCAL)
    ai_client.AIClient()._call(False, lambda b, n: ({"ok": 1}, None, {}), "f")

    class OK:
        status_code = 200

        def json(self):
            return {"choices": [{"message": {"content": '{"achados": []}'}}]}
    second_look.run_agent("texto", ["cpf"], post=lambda *a, **k: OK())
    assert paced == [LOCAL, second_look._endpoint()]


# --- cliente de IA -------------------------------------------------------------------------------
@pytest.fixture()
def client(monkeypatch):
    from utils import ai_client
    monkeypatch.setenv("AI_PROVIDER", "openai")
    monkeypatch.setenv("AI_BASE_URL", "http://localhost:1234/v1")
    waits = []
    monkeypatch.setattr(ai_client.time, "sleep", waits.append)
    c = ai_client.AIClient()
    c.waits = waits
    return c


def test_short_limit_waits_and_does_not_trip_the_breaker(client):
    answers = [ratelimit.RateLimited(36.0, False), ratelimit.RateLimited(36.0, False), ({"ok": True}, None, {})]

    def attempt(backend, n):
        a = answers.pop(0)
        if isinstance(a, Exception):
            raise a
        return a
    result = client._call(False, attempt, "falha")
    assert result[0] == {"ok": True} and client.waits == [36.0, 36.0]
    assert not ratelimit.hit()
    assert all(not s["falhas_seguidas"] and not s["desligado"] for s in client.breaker.snapshot().values())


def test_long_limit_gives_up_at_once_and_is_marked(client):
    calls = []

    def attempt(backend, n):
        calls.append(n)
        raise ratelimit.RateLimited(36.0, True)
    response = client._call(False, attempt, "falha")[0]
    assert response["rate_limited"] and "429" in response["error"]       # erro = página para revisão (I-02)
    assert calls == [0] and client.waits == [] and ratelimit.hit()
    assert all(not s["desligado"] for s in client.breaker.snapshot().values())


def test_short_limit_that_persists_counts_as_long(client):
    def attempt(backend, n):
        raise ratelimit.RateLimited(1.0, False)
    assert client._call(False, attempt, "falha")[0]["rate_limited"] and ratelimit.hit()


def test_pending_mode_stops_spending_requests(client, monkeypatch):
    ratelimit.note()
    calls = []
    assert "error" not in client._call(False, lambda b, n: calls.append(n) or ({"ok": 1}, None, {}), "f")[0]
    monkeypatch.setenv("AI_LIMIT_ACTION", "pendente")
    assert "error" not in client._call(False, lambda b, n: calls.append(n) or ({"ok": 1}, None, {}), "f")[0]
    ratelimit.allow_pending()                                             # só o processo de um documento do serviço
    response = client._call(False, lambda b, n: calls.append(n) or ({"ok": 1}, None, {}), "f")[0]
    assert response["rate_limited"] and calls == [0, 0]                  # a terceira chamada não saiu


def test_agent_does_not_wait_on_daily_quota(monkeypatch):
    from utils import second_look
    waits = []
    monkeypatch.setattr(second_look.time, "sleep", waits.append)
    monkeypatch.setenv("AI_PROVIDER", "openai")
    monkeypatch.setenv("AI_BASE_URL", "http://localhost:1234/v1")
    posts = []
    items, info = second_look.run_agent("texto", ["cpf"], post=lambda *a, **k: posts.append(1) or Resp(PER_DAY))
    assert items is None and "429" in info["erro"] and waits == [] and len(posts) == 1 and ratelimit.hit()


# --- pipeline: pendente nunca gera PDF ------------------------------------------------------------
def _app(tmp_path, monkeypatch):
    from main import SentryApp
    from test_doc_templates import make_pdf
    monkeypatch.setenv("BASE_DPI", "72")
    monkeypatch.setenv("VERIFY_OCR", "0")
    monkeypatch.setenv("YOLO_MODEL_PATH", str(tmp_path / "sem_modelo.pt"))
    a = SentryApp(make_pdf(tmp_path / "doc.pdf"), output_dir=str(tmp_path / "out"), final_dir=str(tmp_path / "final"))

    def fake_ocr(img_path):
        return "", a._native_text_maps(len(a.image_paths))[a._extract_page_num(img_path) - 1], [], False
    monkeypatch.setattr(a, "_ocr_page", fake_ocr)

    def limited(path, prompt, only=None):
        ratelimit.note()
        return {"error": "HTTP 429: limite de uso do provedor de IA", "rate_limited": True}, None, {}
    a.address_redactor.ai.analyze_image = limited
    return a


def test_pipeline_pending_stops_without_pdf(tmp_path, monkeypatch):
    from main import LimitPending
    monkeypatch.setenv("AI_LIMIT_ACTION", "pendente")
    ratelimit.allow_pending()
    a = _app(tmp_path, monkeypatch)
    with pytest.raises(LimitPending):
        a.run()
    a.session.close()
    assert not os.path.exists(tmp_path / "final") or not os.listdir(tmp_path / "final")


def test_command_line_never_pends_and_the_next_document_starts_clean(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_LIMIT_ACTION", "pendente")                     # sem allow_pending: como na CLI
    a = _app(tmp_path, monkeypatch)
    a.run()
    a.session.close()
    assert a.final_state()["needs_review"] and ratelimit.hit()
    (tmp_path / "b").mkdir()
    b = _app(tmp_path / "b", monkeypatch)
    b.address_redactor.ai.analyze_image = lambda p, prompt, only=None: ({"addresses": []}, b"", {})
    b.run()
    b.session.close()
    assert not ratelimit.hit()                                            # o limite do 1º não marca o 2º


def test_pipeline_default_sends_the_page_to_review(tmp_path, monkeypatch):
    a = _app(tmp_path, monkeypatch)                                       # AI_LIMIT_ACTION padrão: revisao
    a.run()
    state = a.final_state()
    a.session.close()
    assert state["status"] == "Requer revisão" and state["needs_review"]


# --- serviço --------------------------------------------------------------------------------------
@pytest.fixture()
def svc(monkeypatch):
    import app_service
    importlib.reload(app_service)
    started = []
    monkeypatch.setattr(app_service, "start_worker", lambda tid, **kw: started.append(tid))
    monkeypatch.setattr(app_service, "_ensure_dispatcher", lambda: None)
    from fastapi.testclient import TestClient
    c = TestClient(app_service.app)
    tid = c.post("/upload", files={"file": ("doc.pdf", b"%PDF-1.4\n%fake\n")}).json()["task_id"]
    started.clear()
    return c, app_service, tid, started


def _pend(c, mod, tid):
    r = c.post(f"/internal/update/{tid}", json={"pendente": True}, headers={"X-Internal-Secret": mod.INTERNAL_SECRET})
    assert r.status_code == 200
    return mod.tasks[tid]


def test_pending_task_has_no_pdf_and_is_never_approved(svc):
    c, mod, tid, _ = svc
    t = _pend(c, mod, tid)
    assert t["pendente"] and not t["completed"] and not t["error"] and t["pendente_tentativas"] == 1
    assert t["pendente_ate"] > mod.time.time() + 59 * 60                  # padrão: 60 min
    assert c.get(f"/download/{tid}?final=true").status_code == 409
    assert c.get(f"/download/{tid}").status_code == 202
    assert not mod.approved(tid, t)
    mod.reconcile_interrupted_tasks()                                     # reinício do serviço não vira erro
    assert t["status"].startswith("Pendente") and not t["error"]


def test_pending_resumes_only_after_the_wait(svc):
    c, mod, tid, started = svc
    t = _pend(c, mod, tid)
    assert mod.resume_pending() == 0 and started == []
    assert mod.resume_pending(now=t["pendente_ate"] + 1) == 1 and started == [tid]
    assert "pendente" not in t and t["status"] == "Retomando..." and t["pendente_tentativas"] == 1
    assert mod.resume_pending(now=t.get("pendente_ate", 0) + 10 ** 9) == 0  # não retoma duas vezes


def test_person_can_resume_now_and_reprocess_restarts_the_count(svc):
    c, mod, tid, started = svc
    _pend(c, mod, tid)
    assert c.post("/process-all").json()["count"] == 1 and "pendente" not in mod.tasks[tid]
    _pend(c, mod, tid)
    assert mod.tasks[tid]["pendente_tentativas"] == 2
    c.post(f"/reprocess/{tid}")
    assert "pendente_tentativas" not in mod.tasks[tid] and "pendente" not in mod.tasks[tid]


def test_ceiling_runs_the_last_resume_without_pending(monkeypatch):
    import app_service
    importlib.reload(app_service)
    mod = app_service
    created = []

    class FakeProc:
        def __init__(self, target, args, kwargs):
            created.append(kwargs)

        def start(self):
            pass

        def is_alive(self):
            return False
    monkeypatch.setattr(mod.multiprocessing, "Process", FakeProc)
    monkeypatch.setenv("AI_LIMIT_MAX_RETRIES", "2")
    inp = os.path.join(mod.INPUT_DIR, "x.pdf")
    open(inp, "wb").write(b"%PDF-1.4\n")
    tid = str(uuid.uuid4())
    mod.tasks[tid] = {"input_path": inp, "status": "x", "pendente_tentativas": 1}
    mod.start_worker(tid)
    mod.tasks[tid]["pendente_tentativas"] = 2
    mod.start_worker(tid)
    assert created == [{"no_pending": False}, {"no_pending": True}]


def test_worker_reports_pending_and_respects_the_ceiling(svc, monkeypatch):
    _, mod, _, _ = svc
    from main import LimitPending
    posts = []

    class Http:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, json=None, headers=None):
            posts.append(json)

    class App:
        def __init__(self, *a, **k):
            pass

        def run(self, **k):
            raise LimitPending("limite")
    monkeypatch.setattr(mod.httpx, "Client", Http)
    monkeypatch.setattr(mod, "SentryApp", App)
    mod.redaction_worker("tid", "x.pdf")
    assert posts == [{"pendente": True}]                                  # sem erro, sem "Concluído", sem PDF
    monkeypatch.setenv("AI_LIMIT_ACTION", "pendente")
    assert ratelimit.pending_mode()                                       # o worker liga; o serviço e a CLI não
    mod.redaction_worker("tid", "x.pdf", no_pending=True)
    assert not ratelimit.pending_mode()                                   # teto: esta rodada vai para revisão


def test_pending_cannot_be_finalized_and_a_started_worker_ends_the_wait(svc, monkeypatch):
    c, mod, tid, started = svc
    t = _pend(c, mod, tid)
    assert c.post(f"/finalize/{tid}", json=[]).status_code == 409
    monkeypatch.setattr(mod.multiprocessing, "Process", type("P", (), {
        "__init__": lambda self, **k: None, "start": lambda self: None, "is_alive": lambda self: False}))
    mod._spawn(tid, None, False)
    assert "pendente" not in t and "pendente_ate" not in t
    t.update(pendente=True, pendente_ate=0, completed=True)               # estado impossível, por garantia
    assert mod.resume_pending(now=10 ** 10) == 0 and started == []


def test_admin_offers_the_limit_options(svc):
    c, mod, _, _ = svc
    keys = {f["key"]: f for f in c.get("/admin/settings").json()["campos"]}
    assert keys["AI_LIMIT_ACTION"]["choices"] == ["revisao", "pendente"]
    assert {"AI_LIMIT_RETRY_MINUTES", "AI_REQUESTS_PER_MINUTE"} <= set(keys)


# --- MCP ------------------------------------------------------------------------------------------
def test_mcp_reports_pending_and_wait_returns(svc):
    import sentry_mcp
    c, mod, tid, _ = svc
    _pend(c, mod, tid)
    agent = sentry_mcp.Sentry(base_url="http://127.0.0.1:8001", token="", http=c)
    agent.sleep = lambda s: pytest.fail("pendente pode levar horas: sentry_wait não pode ficar esperando")
    info = agent.sentry_wait(tid, timeout_s=60)
    assert info["situacao"] == "pendente" and info["pendente"] and not info["concluido"] and not info["erro"]

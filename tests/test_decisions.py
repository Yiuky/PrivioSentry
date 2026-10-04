# SPDX-License-Identifier: AGPL-3.0-or-later
"""Decisor local + automelhoramento (utils/decisions), com motor falso: sem Laya, sem rede, sem GPU."""
import json
import os

import pytest

from main import SentryApp
from sentry_testkit import CPF_A_FMT, make_text_pdf, word
from utils import decisions
from utils.decisions import feedback, learning, synthetic
from utils.decisions.engine import DecisionService, Profile, get_engine
from utils.decisions.policy import Thresholds, combine_address_decision
from utils.decisions.questions import FEATURE_IDS, normalize_state

# Sinais de moradia e de não moradia ("Residencial Aurora" é bairro e aparece também em endereços
# comerciais, por isso "residencial" fica de fora).
RESID_WORDS = ("casa", "apto", "apartamento", "sobrado", "fundos", "kitnet", "residência", "domicílio", "reside",
               "morador", "residente", "domiciliado", "habitacional")
OTHER_WORDS = ("ltda", "s/a", " me", "sala", "loja", "galpão", "escritório", "clínica", "secretaria", "prefeitura",
               "tribunal", "câmara", "autarquia", "defensoria", "fazenda", "sítio", "chácara modelo", "gleba", "lote 00 do",
               "obra", "empreendimento", "rodovia", "hospital", "escola", "cartório", "posto", "delegacia", "indústria",
               "supermercado", "shopping", "empresa", "palácio", "assentamento")


class KeywordEngine:
    """Motor falso: 'responde' as perguntas olhando palavras-chave (determinístico e rápido)."""

    name = "fake"

    def __init__(self, fail=False, noise=False):
        self.fail, self.noise, self.calls = fail, noise, 0

    def features(self, texts):
        self.calls += 1
        if self.fail:
            raise RuntimeError("modelo indisponível")
        out = []
        for t in texts:
            low = t.lower()
            pos = 3.0 if any(w in low for w in RESID_WORDS) else 0.0
            neg = 3.0 if any(w in low for w in OTHER_WORDS) else 0.0
            row = [pos - neg, neg] + [0.0] * (len(FEATURE_IDS) - 2)
            out.append([0.0] * len(FEATURE_IDS) if self.noise else row)
        return out


# --- normalização e política --------------------------------------------------------------------
def test_normalize_state_masks_digits_and_cpf():
    text = normalize_state(f"Rua X, 123, apto 45, CPF {CPF_A_FMT}")
    assert not any(ch.isdigit() and ch != "0" for ch in text)
    assert CPF_A_FMT not in text


@pytest.mark.parametrize("llm, p, mode, expected", [
    (True, 0.0, "assist", (True, None)),        # nunca reduz proteção
    (False, 0.95, "assist", (True, "residencial")),
    (False, 0.5, "assist", (False, "incerto")),
    (False, 0.05, "assist", (False, None)),
    (False, None, "assist", (False, "indisponível")),
    (False, 0.99, "shadow", (False, None)),     # sombra: só observa
])
def test_combine_address_decision(llm, p, mode, expected):
    is_personal, reason = combine_address_decision(llm, p, mode, Thresholds(0.9, 0.1))
    assert is_personal == expected[0]
    assert (reason is None) if expected[1] is None else (expected[1] in reason)


def test_assist_without_approved_profile_falls_back_to_shadow():
    assert DecisionService(KeywordEngine(), Profile(approved=False), "assist").mode == "shadow"
    assert DecisionService(KeywordEngine(), Profile(approved=True), "assist").mode == "assist"


def test_engine_failure_becomes_none_decision():
    out = DecisionService(KeywordEngine(fail=True)).decide_many(["Rua A, 1"])
    assert out[0].p_personal is None


def test_get_engine_is_off_by_default_and_rejects_unknown(monkeypatch):
    assert get_engine() is None
    decisions.reset_engine()
    monkeypatch.setenv("DECISION_ENGINE", "outro")
    assert get_engine() is None


# --- treino, portão e versões --------------------------------------------------------------------
def test_synthetic_data_is_deterministic_balanced_and_fictional():
    rows = synthetic.generate(40)
    assert rows == synthetic.generate(40) and sum(l for _, l in rows) == 20
    assert synthetic.holdout(20) != synthetic.generate(20)


def test_train_approves_good_candidate_and_activates_it(tmp_path):
    store = learning.LearningStore(tmp_path / "learn")
    report = learning.train(store, KeywordEngine().features, model="fake", n_synthetic=80)
    assert report["approved"] and report["active"] == "v1"
    assert report["metrics"]["auc"] >= learning.GATE["min_auc"]
    profile = store.active_profile(model="fake")
    assert profile.approved and profile.thresholds.personal > profile.thresholds.not_personal
    zeros = [0.0] * (len(FEATURE_IDS) - 2)
    assert profile.probability([3.0, 0.0] + zeros) > 0.5 > profile.probability([-3.0, 3.0] + zeros)


def test_gate_rejects_bad_candidate_and_keeps_active_profile(tmp_path):
    store = learning.LearningStore(tmp_path / "learn")
    learning.train(store, KeywordEngine().features, model="fake", n_synthetic=80)
    store.cache_path = str(tmp_path / "other_cache.json")  # outro "modelo": força recalcular
    report = learning.train(store, KeywordEngine(noise=True).features, model="fake", n_synthetic=80)
    assert not report["approved"] and report["reasons"]
    assert store.manifest()["active"] == "v1"


def test_rollback_and_purge(tmp_path):
    store = learning.LearningStore(tmp_path / "learn")
    learning.train(store, KeywordEngine().features, model="fake", n_synthetic=80)
    learning.train(store, KeywordEngine().features, model="fake", n_synthetic=80)
    assert store.manifest()["active"] == "v2"
    assert store.rollback() == "v1" and store.rollback() is None
    store.purge()
    assert not os.path.exists(store.root)


def test_purge_never_deletes_foreign_files(tmp_path):
    root = tmp_path / "pasta_do_usuario"
    root.mkdir()
    (root / "documento_importante.txt").write_text("não apagar", encoding="utf-8")
    store = learning.LearningStore(root)
    learning.train(store, KeywordEngine().features, model="fake", n_synthetic=80)
    store.purge()
    assert (root / "documento_importante.txt").exists()
    assert sorted(os.listdir(root)) == ["documento_importante.txt"]


def test_models_never_float_on_the_hub(monkeypatch, tmp_path):
    from utils.decisions.engine import PINNED_MODEL_REVISIONS, LayaEngine

    class CompromisedLaya:  # o pin não vem do pacote laya
        PINNED_REVISIONS = {"convaiinnovations/laya-multilingual": "commit-malicioso"}

    official = PINNED_MODEL_REVISIONS["convaiinnovations/laya-multilingual"]
    assert LayaEngine()._revision(CompromisedLaya) == official
    with pytest.raises(ValueError, match="sem commit fixo"):
        LayaEngine(model_id="outro/modelo")._revision()
    assert LayaEngine(model_id=str(tmp_path))._revision() is None   # pasta local
    monkeypatch.setenv("LAYA_REVISION", "def456")
    assert LayaEngine(model_id="outro/modelo")._revision() == "def456"


def test_unpinned_model_failure_falls_back_safely(monkeypatch):
    import sys
    import types
    from utils.decisions.engine import LayaEngine
    monkeypatch.setitem(sys.modules, "laya", types.SimpleNamespace(load=lambda *a, **k: None))
    service = DecisionService(LayaEngine(model_id="outro/modelo"))
    assert service.decide_many(["Rua A"])[0].p_personal is None   # sem decisor: a política pede revisão


def test_examples_are_removed_with_their_task(tmp_path, monkeypatch):
    task_dir = tmp_path / "tarefa_a"
    task_dir.mkdir()
    feedback.write_decision_log(str(task_dir), ENTRIES)
    monkeypatch.setenv("LEARNING_ENABLED", "1")
    store = learning.LearningStore(tmp_path / "learn")
    feedback.capture_review(str(task_dir), [], store)
    store.add_examples([{"text": "outro exemplo", "label": 1, "source": "import"}])
    assert len(store.examples()) == 3
    assert store.remove_task("tarefa_a") == 2
    assert [e["text"] for e in store.examples()] == ["outro exemplo"]


def test_default_learning_dir_is_inside_the_project(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)  # abrir o programa de outra pasta não muda onde o aprendizado fica
    monkeypatch.delenv("PRIVIO_LEARNING_DIR", raising=False)
    assert learning.LearningStore().root == os.path.join(learning.PROJECT_DIR, "learning")


def test_profile_from_other_question_version_is_ignored(tmp_path):
    store = learning.LearningStore(tmp_path / "learn")
    learning.train(store, KeywordEngine().features, model="fake", n_synthetic=80)
    path = store._profile_path("v1")
    data = json.load(open(path, encoding="utf-8"))
    data["questions_version"] = -1
    json.dump(data, open(path, "w", encoding="utf-8"))
    assert store.active_profile(model="fake") is None


def test_examples_are_minimized_and_latest_label_wins(tmp_path):
    store = learning.LearningStore(tmp_path / "learn")
    store.add_examples([{"text": "Rua Y, 77, casa 2", "label": 1, "source": "review"},
                        {"text": "Rua Y, 77, casa 2", "label": 0, "source": "review"},
                        {"text": "sem rótulo", "label": None}])
    rows = store.examples()
    assert len(rows) == 1 and rows[0]["label"] == 0 and "77" not in rows[0]["text"]


def test_review_examples_change_the_trained_model(tmp_path):
    store = learning.LearningStore(tmp_path / "learn")
    base = learning.train(store, KeywordEngine().features, model="fake", n_synthetic=80)
    store.add_examples([{"text": f"Rua Nova {i}, casa {i}", "label": 0, "source": "review"} for i in range(30)])
    after = learning.train(store, KeywordEngine().features, model="fake", n_synthetic=80)
    assert after["metrics"]["trained_on"]["examples"] >= 1
    assert after["version"] != base["version"]


# --- correções do revisor --------------------------------------------------------------------------
ENTRIES = [
    {"page": 1, "text": "Rua A casa", "word_boxes": [[10, 10, 20, 10], [40, 10, 20, 10]]},
    {"page": 1, "text": "Av B sala", "word_boxes": [[10, 50, 20, 10]]},
    {"page": 2, "text": "sem caixas", "word_boxes": []},
]


def test_labels_from_review_uses_final_boxes():
    final = [{"page": 1, "coords": [0, 0, 100, 30]}]  # cobre só o 1º endereço
    rows = feedback.labels_from_review(ENTRIES, final)
    assert [(r["text"], r["label"]) for r in rows] == [("Rua A casa", 1), ("Av B sala", 0)]


def test_capture_review_requires_opt_in(tmp_path, monkeypatch):
    feedback.write_decision_log(str(tmp_path), ENTRIES)
    store = learning.LearningStore(tmp_path / "learn")
    assert feedback.capture_review(str(tmp_path), [], store) == 0          # desligado por padrão
    monkeypatch.setenv("LEARNING_ENABLED", "1")
    assert feedback.capture_review(str(tmp_path), [], store) == 2
    assert {r["label"] for r in store.examples()} == {0}


# --- integração com o pipeline ----------------------------------------------------------------------
@pytest.fixture()
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("BASE_DPI", "50")
    a = SentryApp(make_text_pdf(tmp_path / "doc.pdf"))
    a.grounding_maps = [[word(0, "Rua", 0), word(1, "Nova", 60), word(2, "casa", 140)]]
    a.indexed_texts = ["[0] Rua [1] Nova [2] casa"]
    a.address_redactor.results = {1: [{"text": "Rua Nova casa", "type": "profissional", "type_original": "Profissional"}]}
    yield a
    a.session.close()


def _install(monkeypatch, mode, approved=True):
    profile = Profile(version="v9", weights=[1.0] + [0.0] * (len(FEATURE_IDS) - 1), bias=0.0, thresholds=Thresholds(0.9, 0.1), approved=approved)
    service = DecisionService(KeywordEngine(), profile, mode)
    monkeypatch.setattr(decisions, "get_engine", lambda: service)
    return service


def test_pipeline_assist_adds_protection_and_review(app, monkeypatch):
    _install(monkeypatch, "assist")
    app.apply_address_decisions()
    addr = app.address_redactor.results[1][0]
    assert addr["type"] == "pessoal" and addr["decided_by"] == "fake"
    assert app.needs_review and "decisor local" in app.review_pages[1][0]
    log = json.load(open(os.path.join(app.session.output_dir, "decisions.json"), encoding="utf-8"))
    assert log[0]["final_type"] == "pessoal" and len(log[0]["word_boxes"]) == 2  # "Rua" é imune


def test_pipeline_shadow_changes_nothing_but_logs(app, monkeypatch):
    _install(monkeypatch, "shadow")
    app.apply_address_decisions()
    assert app.address_redactor.results[1][0]["type"] == "profissional"
    assert not app.needs_review
    assert os.path.exists(os.path.join(app.session.output_dir, "decisions.json"))


def test_pipeline_without_engine_is_a_noop(app):
    app.apply_address_decisions()
    assert not os.path.exists(os.path.join(app.session.output_dir, "decisions.json"))


def test_preload_loads_model_once_even_when_racing_with_use(monkeypatch):
    import sys
    import threading
    import time
    import types
    from utils.decisions.engine import LayaEngine

    loads = []

    def slow_load(*a, **k):
        loads.append(threading.current_thread().name)
        time.sleep(0.2)
        return types.SimpleNamespace(predict_batch=lambda states, q: [
            {"answers": {qid: {"noul": 0.9} for qid in q}} for _ in states])

    monkeypatch.setitem(sys.modules, "laya", types.SimpleNamespace(load=slow_load))
    engine = LayaEngine(model_id="convaiinnovations/laya-multilingual")
    thread = DecisionService(engine).preload()          # começa a carregar em segundo plano
    feats = engine.features(["Rua A, casa 1"])           # uso concorrente: espera a mesma carga
    thread.join()
    assert len(loads) == 1 and len(feats[0]) == len(FEATURE_IDS)


def test_preload_is_optional_for_engines_without_it():
    assert DecisionService(KeywordEngine()).preload() is None

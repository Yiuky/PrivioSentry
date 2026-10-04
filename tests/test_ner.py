# SPDX-License-Identifier: AGPL-3.0-or-later
"""Detector opcional de nomes (GLiNER): limiares de confiança, filiação, blocos e fase de política.

Usa um motor FALSO (sem baixar modelo, sem rede, sem GPU: I-08). Nomes fictícios."""
import pytest

from sentry_testkit import word
from utils.detect import catalog, ner, profiles


class FakeEngine:
    """Acha os nomes de uma tabela {nome: confiança}, como o GLiNER devolveria (posições no texto recebido)."""

    def __init__(self, scores):
        self.scores = scores
        self.calls = []

    def predict(self, text, labels, threshold):
        self.calls.append((len(text), tuple(labels), threshold))
        out = []
        for name, score in self.scores.items():
            start = text.find(name)
            while start != -1:
                if score >= threshold:
                    out.append({"start": start, "end": start + len(name), "label": "person", "score": score})
                start = text.find(name, start + 1)
        return out


def grounding(text):
    return [word(i, t, 100 * i) for i, t in enumerate(text.split())]


def ids(commands):
    return set(commands)


def test_confidence_splits_redact_review_and_ignore():
    g = grounding("Requerente Maria Exemplo e testemunha Pedro Modelo e Ana Teste")
    hits = ner.find_names(g, FakeEngine({"Maria Exemplo": 0.92, "Pedro Modelo": 0.55, "Ana Teste": 0.2}))
    slot = hits["nome_pessoa"]
    assert ids(slot["tarjar"]) == {1, 2}            # alta confiança
    assert ids(slot["alertar"]) == {5, 6}           # média: revisão
    assert slot["valores"] == {"maria exemplo", "pedro modelo"}  # "Ana Teste" abaixo do limiar de alerta


def test_name_after_filiation_words_is_filiacao():
    g = grounding("Nome: Lucas Simulado, filho de Carla Amostra")
    hits = ner.find_names(g, FakeEngine({"Lucas Simulado": 0.9, "Carla Amostra": 0.9}))
    assert hits["nome_pessoa"]["valores"] == {"lucas simulado"}
    assert hits["filiacao"]["valores"] == {"carla amostra"}


def test_long_text_is_split_in_blocks_and_positions_stay_right(monkeypatch):
    from utils.detect import config
    real = config.param
    monkeypatch.setattr(config, "param", lambda s, k: 40 if (s, k) == ("nomes", "tamanho_bloco") else real(s, k))
    g = grounding(" ".join(["texto"] * 30 + ["Rafael Ensaio"] + ["texto"] * 30))
    engine = FakeEngine({"Rafael Ensaio": 0.95})
    hits = ner.find_names(g, engine)
    assert ids(hits["nome_pessoa"]["tarjar"]) == {30, 31}
    assert len(engine.calls) > 1 and all(n <= 40 for n, _, _ in engine.calls)


def test_disabled_by_default_and_catalog_shows_optional(monkeypatch):
    monkeypatch.delenv("NER_ENGINE", raising=False)
    assert not ner.enabled() and not ner.available()
    assert catalog.get("nome_pessoa").estado == catalog.OPCIONAL
    assert "nome_pessoa" not in profiles.runnable_actions("gdpr")
    with pytest.raises(ner.NERUnavailable):
        ner.get_engine()


def test_enabled_without_package_is_not_runnable(monkeypatch):
    monkeypatch.setenv("NER_ENGINE", "gliner")
    monkeypatch.setattr(ner.importlib.util, "find_spec", lambda name: None)
    assert ner.enabled() and not ner.available()
    assert "nome_pessoa" not in profiles.runnable_actions("gdpr")


# --- fase de política ---------------------------------------------------------------------------------------
@pytest.fixture()
def app(tmp_path, monkeypatch):
    from main import SentryApp
    from sentry_testkit import make_text_pdf
    monkeypatch.setenv("BASE_DPI", "40")
    monkeypatch.setenv("NER_ENGINE", "gliner")
    monkeypatch.setattr(ner, "available", lambda: True)
    a = SentryApp(make_text_pdf(tmp_path / "doc.pdf"))
    a.run_phase_0()
    a.grounding_maps = [grounding("Requerente Maria Exemplo e testemunha Pedro Modelo")]
    a.grounding_maps_sparse = [[]]
    a.grounding_maps_native = [[]]
    yield a
    a.session.close()
    ner.reset()


def test_policy_phase_redacts_confident_names_and_reviews_the_rest(app, monkeypatch):
    monkeypatch.setattr(ner, "get_engine", lambda: FakeEngine({"Maria Exemplo": 0.9, "Pedro Modelo": 0.5}))
    app.policy_profile = "lgpd_publicacao"                        # nome_pessoa: tarjar
    app.run_policy_phase()
    assert len(app.global_redactions[1]) == 2                     # "Maria" e "Exemplo"
    assert set(app.box_labels[1].values()) == {"Nome de pessoa"}
    assert app.pii_summary["nome_pessoa"] == 2
    assert any("confiança média" in m["reason"] for m in app.review_marks)


def test_engine_failure_fails_closed(app, monkeypatch):
    def boom():
        raise ner.NERUnavailable("sem modelo")
    monkeypatch.setattr(ner, "get_engine", boom)
    app.policy_profile = "lgpd_publicacao"
    app.run_policy_phase()
    assert not app.global_redactions[1]
    assert app.needs_review and any("Detector de nomes falhou" in r for r in app.review_pages[1])


def test_profile_without_names_never_loads_the_model(app, monkeypatch):
    def boom():
        raise AssertionError("não deveria carregar o modelo")
    monkeypatch.setattr(ner, "get_engine", boom)
    app.policy_profile = "lgpd_interno"                           # não pede nomes
    app.run_policy_phase()


def test_model_revision_is_always_pinned(tmp_path):
    assert ner.revision_for(ner.DEFAULT_MODEL) == ner.PINNED_MODEL_REVISIONS[ner.DEFAULT_MODEL]
    assert ner.revision_for(ner.DEFAULT_MODEL, "abc123") == "abc123"
    assert ner.revision_for(str(tmp_path)) is None                       # pasta local
    with pytest.raises(ValueError):
        ner.revision_for("alguem/outro-modelo")                          # remoto sem commit fixo

# SPDX-License-Identifier: AGPL-3.0-or-later
"""Regras e limiares como dados (utils/detect/data/*.json): formato, consistência e semântica das frases."""
import json
import os

import pytest

from utils.detect import catalog, config, ner, rules


def test_data_files_load_and_are_consistent():
    lex = config.lexicon()
    assert "RUA" in lex["imunes"] and "A" in lex["conectores"]
    for section, key in [("endereco", "cobertura_minima"), ("endereco", "partes_minimas"),
                         ("endereco", "folga_max_palavras"), ("endereco", "comprimento_extra"),
                         ("ruido_ocr", "alternancias_minimas"), ("ruido_ocr", "digitos_max_entre_letras")]:
        assert config.param(section, key) > 0
    contexts = json.load(open(os.path.join(config.DATA_DIR, "contextos.json"), encoding="utf-8"))
    for type_id in (k for k in contexts if not k.startswith("_")):
        assert type_id in catalog.BY_ID, type_id
        if type_id == "nome_pessoa":  # detector de nomes (ner.py): sem palavras de contexto, só rótulos do modelo
            assert config.strings(type_id, "rotulos_ner")
            continue
        assert type_id in rules.RULES_BY_TYPE or type_id in ner.TYPES, type_id
        assert config.context(type_id)[0] is not None


def test_every_rule_with_required_context_has_context_words():
    for rule in rules.RULES:
        if rule.context_required:
            assert rule.context is not None, rule.type_id


@pytest.mark.parametrize("phrases, text, expected", [
    (["nascid*"], "nascida em", True),
    (["nascimento"], "renascimento", False),            # palavra inteira
    (["titulo de eleitor"], "titulo   de\neleitor", True),  # qualquer espaçamento
    (["r.g."], "portador do r.g. 123", True),            # ponto literal
    (["r.g."], "portador do rxgx 123", False),
    (["c/c"], "conta c/c", True),
])
def test_phrase_regex_semantics(phrases, text, expected):
    assert bool(config.phrase_regex(phrases).search(text)) is expected


def test_invalid_data_gives_a_clear_error(tmp_path, monkeypatch):
    (tmp_path / "lexico.json").write_text(json.dumps({"imunes": "RUA", "conectores": []}), encoding="utf-8")
    (tmp_path / "parametros.json").write_text(json.dumps({"endereco": {"cobertura_minima": "metade"}}), encoding="utf-8")
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    config.clear_cache()
    try:
        with pytest.raises(config.ConfigError, match="imunes"):
            config.lexicon()
        with pytest.raises(config.ConfigError, match="cobertura_minima"):
            config.param("endereco", "cobertura_minima")
    finally:
        monkeypatch.undo()
        config.clear_cache()


def test_changing_a_threshold_in_data_changes_behavior(monkeypatch):
    from utils.address_redactor import locate_address_spans
    gm = [{"id": i, "text": t} for i, t in enumerate(["Rua", "Flores", "x", "y", "z", "10"])]
    assert locate_address_spans("Rua Flores 10", gm) == []           # 3 palavras desconhecidas no meio: folga 2
    original = config.param
    monkeypatch.setattr(config, "param", lambda s, k: 3 if (s, k) == ("endereco", "folga_max_palavras") else original(s, k))
    assert locate_address_spans("Rua Flores 10", gm) == [[1, 2, 3, 4, 5]]

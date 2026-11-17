# SPDX-License-Identifier: AGPL-3.0-or-later
"""Benchmark de endereços: corpus de ata de condomínio (fictício) e a pontuação. Sem LLM (I-08)."""
from benchmarks import address_eval, pii_corpus
from benchmarks.pii_eval import text_grounding
from utils.address_redactor import locate_address_spans


def test_condo_corpus_answer_key_is_on_the_page():
    docs = pii_corpus.generate_condo_addresses(6, 2026)
    for d in docs:
        assert sum(k == "pessoal" for _, k in d.enderecos) == 6
        assert all(locate_address_spans(t, text_grounding(d.text)) for t, _ in d.enderecos)


def test_perfect_answer_covers_all_and_ambiguous_building_is_not_over_redaction():
    d = pii_corpus.generate_condo_addresses(1, 7)[0]
    answer = {"addresses": [{"text": t, "type": "pessoal"} for t, k in d.enderecos if k in ("pessoal", "ambiguo")]}
    res, truth = address_eval.evaluate_page(d, answer)
    assert res["tarjadas"] >= truth and res["tarja_a_mais"] == 0 and res["inventados"] == 0


def test_missing_units_lower_the_coverage():
    d = pii_corpus.generate_condo_addresses(1, 7)[0]
    units = [t for t, k in d.enderecos if k == "pessoal"]
    res, truth = address_eval.evaluate_page(d, {"addresses": [{"text": units[0], "type": "pessoal"}]})
    assert 0 < len(res["tarjadas"] & truth) < len(truth)                                    # contra-teste

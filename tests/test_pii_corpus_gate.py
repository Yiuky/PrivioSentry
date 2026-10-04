# SPDX-License-Identifier: AGPL-3.0-or-later
"""Portão do corpus fictício: cada detector precisa manter revocação e precisão mínimas (modo texto, sem OCR).

Mudou regra, lista ou limiar (utils/detect/data/*.json)? Este teste diz se piorou. O relatório completo, inclusive
com OCR real, sai de `python -m benchmarks.pii_eval` (docs/benchmarks.md).
"""
import pytest

from benchmarks import pii_corpus
from benchmarks.pii_eval import evaluate

# Mínimos por tipo. Revocação é o que protege (tarja que falta = vazamento): o mínimo é 100% no modo texto.
MIN_RECALL = 1.0
MIN_PRECISION = 0.98
EXPECTED_TYPES = {"cpf", "cns", "data_nascimento", "email", "pis_nis", "placa_veiculo", "rg", "telefone"}


@pytest.fixture(scope="module", params=[2026, 7])
def report(request):
    return evaluate(pii_corpus.generate(60, request.param))


def test_every_expected_type_is_measured(report):
    assert EXPECTED_TYPES <= set(report)


def test_recall_per_type(report):
    low = {t: r["revocacao"] for t, r in report.items() if r["esperados"] and r["revocacao"] < MIN_RECALL}
    assert not low, f"revocação abaixo do mínimo: {low}"


def test_precision_per_type(report):
    low = {t: (r["precisao"], r["exemplos_fp"]) for t, r in report.items()
           if r["precisao"] is not None and r["precisao"] < MIN_PRECISION}
    assert not low, f"precisão abaixo do mínimo: {low}"


def test_corpus_has_no_real_looking_email_domains():
    for doc in pii_corpus.generate(60, 2026):
        for t, v in doc.gabarito:
            if t == "email":
                assert v.endswith("@example.com")

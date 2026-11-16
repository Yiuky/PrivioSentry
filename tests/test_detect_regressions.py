# SPDX-License-Identifier: AGPL-3.0-or-later
"""Regressões dos detectores por regra (varredura de bugs): o valor INTEIRO precisa ficar sob a tarja.

Cada caso diz o texto e o trecho que precisa estar coberto; o teste confere caractere por caractere (cobertura
parcial, como "Agência/Conta: 1234/98765-4" só com a agência tarjada, também reprova). Valores fictícios.
"""
import pytest

from sentry_testkit import word
from utils.detect import rules


def _covered(text, types):
    """(texto montado, conjunto de posições cobertas, resultado) para um texto separado por espaços simples."""
    g = [word(i, t, 100 * i) for i, t in enumerate(text.split())]
    joined, char_map = rules.build_text(g)
    found = rules.find_in_grounding(g, types)
    marked = {(wid, i) for _t, (cmds, _v) in found.items() for wid, idx in cmds.items() for i in idx}
    return joined, {p for p, ref in enumerate(char_map) if ref in marked}, found


def assert_fully_covered(type_id, text, value):
    joined, pos, _ = _covered(text, [type_id])
    start = joined.index(value)
    left = "".join(ch for p, ch in enumerate(joined[start:start + len(value)], start) if p not in pos and not ch.isspace())
    assert left == "", f"{text!r}: sobrou {left!r} visível"


CASES = [
    # 1. candidato rejeitado não pode esconder o valor verdadeiro que começa dentro dele
    ("titulo_eleitor", "Título de eleitor 2022 1573 6819 0604", "1573 6819 0604"),
    ("cartao_pagamento", "Cartão de crédito 2024 4111 1111 1111 1111", "4111 1111 1111 1111"),
    ("telefone", "Tel: 1111-1111 3321-1234", "3321-1234"),  # já achado antes; continua
    ("telefone", "Tel: 05.3321-1234", "3321-1234"),
    # 2. conta bancária: o valor inteiro, com rótulos variados
    ("conta_bancaria", "Agência/Conta: 1234/98765-4", "1234/98765-4"),
    ("conta_bancaria", "Conta poupança: 013.00012345-6", "013.00012345-6"),
    ("conta_bancaria", "Conta: 98765 - 4", "98765 - 4"),
    ("conta_bancaria", "Conta: 12.345-6", "12.345-6"),
    ("conta_bancaria", "Conta-corrente: 98765-4", "98765-4"),
    ("conta_bancaria", "Conta número: 98765-4", "98765-4"),
    ("conta_bancaria", "Ag. 1234-5 C/C 98765-4", "98765-4"),
    # 3. telefone: rótulos no plural, lista com "/", DDD com ponto
    ("telefone", "Telefones: 3321-1234", "3321-1234"),
    ("telefone", "Fones: 99876-5432", "99876-5432"),
    ("telefone", "Celulares: 99876-5432", "99876-5432"),
    ("telefone", "Contatos: 99876-5432", "99876-5432"),
    ("telefone", "Telefones: (65) 3321-1234 / 99876-5432", "(65) 3321-1234"),
    ("telefone", "Telefones: (65) 3321-1234 / 99876-5432", "99876-5432"),
    ("telefone", "Telefones: (65) 3321-1234 / (65) 3322-1234 / 99876-5432", "99876-5432"),
    ("telefone", "Celular 65.99876.5432", "65.99876.5432"),
    # 4. RG com rótulo combinado ("RG/CPF", "Identidade e CPF") e com espaços
    ("rg", "RG/CPF: 1234567 / 529.982.247-25", "1234567"),
    ("rg", "Identidade e CPF: 12.345.678-9 e 529.982.247-25", "12.345.678-9"),
    ("rg", "RG: 12 345 678-9", "12 345 678-9"),
    # 5. cartões Amex (4-6-5) e Diners (4-6-4)
    ("cartao_pagamento", "Cartão Amex: 3782 822463 10005", "3782 822463 10005"),
    ("cartao_pagamento", "Cartão de crédito: 3056 930902 5904", "3056 930902 5904"),
    # 7. normalização que tira um caractere antes do valor e acrescenta um depois (mesmo comprimento total)
    ("conta_bancaria", "— Conta: 98765-4 ﬁm", "98765-4"),
    ("rg", "— RG: 12.345.678-9 ﬁm", "12.345.678-9"),
    # 9. formatos menos comuns
    ("cns", "CNS: 190.0754.0091.7145", "190.0754.0091.7145"),
    ("pis_nis", "PIS: 526.01815.90 - 7", "526.01815.90 - 7"),
    ("placa_veiculo", "Placa ABC-l234", "ABC-l234"),
    ("passaporte", "Passaporte nº fz123456", "fz123456"),
    ("email", "E-mail: maria. exemplo@example.com", "maria. exemplo@example.com"),
]


@pytest.mark.parametrize("type_id, text, value", CASES)
def test_value_is_fully_covered(type_id, text, value):
    assert_fully_covered(type_id, text, value)


def test_cpf_after_combined_label_is_not_an_rg_nor_split_into_one():
    for text in ("RG: 529.982.247-25", "RG: 123.456.789-00"):  # válido ou não, CPF formatado não vira RG
        _, _, found = _covered(text, ["rg"])
        assert found == {}, text
    _, _, found = _covered("RG/CPF: 1234567 / 529.982.247-25", ["rg"])
    assert found["rg"][1] == {"1234567"}


def test_stop_word_still_cancels_context_after_another_value():
    # "RG: 1234567 CPF: <número>": o número depois do rótulo CPF não é RG
    _, _, found = _covered("RG: 1234567 CPF: 123.456.789-00", ["rg"])
    assert found["rg"][1] == {"1234567"}


def test_dotted_ddd_without_label_is_not_a_phone():
    _, _, found = _covered("protocolo 12.2024-0001", ["telefone"])
    assert found == {}

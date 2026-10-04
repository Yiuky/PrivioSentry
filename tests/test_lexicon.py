# SPDX-License-Identifier: AGPL-3.0-or-later
from utils.lexicon import is_immune


def test_structural_terms_are_immune():
    for w in ["Rua", "BAIRRO", "CEP", "de", "FAZENDA", "Av."]:
        assert is_immune(w)


def test_numbers_and_names_are_not_immune():
    for w in ["78.550-352", "Quadra12", "Silva", "Jacarandá"]:
        assert not is_immune(w)


def test_punctuation_only_is_immune():
    assert is_immune(",")

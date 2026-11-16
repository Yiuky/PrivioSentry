"""Regressões da busca de CPF nas palavras do OCR (usada pela detecção E pelas duas verificações finais).
CPFs fictícios da lista permitida (scripts/audit_public_tree.py)."""
import pytest

from sentry_testkit import word
from utils.ocr_engine import OCREngine


def _cpfs(words):
    return OCREngine(tesseract_path=None).find_cpfs_in_grounding(words)[1]


def _line(*texts, y=100, x0=0):
    out, x = [], x0
    for t in texts:
        out.append((t, x, y))
        x += 20 * len(t) + 15
    return out


def _words(*items):
    return [word(i, t, x, y=y) for i, (t, x, y) in enumerate(items)]


@pytest.mark.parametrize("pitch", [40, 46, 60, 85])
def test_cpf_wrapped_after_a_separator_is_found(pitch):
    items = _line("CPF:", "529.982.") + _line("247-25,", "residente", y=100 + pitch)
    assert _cpfs(_words(*items)) == {"52998224725"}


def test_numbers_on_different_lines_without_separator_do_not_join():
    # contra-teste: sem separador no fim da linha, cada linha é um número próprio
    items = _line("Protocolo", "52998") + _line("224725", "fim", y=150)
    assert _cpfs(_words(*items)) == set()


@pytest.mark.parametrize("text", ["529.982.247-2S", "390.533.447-O5", "lll.444.777-35", "529.9B2.247-25",
                                  "529.982.247-25".replace("0", "O")])
def test_ocr_letter_for_digit_swaps_still_find_the_cpf(text):
    assert len(_cpfs(_words(*_line("CPF:", text)))) == 1


def test_words_that_are_not_numbers_are_untouched():
    assert _cpfs(_words(*_line("SOLO", "IBIS", "BOLSO", "Oslo"))) == set()


@pytest.mark.parametrize("neighbour", ["113", "385", "466", "1000"])
def test_cpf_written_with_spaces_next_to_a_number_is_found(neighbour):
    # "Ramal 113 CPF 529 982 247 25": os 14/15 dígitos passavam no DV de CNPJ/CNS e o CPF sumia
    assert _cpfs(_words(*_line("Ramal", neighbour, "CPF", "529", "982", "247", "25"))) == {"52998224725"}


@pytest.mark.parametrize("noise", ["QD12", "S10", "I5", "lO1", "BOLO12", "ISO 9001"])
def test_stamp_noise_with_letters_does_not_assemble_a_cpf(noise):
    # contra-teste das letras parecidas com dígitos: ruído de carimbo ao lado de números não monta CPF inventado
    assert _cpfs(_words(*_line("Protocolo", noise, "12345", "67"))) == set()

# SPDX-License-Identifier: AGPL-3.0-or-later
"""Caracterizacao do casamento programatico de enderecos (refine_redaction_with_text_ai / is_immune).

A tabela abaixo documenta o comportamento ATUAL, incluindo limitacoes conhecidas:
  - "ok":    tarja exatamente o que se espera;
  - "over":  SOBRE-tarjamento aceito (vies "falhar fechado": prefere tarjar demais a vazar);
  - "under": SUB-tarjamento (limitacao: o OCR leu diferente da IA de visao) -> depende da revisao humana.
Nenhum caso aqui provou defeito que justificasse alterar o algoritmo.
"""
import os

import pytest

from main import SentryApp
from sentry_testkit import make_text_pdf
from utils.lexicon import is_immune


@pytest.fixture()
def redactor(tmp_path):
    app = SentryApp(make_text_pdf(tmp_path / "a.pdf"))
    yield app.address_redactor
    app.session.close()


def run(redactor, ocr_words, addresses):
    gm = [{"id": i, "text": t, "box": {"x": i * 100, "y": 0, "w": 90, "h": 20}} for i, t in enumerate(ocr_words)]
    ids = redactor.refine_redaction_with_text_ai(1, "", addresses, gm)
    return [ocr_words[i] for i in ids]


def pessoal(text):
    return [{"text": text, "type": "pessoal"}]


# (id, palavras do OCR, endereco(s) da IA, esperado, categoria)
CASES = [
    ("simples", ["Rua", "das", "Flores,", "123,", "Bairro", "Centro"],
     pessoal("Rua das Flores, 123, Bairro Centro"), ["Flores,", "123,", "Centro"], "ok"),
    ("acentos", ["Avenida", "Sao", "Joao", "45"], pessoal("Avenida São João, 45"), ["Sao", "Joao", "45"], "ok"),
    ("cep_inteiro", ["CEP", "78.550-352"], pessoal("CEP 78.550-352"), ["78.550-352"], "ok"),
    ("cep_quebrado_pelo_ocr", ["78.550-", "352"], pessoal("78.550-352"), ["78.550-", "352"], "ok"),
    ("quadra_lote_numeros_curtos", ["Quadra", "5", "Lote", "12"], pessoal("Quadra 5 Lote 12"), ["5", "12"], "ok"),
    ("rotulo_com_dois_pontos_nunca", ["Endereco:", "Flores"], pessoal("Endereco: Flores"), ["Flores"], "ok"),
    ("conectores_imunes", ["Rua", "do", "Sol", "e", "da", "Lua"], pessoal("Rua do Sol e da Lua"), ["Sol", "Lua"], "ok"),
    ("rodovia_com_numero_e_redigida", ["BR-163", "km", "10"], pessoal("BR-163 km 10"), ["BR-163", "10"], "ok"),
    ("endereco_profissional_ignorado", ["Avenida", "Brasil", "500"],
     [{"text": "Avenida Brasil 500", "type": "profissional"}], [], "ok"),
    ("sem_enderecos", ["Rua", "Flores"], [], [], "ok"),
    ("varios_enderecos_so_pessoal", ["Flores", "Prado", "Obra"],
     [{"text": "Rua Flores 1", "type": "pessoal"}, {"text": "Rua Prado 2", "type": "secundário"}], ["Flores"], "ok"),
    # --- sobre-tarjamento (aceito) ---
    ("over_numero_igual_em_outro_lugar", ["Pagina", "10", "Rua", "Flores", "10"], pessoal("Rua Flores 10"),
     ["10", "Flores", "10"], "over"),
    ("over_substring_de_palavra_maior", ["Floresta", "Santarem"], pessoal("Rua Flores, Santa Rita"),
     ["Floresta", "Santarem"], "over"),
    ("over_nome_da_cidade_em_qualquer_lugar", ["Cuiaba,", "12", "de", "marco", "Rua", "Alfa", "Cuiaba"],
     pessoal("Rua Alfa, Cuiabá"), ["Cuiaba,", "Alfa", "Cuiaba"], "over"),
    # --- sub-tarjamento (limitacao conhecida) ---
    ("under_ocr_confunde_letra_por_digito", ["Fl0res", "123"], pessoal("Rua Flores 123"), ["123"], "under"),
    ("under_ocr_parte_a_palavra", ["Flo", "res", "123"], pessoal("Rua Flores 123"), ["123"], "under"),
    ("under_ia_abrevia_endereco", ["Jardim", "Primavera"], pessoal("Jd. Primavera"), ["Primavera"], "under"),
    ("over_abreviatura_vira_substring", ["Presidente", "Costa"], pessoal("Pres. Costa"), ["Presidente", "Costa"], "over"),
]


@pytest.mark.parametrize("name,ocr_words,addresses,expected,kind", CASES, ids=[c[0] for c in CASES])
def test_matching_table(redactor, name, ocr_words, addresses, expected, kind):
    assert run(redactor, ocr_words, addresses) == expected


def test_every_known_limitation_is_listed_in_table():
    kinds = {c[4] for c in CASES}
    assert kinds == {"ok", "over", "under"}


def test_fallback_builds_map_from_indexed_text_when_no_coordinates(redactor):
    indexed = "[0] Rua [1] Flores, [2] 123 [3] Obra"
    ids = redactor.refine_redaction_with_text_ai(1, indexed, pessoal("Rua Flores, 123"))
    assert ids == [1, 2]


def test_audit_trail_is_saved_without_page_text(redactor):
    redactor.refine_redaction_with_text_ai(3, "", pessoal("Rua Flores"), [
        {"id": 0, "text": "Flores", "box": {"x": 0, "y": 0, "w": 1, "h": 1}}])
    d = redactor.session.dirs["99_ia_interactions"]
    assert os.path.exists(os.path.join(d, "page_3_text_audit_prompt.txt"))


def test_words_with_only_punctuation_are_never_redacted(redactor):
    assert run(redactor, ["-", "...", "Flores"], pessoal("Rua Flores")) == ["Flores"]


# --- is_immune ---------------------------------------------------------------------------------
@pytest.mark.parametrize("word,expected", [
    ("Rua", True), ("rua.", True), ("AV.", True), ("(CEP)", True), ("S/N", True), ("N°", True),
    ("de", True), ("DA", True), ("e", True), ("", True), ("...", True), ("  ", True),
    ("Flores", False), ("Centro", False), ("123", False), ("A1", False), ("BR-163", False),
    ("Q5", False), ("Lote5", False), ("São", False),
    ("Brasil", True), ("CPF", True), ("Fazenda", True), ("Sítio", True),
])
def test_is_immune_table(word, expected):
    assert is_immune(word) is expected

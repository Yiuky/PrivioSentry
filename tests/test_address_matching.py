# SPDX-License-Identifier: AGPL-3.0-or-later
"""Caracterização do casamento programático de endereços (refine_redaction_with_text_ai / is_immune).

Desde a 5.4.1 o endereço é localizado como TRECHO contínuo do OCR (utils/address_redactor.locate_address_spans), e
não como "saco de palavras". Antes, qualquer palavra do endereço era tarjada em QUALQUER ponto da página ("à",
números, a cidade, até datas que continham um número do endereço). Categorias da tabela:
  - "ok":     tarja exatamente o que se espera;
  - "revisao": o endereço pessoal não foi localizado com segurança -> nenhuma tarja espalhada e a página vai
              para revisão humana (falha fechado; ver test_unlocated_personal_address_goes_to_review).
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
    ("rotulo_com_dois_pontos_nunca", ["Endereco:", "Flores", "10"], pessoal("Endereco: Flores 10"), ["Flores", "10"], "ok"),
    ("conectores_imunes", ["Rua", "do", "Sol", "e", "da", "Lua"], pessoal("Rua do Sol e da Lua"), ["Sol", "Lua"], "ok"),
    ("rodovia_com_numero_e_redigida", ["BR-163", "km", "10"], pessoal("BR-163 km 10"), ["BR-163", "10"], "ok"),
    ("endereco_profissional_ignorado", ["Avenida", "Brasil", "500"],
     [{"text": "Avenida Brasil 500", "type": "profissional"}], [], "ok"),
    ("sem_enderecos", ["Rua", "Flores"], [], [], "ok"),
    ("numero_igual_em_outro_lugar_nao_e_tarjado", ["Pagina", "10", "Rua", "Flores", "10"], pessoal("Rua Flores 10"),
     ["Flores", "10"], "ok"),
    ("palavra_maior_nao_e_o_endereco", ["Floresta", "Santarem"], pessoal("Rua Flores, Santa Rita"), [], "revisao"),
    ("cidade_solta_em_outro_lugar_nao_e_tarjada", ["Cuiaba,", "12", "de", "marco", "Rua", "Alfa", "Cuiaba"],
     pessoal("Rua Alfa, Cuiabá"), ["Alfa", "Cuiaba"], "ok"),
    ("ocr_confunde_letra_por_digito", ["Fl0res", "123"], pessoal("Rua Flores 123"), ["Fl0res", "123"], "ok"),
    ("ocr_parte_a_palavra", ["Flo", "res", "123"], pessoal("Rua Flores 123"), ["Flo", "res", "123"], "ok"),
    ("ia_abrevia_endereco", ["Jardim", "Primavera"], pessoal("Jd. Primavera"), ["Jardim", "Primavera"], "ok"),
    ("abreviatura_casa_palavra_inteira", ["Presidente", "Costa"], pessoal("Pres. Costa"), ["Presidente", "Costa"], "ok"),
    ("endereco_incompleto_no_ocr", ["Flores", "Prado", "Obra"],
     [{"text": "Rua Flores 1", "type": "pessoal"}, {"text": "Rua Prado 2", "type": "secundário"}], [], "revisao"),
    # --- casos do documento real que motivou a mudança (texto fictício, mesmo formato) ---
    ("crase_solta_na_pagina_nao_e_tarjada", ["reunião", "realizada", "à", "noite.", "Moradora", "à", "Rua", "Alfa,",
                                              "45", "Centro"], pessoal("à Rua Alfa, 45, Centro"), ["Alfa,", "45", "Centro"], "ok"),
    ("data_colada_pelo_llm_nunca_e_tarjada", ["em", "05/03/2024", "na", "Rua", "Alfa,", "45"],
     pessoal("05/03/2024 na Rua Alfa, 45"), ["Alfa,", "45"], "ok"),
    ("data_com_numero_do_endereco_nao_e_tarjada", ["Rua", "Alfa", "2024", "assinado", "em", "01/02/2024"],
     pessoal("Rua Alfa 2024"), ["Alfa", "2024"], "ok"),
    ("endereco_repetido_tarja_as_duas_vezes", ["Rua", "Alfa", "45", "...", "texto", "longo", "aqui", "...", "Rua",
                                                "Alfa", "45"], pessoal("Rua Alfa 45"), ["Alfa", "45", "Alfa", "45"], "ok"),
]


@pytest.mark.parametrize("name,ocr_words,addresses,expected,kind", CASES, ids=[c[0] for c in CASES])
def test_matching_table(redactor, name, ocr_words, addresses, expected, kind):
    assert run(redactor, ocr_words, addresses) == expected


def test_unlocated_personal_address_goes_to_review(redactor):
    gm = [{"id": i, "text": t, "box": {"x": i * 100, "y": 0, "w": 90, "h": 20}} for i, t in enumerate(["Floresta"])]
    assert redactor.refine_redaction_with_text_ai(1, "", pessoal("Rua Flores, Santa Rita"), gm) == []
    assert redactor.unlocated[1] == ["Rua Flores, Santa Rita"]


def test_every_known_limitation_is_listed_in_table():
    kinds = {c[4] for c in CASES}
    assert kinds == {"ok", "revisao"}


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
    assert run(redactor, ["-", "...", "Flores", "-", "10"], pessoal("Rua Flores 10")) == ["Flores", "10"]


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

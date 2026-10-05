# SPDX-License-Identifier: AGPL-3.0-or-later
"""Segundo olhar: ciclo de agente pela API, só acrescenta, descarta o que não existe na página. Sem modelo (I-08)."""
import json

import pytest

from sentry_testkit import CPF_A_FMT, make_text_pdf, word
from utils import second_look


class FakeAPI:
    """Simula /v1/chat/completions: 1ª resposta chama ler_pagina; a 2ª devolve `final` (lista de achados)."""

    def __init__(self, final, fail=False):
        self.final, self.fail, self.calls = final, fail, []

    def __call__(self, url, json=None, headers=None, timeout=None):
        self.calls.append(json)
        outer = self

        class R:
            status_code = 500 if outer.fail else 200
            text = "erro"

            def json(self_inner):
                if len(outer.calls) == 1:
                    return {"choices": [{"message": {"content": "", "tool_calls": [
                        {"id": "c1", "function": {"name": "ler_pagina", "arguments": '{"inicio": 1}'}}]}}],
                            "usage": {"prompt_tokens": 300}}
                return {"choices": [{"message": {"content": __import__("json").dumps({"achados": outer.final})}}],
                        "usage": {"prompt_tokens": 500}}
        return R()


def test_agent_reads_the_page_with_a_tool_then_answers():
    api = FakeAPI([{"tipo": "cpf", "texto": CPF_A_FMT}])
    items, info = second_look.run_agent("linha 1\nCPF " + CPF_A_FMT, ["cpf"], post=api)
    assert items == [("cpf", CPF_A_FMT)] and info["passos"] == 2 and info["tokens"] == 800
    tool_msg = api.calls[1]["messages"][-1]
    assert tool_msg["role"] == "tool" and CPF_A_FMT in tool_msg["content"] and tool_msg["content"].startswith("1: ")
    assert {t["function"]["name"] for t in api.calls[0]["tools"]} == {"ler_pagina", "buscar"}


def test_agent_failure_is_reported():
    items, info = second_look.run_agent("x", ["cpf"], post=FakeAPI([], fail=True))
    assert items is None and "HTTP 500" in info["erro"]


def test_locate_finds_values_across_ocr_words_and_rejects_invented_ones():
    g = [word(0, "Nome:", 0), word(1, "Maria", 100), word(2, "Exemplo,", 200), word(3, "CPF", 300),
         word(4, CPF_A_FMT[:7], 400), word(5, CPF_A_FMT[7:], 500)]
    assert set(second_look.locate("Maria Exemplo", g)) == {1, 2}
    assert set(second_look.locate(CPF_A_FMT, g)) == {4, 5}          # CPF partido pelo OCR
    assert second_look.locate("João Inventado", g) == {}            # não existe na página: descartado
    assert second_look.locate("abc", g) == {}                       # curto demais para valer


@pytest.mark.parametrize("label, expected", [("CPF", "cpf"), ("e-mail", "email"), ("Nome de pessoa", "nome_pessoa"),
                                             ("cartão SUS", "cns"), ("placa de veículo", "placa_veiculo"),
                                             ("qualquer", None)])
def test_type_labels(label, expected):
    assert second_look.type_id_for(label) == expected


@pytest.fixture()
def app(tmp_path, monkeypatch):
    from main import SentryApp
    monkeypatch.setenv("BASE_DPI", "40")
    monkeypatch.setenv("SECOND_LOOK", "1")
    a = SentryApp(make_text_pdf(tmp_path / "d.pdf", n_pages=2))
    a.run_phase_0()
    page = [word(0, "Contato:", 10), word(1, "(65)", 200), word(2, "99999-1234", 300),
            word(3, "Maria", 10, y=200), word(4, "Exemplo", 120, y=200)]
    a.grounding_maps = [page, page]
    a.grounding_maps_sparse = [[], []]
    a.grounding_maps_native = [[], []]
    a.policy_profile = "lgpd_publicacao"       # tarja telefone e nome
    yield a
    a.session.close()


def _agent(monkeypatch, items=None, fail=False):
    calls = []

    def fake(text, types, post=None):
        calls.append((text, tuple(types)))
        if fail:
            return None, {"erro": "servidor fora"}
        return items, {"passos": 2}
    monkeypatch.setattr(second_look, "run_agent", fake)
    return calls


def test_second_look_only_on_review_pages_and_only_adds(app, monkeypatch):
    calls = _agent(monkeypatch, [("telefone", "(65) 99999-1234"), ("nome", "Maria Exemplo"), ("cpf", "inventado 123"),
                                 ("nome", "João Inventado")])
    app.add_review(2, "alerta qualquer")
    app.run_second_look()
    assert len(calls) == 1                                          # só a página 2 estava em revisão
    assert "Maria Exemplo" in calls[0][0] and "telefone" in calls[0][1]
    assert len(app.global_redactions[2]) == 4 and not app.global_redactions[1]  # (65), 99999-1234, Maria, Exemplo
    assert app.second_look_stats["implausiveis"] == 1               # "CPF" sem formato: recusado
    assert app.second_look_stats["nao_localizadas"] == 1            # nome que não existe na página: descartado
    assert any("Segundo olhar (IA) acrescentou tarja" in r for r in app.review_pages[2])


def test_already_covered_values_are_not_duplicated(app, monkeypatch):
    _agent(monkeypatch, [("telefone", "(65) 99999-1234")])
    monkeypatch.setenv("SECOND_LOOK_SCOPE", "todas")
    app.run_policy_phase()                                          # as regras já tarjam o telefone
    before = len(app.global_redactions[1])
    app.run_second_look()
    assert len(app.global_redactions[1]) == before and app.second_look_stats["ja_cobertas"] >= 1


def test_agent_failure_sends_page_to_review(app, monkeypatch):
    _agent(monkeypatch, fail=True)
    monkeypatch.setenv("SECOND_LOOK_SCOPE", "todas")
    app.run_second_look()
    assert all(any("Segundo olhar (IA) falhou" in r for r in app.review_pages[p]) for p in (1, 2))


def test_off_by_default(app, monkeypatch):
    monkeypatch.delenv("SECOND_LOOK", raising=False)
    calls = _agent(monkeypatch, [])
    app.add_review(1, "x")
    app.run_second_look()
    assert calls == []


def test_endpoint_follows_the_main_ai_server(monkeypatch):
    monkeypatch.delenv("SECOND_LOOK_BASE_URL", raising=False)
    monkeypatch.setenv("AI_BASE_URL", "http://ia.org:11434")
    assert second_look._endpoint() == "http://ia.org:11434/v1/chat/completions"
    monkeypatch.setenv("AI_PROVIDER", "openai")
    monkeypatch.setenv("AI_BASE_URL", "http://lm:1234/v1")
    assert second_look._endpoint() == "http://lm:1234/v1/chat/completions"
    json.dumps(second_look.TOOLS)  # ferramentas serializáveis


@pytest.mark.parametrize("type_id, value, ok", [
    ("cpf", CPF_A_FMT, True), ("cpf", "124.911.3969-00", False),          # 12 dígitos: lixo de OCR
    ("placa_veiculo", "ABC1D23", True), ("placa_veiculo", "BR4.47", False),
    ("cns", "cnsminda", False), ("telefone", "(65) 99999-1234", True),
    ("email", "maria@example.com", True), ("email", "maria", False),
    ("nome_pessoa", "Maria Exemplo", True), ("nome_pessoa", "MARIA EXEMPLO", True),
    ("nome_pessoa", "Lucas", False), ("nome_pessoa", "Dosammaso", False),
    ("nome_pessoa", "EEE ERR E EOUBESO SSFRUP", False), ("data_nascimento", "01/02/1980", True),
])
def test_only_plausible_values_are_added(type_id, value, ok):
    # Medido no benchmark: sem esta checagem o agente acrescentava lixo de OCR com cara de dado
    assert second_look.plausible(type_id, value) is ok


def test_numeric_values_keep_only_the_digits_and_service_phones_are_not_personal():
    # Documentos reais: o agente incluía o órgão emissor no RG e apontava números 0800 como telefone pessoal
    assert second_look.core_value("rg", "12345678 SSP/MT") == "12345678"
    assert second_look.core_value("nome_pessoa", "Maria Exemplo") == "Maria Exemplo"
    assert not second_look.plausible("telefone", "0800 123 4567")
    assert not second_look.plausible("telefone", "4004-1234")
    assert second_look.plausible("telefone", "(65) 99999-1234")


def test_old_plate_needs_context_like_the_rules():
    assert not second_look.plausible("placa_veiculo", "PHC3028")                      # sem "placa" perto
    assert second_look.plausible("placa_veiculo", "PHC3028", "Veículo placa PHC3028")
    assert second_look.plausible("placa_veiculo", "ABC1D23")                          # Mercosul vale sozinho

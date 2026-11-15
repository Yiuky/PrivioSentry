# SPDX-License-Identifier: AGPL-3.0-or-later
r"""Testes AO VIVO contra um provedor de IA de verdade (procedimento: docs/procedimento-ia-externa.md).

Não rodam por padrão nem no CI (I-08): só com PRIVIO_LIVE_AI=1 e a chave na variável indicada. Usam SÓ dados
fictícios (benchmarks/provider_check.py). Exemplo, com o Gemini (AI Studio):

    PRIVIO_LIVE_AI=1 PRIVIO_LIVE_PRESET=gemini PRIVIO_LIVE_KEY_ENV=GEMINI_API_KEY \
    PRIVIO_LIVE_MODEL=gemini-flash-lite-latest pytest -m live -v
"""
import os

import pytest

pytestmark = pytest.mark.live

KEY_ENV = os.getenv("PRIVIO_LIVE_KEY_ENV", "GEMINI_API_KEY")
if os.getenv("PRIVIO_LIVE_AI") != "1" or not os.getenv(KEY_ENV):
    pytest.skip("teste ao vivo: defina PRIVIO_LIVE_AI=1 e a chave do provedor", allow_module_level=True)


@pytest.fixture(scope="module")
def report(tmp_path_factory):
    from benchmarks import provider_check
    mp = pytest.MonkeyPatch()
    mp.setenv("PRIVIO_RUNTIME_DIR", str(tmp_path_factory.mktemp("runtime")))
    try:
        yield provider_check.run(os.getenv("PRIVIO_LIVE_PRESET", "gemini"), KEY_ENV,
                                 os.getenv("PRIVIO_LIVE_MODEL", "gemini-flash-lite-latest"),
                                 str(tmp_path_factory.mktemp("relatorio")))
    finally:
        mp.undo()


def result(report, name):
    return next(r for r in report["resultados"] if r["verificacao"] == name)


@pytest.mark.parametrize("name", ["trava_de_saida", "conexao_e_chave", "chat_json", "visao_enderecos",
                                  "agente_ferramentas", "inspecao_modelo", "rascunho_modelo_ia"])
def test_provider(report, name):
    r = result(report, name)
    assert r["status"] in ("OK", "PULADA"), r


def test_key_never_reaches_the_report(report):
    import json
    with open(report["arquivo"], encoding="utf-8") as fh:
        text = fh.read()
    assert os.environ[KEY_ENV] not in text and json.loads(text)["servidor"]["com_chave"] is True


def test_only_the_configured_provider_was_contacted(report):
    from utils import egress
    assert report["destinos_externos_usados"] == [egress.host_of(report["servidor"]["endereco"])]

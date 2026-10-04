# SPDX-License-Identifier: AGPL-3.0-or-later
"""Perguntas feitas ao modelo de decisão e normalização do texto.

Mantenha as perguntas aqui: mudar o texto de uma pergunta muda o que o modelo responde, então os
perfis aprendidos ficam marcados com QUESTIONS_VERSION e um perfil de outra versão é ignorado.

As perguntas viram as "características" (features) da cabeça treinável (utils/decisions/learning.py):
o Laya responde todas numa única passada e o treino aprende como combiná-las. A primeira é a
pergunta principal; sem perfil treinado, só ela é usada (zero-shot, apenas em modo sombra).
"""
import re

from utils.pii import mask_text

# Suba este número sempre que mudar o texto, a ordem das perguntas ou a normalização abaixo.
QUESTIONS_VERSION = 2


def _noul(instructions, false, true):
    return {"type": "noul", "instructions": instructions, "criteria": {"false": false, "true": true}}


ADDRESS_QUESTIONS = {
    "residencial": _noul(
        "O endereço abaixo é residencial, isto é, a moradia de uma pessoa física?",
        "endereço de empresa, escritório, órgão público, obra, fazenda, imóvel rural ou empreendimento",
        "endereço residencial de pessoa física (casa, apartamento, condomínio, moradia)",
    ),
    "empresa": _noul(
        "O endereço abaixo é de uma empresa, loja, escritório ou sala comercial?",
        "não é endereço comercial", "é endereço comercial ou empresarial",
    ),
    "orgao_publico": _noul(
        "O endereço abaixo é de um órgão público (secretaria, prefeitura, tribunal, autarquia)?",
        "não é órgão público", "é endereço de órgão público",
    ),
    "rural_obra": _noul(
        "O endereço abaixo é de imóvel rural, fazenda, lote, obra ou empreendimento?",
        "não é rural nem obra", "é imóvel rural, fazenda, lote, obra ou empreendimento",
    ),
    # Perguntas objetivas ("o texto menciona...?"): o Laya responde melhor a elas do que às de juízo.
    # Juntas, as 9 perguntas elevaram o AUC no conjunto realista de 0,875 (4 perguntas) para 0,91.
    "menciona_moradia": _noul(
        "O texto menciona moradia: casa, apartamento, apto, bloco residencial, condomínio, kitnet, sobrado ou residência?",
        "não menciona moradia", "menciona moradia",
    ),
    "menciona_empresa": _noul(
        "O texto menciona empresa, loja, escritório, sala comercial, clínica, indústria, shopping ou CNPJ?",
        "não menciona empresa", "menciona empresa ou comércio",
    ),
    "menciona_orgao": _noul(
        "O texto menciona órgão ou serviço público: secretaria, prefeitura, tribunal, câmara, escola, hospital, "
        "delegacia, cartório, posto de saúde?",
        "não menciona órgão público", "menciona órgão ou serviço público",
    ),
    "menciona_rural": _noul(
        "O texto menciona fazenda, sítio, gleba, assentamento, rodovia, km, zona rural, obra ou canteiro?",
        "não menciona área rural nem obra", "menciona área rural, rodovia ou obra",
    ),
    "pessoa_reside": _noul(
        "O texto diz que uma pessoa mora ou reside no endereço (residente, domiciliado, morador, residência)?",
        "não diz que alguém mora ali", "diz que uma pessoa mora ali",
    ),
}
FEATURE_IDS = list(ADDRESS_QUESTIONS)  # ordem fixa das características
PRIMARY_QUESTION = FEATURE_IDS[0]

_DIGITS = re.compile(r"\d")
_SPACES = re.compile(r"\s+")


def normalize_state(text, max_chars=400):
    """
    Texto enviado ao modelo e guardado nos exemplos de treino.

    Minimização de dados: CPFs mascarados e todos os dígitos trocados por "0" (número, CEP, apto).
    Para decidir se um endereço é residencial, as palavras importam; os números, não. A mesma
    função vale na inferência e no treino, para que os dois vejam o texto do mesmo jeito.
    """
    value = mask_text(str(text or ""))
    value = _DIGITS.sub("0", value)
    return _SPACES.sub(" ", value).strip()[:max_chars]

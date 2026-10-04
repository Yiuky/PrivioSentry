# SPDX-License-Identifier: AGPL-3.0-or-later
"""Perfis de política: o que fazer com cada tipo do catálogo.

Ações:
    tarjar   vira tarja SUGERIDA (o revisor confirma, como todas as tarjas da IA)
    alertar  marca a região para revisão, sem tarja (para tipos que nem sempre devem sair do documento)

O perfil ativo vem de POLICY_PROFILE (padrão: cpf_endereco, o comportamento original). Tipos "planejados" no
catálogo podem aparecer nos perfis: passam a valer sozinhos quando o detector existir.
"""
import os

from . import catalog

TARJAR = "tarjar"
ALERTAR = "alertar"

_DOCUMENTOS = ["cpf", "rg", "cnh", "titulo_eleitor", "pis_nis", "cns", "passaporte", "ctps"]
_FINANCEIRO = ["cartao_pagamento", "conta_bancaria", "chave_pix"]
_CONTATO = ["endereco_residencial", "telefone", "email"]
_SENSIVEIS = ["saude", "biometrico_genetico", "religiao", "opiniao_politica", "filiacao_sindical", "origem_etnica",
              "vida_sexual", "antecedentes_criminais"]


def _actions(tarjar=(), alertar=()):
    out = {t: TARJAR for t in tarjar}
    out.update({t: ALERTAR for t in alertar})
    return out


PROFILES = {
    "cpf_endereco": {
        "nome": "Só CPF e endereço residencial",
        "descricao": "Comportamento original do SENTRY Redact.",
        "acoes": _actions(tarjar=["cpf", "endereco_residencial"]),
    },
    "lgpd_publicacao": {
        "nome": "LGPD: publicação (transparência / LAI)",
        "descricao": "Para publicar documentos (LAI art. 31): tarja identificadores diretos, contato, financeiro e datas "
                     "de nascimento; alerta para identificadores indiretos e dados sensíveis.",
        "acoes": _actions(tarjar=_DOCUMENTOS + _FINANCEIRO + _CONTATO + ["data_nascimento", "nome_pessoa", "filiacao",
                                                                          "foto_rosto"],
                          alertar=["placa_veiculo", "ip", "geolocalizacao"] + _SENSIVEIS),
    },
    "lgpd_interno": {
        "nome": "LGPD: compartilhamento interno",
        "descricao": "Para circular dentro da organização: tarja documentos e dados financeiros; alerta para contato e "
                     "dados sensíveis (decisão do revisor conforme a finalidade).",
        "acoes": _actions(tarjar=_DOCUMENTOS + _FINANCEIRO,
                          alertar=_CONTATO + ["data_nascimento", "placa_veiculo", "ip"] + _SENSIVEIS),
    },
    "gdpr": {
        "nome": "GDPR (União Europeia)",
        "descricao": "Identificadores diretos e online (inclui IP) tarjados; categorias especiais (art. 9) e dados "
                     "criminais (art. 10) alertados para revisão.",
        "acoes": _actions(tarjar=_DOCUMENTOS + _FINANCEIRO + _CONTATO + ["data_nascimento", "ip", "placa_veiculo",
                                                                          "nome_pessoa", "filiacao", "foto_rosto",
                                                                          "geolocalizacao"],
                          alertar=_SENSIVEIS),
    },
    "saude_hipaa": {
        "nome": "Saúde (referência HIPAA Safe Harbor)",
        "descricao": "Tarja os identificadores da lista Safe Harbor que o projeto detecta (documentos, contato, datas, "
                     "contas, placas, IP, nomes, fotos) e alerta para dados de saúde.",
        "acoes": _actions(tarjar=_DOCUMENTOS + _FINANCEIRO + _CONTATO + ["data_nascimento", "ip", "placa_veiculo",
                                                                          "nome_pessoa", "filiacao", "foto_rosto",
                                                                          "geolocalizacao"],
                          alertar=_SENSIVEIS),
    },
}
DEFAULT_PROFILE = "cpf_endereco"


def active_profile_id():
    value = (os.getenv("POLICY_PROFILE") or DEFAULT_PROFILE).strip().lower()
    return value if value in PROFILES else DEFAULT_PROFILE


def get_profile(profile_id=None):
    pid = profile_id or active_profile_id()
    return pid, PROFILES[pid]


def runnable_actions(profile_id=None):
    """Ações do perfil só para tipos com detector ativo, separando os que já têm fase própria no pipeline."""
    _, profile = get_profile(profile_id)
    return {t: a for t, a in profile["acoes"].items() if catalog.get(t).estado == catalog.ATIVO}


def describe_all():
    """Perfis para a API/documentação (sem dado pessoal)."""
    out = {}
    for pid, p in PROFILES.items():
        out[pid] = {"nome": p["nome"], "descricao": p["descricao"],
                    "acoes": {t: {"acao": a, "estado": catalog.get(t).estado} for t, a in p["acoes"].items()}}
    return out

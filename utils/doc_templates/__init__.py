# SPDX-License-Identifier: AGPL-3.0-or-later
"""Modelos de documento (SENTRY Redact): documentos de layout conhecido tarjados por regras, sem IA.

Um modelo diz como RECONHECER um tipo de documento (frases fixas do cabeçalho/título) e ONDE estão os dados
pessoais (campos ancorados em rótulos: "PROPRIETÁRIO:" -> o valor à direita ou abaixo). Reconhecer e tarjar não
gastam token. Depois, a inspeção (regras e, opcionalmente, um agente sobre o texto já tarjado) procura o que ficou
de fora. Nada aqui aprova o documento: a revisão humana continua obrigatória (I-02, I-11).

    schema.py   formato, validação estrita (sem regex do usuário) e pasta de modelos (PRIVIO_DOC_TEMPLATES_DIR)
    engine.py   normalização, reconhecimento, aplicação dos campos e inspeção por rótulos
    draft.py    rascunho de modelo a partir de um documento já revisado (com ajuda opcional da IA)

Contrato JSON (API /doc-templates/*): pronto para virar serviço separado, como utils/detect.
"""
import os


def enabled():
    return os.getenv("DOC_TEMPLATES", "1").strip().lower() not in ("0", "false", "nao", "não", "off", "no")


def inspection_mode():
    """agente (padrão): agente de IA lê o texto já tarjado; regras: só regras locais, zero token."""
    return "regras" if os.getenv("DOC_TEMPLATE_INSPECTION", "agente").strip().lower() == "regras" else "agente"

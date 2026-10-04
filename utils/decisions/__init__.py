# SPDX-License-Identifier: AGPL-3.0-or-later
"""Camada de decisão local (modelo de decisão calibrado, ex.: Laya) com automelhoramento.

Visão geral (detalhes em docs/decisions.md):

    detectar (regras/OCR/LLM)  ->  DECIDIR (este pacote)  ->  revisão humana  ->  tarja
                                        ^                          |
                                        +---- aprender (learning) -+   correções do revisor

Módulos:
    questions  perguntas feitas ao modelo e normalização do texto (mesma na inferência e no treino)
    engine     motores de decisão: NullEngine (desligado) e LayaEngine (carregamento preguiçoso)
    policy     regra que combina a decisão com o LLM -- o decisor NUNCA reduz proteção sozinho
    learning   exemplos rotulados, treino (calibração + limiares), portão de qualidade, versões
    feedback   transforma as correções do revisor em exemplos rotulados
    synthetic  endereços fictícios rotulados (treino inicial e conjunto fixo de avaliação)
    cli        python -m utils.decisions {status,seed,train,rollback,purge}

Tudo roda localmente. Nenhum texto de documento sai da máquina.
"""
from .engine import Decision, get_engine, reset_engine
from .policy import combine_address_decision

__all__ = ["Decision", "get_engine", "reset_engine", "combine_address_decision"]

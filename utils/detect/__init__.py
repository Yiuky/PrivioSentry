# SPDX-License-Identifier: AGPL-3.0-or-later
"""SENTRY Detect: catálogo de PII, enquadramento legal, perfis de política e detectores por regra.

Pacote isolado, sem dependência do pipeline, com entrada e saída simples (mapas de palavras e dicionários
JSON). Hoje roda dentro do processo de cada tarefa; o mesmo contrato pode virar um serviço separado no
futuro (visão SENTRY Gateway) sem mudar quem o usa. A API só de leitura está em /policy/catalog e
/policy/profiles (app_service.py).

    catalog     tipos de PII e enquadramento (LGPD, GDPR, ISO/IEC 29100, NIST SP 800-122, HIPAA Safe Harbor)
    profiles    o que tarjar/alertar em cada perfil (POLICY_PROFILE)
    rules       detectores por regra para os tipos de formato conhecido
    validators  dígitos verificadores oficiais (PIS, CNS, título de eleitor, Luhn...)
"""
from . import catalog, profiles, rules  # noqa: F401
from .profiles import ALERTAR, TARJAR, active_profile_id, get_profile, runnable_actions  # noqa: F401
from .rules import find_in_grounding  # noqa: F401

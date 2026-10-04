# SPDX-License-Identifier: AGPL-3.0-or-later
"""Proteção do serviço local contra outros sites abertos no mesmo navegador.

Sem `API_TOKEN`, o serviço confia em escutar só em 127.0.0.1. Isso não basta contra:
  * DNS rebinding: um site malicioso faz o próprio domínio apontar para 127.0.0.1 e lê as rotas
    (imagens originais sem tarja, PDFs, tarefas) como se fosse "mesma origem". Defesa: só aceitar
    requisições cujo cabeçalho Host seja um nome esperado (loopback, APP_HOST, ALLOWED_HOSTS).
  * CSRF: qualquer site dispara POST/DELETE "simples" para http://127.0.0.1:8001. Defesa: recusar
    métodos que alteram estado quando Origin (ou Sec-Fetch-Site) indica outro site.

Com `API_TOKEN` definido, o token já cobre os dois casos (o cookie é SameSite=Strict e pertence ao
host legítimo), então a checagem de Host é dispensada para permitir acesso pela rede.
"""
from __future__ import annotations

import os
from urllib.parse import urlsplit

LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
WILDCARD_HOSTS = {"", "0.0.0.0", "::"}
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def _hostname(value):
    """'Exemplo.com:8001' / '[::1]:8001' / 'http://x:1' -> nome do host em minúsculas, sem porta."""
    value = (value or "").strip()
    if not value:
        return ""
    if "://" not in value:
        value = "//" + value
    try:
        return (urlsplit(value).hostname or "").lower()
    except ValueError:
        return ""


def allowed_hosts():
    """Nomes aceitos no Host/Origin. Lido a cada chamada (o ambiente pode mudar nos testes)."""
    hosts = set(LOOPBACK_HOSTS)
    app_host = os.getenv("APP_HOST", "127.0.0.1").strip().lower()
    if app_host not in WILDCARD_HOSTS:
        hosts.add(app_host)
    extra = os.getenv("ALLOWED_HOSTS", "")
    hosts |= {h.strip().lower() for h in extra.split(",") if h.strip()}
    return hosts


def check_request(method, headers, token_enabled):
    """
    Devolve None se a requisição pode seguir, ou (status, mensagem) para recusá-la.
    headers: mapeamento com chaves em minúsculas (como o de Starlette).
    """
    if token_enabled:
        return None
    hosts = allowed_hosts()
    if "*" not in hosts and _hostname(headers.get("host")) not in hosts:
        return 421, "Host não permitido (defina ALLOWED_HOSTS para acessar por outro nome)"
    if method.upper() in UNSAFE_METHODS:
        if (headers.get("sec-fetch-site") or "").lower() == "cross-site":
            return 403, "Requisição de outro site recusada"
        origin = headers.get("origin")
        if origin and origin != "null" and "*" not in hosts and _hostname(origin) not in hosts:
            return 403, "Origem não permitida"
        if origin == "null":
            return 403, "Origem não permitida"
    return None

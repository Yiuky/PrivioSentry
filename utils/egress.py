# SPDX-License-Identifier: AGPL-3.0-or-later
"""Saída de conteúdo de documento para fora da rede local (IA externa por chave de API).

Local-first por padrão: um servidor de IA fora da máquina/rede local (OpenAI, Anthropic, Google, OpenRouter...)
só recebe conteúdo de documento com AI_ALLOW_EXTERNAL=1, ligado de propósito pelo administrador (tela Admin ou
.env). Sem isso, a chamada nem sai: vira erro, e o pipeline manda a página para revisão (falha fechado).

"Local" = loopback, IP privado/link-local, nomes sem ponto, *.localhost/.local/.lan/.internal/.intranet/.home.arpa,
ou nome que o DNS resolve SÓ para endereços privados (servidor de IA da organização na intranet). Nome que não
resolve conta como externo.

Cada processo de tarefa anota os destinos externos efetivamente chamados (record/sent): o estado final da tarefa
diz quais foram, para a interface não afirmar "Processado localmente" quando não foi.
"""
import ipaddress
import os
import socket
from functools import lru_cache
from urllib.parse import urlsplit

LOCAL_SUFFIXES = (".localhost", ".local", ".lan", ".internal", ".intranet", ".home.arpa")
_sent = set()


class ExternalBlocked(RuntimeError):
    pass


def host_of(url):
    try:
        return (urlsplit(url if "://" in str(url) else "//" + str(url)).hostname or "").lower()
    except ValueError:
        return ""


def _ip_is_local(ip):
    addr = ipaddress.ip_address(ip)
    return addr.is_loopback or addr.is_private or addr.is_link_local


@lru_cache(maxsize=64)
def _host_is_external(host):
    if not host:
        return True
    try:
        return not _ip_is_local(host)
    except ValueError:
        pass  # é um nome, não um IP
    if host == "localhost" or "." not in host or host.endswith(LOCAL_SUFFIXES):
        return False
    try:
        ips = {info[4][0].split("%")[0] for info in socket.getaddrinfo(host, None)}
    except OSError:
        return True
    return not ips or not all(_ip_is_local(ip) for ip in ips)


def is_external(url):
    return _host_is_external(host_of(url))


def external_allowed():
    return os.getenv("AI_ALLOW_EXTERNAL", "0").strip().lower() in ("1", "true", "sim", "on", "yes")


def check(url, what="servidor de IA"):
    """Levanta ExternalBlocked se o destino é externo e o administrador não liberou. Devolve True se é externo."""
    external = is_external(url)
    if external and not external_allowed():
        raise ExternalBlocked(f"{what} externo bloqueado ({host_of(url)}): o conteúdo do documento sairia desta "
                              "rede. Libere em Admin > IA (AI_ALLOW_EXTERNAL=1) ou use um servidor local.")
    return external


def record(url):
    """Anota que conteúdo de documento foi enviado a este destino externo (neste processo)."""
    if is_external(url):
        _sent.add(host_of(url))


def sent():
    return sorted(_sent)

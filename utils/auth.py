# SPDX-License-Identifier: AGPL-3.0-or-later
"""Autenticação por API_TOKEN com sessão (usada pelo app e pelo gatekeeper).

Formas aceitas quando API_TOKEN está definido:
  * cabeçalho X-API-Token: para scripts e integrações;
  * cookie de sessão: um identificador ALEATÓRIO, nunca o token. É criado ao abrir uma página uma vez
    com ?token=<token>; o servidor responde 303 para a mesma página SEM o token, assim ele não fica no
    histórico do navegador nem nos registros seguintes. O cookie é HttpOnly, SameSite=Strict e Secure
    quando a conexão é HTTPS (direta ou via proxy com X-Forwarded-Proto: https).

Cada processo guarda as próprias sessões em memória (reiniciar o serviço pede login de novo). Por isso o
app e o gatekeeper usam cookies com nomes diferentes.
"""
import os
import secrets
import time

from fastapi.responses import JSONResponse, RedirectResponse


def _ttl_seconds():
    try:
        return max(0.1, float(os.getenv("SESSION_TTL_HOURS", "12"))) * 3600
    except ValueError:
        return 12 * 3600


class TokenAuth:
    def __init__(self, cookie_name):
        self.cookie_name = cookie_name
        self._sessions = {}  # id da sessão -> instante de expiração

    def _new_session(self):
        now = time.time()
        self._sessions = {sid: exp for sid, exp in self._sessions.items() if exp > now}  # limpa as vencidas
        sid = secrets.token_urlsafe(32)
        self._sessions[sid] = now + _ttl_seconds()
        return sid

    def _valid_session(self, sid):
        exp = self._sessions.get(sid or "")
        if exp is None:
            return False
        if exp < time.time():
            self._sessions.pop(sid, None)
            return False
        return True

    @staticmethod
    def _is_https(request):
        return request.url.scheme == "https" or request.headers.get("x-forwarded-proto", "").lower() == "https"

    def check(self, request, token):
        """None = autorizado; senão a resposta a devolver (401 ou o 303 de login)."""
        if not token:
            return None
        supplied_query = request.query_params.get("token")
        if supplied_query is not None:
            if request.method == "GET" and secrets.compare_digest(supplied_query, token):
                clean = request.url.remove_query_params("token")
                target = clean.path + (f"?{clean.query}" if clean.query else "")  # só o caminho: sem redirecionamento aberto
                response = RedirectResponse(target, status_code=303)
                response.set_cookie(self.cookie_name, self._new_session(), httponly=True, samesite="strict",
                                    secure=self._is_https(request), max_age=int(_ttl_seconds()))
                return response
            return JSONResponse({"detail": "Não autorizado"}, status_code=401)
        header = request.headers.get("x-api-token")
        if header and secrets.compare_digest(header, token):
            return None
        if self._valid_session(request.cookies.get(self.cookie_name)):
            return None
        return JSONResponse({"detail": "Não autorizado"}, status_code=401)

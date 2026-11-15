# SPDX-License-Identifier: AGPL-3.0-or-later
"""Servidor MCP local do PRIVIO SENTRY (stdio, JSON-RPC 2.0): agentes de IA usam o SENTRY Redact pela API.

Uso (cliente MCP: Claude Code, Claude Desktop e afins; guia em docs/mcp.md):
    python sentry_mcp.py
    PRIVIO_URL   endereço do serviço (padrão http://127.0.0.1:8001; o app_service.py precisa estar no ar)
    API_TOKEN    o mesmo do serviço, se ele exigir

Regras (I-02, I-07): o agente envia, acompanha e baixa; quem APROVA é o revisor humano no portal.
  * Nenhuma ferramenta aprova, edita tarjas, apaga ou purga.
  * O PDF só sai com /download?final=true: depois de "Aplicar proteção" e sem pendência de revisão.
  * O que volta ao agente (e ao modelo por trás dele, talvez na nuvem) são situação, contagens, páginas a revisar e
    caminhos: nunca texto de OCR, logs, motivos dos alertas nem coordenadas de tarjas.
Sem dependência nova: o protocolo é implementado aqui (initialize, ping, tools/list, tools/call).
"""
import json
import os
import re
import sys
import time

import httpx

SUPPORTED_VERSIONS = ("2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25")
INSTRUCTIONS = ("PRIVIO SENTRY protege dados pessoais em PDFs. Fluxo: sentry_submit_pdf -> sentry_wait -> peça ao "
                "humano para revisar no link 'revisar_em' e clicar em 'Aplicar proteção' -> sentry_download_final. "
                "A detecção é probabilística: nunca diga que o documento está anonimizado sem a revisão humana.")


def _schema(props=None, required=()):
    return {"type": "object", "properties": props or {}, "required": list(required), "additionalProperties": False}


TASK_ID = {"type": "string", "description": "task_id devolvido por sentry_submit_pdf"}
TOOLS = [
    {"name": "sentry_status", "description": "Versão, fila, modos do serviço e se há IA externa ligada.",
     "inputSchema": _schema(), "annotations": {"readOnlyHint": True}},
    {"name": "sentry_profiles", "description": "Perfis de proteção (o que cada um procura) e o perfil padrão.",
     "inputSchema": _schema(), "annotations": {"readOnlyHint": True}},
    {"name": "sentry_list_documents", "description": "Documentos no serviço, com situação e pendências de revisão.",
     "inputSchema": _schema(), "annotations": {"readOnlyHint": True}},
    {"name": "sentry_submit_pdf", "description": "Envia um PDF desta máquina para detecção de dados pessoais. "
                                                 "Devolve task_id e o link do portal para a revisão humana.",
     "inputSchema": _schema({
         "caminho": {"type": "string", "description": "Caminho do PDF nesta máquina"},
         "perfil": {"type": "string", "description": "Perfil de proteção (sentry_profiles); vazio = padrão"},
         "nomes": {"type": "boolean", "description": "Procurar nomes de pessoa (se o detector estiver instalado)"},
         "baixa_qualidade": {"type": "boolean", "description": "Documento ruim: leitura extra e segundo olhar"},
     }, ["caminho"])},
    {"name": "sentry_document", "description": "Situação de um documento: progresso, páginas a revisar, tipos de "
                                               "dado encontrados (só quantidades) e se já foi aprovado.",
     "inputSchema": _schema({"task_id": TASK_ID}, ["task_id"]), "annotations": {"readOnlyHint": True}},
    {"name": "sentry_wait", "description": "Espera o processamento de um documento terminar (ou o tempo acabar).",
     "inputSchema": _schema({"task_id": TASK_ID,
                             "timeout_s": {"type": "integer", "minimum": 5, "maximum": 1800,
                                           "description": "Padrão 300"}}, ["task_id"]),
     "annotations": {"readOnlyHint": True}},
    {"name": "sentry_download_final", "description": "Salva o PDF protegido. Só funciona depois que um revisor "
                                                     "aprovou no portal ('Aplicar proteção') sem pendências.",
     "inputSchema": _schema({"task_id": TASK_ID,
                             "destino": {"type": "string", "description": "Arquivo .pdf ou pasta de destino"},
                             "sobrescrever": {"type": "boolean", "description": "Padrão false"}},
                            ["task_id", "destino"])},
]


class ToolError(Exception):
    pass


class Sentry:
    def __init__(self, base_url=None, token=None, http=None):
        self.base = (base_url or os.getenv("PRIVIO_URL") or "http://127.0.0.1:8001").rstrip("/")
        token = os.getenv("API_TOKEN", "") if token is None else token
        self.http = http or httpx.Client(base_url=self.base, timeout=120,
                                         headers={"X-API-Token": token} if token else {})
        self.sleep, self.clock = time.sleep, time.monotonic  # trocáveis nos testes

    def _req(self, method, path, **kw):
        try:
            r = self.http.request(method, path, **kw)
        except httpx.HTTPError as e:
            raise ToolError(f"Serviço PRIVIO SENTRY fora do ar em {self.base} ({type(e).__name__}). "
                            "Inicie o app_service.py ou ajuste PRIVIO_URL.")
        if r.status_code >= 400:
            try:
                detail = r.json().get("detail")
            except ValueError:
                detail = None
            raise ToolError(f"HTTP {r.status_code}: {detail if isinstance(detail, str) else 'erro do serviço'}")
        return r

    def summary(self, task_id, t):
        """O que o agente pode ver: sem texto do documento, sem motivos dos alertas, sem caminhos do servidor."""
        pages = sorted({int(m.group(1)) for a in t.get("alerts") or [] for m in [re.match(r"P[áa]g (\d+):", str(a))]
                        if m} | {int(m["page"]) for m in t.get("review_marks") or [] if isinstance(m, dict)
                                 and str(m.get("page", "")).isdigit()})
        # situação num conjunto fixo: o texto livre ("Erro: <exceção>") pode carregar caminhos do servidor
        if t.get("error"):
            state = "erro"
        elif t.get("queued") or t.get("na_fila"):
            state = "na_fila"
        elif t.get("completed"):
            state = "requer_revisao" if t.get("needs_review") else "concluido"
        elif t.get("pendente"):  # limite de uso da IA: o serviço refaz sozinho depois; não há PDF
            state = "pendente"
        else:
            state = "processando"
        return {"task_id": task_id, "arquivo": t.get("file"), "situacao": state,
                "progresso": t.get("percentage"), "concluido": bool(t.get("completed")), "erro": bool(t.get("error")),
                "na_fila": bool(t.get("queued") or t.get("na_fila")), "pendente": bool(t.get("pendente")),
                "requer_revisao": bool(t.get("needs_review")), "alertas": len(t.get("alerts") or []),
                "paginas_a_revisar": pages,
                "tipos_encontrados": {k: v for k, v in (t.get("pii_summary") or {}).items() if isinstance(v, int)},
                "perfil": (t.get("options") or {}).get("perfil") or t.get("policy_profile"),
                "aprovado_pelo_revisor": bool(t.get("finalizado")) and not t.get("needs_review"),
                "ia_externa": list(t.get("ia_externa") or []),
                "revisar_em": f"{self.base}/?task={task_id}"}

    # ------------------------------------------------------------------ ferramentas
    def sentry_status(self):
        return self._req("GET", "/api/info").json()

    def sentry_profiles(self):
        data = self._req("GET", "/policy/profiles").json()
        return {"padrao": data.get("ativo"),
                "perfis": [{"id": pid, "nome": p.get("nome"), "descricao": p.get("descricao"),
                            "procura": sorted(p.get("acoes") or {})} for pid, p in (data.get("perfis") or {}).items()]}

    def sentry_list_documents(self):
        tasks = self._req("GET", "/tasks").json()
        return {"documentos": [self.summary(tid, t) for tid, t in tasks.items()]}

    def sentry_submit_pdf(self, caminho, perfil=None, nomes=None, baixa_qualidade=None):
        path = os.path.abspath(os.path.expanduser(caminho))
        if not os.path.isfile(path) or not path.lower().endswith(".pdf"):
            raise ToolError(f"Não é um arquivo PDF existente: {path}")
        form = {k: ("sim" if v else "não") if isinstance(v, bool) else v
                for k, v in (("perfil", perfil), ("nomes", nomes), ("baixa_qualidade", baixa_qualidade))
                if v is not None and v != ""}
        with open(path, "rb") as fh:
            r = self._req("POST", "/upload", files={"file": (os.path.basename(path), fh, "application/pdf")},
                          data=form)
        tid = r.json()["task_id"]
        return {"task_id": tid, "revisar_em": f"{self.base}/?task={tid}",
                "proximo_passo": "sentry_wait; depois um humano revisa no link e clica em 'Aplicar proteção'."}

    def sentry_document(self, task_id):
        return self.summary(task_id, self._req("GET", f"/tasks/{task_id}").json())

    def sentry_wait(self, task_id, timeout_s=300, interval=2.0):
        deadline = self.clock() + max(5, min(int(timeout_s or 300), 1800))
        while True:
            info = self.sentry_document(task_id)
            if info["concluido"] or info["erro"] or info["pendente"]:  # pendente pode levar horas: não espera
                return dict(info, tempo_esgotado=False)
            if self.clock() >= deadline:
                return dict(info, tempo_esgotado=True)
            self.sleep(interval)

    def sentry_download_final(self, task_id, destino, sobrescrever=False):
        target = os.path.abspath(os.path.expanduser(destino))
        if os.path.isdir(target):
            info = self._req("GET", f"/tasks/{task_id}").json()
            stem = os.path.splitext(os.path.basename(info.get("file") or "documento.pdf"))[0]
            target = os.path.join(target, f"{stem}_PROTEGIDO.pdf")
        if not target.lower().endswith(".pdf"):
            raise ToolError("O destino precisa ser uma pasta ou um arquivo .pdf")
        if os.path.exists(target) and not sobrescrever:
            raise ToolError(f"Já existe: {target} (use sobrescrever=true)")
        try:
            r = self._req("GET", f"/download/{task_id}", params={"final": "true"})
        except ToolError as e:
            if "409" in str(e):
                raise ToolError(f"{e}. Peça ao revisor: {self.base}/?task={task_id}")
            raise
        os.makedirs(os.path.dirname(target), exist_ok=True)
        tmp = target + ".part"
        with open(tmp, "wb") as fh:
            fh.write(r.content)
        os.replace(tmp, target)
        return {"arquivo": target, "bytes": len(r.content),
                "aviso": "Detecção probabilística: o resultado foi aprovado por um revisor, não é anonimização "
                         "comprovada."}

    def call(self, name, args):
        if name not in {t["name"] for t in TOOLS}:
            raise ToolError(f"Ferramenta desconhecida: {name}")
        return getattr(self, name)(**(args or {}))


# ------------------------------------------------------------------ protocolo
def handle(sentry, msg):
    """Uma mensagem JSON-RPC -> resposta (ou None para notificações)."""
    if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0":
        return {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Requisição inválida"}}
    method, mid, params = msg.get("method"), msg.get("id"), msg.get("params") or {}
    if mid is None:
        return None  # notificação (ex.: notifications/initialized)

    def ok(result):
        return {"jsonrpc": "2.0", "id": mid, "result": result}

    if method == "initialize":
        asked = params.get("protocolVersion")
        return ok({"protocolVersion": asked if asked in SUPPORTED_VERSIONS else SUPPORTED_VERSIONS[-1],
                   "capabilities": {"tools": {"listChanged": False}},
                   "serverInfo": {"name": "privio-sentry", "title": "PRIVIO SENTRY", "version": _version()},
                   "instructions": INSTRUCTIONS})
    if method == "ping":
        return ok({})
    if method == "tools/list":
        return ok({"tools": TOOLS})
    if method == "tools/call":
        try:
            result = sentry.call(params.get("name"), params.get("arguments"))
            return ok({"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, indent=1)}],
                       "structuredContent": result, "isError": False})
        except ToolError as e:
            return ok({"content": [{"type": "text", "text": str(e)}], "isError": True})
        except TypeError as e:
            return ok({"content": [{"type": "text", "text": f"Argumentos inválidos: {e}"}], "isError": True})
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"Método desconhecido: {method}"}}


def _version():
    try:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "pyproject.toml"), encoding="utf-8") as fh:
            m = re.search(r'^version\s*=\s*"([^"]+)"', fh.read(), re.M)
        return m.group(1) if m else "?"
    except OSError:
        return "?"


def serve(stdin=None, stdout=None, sentry=None):
    if stdin is None:  # clientes MCP mandam UTF-8; no Windows o stdin em pipe viria como cp1252 ("JoÃ£o")
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    sentry = sentry or Sentry()
    for line in stdin:
        if not line.strip():
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            reply = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "JSON inválido"}}
        else:
            reply = handle(sentry, msg)
        if reply is not None:
            stdout.write(json.dumps(reply, ensure_ascii=True) + "\n")
            stdout.flush()


if __name__ == "__main__":
    serve()

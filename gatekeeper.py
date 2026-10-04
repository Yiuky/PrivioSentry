# SPDX-License-Identifier: AGPL-3.0-or-later
import os
import subprocess
import threading
import time
import httpx
import logging
import sys
import asyncio
import json
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse, PlainTextResponse
from fastapi.templating import Jinja2Templates
import uvicorn
from utils.auth import TokenAuth
from utils.net_guard import check_request
from utils.pii import install_access_log_masking, install_log_masking

# Filtro para suprimir erros de conexão resetada no Windows (Harmless WinError 10054)
class WinErrorFilter(logging.Filter):
    def filter(self, record):
        msg = record.getMessage()
        if "WinError 10054" in msg or "ConnectionResetError" in msg:
            return False
        return True

# Configuração de Log exaustiva
logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s - [GATEKEEPER] - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("Gatekeeper")

# Aplica o filtro nos loggers do uvicorn
for logger_name in ["uvicorn.error", "uvicorn.access", "Gatekeeper"]:
    l = logging.getLogger(logger_name)
    l.addFilter(WinErrorFilter())

install_log_masking()          # CPF e ?token= mascarados nos registros
install_access_log_masking()

IS_WINDOWS = os.name == 'nt'  # constante para facilitar testes
app = FastAPI(title="Gatekeeper Service")

# Rotas do próprio painel. Com API_TOKEN definido, exigem o token (cabeçalho X-API-Token ou sessão
# aberta com ?token=, ver utils/auth.py). As demais rotas são repassadas ao app, que cobra o token dele.
PANEL_PATHS = ("/gatekeeper", "/manage", "/api/")
GK_AUTH = TokenAuth("privio_gk_session")


@app.middleware("http")
async def origin_guard(request: Request, call_next):
    # O gatekeeper não tem autenticação própria e repassa tudo para o app: sem esta checagem ele seria um
    # atalho para DNS rebinding/CSRF (inclusive no /api/toggle). Para acessá-lo por outro nome, use ALLOWED_HOSTS.
    blocked = check_request(request.method, request.headers, token_enabled=False)
    if blocked:
        return JSONResponse({"detail": blocked[1]}, status_code=blocked[0])
    token = os.getenv("API_TOKEN", "")
    if token and request.url.path.startswith(PANEL_PATHS):
        denied = GK_AUTH.check(request, token)
        if denied is not None:
            return denied
    return await call_next(request)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")

# Verifica se o diretório de templates existe
if not os.path.exists(TEMPLATES_DIR):
    os.makedirs(TEMPLATES_DIR, exist_ok=True)
    logger.warning(f"Diretório de templates não existia: {TEMPLATES_DIR}")

templates = Jinja2Templates(directory=TEMPLATES_DIR)

class GlobalState:
    process = None
    app_running = False
    app_port = int(os.getenv("APP_PORT", "8001"))  # porta interna do app_service (mesmo env que ele lê)
    gatekeeper_ports = [int(os.getenv("GATEKEEPER_PORT", "8000"))]
    
    # Controle de "Desejo" do usuário
    should_run = False 
    state_file = os.getenv("GATEKEEPER_STATE_FILE") or os.path.join(BASE_DIR, ".gatekeeper_state")

    def save_state(self):
        try:
            with open(self.state_file, "w") as f:
                json.dump({"should_run": self.should_run}, f)
        except Exception as e:
            logger.error(f"Erro ao salvar estado: {e}")

    def load_state(self):
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, "r") as f:
                    data = json.load(f)
                    self.should_run = data.get("should_run", False)
            except Exception as e:
                logger.error(f"Erro ao carregar estado: {e}")

state = GlobalState()
state.load_state()

async def check_app_alive():
    """Verifica se o app está respondendo na porta interna (Assíncrono)."""
    try:
        url = f"http://127.0.0.1:{state.app_port}/tasks"
        async with httpx.AsyncClient() as client:
            response = await client.get(url, timeout=2.0)
            return response.status_code in (200, 401)  # 401 = vivo, mas exige API_TOKEN
    except Exception:
        return False

def _listening_pids(port):
    """PIDs escutando na porta (Windows, via `netstat -ano`, sem shell)."""
    output = subprocess.check_output(["netstat", "-ano"], text=True, errors="replace")
    pids = set()
    for line in output.splitlines():
        parts = line.split()
        if len(parts) >= 5 and "LISTEN" in parts[3].upper() and parts[1].rsplit(":", 1)[-1] == str(port):
            if parts[-1].isdigit():
                pids.add(parts[-1])
    return pids


def _process_command_line(pid):
    """Linha de comando do processo (Windows), ou "" se não der para ler."""
    try:
        return subprocess.check_output(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command",
             f"(Get-CimInstance Win32_Process -Filter 'ProcessId={int(pid)}').CommandLine"],
            text=True, errors="replace", timeout=10).strip()
    except Exception:
        return ""


def kill_port_owner(port):
    """
    Libera a porta do app SÓ se quem a ocupa for um app_service.py órfão (de uma execução anterior).
    Qualquer outro programa na porta é preservado; o app simplesmente não sobe e o motivo vai para o log.
    """
    if not IS_WINDOWS:
        return
    try:
        for pid in _listening_pids(port):
            if "app_service.py" in _process_command_line(pid):
                logger.info(f"Encerrando app_service.py órfão (PID {pid}) na porta {port}...")
                subprocess.call(['taskkill', '/F', '/T', '/PID', pid])
            else:
                logger.error(f"A porta {port} está em uso por outro programa (PID {pid}); ele NÃO será encerrado.")
    except Exception:
        # Sem netstat ou sem processo na porta: nada a fazer
        pass

def manage_process(action):
    try:
        if action == "start":
            state.should_run = True
            state.save_state()
            
            if state.process is None or state.process.poll() is not None:
                kill_port_owner(state.app_port)
                
                logger.info(f"Iniciando app_service.py na porta {state.app_port}...")
                state.process = subprocess.Popen(
                    [sys.executable, os.path.join(BASE_DIR, "app_service.py")],
                    # Saída herdada (console do gatekeeper): um PIPE que ninguém lê enche e trava o app (B-52)
                    stdout=None,
                    stderr=None,
                    text=True,
                    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if IS_WINDOWS else 0
                )
                time.sleep(1) # Pequena pausa para o processo subir
                state.app_running = True
        elif action == "stop":
            state.should_run = False
            state.save_state()
            
            if state.process:
                logger.info("Encerrando app_service.py...")
                if IS_WINDOWS:
                    subprocess.call(['taskkill', '/F', '/T', '/PID', str(state.process.pid)])
                else:
                    state.process.terminate()
                state.process = None
                state.app_running = False
    except Exception as e:
        logger.error(f"Erro ao gerenciar processo: {e}")

async def watchdog_task():
    """Background task para manter o serviço rodando se o usuário assim desejar."""
    logger.info("Watchdog do Gatekeeper iniciado.")
    consecutive_failures = 0
    while True:
        try:
            if state.should_run:
                # 1. Verifica se o processo OS ainda existe
                proc_dead = state.process is None or state.process.poll() is not None
                
                # 2. Verifica se o app responde HTTP
                alive = await check_app_alive()
                
                if proc_dead or not alive:
                    consecutive_failures += 1
                    if proc_dead:
                        logger.warning("Processo app_service.py não encontrado. Reiniciando via Watchdog...")
                        manage_process("start")
                        consecutive_failures = 0
                    elif consecutive_failures >= 3:
                        logger.warning(f"App não responde na porta {state.app_port} há 3 tentativas. Forçando reinício...")
                        manage_process("start")
                        consecutive_failures = 0
                else:
                    consecutive_failures = 0
                    state.app_running = True
            
        except Exception as e:
            logger.error(f"Erro no loop do Watchdog: {e}")
        
        await asyncio.sleep(10)

@app.on_event("startup")
async def startup_event():
    # Inicia o Watchdog
    asyncio.create_task(watchdog_task())
    
    # Se o estado salvo for True, tenta iniciar o serviço
    if state.should_run:
        logger.info("[STARTUP] Restaurando serviço SENTRY Redact...")
        manage_process("start")

@app.get("/api/status")
async def get_status():
    if state.process and state.process.poll() is not None:
        state.app_running = False
        state.process = None
    
    state.app_running = await check_app_alive()
    return {"app_running": state.app_running, "should_run": state.should_run}

@app.post("/api/toggle")
async def toggle_service(request: Request):
    try:
        data = await request.json()
        action = data.get("action")
        manage_process(action)
        return {"status": "ok", "app_running": state.app_running}
    except Exception as e:
        logger.error(f"Erro no toggle: {e}")
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)

async def proxy_handler(request: Request):
    if not state.app_running:
        return safe_template_response(request, "gatekeeper.html")

    url = httpx.URL(str(request.url))
    target_url = f"http://127.0.0.1:{state.app_port}{url.path}"
    if url.query:
        # httpx.URL.query é bytes: interpolar direto geraria "?b'a=1'" e perderia os parâmetros.
        target_url += "?" + url.query.decode("utf-8")

    async with httpx.AsyncClient() as client:
        content = await request.body()
        headers = dict(request.headers)
        headers.pop("host", None)
        headers.pop("content-length", None)
        
        try:
            proxy_res = await client.request(
                method=request.method,
                url=target_url,
                headers=headers,
                content=content,
                timeout=30.0
            )
            # aiter_bytes() entrega o corpo JÁ descompactado: repassar content-encoding/length/
            # transfer-encoding do upstream corromperia a resposta no cliente.
            headers_out = {k: v for k, v in proxy_res.headers.items()
                           if k.lower() not in ("content-encoding", "content-length", "transfer-encoding", "connection")}
            return StreamingResponse(
                proxy_res.aiter_bytes(),
                status_code=proxy_res.status_code,
                headers=headers_out
            )
        except Exception as e:
            logger.error(f"Erro no Proxy para {target_url}: {e}")
            state.app_running = False
            return safe_template_response(request, "gatekeeper.html")

@app.get("/gatekeeper", response_class=HTMLResponse)
@app.get("/manage", response_class=HTMLResponse)
async def management_page(request: Request):
    return safe_template_response(request, "gatekeeper.html")

def safe_template_response(request, name):
    try:
        return templates.TemplateResponse(request=request, name=name)
    except Exception as e:
        logger.error(f"Erro ao renderizar template {name}: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return PlainTextResponse(f"Erro Interno: Template {name} falhou. {e}", status_code=500)

@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    if await check_app_alive():
        state.app_running = True
        return await proxy_handler(request)
    else:
        state.app_running = False
        return safe_template_response(request, "gatekeeper.html")

@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def catch_all(request: Request, path: str):
    # Ignora chamadas para a própria API do gatekeeper
    if path.startswith("api/") or path == "gatekeeper" or path == "manage":
        return PlainTextResponse("Not Found", status_code=404)
        
    if await check_app_alive():
        state.app_running = True
        return await proxy_handler(request)
    else:
        state.app_running = False
        return safe_template_response(request, "gatekeeper.html")

def run_gatekeeper(port):
    try:
        config = uvicorn.Config(app, host=os.getenv("APP_HOST", "127.0.0.1"), port=port, log_level="info")
        server = uvicorn.Server(config)
        server.run()
    except Exception as e:
        logger.error(f"Erro ao iniciar servidor na porta {port}: {e}")

if __name__ == "__main__":
    # Se houver apenas uma porta, rodamos no processo principal para melhor sinalização
    if len(state.gatekeeper_ports) == 1:
        run_gatekeeper(state.gatekeeper_ports[0])
    else:
        threads = []
        for p in state.gatekeeper_ports:
            t = threading.Thread(target=run_gatekeeper, args=(p,), daemon=True)
            t.start()
            threads.append(t)
        
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("Encerrando Gatekeeper...")
            manage_process("stop")

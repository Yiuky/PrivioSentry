# SPDX-License-Identifier: AGPL-3.0-or-later
import os
import sys
import re
import uuid
import secrets
import multiprocessing
import json
import logging
import shutil
import threading
import time
from datetime import datetime, timedelta
import httpx
from fastapi import FastAPI, UploadFile, File, Form, BackgroundTasks, HTTPException, Body, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from main import LimitPending, SentryApp
from utils.pii import install_access_log_masking, install_log_masking
from utils.auth import TokenAuth
from utils.net_guard import check_request
from dotenv import load_dotenv
load_dotenv()
from utils import ratelimit
from utils import settings as admin_settings
admin_settings.apply()  # valores salvos na tela Admin valem sobre o .env (utils/settings.py)
admin_settings.mark_startup()

# Configuração de Log própria do App
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
install_log_masking()  # LGPD: nenhum CPF completo em log (root + handlers do app)
install_access_log_masking()  # uvicorn: CPF e ?token= mascarados nos registros de acesso
app_logger = logging.getLogger("AppTarjadorService")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def app_version():
    try:
        with open(os.path.join(BASE_DIR, "pyproject.toml"), encoding="utf-8") as fh:
            match = re.search(r'^version\s*=\s*"([^"]+)"', fh.read(), re.M)
        return match.group(1) if match else "?"
    except OSError:
        return "?"


# /docs e /redoc do FastAPI carregam scripts de CDN (I-04): desligados. O contrato fica em /openapi.json e docs/api.md.
app = FastAPI(title="PRIVIO SENTRY Service", version=app_version(), docs_url=None, redoc_url=None)


def _flag_env(name, default="1"):
    return os.getenv(name, default).strip().lower() not in ("0", "false", "nao", "não", "off", "no")


def portal_enabled():
    """PORTAL_ENABLED=0: só API (sem a interface web)."""
    return _flag_env("PORTAL_ENABLED")


def admin_enabled():
    """ADMIN_ENABLED=0: sem a tela nem a API de Administração (configuração só pelo .env)."""
    return _flag_env("ADMIN_ENABLED")

# Configuration
INPUT_DIR = os.getenv("PRIVIO_INPUT_DIR") or os.path.join(BASE_DIR, "WEB_INPUT")
OUTPUT_DIR = os.getenv("PRIVIO_OUTPUT_DIR") or os.path.join(BASE_DIR, "output")
FINAL_DIR = os.getenv("PRIVIO_FINAL_DIR") or os.path.join(BASE_DIR, "documentos_finais")
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
TASKS_FILE = os.getenv("PRIVIO_TASKS_FILE") or os.path.join(BASE_DIR, "tasks.json")

APP_HOST = os.getenv("APP_HOST", "127.0.0.1")
APP_PORT = int(os.getenv("APP_PORT", "8001"))
API_TOKEN = os.getenv("API_TOKEN", "")  # Se definido, exigido em todas as rotas (exceto /internal)
if API_TOKEN.startswith("troque-por"):  # o valor de exemplo de deploy/k8s/secrets.env.example é público
    raise SystemExit("API_TOKEN ainda é o valor de exemplo: gere um token (python -c \"import secrets; "
                     "print(secrets.token_urlsafe(32))\") e troque no secrets.env/.env.")
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_MB", "500")) * 1024 * 1024


def _env_days(name):
    try:
        return max(0.0, float(os.getenv(name, "0") or 0))
    except ValueError:
        return 0.0


# Retenção opcional: tarefas mais antigas que N dias são apagadas (com todos os artefatos) no startup. 0 = desligado.
RETENTION_DAYS = _env_days("RETENTION_DAYS")
UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")

os.makedirs(INPUT_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(FINAL_DIR, exist_ok=True)
os.makedirs(TEMPLATES_DIR, exist_ok=True)

# Templates
templates = Jinja2Templates(directory=TEMPLATES_DIR)

# Segredo compartilhado com os workers (gerado a cada subida; passado por argumento,
# pois no Windows o processo filho reimporta o módulo e geraria outro valor).
INTERNAL_SECRET = secrets.token_hex(16)

# Lock de IA compartilhado entre PROCESSOS (threading.Lock não cruza processos).
AI_LOCK = multiprocessing.Lock()

# Processos de worker ativos, por task_id
procs = {}

# Global task storage
tasks_lock = threading.RLock()

def load_tasks():
    if os.path.exists(TASKS_FILE):
        try:
            with open(TASKS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            app_logger.error(f"Erro ao ler tasks.json (iniciando vazio): {e}")
    return {}

def save_tasks():
    """Escrita atômica: arquivo temporário + os.replace."""
    with tasks_lock:
        tmp_path = TASKS_FILE + ".tmp"
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(tasks, f, indent=4, ensure_ascii=False)
            os.replace(tmp_path, TASKS_FILE)
        except Exception as e:
            app_logger.error(f"Erro ao salvar tasks.json: {e}")

tasks = load_tasks()

def reconcile_interrupted_tasks():
    """Tarefas que estavam em andamento quando o serviço caiu não têm mais processo."""
    changed = False
    for t in tasks.values():
        if not t.get("completed") and not t.get("error") and not t.get("pendente"):  # pendente: a fila retoma
            t["status"] = "Interrompido"
            t["error"] = True
            changed = True
    if changed:
        save_tasks()

def final_pdf_path(task):
    return os.path.join(FINAL_DIR, f"{task_base(task)}_TARJADO_FINAL.pdf")

def _is_within(base, path):
    """True se 'path' está dentro de 'base' (resolvendo symlinks/..)."""
    try:
        base_r = os.path.realpath(base)
        return os.path.commonpath([base_r, os.path.realpath(path)]) == base_r
    except ValueError:
        return False

def _remove_path(path, base, removed, errors):
    """Remove arquivo/pasta SOMENTE se estiver dentro de 'base'; acumula resultado."""
    if not os.path.lexists(path):
        return
    if not _is_within(base, path):
        # tasks.json adulterado/antigo: NUNCA apaga fora da área de trabalho; só registra.
        app_logger.warning(f"Ignorando caminho fora da área permitida: {os.path.basename(path)}")
        return
    try:
        if os.path.isdir(path) and not os.path.islink(path):
            shutil.rmtree(path)
        else:
            os.remove(path)
        removed.append(os.path.relpath(path, base))
    except Exception as e:
        errors.append(f"{os.path.basename(path)}: {e}")

def remove_task_artifacts(task):
    """Apaga TUDO que a tarefa gerou: pasta output/<nome>, PDF de entrada e PDF final (LGPD)."""
    removed, errors = [], []
    _remove_path(os.path.join(OUTPUT_DIR, task_base(task)), OUTPUT_DIR, removed, errors)
    _remove_path(task.get("input_path", ""), INPUT_DIR, removed, errors)
    _remove_path(final_pdf_path(task), FINAL_DIR, removed, errors)
    try:  # exemplos de treino do decisor local vindos desta tarefa (só existem com LEARNING_ENABLED=1)
        from utils.decisions.learning import LearningStore
        if LearningStore().remove_task(task_base(task)):
            removed.append("learning/examples (desta tarefa)")
    except Exception as e:
        errors.append(f"learning: {e}")
    return removed, errors

# Pastas de trabalho com imagens/recortes/respostas SEM tarja (ou parcialmente tarjadas).
# Mantidos: 05_final_export/combined e 05_phase_5_export (já tarjadas), logs e metadados .json/.txt.
PURGE_DIRS = (
    "00_original_images", "01_ocr_results", "02_signature_crops", "04_signatures_crops_ia",
    "04_signatures_crops_tarjados", "04_micro_audit_results", "06_final_enhanced",
    "07_addresses_crops_ia", "08_addresses_crops_tarjados", "99_ia_interactions",
    os.path.join("05_final_export", "cpf_only"), os.path.join("05_final_export", "address_only"),
    "decisions.json",  # texto (minimizado) dos endereços avaliados pelo decisor local
)

def purge_task_originals(task, include_input=False):
    """Remove as imagens originais sem tarja e intermediários, mantendo o PDF final e os metadados."""
    removed, errors = [], []
    base = os.path.join(OUTPUT_DIR, task_base(task))
    for name in PURGE_DIRS:
        _remove_path(os.path.join(base, name), OUTPUT_DIR, removed, errors)
    if include_input:
        _remove_path(task.get("input_path", ""), INPUT_DIR, removed, errors)
    return removed, errors

def sweep_retention(now=None):
    """Apaga tarefas (e artefatos) mais antigas que RETENTION_DAYS. Retorna os ids removidos."""
    if RETENTION_DAYS <= 0:
        return []
    limit = (now or datetime.now()) - timedelta(days=RETENTION_DAYS)
    expired = []
    for tid, t in list(tasks.items()):
        try:
            created = datetime.fromisoformat(t.get("created_at", ""))
        except (TypeError, ValueError):
            continue  # sem data confiável: não apaga
        if created < limit and not is_running(tid):
            expired.append(tid)
    deleted = []
    for tid in expired:
        _, errors = remove_task_artifacts(tasks[tid])
        if errors:
            app_logger.error(f"Retenção: falha ao apagar artefatos de {tid}: {errors}")
            continue
        with tasks_lock:
            tasks.pop(tid, None)
        deleted.append(tid)
    if deleted:
        save_tasks()
        app_logger.info(f"Retenção ({RETENTION_DAYS:g} dia(s)): {len(deleted)} tarefa(s) apagada(s).")
    return deleted

def startup_maintenance():
    """Só no processo principal: workers (spawn) reimportam este módulo e NÃO podem reconciliar/varrer."""
    if multiprocessing.current_process().name != "MainProcess":
        return
    reconcile_interrupted_tasks()
    sweep_retention()
    if any(t.get("pendente") for t in tasks.values()):
        _ensure_dispatcher()

def get_task(task_id: str):
    """Valida o formato do id (evita path traversal) e devolve a tarefa."""
    if not UUID_RE.match(task_id) or task_id not in tasks:
        raise HTTPException(status_code=404, detail="Tarefa não encontrada")
    return tasks[task_id]

def task_base(task):
    return os.path.splitext(os.path.basename(task["input_path"]))[0]

def is_running(task_id: str) -> bool:
    p = procs.get(task_id)
    return p is not None and p.is_alive()

def require_input(task):
    if not os.path.exists(task["input_path"]):
        raise HTTPException(status_code=409, detail="O PDF de entrada não existe mais (removido). Envie o arquivo novamente.")

# Fila: no máximo MAX_PARALLEL_TASKS documentos processando ao mesmo tempo. Sem limite, cada upload abria um
# processo com OCR em paralelo + modelos (nomes, decisor): vários uploads de uma vez esgotavam memória e CPU.
MAX_PARALLEL_TASKS = max(1, int(os.getenv("MAX_PARALLEL_TASKS", "2") or 2))
task_queue = []  # [(task_id, manual_redactions, native_mode)], na ordem de chegada
queue_lock = threading.RLock()
_dispatcher = None


def running_count():
    return sum(1 for p in procs.values() if p.is_alive())


def is_queued(task_id):
    with queue_lock:
        return any(q[0] == task_id for q in task_queue)


def dequeue(task_id):
    """Tira a tarefa da fila (ao apagar). Devolve True se ela estava na fila."""
    with queue_lock:
        before = len(task_queue)
        task_queue[:] = [q for q in task_queue if q[0] != task_id]
        return len(task_queue) != before


def _spawn(task_id, manual_redactions, native_mode):
    task = tasks[task_id]
    task.pop("queued", None)
    task.pop("pendente", None)  # qualquer início de worker encerra a espera (a fila não refaz por cima)
    task.pop("pendente_ate", None)
    p = multiprocessing.Process(
        target=redaction_worker,
        args=(task_id, task["input_path"], manual_redactions, native_mode, APP_PORT, INTERNAL_SECRET, AI_LOCK,
              task.get("options")),
        # teto de retomadas: a última roda como hoje (página sem IA vai para revisão), nunca fica pendente para sempre
        kwargs={"no_pending": int(task.get("pendente_tentativas") or 0) >= ratelimit.max_resumes()},
    )
    p.start()
    procs[task_id] = p


def dispatch_queue():
    """Inicia as próximas tarefas da fila enquanto houver vaga. Devolve quantas iniciou."""
    started = 0
    with queue_lock:
        while task_queue and running_count() < MAX_PARALLEL_TASKS:
            task_id, manual_redactions, native_mode = task_queue.pop(0)
            task = tasks.get(task_id)
            if task is None:
                continue
            if not os.path.exists(task["input_path"]):  # PDF removido enquanto esperava: erro visível, não silêncio
                task.pop("queued", None)
                task.update(status="Erro: PDF de entrada removido enquanto aguardava na fila.", error=True)
                continue
            _spawn(task_id, manual_redactions, native_mode)
            started += 1
    if started:
        save_tasks()
    return started


def _ensure_dispatcher():
    global _dispatcher
    if _dispatcher is not None and _dispatcher.is_alive():
        return

    def loop():
        while True:
            time.sleep(1)
            try:
                dispatch_queue()
                resume_pending()
            except Exception as e:  # a fila nunca pode morrer em silêncio
                app_logger.error(f"Fila de tarefas: {e}")
    _dispatcher = threading.Thread(target=loop, name="fila-tarefas", daemon=True)
    _dispatcher.start()


def mark_pending(task):
    """Limite de uso da IA com AI_LIMIT_ACTION=pendente: nenhum PDF; a fila refaz o documento depois."""
    task.update(status="Pendente: limite de uso da IA", percentage=0, completed=False, error=False,
                needs_review=False, pendente=True, pendente_ate=time.time() + ratelimit.retry_minutes() * 60,
                pendente_tentativas=int(task.get("pendente_tentativas") or 0) + 1)
    _ensure_dispatcher()


def resume_pending(now=None):
    """Refaz do início os documentos pendentes cujo prazo chegou. Devolve quantos retomou."""
    now = time.time() if now is None else now
    count = 0
    for tid, task in list(tasks.items()):
        if (task.get("pendente") and not task.get("completed") and now >= float(task.get("pendente_ate") or 0)
                and not is_running(tid) and not is_queued(tid)):
            reset_task_state(task, "Retomando...")
            try:
                start_worker(tid)
                count += 1
            except HTTPException as e:  # ex.: PDF de entrada removido
                task.update(status=f"Erro: {e.detail}", error=True)
    if count:
        save_tasks()
    return count


def start_worker(task_id, manual_redactions=None, native_mode=False):
    """Inicia o worker da tarefa (ou a põe na fila se já houver MAX_PARALLEL_TASKS rodando); 409 se já estiver
    rodando ou na fila."""
    if is_running(task_id) or is_queued(task_id):
        raise HTTPException(status_code=409, detail="Tarefa já está em execução ou na fila.")
    task = tasks[task_id]
    require_input(task)
    with queue_lock:
        if running_count() >= MAX_PARALLEL_TASKS:
            task_queue.append((task_id, manual_redactions, native_mode))
            task["queued"] = True
            task["status"] = f"Na fila ({len(task_queue)}º)"
            _ensure_dispatcher()
            return
        _spawn(task_id, manual_redactions, native_mode)

def sanitize_filename(name: str) -> str:
    name = os.path.basename((name or "").replace("\\", "/"))
    name = re.sub(r"[^\w\s.\-()°]", "_", name, flags=re.UNICODE).strip(" .")
    if len(name) > 150:
        stem, ext = os.path.splitext(name)
        name = stem[:150 - len(ext)] + ext
    return name or "documento.pdf"

startup_maintenance()  # após todas as definições acima (usa is_running/task_base)

AUTH = TokenAuth("privio_session")


@app.middleware("http")
async def token_guard(request: Request, call_next):
    # Sem token: só aceita Host esperado (anti DNS rebinding) e recusa POST/DELETE de outros sites (anti CSRF).
    # /internal/ fica de fora: os workers chamam por 127.0.0.1 e são autenticados pelo segredo interno.
    # /healthz: sem dado nenhum; a sonda do Kubernetes chega com o IP do pod no Host (seria 421)
    if not request.url.path.startswith("/internal/") and request.url.path != "/healthz":
        blocked = check_request(request.method, request.headers, token_enabled=bool(API_TOKEN))
        if blocked:
            return JSONResponse({"detail": blocked[1]}, status_code=blocked[0])
    if API_TOKEN and not request.url.path.startswith("/internal/") and request.url.path != "/healthz":
        # Cabeçalho X-API-Token ou sessão aleatória (o token nunca vai para o cookie). Ver utils/auth.py.
        denied = AUTH.check(request, API_TOKEN)
        if denied is not None:
            return denied
    return await call_next(request)

def redaction_worker(task_id: str, file_path: str, manual_redactions=None, native_mode=False,
                     api_port=8001, internal_secret="", ai_lock=None, options=None, no_pending=False):
    """
    Motor do SENTRY Redact executado em um PROCESSO SEPARADO (Multi-Core).
    options: escolhas da interface para ESTE documento (utils/task_options.py), aplicadas só neste processo.
    """
    from utils.task_options import apply_to_environment
    apply_to_environment(options)
    ratelimit.allow_pending(not no_pending)  # só o processo de um documento pode ficar pendente
    if ai_lock is not None:
        import utils.ai_client as ai_client
        ai_client.ollama_lock = ai_lock
        ratelimit.lock = ai_lock  # a vez de cada pedido é reservada com a mesma trava entre processos

    def progress_callback(data):
        try:
            # Notifica o processo principal sobre o progresso via HTTP local
            with httpx.Client(timeout=10.0) as client:
                client.post(f"http://127.0.0.1:{api_port}/internal/update/{task_id}", json=data,
                            headers={"X-Internal-Secret": internal_secret})
        except Exception as e:
            print(f"[Worker Task {task_id}] Erro ao reportar progresso: {e}")

    try:
        pipeline = SentryApp(file_path, output_dir=OUTPUT_DIR, final_dir=FINAL_DIR)
        pipeline.run(progress_callback=progress_callback, manual_redactions=manual_redactions, native_mode=native_mode)

        # Conclusão final redundante para garantir estado. "finalizado" = PDF gerado com as tarjas do revisor
        # ("Aplicar proteção"); o PDF do processamento automático é preliminar.
        state = pipeline.final_state()
        state["finalizado"] = manual_redactions is not None
        progress_callback(state)
    except LimitPending:
        progress_callback({"pendente": True})
    except Exception as e:
        progress_callback({"status": f"Erro: {str(e)}", "error": True})

@app.post("/internal/update/{task_id}")
async def internal_update(task_id: str, request: Request, data: dict = Body(...)):
    """API Interna para receber atualizações do worker em outro processo."""
    supplied = request.headers.get("x-internal-secret", "")
    if not secrets.compare_digest(supplied, INTERNAL_SECRET):
        raise HTTPException(status_code=403, detail="Segredo interno inválido")
    if task_id in tasks:
        with tasks_lock:
            if data.get("pendente"):
                mark_pending(tasks[task_id])
            else:
                tasks[task_id].update(data)
                if "alerts" in data and data["alerts"]:
                    tasks[task_id]["alerts"] = data["alerts"]
            save_tasks()
    return {"status": "ok"}

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    if not portal_enabled():
        return JSONResponse({"servico": "PRIVIO SENTRY", "portal": False, "api": "/openapi.json",
                             "info": "/api/info"})
    return templates.TemplateResponse(request=request, name="index.html")


@app.get("/healthz")
def healthz():
    """Vivo? Sem token e sem nenhum dado (healthcheck do Docker, balanceadores)."""
    return {"ok": True}


def external_ai_now():
    """Servidores de IA externos que o próximo documento usaria (vazio = tudo local ou externo bloqueado)."""
    from utils import egress, second_look
    from utils.ai_client import configured_backends
    urls = [b.base_url for b in configured_backends()]
    if second_look.enabled():
        urls.append(second_look._endpoint())
    if not egress.external_allowed():
        return []
    return sorted({egress.host_of(u) for u in urls if egress.is_external(u)})


@app.get("/api/info")
def api_info():
    """Para clientes da API, agentes e para a interface: versão, modos e se há IA externa ligada."""
    return {"servico": "PRIVIO SENTRY", "produto": "SENTRY Redact", "versao": app_version(),
            "portal": portal_enabled(), "admin": admin_enabled(), "token_exigido": bool(API_TOKEN),
            "ia_externa": external_ai_now(),
            "fila": {"rodando": running_count(), "na_fila": len(task_queue), "maximo": MAX_PARALLEL_TASKS},
            "documentacao": {"openapi": "/openapi.json", "guia": "docs/api.md", "mcp": "docs/mcp.md"}}

@app.get("/options")
def get_options():
    """Opções por documento para a interface: perfis, padrões e o que está instalado (com o motivo do que não está)."""
    from utils.task_options import catalog
    return catalog()


@app.get("/health/ai")
def ai_health():
    """Servidores de IA configurados (sem chaves), disjuntor e teste de saúde pela API de cada um."""
    from utils.ai_client import AIClient
    return AIClient().health(live=True)


@app.get("/policy/catalog")
async def policy_catalog():
    """Catálogo de tipos de PII e enquadramento legal (sem nenhum dado pessoal)."""
    from utils.detect import catalog
    return {"tipos": [t.to_dict() for t in catalog.CATALOG]}

@app.get("/policy/profiles")
async def policy_profiles():
    """Perfis de política e o perfil ativo (POLICY_PROFILE)."""
    from utils.detect import profiles
    return {"ativo": profiles.active_profile_id(), "perfis": profiles.describe_all()}

@app.get("/readme")
async def readme():
    path = os.path.join(BASE_DIR, "README.md")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return {"content": f.read()}
    except Exception:
        raise HTTPException(status_code=404, detail="README não encontrado")

@app.post("/upload")
async def upload_file(background_tasks: BackgroundTasks, file: UploadFile = File(...), force: bool = False,
                      perfil: str = Form(None), nomes: str = Form(None), baixa_qualidade: str = Form(None)):
    from utils.task_options import OptionsError, resolve
    try:  # o servidor valida as opções (a interface só ajuda)
        options = resolve(perfil, nomes, baixa_qualidade)
    except OptionsError as e:
        raise HTTPException(status_code=400, detail=str(e))
    clean_name = sanitize_filename(file.filename)
    if not clean_name.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Apenas arquivos PDF são permitidos.")

    if file.file.read(5) != b"%PDF-":
        raise HTTPException(status_code=400, detail="O arquivo não é um PDF válido.")
    file.file.seek(0)

    task_id = str(uuid.uuid4())
    file_path = os.path.join(INPUT_DIR, f"{task_id}_{clean_name}")

    written = 0
    try:
        with open(file_path, "wb") as buffer:
            while True:
                chunk = file.file.read(1024 * 1024)
                if not chunk:
                    break
                written += len(chunk)
                if written > MAX_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail="Arquivo excede o tamanho máximo permitido.")
                buffer.write(chunk)
    except HTTPException:
        if os.path.exists(file_path):
            os.remove(file_path)
        raise

    from datetime import datetime
    with tasks_lock:
        tasks[task_id] = {
            "file": clean_name,
            "input_path": file_path,
            "created_at": datetime.now().isoformat(),
            "status": "Iniciando...",
            "percentage": 0,
            "completed": False,
            "error": False,
            "alerts": [],
            "options": options,
        }
        save_tasks()

    # Inicia Processo Separado (Multi-Core)
    start_worker(task_id)

    return {"status": "started", "task_id": task_id}

PRIVATE_TASK_FIELDS = ("input_path",)  # caminho no disco do servidor: não interessa a clientes da API


def public_task(task):
    return {k: v for k, v in task.items() if k not in PRIVATE_TASK_FIELDS}


@app.get("/tasks")
async def get_tasks():
    return {tid: public_task(t) for tid, t in tasks.items()}


@app.get("/tasks/{task_id}")
async def get_one_task(task_id: str):
    task = get_task(task_id)
    return dict(public_task(task), task_id=task_id, rodando=is_running(task_id), na_fila=is_queued(task_id),
                pdf_disponivel=os.path.exists(final_pdf_path(task)))

def reset_task_state(task, status):
    task["status"] = status
    task["percentage"] = 0
    task["completed"] = False
    task["error"] = False
    task["needs_review"] = False
    task["alerts"] = []
    task["review_marks"] = []
    task["finalizado"] = False
    task.pop("ia_externa", None)  # o novo processamento informa de novo, se usar IA externa
    task.pop("pendente", None)
    task.pop("pendente_ate", None)
    task.pop("purged", None)  # reprocessar regenera as imagens

@app.post("/reprocess/{task_id}")
async def reprocess_task(task_id: str):
    task = get_task(task_id)
    if is_running(task_id):
        raise HTTPException(status_code=409, detail="Tarefa já está em execução.")
    require_input(task)  # antes de alterar o estado (evita tarefa presa em "Reiniciando...")
    reset_task_state(task, "Reiniciando...")
    task.pop("pendente_tentativas", None)  # pedido de uma pessoa: a contagem de retomadas recomeça
    save_tasks()
    start_worker(task_id)
    return {"status": "restarted"}

@app.get("/logs/{task_id}")
async def get_logs(task_id: str):
    if not UUID_RE.match(task_id) or task_id not in tasks: return {"log": "Tarefa não encontrada."}
    task = tasks[task_id]
    log_path = os.path.join(OUTPUT_DIR, task_base(task), "process_log.log")
    if os.path.exists(log_path):
        try:
            with open(log_path, "r", encoding="utf-8") as f:
                return {"log": f.read()}
        except Exception: return {"log": "Erro ao ler as linhas de log."}
    return {"log": "Nenhum log encontrado."}

@app.post("/process-all")
async def process_all():
    count = 0
    for tid, t in tasks.items():
        if (t["status"] == "Aguardando" or t.get("error") or t.get("pendente")) and not is_running(tid):
            was_error = t.get("error")
            t["error"] = False
            try:
                start_worker(tid)
                t.pop("pendente", None)  # retomado agora, sem esperar o prazo
            except HTTPException as e:  # ex.: PDF de entrada removido; não derruba o lote
                t["error"] = was_error
                app_logger.warning(f"process-all: tarefa {tid} ignorada ({e.detail})")
                continue
            count += 1
    save_tasks()
    return {"status": "started", "count": count}

@app.delete("/delete-all")
async def delete_all():
    if any(is_running(tid) for tid in tasks):
        raise HTTPException(status_code=409, detail="Há tarefas em execução.")
    with queue_lock:
        task_queue.clear()
    if any(is_running(tid) for tid in tasks):
        raise HTTPException(status_code=409, detail="Há tarefas em execução.")
    failures = []
    with tasks_lock:
        for tid in list(tasks):
            _, errors = remove_task_artifacts(tasks[tid])
            if errors:  # mantém a tarefa: arquivos com PII ainda existem
                failures.append({"task_id": tid, "errors": errors})
            else:
                del tasks[tid]
        save_tasks()
    if failures:
        raise HTTPException(status_code=500, detail={"msg": "Falha ao apagar artefatos de algumas tarefas.", "failures": failures})
    return {"status": "deleted_all"}

@app.get("/previews/{task_id}/{page}")
def get_preview(task_id: str, page: int):
    task = get_task(task_id)
    filename_base = task_base(task)
    preview_path = os.path.join(OUTPUT_DIR, filename_base, "00_original_images", f"{filename_base}_page_{page}.png")
    if not os.path.exists(preview_path):
        preview_path = os.path.join(OUTPUT_DIR, filename_base, "05_final_export", "combined", f"page_{page}_REDACTED.jpg")
    if not os.path.exists(preview_path):
        raise HTTPException(status_code=404, detail="Imagem não encontrada")
    return FileResponse(preview_path)

def read_redactions(task):
    """Tarjas manuais (editor) têm prioridade sobre as da IA."""
    filename_base = task_base(task)
    for name in ("manual_redactions.json", "redactions_metadata.json"):
        path = os.path.join(OUTPUT_DIR, filename_base, name)
        if os.path.exists(path):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                app_logger.error(f"Erro ao ler {path}: {e}")
    return []

@app.get("/metadata/{task_id}")
def get_metadata(task_id: str):
    task = get_task(task_id)
    return {"redactions": read_redactions(task)}

@app.post("/update-redactions/{task_id}")
async def update_redactions(task_id: str, redactions: list = Body(...)):
    task = get_task(task_id)
    metadata_path = os.path.join(OUTPUT_DIR, task_base(task), "manual_redactions.json")
    try:
        with open(metadata_path, 'w', encoding='utf-8') as f:
            json.dump(redactions, f, indent=2)
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/reprocess-metadata/{task_id}")
async def reset_to_ai_metadata(task_id: str):
    task = get_task(task_id)
    metadata_path = os.path.join(OUTPUT_DIR, task_base(task), "manual_redactions.json")
    if os.path.exists(metadata_path):
        os.remove(metadata_path)
    return {"status": "success"}

def finalize(task_id: str, native_mode: bool):
    task = get_task(task_id)
    if is_running(task_id):
        raise HTTPException(status_code=409, detail="Tarefa já está em execução.")
    if task.get("pendente"):  # a análise parou no meio: não há o que aprovar
        raise HTTPException(status_code=409, detail="Documento pendente (limite de uso da IA): aguarde a nova "
                                                    "tentativa ou use Reprocessar.")
    if task.get("purged") and not native_mode:
        raise HTTPException(status_code=409, detail="Imagens originais foram removidas (purge); use o retarjamento nativo.")
    require_input(task)
    task["status"] = "Gerando PDF Nativo..." if native_mode else "Gerando PDF Final..."
    task["percentage"] = 90
    task["completed"] = False
    task["error"] = False
    task["finalizado"] = False
    save_tasks()
    start_worker(task_id, manual_redactions=read_redactions(task), native_mode=native_mode)
    return {"status": "started"}

@app.post("/finalize-native/{task_id}")
async def finalize_native_task(task_id: str):
    return finalize(task_id, native_mode=True)

@app.post("/finalize/{task_id}")
async def finalize_legacy_task(task_id: str):
    """Finalização legada: reconstrói o PDF a partir das imagens tarjadas (rasterizado)."""
    return finalize(task_id, native_mode=False)

@app.get("/download/{task_id}")
def download_result(task_id: str, inline: bool = False, final: bool = False):
    """final=true (clientes da API e agentes): só entrega o PDF aprovado pelo revisor ("Aplicar proteção") e sem
    pendência de revisão. Sem ele, entrega o PDF que existir (inclusive o preliminar do processamento automático)."""
    task = get_task(task_id)
    path_pdf_final = final_pdf_path(task)
    if final and not approved(task_id, task):
        raise HTTPException(status_code=409, detail="PDF ainda não aprovado: revise no portal e use \"Aplicar "
                                                    "proteção\" (sem pendências de revisão).")

    if os.path.exists(path_pdf_final):
        original_name = task.get("file", "documento.pdf")
        clean_name = os.path.splitext(original_name)[0]
        final_download_name = f"{clean_name}_TARJADO.pdf"
        from urllib.parse import quote
        headers = {
            "Content-Disposition": f"{'inline' if inline else 'attachment'}; filename*=UTF-8''{quote(final_download_name)}",
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache", "Expires": "0"
        }
        return FileResponse(path_pdf_final, media_type="application/pdf", headers=headers)

    if not task.get("completed", False):
         raise HTTPException(status_code=202, detail="Em processamento...")

    raise HTTPException(status_code=404, detail="Arquivo não encontrado")

@app.delete("/task/{task_id}")
async def delete_task(task_id: str):
    task = get_task(task_id)
    dequeue(task_id)
    if is_running(task_id):
        raise HTTPException(status_code=409, detail="Tarefa em execução.")
    removed, errors = remove_task_artifacts(task)
    if errors:  # fail-safe: não "esquece" a tarefa enquanto houver arquivos com PII no disco
        raise HTTPException(status_code=500, detail={"msg": "Falha ao apagar artefatos.", "errors": errors})
    with tasks_lock:
        tasks.pop(task_id, None)
        save_tasks()
    return {"status": "deleted", "removed": removed}

@app.post("/purge/{task_id}")
async def purge_task(task_id: str, include_input: bool = False, force: bool = False):
    """Remove imagens originais SEM tarja (e demais intermediários), mantendo PDF final e metadados.

    Só é permitido com PDF final existente e tarefa sem pendência de revisão (use force=true para
    purgar mesmo assim). include_input=true também apaga o PDF original enviado (inviabiliza o
    retarjamento nativo e o reprocessamento).
    """
    task = get_task(task_id)
    if is_running(task_id):
        raise HTTPException(status_code=409, detail="Tarefa em execução.")
    if not os.path.exists(final_pdf_path(task)):
        raise HTTPException(status_code=409, detail="Não há PDF final: purgar impediria a revisão/geração.")
    if task.get("needs_review") and not force:
        raise HTTPException(status_code=409, detail="Tarefa requer revisão; aprove antes de purgar (ou use force=true).")
    removed, errors = purge_task_originals(task, include_input=include_input)
    with tasks_lock:
        task["purged"] = True
        if include_input:
            task["input_purged"] = True
        save_tasks()
    return {"status": "purged", "removed": removed, "errors": errors}

def approved(task_id, task):
    """PDF gerado com as tarjas confirmadas pelo revisor, sem pendência de revisão nem erro."""
    return bool(task.get("finalizado") and task.get("completed") and not task.get("needs_review")
                and not task.get("error") and not is_running(task_id) and not is_queued(task_id))


# ------------------------------------------------------------------------------------------- Administração
def require_admin():
    if not admin_enabled():
        raise HTTPException(status_code=404, detail="Administração desligada (ADMIN_ENABLED=0)")


@app.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request):
    require_admin()
    if not portal_enabled():
        raise HTTPException(status_code=404, detail="Portal desligado (PORTAL_ENABLED=0): use a API /admin/settings")
    return templates.TemplateResponse(request=request, name="admin.html")


def _admin_state():
    from utils import egress
    from utils.ai_client import AIClient
    data = admin_settings.describe()
    data["ia"] = AIClient().health(live=False)  # sem chaves
    data["ia"]["externo_permitido"] = egress.external_allowed()
    data["ia_externa"] = external_ai_now()
    data["versao"] = app_version()
    data["token_exigido"] = bool(API_TOKEN)
    # Para o trecho de configuração do cliente MCP (docs/mcp.md): o Python e o script desta instalação
    data["mcp"] = {"comando": sys.executable, "args": [os.path.join(BASE_DIR, "sentry_mcp.py")]}
    return data


@app.get("/admin/settings")
def admin_get_settings():
    require_admin()
    return _admin_state()


@app.post("/admin/settings")
def admin_save_settings(payload: dict = Body(...)):
    """{"values": {"CHAVE": "valor" | null}}. null = voltar ao .env/padrão; chave secreta vazia = manter."""
    require_admin()
    try:
        admin_settings.save(payload.get("values"))
    except admin_settings.SettingsError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except OSError as e:  # pasta sem permissão de escrita (ex.: contêiner): diz onde, sem 500 genérico
        raise HTTPException(status_code=500, detail=f"Não foi possível gravar {admin_settings.path()}: "
                                                    f"{type(e).__name__}")
    app_logger.info("Configuração alterada pela tela Admin: %s",
                    ", ".join(sorted((payload.get("values") or {}).keys())))  # só os nomes, nunca os valores
    return _admin_state()


def _admin_backend(papel):
    from utils.ai_client import configured_backends
    for b in configured_backends():
        if b.role == papel:
            return b
    raise HTTPException(status_code=404, detail=f"IA '{papel}' não configurada")


@app.post("/admin/ai/test")
def admin_test_ai(papel: str = "principal"):
    """Testa a IA SALVA (conexão, chave e modelo) com um pedido curto, sem nenhum conteúdo de documento.
    Devolve só ok/motivo: nunca o corpo da resposta do servidor."""
    require_admin()
    from utils import egress
    backend = _admin_backend(papel)
    t0 = time.time()
    ok, why = backend.probe(vision=True, timeout=15)
    if ok:
        try:
            content, _m, _raw, is_chat = backend.chat("Responda só com JSON.", 'Responda exatamente {"ok": true}',
                                                      None, 60, vision=True)
            ok = bool(is_chat and content)
            why = "ok" if ok else "o servidor respondeu fora do formato de chat"
        except Exception as e:
            ok, why = False, f"{type(e).__name__}: {str(e)[:160]}"
    return {"ok": ok, "motivo": why, "papel": papel, "modelo": backend.vision_model,
            "externo": egress.is_external(backend.base_url), "externo_permitido": egress.external_allowed(),
            "segundos": round(time.time() - t0, 2)}


@app.get("/admin/ai/models")
def admin_list_models(papel: str = "principal"):
    """Nomes dos modelos que o servidor SALVO oferece (para escolher na tela)."""
    require_admin()
    from utils.ai_client import list_models
    ok, result = list_models(_admin_backend(papel))
    if not ok:
        raise HTTPException(status_code=502, detail=result)
    return {"modelos": result}


# ------------------------------------------------------------------------------------------- Modelos de documento
def _task_source(task_id):
    """Para o gerenciador de modelos: pasta, nome base, PDF de entrada e tarjas revisadas de uma tarefa parada."""
    task = get_task(task_id)
    if is_running(task_id) or is_queued(task_id):
        raise HTTPException(status_code=409, detail="Tarefa em execução: espere terminar.")
    folder = os.path.join(OUTPUT_DIR, task_base(task))
    reviewed = os.path.exists(os.path.join(folder, "manual_redactions.json"))  # o revisor salvou no editor
    return folder, task_base(task), task.get("input_path"), read_redactions(task), reviewed


from utils.doc_templates.api import make_router as _doc_templates_router  # noqa: E402

app.include_router(_doc_templates_router({"require_admin": require_admin, "task_source": _task_source}))


if __name__ == "__main__":
    import uvicorn
    multiprocessing.freeze_support()
    uvicorn.run(app, host=APP_HOST, port=APP_PORT, log_level="info")

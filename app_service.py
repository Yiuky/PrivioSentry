# SPDX-License-Identifier: AGPL-3.0-or-later
import os
import re
import uuid
import secrets
import multiprocessing
import json
import logging
import shutil
import threading
from datetime import datetime, timedelta
import httpx
from fastapi import FastAPI, UploadFile, File, BackgroundTasks, HTTPException, Body, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from main import SentryApp
from utils.pii import install_log_masking
from dotenv import load_dotenv
load_dotenv()

# Configuração de Log própria do App
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
install_log_masking()  # LGPD: nenhum CPF completo em log (root + handlers do app)
app_logger = logging.getLogger("AppTarjadorService")

app = FastAPI(title="PRIVIO SENTRY Service")

# Configuration
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INPUT_DIR = os.getenv("PRIVIO_INPUT_DIR") or os.path.join(BASE_DIR, "WEB_INPUT")
OUTPUT_DIR = os.getenv("PRIVIO_OUTPUT_DIR") or os.path.join(BASE_DIR, "output")
FINAL_DIR = os.getenv("PRIVIO_FINAL_DIR") or os.path.join(BASE_DIR, "documentos_finais")
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
TASKS_FILE = os.getenv("PRIVIO_TASKS_FILE") or os.path.join(BASE_DIR, "tasks.json")

APP_HOST = os.getenv("APP_HOST", "127.0.0.1")
APP_PORT = int(os.getenv("APP_PORT", "8001"))
API_TOKEN = os.getenv("API_TOKEN", "")  # Se definido, exigido em todas as rotas (exceto /internal)
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
        if not t.get("completed") and not t.get("error"):
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
    return removed, errors

# Pastas de trabalho com imagens/recortes/respostas SEM tarja (ou parcialmente tarjadas).
# Mantidos: 05_final_export/combined e 05_phase_5_export (já tarjadas), logs e metadados .json/.txt.
PURGE_DIRS = (
    "00_original_images", "01_ocr_results", "02_signature_crops", "04_signatures_crops_ia",
    "04_signatures_crops_tarjados", "04_micro_audit_results", "06_final_enhanced",
    "07_addresses_crops_ia", "08_addresses_crops_tarjados", "99_ia_interactions",
    os.path.join("05_final_export", "cpf_only"), os.path.join("05_final_export", "address_only"),
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

def start_worker(task_id, manual_redactions=None, native_mode=False):
    """Inicia o worker da tarefa; levanta 409 se já houver um em execução."""
    if is_running(task_id):
        raise HTTPException(status_code=409, detail="Tarefa já está em execução.")
    task = tasks[task_id]
    require_input(task)
    p = multiprocessing.Process(
        target=redaction_worker,
        args=(task_id, task["input_path"], manual_redactions, native_mode, APP_PORT, INTERNAL_SECRET, AI_LOCK)
    )
    p.start()
    procs[task_id] = p

def sanitize_filename(name: str) -> str:
    name = os.path.basename((name or "").replace("\\", "/"))
    name = re.sub(r"[^\w\s.\-()°]", "_", name, flags=re.UNICODE).strip(" .")
    if len(name) > 150:
        stem, ext = os.path.splitext(name)
        name = stem[:150 - len(ext)] + ext
    return name or "documento.pdf"

startup_maintenance()  # após todas as definições acima (usa is_running/task_base)

@app.middleware("http")
async def token_guard(request: Request, call_next):
    if API_TOKEN and not request.url.path.startswith("/internal/"):
        supplied = request.headers.get("x-api-token") or request.cookies.get("api_token") or request.query_params.get("token")
        if not supplied or not secrets.compare_digest(supplied, API_TOKEN):
            return JSONResponse({"detail": "Não autorizado"}, status_code=401)
        response = await call_next(request)
        if request.query_params.get("token"):
            response.set_cookie("api_token", API_TOKEN, httponly=True, samesite="strict")
        return response
    return await call_next(request)

def redaction_worker(task_id: str, file_path: str, manual_redactions=None, native_mode=False,
                     api_port=8001, internal_secret="", ai_lock=None):
    """
    Motor do SENTRY Redact executado em um PROCESSO SEPARADO (Multi-Core).
    """
    if ai_lock is not None:
        import utils.ai_client as ai_client
        ai_client.ollama_lock = ai_lock

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

        # Conclusão final redundante para garantir estado
        progress_callback(pipeline.final_state())
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
            tasks[task_id].update(data)
            if "alerts" in data and data["alerts"]:
                tasks[task_id]["alerts"] = data["alerts"]
            save_tasks()
    return {"status": "ok"}

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(request=request, name="index.html")

@app.get("/readme")
async def readme():
    path = os.path.join(BASE_DIR, "README.md")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return {"content": f.read()}
    except Exception:
        raise HTTPException(status_code=404, detail="README não encontrado")

@app.post("/upload")
async def upload_file(background_tasks: BackgroundTasks, file: UploadFile = File(...), force: bool = False):
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
            "alerts": []
        }
        save_tasks()

    # Inicia Processo Separado (Multi-Core)
    start_worker(task_id)

    return {"status": "started", "task_id": task_id}

@app.get("/tasks")
async def get_tasks():
    return tasks

def reset_task_state(task, status):
    task["status"] = status
    task["percentage"] = 0
    task["completed"] = False
    task["error"] = False
    task["needs_review"] = False
    task["alerts"] = []
    task.pop("purged", None)  # reprocessar regenera as imagens

@app.post("/reprocess/{task_id}")
async def reprocess_task(task_id: str):
    task = get_task(task_id)
    if is_running(task_id):
        raise HTTPException(status_code=409, detail="Tarefa já está em execução.")
    require_input(task)  # antes de alterar o estado (evita tarefa presa em "Reiniciando...")
    reset_task_state(task, "Reiniciando...")
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
        if (t["status"] == "Aguardando" or t.get("error")) and not is_running(tid):
            was_error = t.get("error")
            t["error"] = False
            try:
                start_worker(tid)
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
    if task.get("purged") and not native_mode:
        raise HTTPException(status_code=409, detail="Imagens originais foram removidas (purge); use o retarjamento nativo.")
    require_input(task)
    task["status"] = "Gerando PDF Nativo..." if native_mode else "Gerando PDF Final..."
    task["percentage"] = 90
    task["completed"] = False
    task["error"] = False
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
def download_result(task_id: str, inline: bool = False):
    task = get_task(task_id)
    path_pdf_final = final_pdf_path(task)

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

if __name__ == "__main__":
    import uvicorn
    multiprocessing.freeze_support()
    uvicorn.run(app, host=APP_HOST, port=APP_PORT, log_level="info")

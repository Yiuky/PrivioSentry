# SPDX-License-Identifier: AGPL-3.0-or-later
"""Painel da Administração: o que está pronto, o que precisa de atenção e como está a fila.

Só fatos verificáveis e contagens: nada de nome de arquivo, motivo de alerta, texto de documento ou chave (I-11,
I-12). Nada pesado no processo do serviço: o YOLO não é importado (só se confere o pacote e o arquivo do modelo),
o Tesseract responde a `--version` com prazo curto e o tamanho das pastas é calculado no máximo a cada minuto.
"""
import importlib.util
import os
import shutil
import subprocess
import time

_cache = {}


def _cached(key, seconds, fn):
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < seconds:
        return hit[1]
    value = fn()
    _cache[key] = (time.time(), value)
    return value


def _tesseract_version(exe):
    try:
        out = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    text = (out.stdout or out.stderr or "").strip().splitlines()
    return text[0].replace("tesseract", "").strip() if out.returncode == 0 and text else None


def tesseract():
    exe = os.getenv("TESSERACT_PATH") or shutil.which("tesseract") or ""
    found = bool(exe) and (os.path.isfile(exe) or shutil.which(exe) is not None)
    version = _cached("tess:" + exe, 300, lambda: _tesseract_version(exe)) if found else None
    return {"encontrado": bool(found and version), "versao": version, "do_path": not os.getenv("TESSERACT_PATH")}


def yolo():
    from utils.yolo_engine import resolve_model_path
    return {"pacote": importlib.util.find_spec("ultralytics") is not None,
            "modelo": os.path.isfile(resolve_model_path(os.getenv("YOLO_MODEL_PATH")))}


def _folder_size(folders, limit=200_000):
    total, files, partial = 0, 0, False
    for folder in folders:
        for root, _dirs, names in os.walk(folder):
            for name in names:
                files += 1
                if files > limit:
                    return {"bytes": total, "arquivos": files - 1, "parcial": True}
                try:
                    total += os.path.getsize(os.path.join(root, name))
                except OSError:
                    pass
    return {"bytes": total, "arquivos": files, "parcial": partial}


def disk(folders):
    folders = [f for f in folders if f and os.path.isdir(f)]
    return _cached("disk:" + "|".join(folders), 60, lambda: _folder_size(folders))


def task_counts(tasks, running, queued):
    """Contagem por situação. `running`/`queued`: funções task_id -> bool do serviço."""
    counts = dict.fromkeys(("processando", "na_fila", "pendente", "erro", "requer_revisao", "preliminar",
                            "aprovado"), 0)
    next_retry = None
    for tid, task in tasks.items():
        if queued(tid) or task.get("queued"):
            counts["na_fila"] += 1
        elif running(tid):
            counts["processando"] += 1
        elif task.get("error"):
            counts["erro"] += 1
        elif task.get("pendente") and not task.get("completed"):
            counts["pendente"] += 1
            when = task.get("pendente_ate")
            if isinstance(when, (int, float)):
                next_retry = when if next_retry is None else min(next_retry, when)
        elif task.get("completed") and task.get("needs_review"):
            counts["requer_revisao"] += 1
        elif task.get("completed") and task.get("finalizado"):
            counts["aprovado"] += 1
        elif task.get("completed"):
            counts["preliminar"] += 1
        else:
            counts["processando"] += 1
    counts["total"] = len(tasks)
    counts["proxima_tentativa"] = next_retry
    return counts


def checks(state, ai_health, external_hosts):
    """Lista do painel: cada item com nível (ok, aviso, erro) e dados para a interface montar o texto."""
    from utils import ocr_extra
    from utils.detect import ner
    out = []
    tess = tesseract()
    out.append({"id": "ocr", "nivel": "ok" if tess["encontrado"] else "erro", "dados": tess, "secao": "ocr"})
    yl = yolo()
    out.append({"id": "yolo", "nivel": "ok" if yl["pacote"] and yl["modelo"] else "erro", "dados": yl,
                "secao": None})
    servers = ai_health.get("servidores") or []
    breaker = ai_health.get("disjuntor") or {}
    for server in servers:
        off = any(server["endereco"] in k and v.get("desligado") for k, v in breaker.items())
        blocked = server.get("externo") and not ai_health.get("externo_permitido")
        level = "erro" if blocked else ("aviso" if off else "ok")
        out.append({"id": "ia_" + server["papel"], "nivel": level, "secao": "ia",
                    "dados": {"endereco": server["endereco"], "modelo": server.get("modelo_visao"),
                              "externo": bool(server.get("externo")), "bloqueado": bool(blocked),
                              "desligado": off}})
    out.append({"id": "saida", "nivel": "aviso" if external_hosts else "ok", "secao": "ia",
                "dados": {"destinos": external_hosts}})
    if ner.enabled():
        out.append({"id": "nomes", "nivel": "ok" if ner.available() else "aviso", "secao": "deteccao",
                    "dados": {"instalado": ner.available()}})
    if ocr_extra.enabled():
        out.append({"id": "ocr_extra", "nivel": "ok" if ocr_extra.available() else "aviso", "secao": "deteccao",
                    "dados": {"instalado": ocr_extra.available()}})
    verify = os.getenv("VERIFY_OCR", "1") == "1"
    out.append({"id": "verificacao", "nivel": "ok" if verify else "aviso", "secao": "ocr", "dados": {"ligada": verify}})
    pending_restart = [f["label"] for f in state.get("campos", []) if f.get("pendente_reinicio")]
    if pending_restart:
        out.append({"id": "reiniciar", "nivel": "aviso", "secao": "operacao", "dados": {"itens": pending_restart}})
    return out

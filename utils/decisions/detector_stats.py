# SPDX-License-Identifier: AGPL-3.0-or-later
"""Retorno do revisor por detector: quantas tarjas sugeridas ele manteve, removeu ou acrescentou.

Na finalização nativa, compara as tarjas sugeridas pela IA (redactions_metadata.json, com o rótulo do detector:
"CPF", "Telefone", "Endereço residencial"...) com as tarjas finais do editor:
    mantida     sugestão coberta por uma tarja final
    removida    sugestão que o revisor apagou (provável falso positivo daquele detector)
    adicionada  tarja final sem sugestão por baixo (provável dado que o detector não achou)

Guarda SÓ contagens por rótulo e tarefa (nenhum texto, nenhuma coordenada) em learning/detector_stats.jsonl,
só com LEARNING_ENABLED=1, e apagar a tarefa apaga as linhas dela. O resumo (python -m utils.decisions detectores)
mostra a precisão observada de cada detector e SUGESTÕES para quem mantém as regras. Nada aqui muda regra,
limiar ou perfil sozinho: reduzir proteção exige uma pessoa, uma mudança em utils/detect/data e o corpus
(python -m benchmarks.pii_eval) mostrando que não piorou.
"""
import json
import logging
import os
import tempfile
from datetime import datetime, timezone

from .feedback import learning_enabled

logger = logging.getLogger("decisions")

STATS_FILE = "detector_stats.jsonl"
AI_METADATA = "redactions_metadata.json"
NO_LABEL = "Sem rótulo"
MANUAL = "Manual"
MIN_OVERLAP = 0.5  # fração da menor caixa coberta pela outra para considerar "a mesma tarja"


def _boxes_by_page(redactions, scale_to=None):
    """{página: [(x0, y0, x1, y1, rótulo, largura_da_imagem)]}, ignorando entradas inválidas."""
    out = {}
    for r in redactions or []:
        try:
            x0, y0, x1, y1 = (float(v) for v in r["coords"])
            page = int(r.get("page", 1))
        except (KeyError, TypeError, ValueError):
            continue
        width = r.get("image_width")
        target = (scale_to or {}).get(page)
        if width and target and float(width) != float(target):  # editor em outra escala: traz para a da IA
            k = float(target) / float(width)
            x0, y0, x1, y1 = x0 * k, y0 * k, x1 * k, y1 * k
        out.setdefault(page, []).append((min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1),
                                         str(r.get("label") or ""), width))
    return out


def _same(a, b):
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    smaller = min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1]))
    return smaller > 0 and ix * iy / smaller >= MIN_OVERLAP


def compare(suggested, final):
    """{rótulo: {"mantidas", "removidas", "adicionadas"}} comparando as sugestões da IA com as tarjas finais."""
    ai = _boxes_by_page(suggested)
    widths = {page: next((b[5] for b in boxes if b[5]), None) for page, boxes in ai.items()}
    done = _boxes_by_page(final, scale_to=widths)
    counts = {}

    def bump(label, key):
        row = counts.setdefault(label, {"mantidas": 0, "removidas": 0, "adicionadas": 0})
        row[key] += 1

    for page in set(ai) | set(done):
        suggestions, finals = ai.get(page, []), done.get(page, [])
        for s in suggestions:
            bump(s[4] or NO_LABEL, "mantidas" if any(_same(s, f) for f in finals) else "removidas")
        for f in finals:
            if not any(_same(f, s) for s in suggestions):
                bump(f[4] or MANUAL, "adicionadas")
    return counts


def _path(root):
    return os.path.join(root, STATS_FILE)


def capture(output_dir, final_redactions, root=None):
    """Grava as contagens desta finalização. Devolve o dicionário gravado ({} se desligado/sem dados)."""
    if not learning_enabled():
        return {}
    try:
        meta = os.path.join(output_dir, AI_METADATA)
        if not os.path.exists(meta):
            return {}
        with open(meta, encoding="utf-8") as f:
            suggested = json.load(f)
        counts = compare(suggested, final_redactions)
        if not counts:
            return {}
        from .learning import LearningStore
        root = root or LearningStore().root
        os.makedirs(root, exist_ok=True)
        task = os.path.basename(os.path.normpath(output_dir))
        at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with open(_path(root), "a", encoding="utf-8") as f:
            f.write(json.dumps({"task": task, "at": at, "counts": counts}, ensure_ascii=False) + "\n")
        logger.info(f"[decisions] retorno do revisor por detector guardado ({len(counts)} rótulo(s)).")
        return counts
    except Exception as e:  # estatística nunca pode quebrar a finalização
        logger.warning(f"[decisions] não foi possível guardar o retorno por detector: {e}")
        return {}


def _rows(root):
    path = _path(root)
    if not os.path.exists(path):
        return []
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
    return rows


def remove_task(root, task):
    """Apaga as linhas de uma tarefa (direito de eliminação). Devolve quantas removeu."""
    path = _path(root)
    if not task or not os.path.exists(path):
        return 0
    with open(path, encoding="utf-8") as f:
        lines = f.readlines()
    kept = []
    for line in lines:
        try:
            if json.loads(line).get("task") == str(task):
                continue
        except ValueError:
            pass
        kept.append(line)
    removed = len(lines) - len(kept)
    if removed:
        fd, tmp = tempfile.mkstemp(dir=root, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.writelines(kept)
        os.replace(tmp, path)
    return removed


def summary(root):
    """Totais por rótulo com precisão observada e sugestões (nunca aplicadas automaticamente)."""
    from utils.detect import config
    min_n = int(config.param("retorno_revisor", "amostras_minimas"))
    low_precision = config.param("retorno_revisor", "precisao_alerta")
    many_added = config.param("retorno_revisor", "fracao_adicionadas_alerta")
    totals, tasks = {}, set()
    for row in _rows(root):
        tasks.add(row.get("task"))
        for label, c in (row.get("counts") or {}).items():
            t = totals.setdefault(label, {"mantidas": 0, "removidas": 0, "adicionadas": 0})
            for key in t:
                t[key] += int(c.get(key, 0) or 0)
    report = {}
    for label, t in sorted(totals.items()):
        suggested = t["mantidas"] + t["removidas"]
        precision = t["mantidas"] / suggested if suggested else None
        found = t["mantidas"] + t["adicionadas"]
        added_share = t["adicionadas"] / found if found else 0.0
        tips = []
        if suggested >= min_n and precision is not None and precision < low_precision:
            tips.append("o revisor apaga muitas sugestões: revise as palavras de contexto/limiares deste detector em "
                        "utils/detect/data e meça com python -m benchmarks.pii_eval antes de mudar (sem reduzir "
                        "a proteção às cegas)")
        if found >= min_n and added_share >= many_added:
            tips.append("o revisor acrescenta muitas tarjas deste tipo: possível falta de cobertura; transforme "
                        "casos (fictícios) em exemplos do corpus benchmarks/pii_corpus.py")
        if suggested < min_n and found < min_n:
            tips.append(f"poucos dados ainda (mínimo {min_n} para sugerir algo)")
        report[label] = {**t, "precisao_observada": None if precision is None else round(precision, 3),
                         "fracao_adicionadas": round(added_share, 3), "sugestoes": tips}
    return {"tarefas": len(tasks), "detectores": report}

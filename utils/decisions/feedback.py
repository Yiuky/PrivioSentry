# SPDX-License-Identifier: AGPL-3.0-or-later
"""Transforma as correções do revisor em exemplos rotulados (automelhoramento).

Durante o processamento, main.py grava em output/<tarefa>/decisions.json cada endereço encontrado,
com as caixas das palavras dele na página. Quando o revisor clica em "Aplicar proteção", as caixas
finais dizem o que ele decidiu:
    palavras do endereço cobertas pelas tarjas finais  -> rótulo 1 (pessoal)
    não cobertas                                      -> rótulo 0 (não pessoal)
Só roda com LEARNING_ENABLED=1 e nunca interrompe a finalização.
"""
import json
import logging
import os

logger = logging.getLogger("decisions")

DECISIONS_FILE = "decisions.json"
AI_METADATA = "redactions_metadata.json"  # sugestões da IA, com a largura da imagem de cada página
MIN_COVERED_FRACTION = 0.5  # metade das palavras do endereço sob tarja = o revisor tratou como pessoal


def learning_enabled():
    return os.getenv("LEARNING_ENABLED", "0").strip().lower() in ("1", "true", "sim", "yes")


def write_decision_log(output_dir, entries):
    path = os.path.join(output_dir, DECISIONS_FILE)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)
    return path


def _center_inside(word, box):
    cx, cy = word[0] + word[2] / 2.0, word[1] + word[3] / 2.0
    x0, y0, x1, y1 = box
    return x0 <= cx <= x1 and y0 <= cy <= y1


def labels_from_review(entries, final_redactions, min_fraction=MIN_COVERED_FRACTION, page_widths=None):
    """
    entries: registros de decisions.json ({"text", "page", "word_boxes": [[x, y, w, h], ...], ...}).
    final_redactions: tarjas confirmadas no editor ({"page", "coords": [x0, y0, x1, y1], "image_width"?}).
    page_widths: {página: largura em pixels da imagem da página} (a escala das word_boxes); tarja com
    image_width diferente é reescalada para ela, como em detector_stats.
    """
    by_page = {}
    for r in final_redactions or []:
        try:
            page = int(r.get("page", 1))
            coords = [float(v) for v in r["coords"]]
            width, target = r.get("image_width"), (page_widths or {}).get(page)
            if width and target and float(width) != float(target):  # editor em outra escala
                coords = [c * float(target) / float(width) for c in coords]
            by_page.setdefault(page, []).append(coords)
        except (KeyError, TypeError, ValueError, ZeroDivisionError):
            continue
    rows = []
    for e in entries or []:
        words = e.get("word_boxes") or []
        if not words or not e.get("text"):
            continue
        boxes = by_page.get(int(e.get("page", 0)), [])
        covered = sum(1 for w in words if any(_center_inside(w, b) for b in boxes))
        rows.append({"text": e["text"], "label": 1 if covered / len(words) >= min_fraction else 0, "source": "review"})
    return rows


def _page_widths(output_dir):
    """{página: largura da imagem} das sugestões da IA (redactions_metadata.json), a escala das word_boxes."""
    try:
        with open(os.path.join(output_dir, AI_METADATA), encoding="utf-8") as f:
            suggested = json.load(f)
    except (OSError, ValueError):
        return {}
    widths = {}
    for r in suggested if isinstance(suggested, list) else []:
        try:
            if r.get("image_width"):
                widths.setdefault(int(r.get("page", 1)), float(r["image_width"]))
        except (AttributeError, TypeError, ValueError):
            continue
    return widths


def capture_review(output_dir, final_redactions, store=None):
    """Lê decisions.json da tarefa e grava os rótulos do revisor. Devolve quantos exemplos gravou."""
    if not learning_enabled():
        return 0
    path = os.path.join(output_dir, DECISIONS_FILE)
    if not os.path.exists(path):
        return 0
    try:
        with open(path, encoding="utf-8") as f:
            entries = json.load(f)
        from .learning import LearningStore
        rows = labels_from_review(entries, final_redactions, page_widths=_page_widths(output_dir))
        task = os.path.basename(os.path.normpath(output_dir))
        for r in rows:
            r["task"] = task  # apagar a tarefa apaga também estes exemplos
        n = (store or LearningStore()).add_examples(rows)
        logger.info(f"[decisions] {n} correção(ões) do revisor guardada(s) para o próximo treino.")
        return n
    except Exception as e:  # aprendizado nunca pode quebrar a finalização
        logger.warning(f"[decisions] não foi possível guardar as correções do revisor: {e}")
        return 0

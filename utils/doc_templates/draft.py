# SPDX-License-Identifier: AGPL-3.0-or-later
"""Rascunho de modelo a partir de um documento JÁ REVISADO: as tarjas confirmadas dizem onde estão os dados.

Sem IA (zero token): cada tarja vira um campo ancorado no rótulo à esquerda ("CPF/CNPJ:") ou na linha de cima; as
âncoras de reconhecimento são as primeiras linhas fixas da página 1 (sem dígitos, sem nada tarjado, sem palavras
que foram tarjadas em outro lugar). Tarja sem rótulo perto não vira campo (é contada e avisada).

Com IA (opcional): o modelo de IA recebe só o texto MASCARADO (tarjas -> █, dígitos -> #) e sugere nome, âncoras e
rótulos de dado pessoal. Sugestão que não existe literalmente na página é descartada (defesa contra invenção).
O resultado é sempre RASCUNHO: o administrador revisa, testa e aprova.
"""
import re

from utils.doc_templates import engine
from utils.doc_templates.schema import slug

LABEL_TO_TYPE = {"cpf": "cpf", "endereco residencial": "endereco_residencial", "endereco": "endereco_residencial"}
MAX_ANCHORS = 6


def _type_for(label):
    key = engine.norm(label or "")
    if key in LABEL_TO_TYPE:
        return LABEL_TO_TYPE[key]
    try:
        from utils.detect import catalog
        for t in catalog.CATALOG:
            if engine.norm(t.nome) == key or t.id == key:
                return t.id
    except Exception:
        pass
    return "outro"


def _label_left(words, line, start, covered):
    """Rótulo terminado em ':' logo antes da posição 'start' (até 5 palavras, sem tarja)."""
    p = start - 1
    if p < 0 or line[p] in covered:
        return None
    text = str(words[line[p]].get("text", "")).strip()
    colon = text.endswith(":") or text == ":"
    if not colon:
        return None
    parts = [] if text == ":" else [text.rstrip(":").strip()]
    q = p - 1
    if text == ":":
        if q < 0 or line[q] in covered:
            return None
        parts, q = [str(words[line[q]].get("text", "")).strip()], q - 1
    h = words[line[p]]["box"]["h"]
    while q >= 0 and len(parts) < 5 and line[q] not in covered:
        prev = str(words[line[q]].get("text", "")).strip()
        gap = words[line[q + 1]]["box"]["x"] - (words[line[q]]["box"]["x"] + words[line[q]]["box"]["w"])
        if prev.endswith(":") or gap > 3 * h or re.search(r"\d", prev):
            break
        parts.insert(0, prev)
        q -= 1
    label = " ".join(x for x in parts if x).strip(" :")
    return label or None


def _label_above(words, rows, li, run, covered):
    """Rótulo na linha de cima, sobre o início do valor (formulário em caixas)."""
    if li == 0:
        return None
    x0 = words[run[0]]["box"]["x"]
    h = words[run[0]]["box"]["h"]
    above = [i for i in rows[li - 1] if abs(words[i]["box"]["x"] - x0) <= 3 * h or
             x0 - 3 * h <= words[i]["box"]["x"] <= words[run[-1]]["box"]["x"] + words[run[-1]]["box"]["w"]]
    if not above or len(above) > 5 or any(i in covered for i in above):
        return None
    text = " ".join(str(words[i].get("text", "")) for i in above).strip()
    if re.search(r"\d", text) or len(text) > 60:
        return None
    return text.strip(" :") or None


def _runs(line, covered):
    runs, cur = [], []
    for pos, wid in enumerate(line):
        if wid in covered:
            cur.append(pos)
        elif cur:
            runs.append(cur)
            cur = []
    if cur:
        runs.append(cur)
    return runs


def build(pages_words, page_boxes, box_labels=None, name=None):
    """pages_words: palavras por página; page_boxes: {página: [{x, y, w, h} em pixels]} das tarjas revisadas;
    box_labels: {página: [rótulo de cada caixa]} (tipo). Devolve (rascunho, relatório)."""
    box_labels = box_labels or {}
    fields, unanchored = {}, 0
    covered_tokens = set()
    covered_by_page = {}
    for page, words in enumerate(pages_words, start=1):
        boxes = page_boxes.get(page, [])
        covered = engine.covered_ids(words, boxes)
        covered_by_page[page] = covered
        covered_tokens |= {engine.norm_token(words[i].get("text", "")) for i in covered}
        rows = engine.lines(words)
        for li, line in enumerate(rows):
            for run_pos in _runs(line, covered):
                run = [line[p] for p in run_pos]
                tipo = "outro"
                for k, b in enumerate(boxes):  # tipo da tarja que cobre o início do valor
                    w = words[run[0]]["box"]
                    if b["x"] <= w["x"] + w["w"] / 2 <= b["x"] + b["w"] and b["y"] <= w["y"] + w["h"] / 2 <= b["y"] + b["h"]:
                        labels = box_labels.get(page) or []
                        tipo = _type_for(labels[k]) if k < len(labels) else "outro"
                        break
                label, direction = _label_left(words, line, run_pos[0], covered), "direita"
                if label is None:
                    label, direction = _label_above(words, rows, li, run, covered), "abaixo"
                if label is None:
                    unanchored += 1
                    continue
                key = (engine.norm(label), direction)
                slot = fields.setdefault(key, {"rotulo": label, "tipo": tipo, "direcao": direction, "max_palavras": 1,
                                               "linhas": 1, "obrigatorio": True, "paginas": []})
                slot["max_palavras"] = min(60, max(slot["max_palavras"], len(run) + 4))
                if slot["tipo"] == "outro":
                    slot["tipo"] = tipo
                # valor que continua na linha de baixo (endereço quebrado), sem rótulo antes
                nxt = rows[li + 1] if li + 1 < len(rows) else []
                h = words[run[0]]["box"]["h"]
                if nxt and nxt[0] in covered and min(abs(words[nxt[0]]["box"]["x"] - words[run[0]]["box"]["x"]),
                                                     abs(words[nxt[0]]["box"]["x"] - words[line[0]]["box"]["x"])) <= 2 * h:
                    slot["linhas"] = max(slot["linhas"], 2)
    anchors = _anchors(pages_words[0] if pages_words else [], covered_by_page.get(1, set()), covered_tokens)
    title = name or (anchors[0] if anchors else "Modelo de documento")
    n_pages = len(pages_words)
    draft = {"id": slug(title), "nome": title[:120], "descricao": "", "status": "rascunho", "origem": "documento",
             "reconhecimento": {"ancoras": anchors, "minimo": 0.8 if len(anchors) >= 3 else 1.0,
                                "paginas_min": 1, "paginas_max": max(n_pages + 5, n_pages * 2)},
             "campos": list(fields.values()), "dispensa_ia": False}
    report = {"campos": len(fields), "tarjas_sem_rotulo": unanchored, "ancoras": len(anchors), "ia": None}
    return draft, report


def _anchors(words, covered, covered_tokens):
    """Primeiras linhas fixas da página 1: sem dígito, sem tarja, sem ':' seguido de valor, sem palavra tarjada."""
    out = []
    for line in engine.lines(words):
        if any(i in covered for i in line):
            continue
        text = " ".join(str(words[i].get("text", "")) for i in line).strip()
        n = engine.norm(text)
        if len(n) < 10 or len(n.split()) < 2 or re.search(r"\d", text) or len(text) > 200:
            continue
        if re.search(r":\s*\S", text):
            continue  # "Rótulo: valor" (valor variável)
        if any(engine.norm_token(t) in covered_tokens for t in text.split() if len(engine.norm_token(t)) >= 4):
            continue  # nome tarjado em outro lugar aparecendo aqui: não vira âncora
        if text not in out:
            out.append(text)
    # As primeiras linhas costumam ser o cabeçalho do ÓRGÃO, igual em todos os tipos de documento dele (medido:
    # o modelo de um documento reconhecia outro tipo do mesmo órgão). Ficam 2 delas + títulos (linhas em maiúsculas,
    # as mais longas primeiro), que distinguem o TIPO do documento.
    head, rest = out[:2], out[2:]
    titles = sorted((t for t in rest if sum(c.isupper() for c in t) >= 0.8 * sum(c.isalpha() for c in t)),
                    key=len, reverse=True)
    others = [t for t in rest if t not in titles]
    return (head + titles + others)[:MAX_ANCHORS]


# ------------------------------------------------------------------------------------------- ajuda da IA
PROMPT = ("Abaixo está o texto de um documento-modelo. Trechos com dados pessoais já foram trocados por █ e todos "
          "os dígitos por #. Responda SÓ com JSON no formato "
          '{"nome": "tipo do documento", "descricao": "uma frase", "ancoras": ["frases FIXAS que identificam este '
          'tipo de documento, copiadas do texto"], "rotulos": [{"rotulo": "rótulo copiado do texto, sem os dois-'
          'pontos", "tipo": "cpf|nome_pessoa|endereco_residencial|telefone|email|rg|data_nascimento|outro"}]}. '
          "Em rotulos, liste os rótulos de formulário que vêm ANTES de um dado pessoal (█). Copie exatamente; não "
          "invente.\n\nTEXTO:\n")


def masked_document(pages_words, page_boxes):
    parts = []
    for page, words in enumerate(pages_words[:3], start=1):
        covered = engine.covered_ids(words, page_boxes.get(page, []))
        parts.append(re.sub(r"\d", "#", engine.masked_text(words, covered)))
    return "\n\n".join(parts)[:12000]


def ai_suggest(draft, pages_words, page_boxes, client=None):
    """Acrescenta ao rascunho as sugestões da IA que existem literalmente no texto. Devolve (rascunho, nota)."""
    from utils.ai_client import AIClient
    text = masked_document(pages_words, page_boxes)
    try:
        response, _metrics = (client or AIClient()).analyze_text(PROMPT + text, vision_model=True)
    except Exception as e:
        return draft, f"IA indisponível: {type(e).__name__}"
    if not isinstance(response, dict) or "error" in response:
        return draft, f"IA não respondeu no formato pedido ({str((response or {}).get('error', ''))[:120]})"
    doc = " " + " ".join(engine.page_norm_text(w) for w in pages_words) + " "
    masked = engine.norm(text)
    added_a, added_f = 0, 0
    for a in response.get("ancoras") or []:
        a = str(a).strip()
        if a and "#" not in a and "█" not in a and f" {engine.norm(a)} " in doc and len(engine.norm(a)) >= 6 \
                and a not in draft["reconhecimento"]["ancoras"] and len(draft["reconhecimento"]["ancoras"]) < 30:
            draft["reconhecimento"]["ancoras"].append(a[:200])
            added_a += 1
    known = {engine.norm(f["rotulo"]) for f in draft["campos"]}
    for item in response.get("rotulos") or []:
        if not isinstance(item, dict):
            continue
        label = str(item.get("rotulo") or "").strip().strip(":").strip()
        n = engine.norm(label)
        if not n or n in known or len(label) > 80 or f"{n} " not in masked + " ":
            continue
        draft["campos"].append({"rotulo": label, "tipo": _type_for(item.get("tipo")), "direcao": "direita",
                                "max_palavras": 12, "linhas": 1, "obrigatorio": False, "paginas": [],
                                "sugerido_ia": True})
        known.add(n)
        added_f += 1
    if response.get("nome") and draft["origem"] == "documento":
        draft["nome"] = str(response["nome"]).strip()[:120] or draft["nome"]
        draft["id"] = slug(draft["nome"])
    if response.get("descricao"):
        draft["descricao"] = str(response["descricao"]).strip()[:500]
    draft["origem"] = "documento+ia"
    if len(draft["reconhecimento"]["ancoras"]) >= 3:
        draft["reconhecimento"]["minimo"] = 0.8
    return draft, f"IA sugeriu {added_a} âncora(s) e {added_f} campo(s) conferidos no texto"

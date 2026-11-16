# SPDX-License-Identifier: AGPL-3.0-or-later
"""Reconhecer o documento, aplicar os campos do modelo e inspecionar rótulos sem tarja. Nenhuma chamada de IA.

Palavras = itens do grounding map ({"text", "box": {x, y, w, h}}, em pixels da imagem da página), as mesmas que o
resto do pipeline usa (texto digital do PDF quando existe, senão o OCR).

Regras de segurança (I-03): na dúvida sobre o fim do valor, o campo pega a linha até o PRÓXIMO RÓTULO (nunca para
num espaço grande) e, se o limite de palavras cortar antes disso, avisa ("truncado") para virar revisão.
"""
import json
import os
import re
import unicodedata
from functools import lru_cache

DATA = os.path.join(os.path.dirname(os.path.dirname(__file__)), "detect", "data", "rotulos_inspecao.json")


def _ascii(text):
    return unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode("ascii").lower()


def norm(text):
    """'PROPRIETÁRIO:  João' -> 'proprietario joao' (frases de âncora e texto da página)."""
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", _ascii(text))).strip()


def norm_token(text):
    return re.sub(r"[^a-z0-9]+", "", _ascii(text))


def lines(words):
    """Índices das palavras agrupados em linhas (mesma altura), em ordem de leitura."""
    rows = []
    for i in sorted(range(len(words)), key=lambda k: (words[k]["box"]["y"], words[k]["box"]["x"])):
        b = words[i]["box"]
        if rows and abs(rows[-1][0] - b["y"]) <= max(4, b["h"] * 0.6):
            rows[-1][1].append(i)
        else:
            rows.append([b["y"], [i]])
    return [sorted(r[1], key=lambda k: words[k]["box"]["x"]) for r in rows]


def page_norm_text(words):
    return " ".join(norm(" ".join(str(words[i].get("text", "")) for i in ln)) for ln in lines(words))


# ------------------------------------------------------------------------------------------- reconhecimento
def match(templates, pages_words):
    """Escolhe o modelo do documento pelas âncoras (frases fixas). Mais de um modelo passa no próprio mínimo =
    nenhum é aplicado (I-13): um modelo genérico de 1 âncora não pode vencer um específico, nem o contrário.

    Devolve {"modelo": dict|None, "pontuacao", "ancoras_encontradas", "ambiguos": [ids], "candidatos": [...]}."""
    n_pages = len(pages_words)
    doc = " " + " ".join(page_norm_text(w) for w in pages_words) + " "
    scored = []
    for t in templates:
        rec = t["reconhecimento"]
        if not rec["paginas_min"] <= n_pages <= rec["paginas_max"]:
            continue
        found = [a for a in rec["ancoras"] if norm(a) and f" {norm(a)} " in doc]
        score = len(found) / len(rec["ancoras"])
        scored.append((round(score, 3), t, found))
    scored.sort(key=lambda s: s[0], reverse=True)
    candidates = [{"id": t["id"], "pontuacao": s} for s, t, _ in scored[:5]]
    passing = [s for s in scored if s[0] >= s[1]["reconhecimento"]["minimo"]]
    if not passing:
        return {"modelo": None, "pontuacao": 0, "ancoras_encontradas": [], "ambiguos": [], "candidatos": candidates}
    if len(passing) > 1:
        return {"modelo": None, "pontuacao": passing[0][0], "ancoras_encontradas": [],
                "ambiguos": [p[1]["id"] for p in passing], "candidatos": candidates}
    score, template, found = passing[0]
    return {"modelo": template, "pontuacao": score, "ancoras_encontradas": found, "ambiguos": [],
            "candidatos": candidates}


# ------------------------------------------------------------------------------------------- campos
def _label_tokens(label):
    return [t for t in (norm_token(x) for x in str(label).split()) if t]


def _looks_like_label(text):
    """'Fone:' / 'CPF/CNPJ:' / 'Data da licença:' (fim de rótulo): o valor de um campo nunca entra nele."""
    text = str(text).strip()
    return text.endswith(":") and 1 < len(text) <= 32 and bool(re.search(r"[A-Za-zÀ-ÿ]", text))


def _find_label(words, line, tokens):
    """Ocorrências do rótulo na linha: [(posição da última palavra do rótulo, início do valor colado | None)]."""
    out = []
    norms = [norm_token(words[i].get("text", "")) for i in line]
    n = len(tokens)
    for start in range(len(line)):
        if start + n > len(line):
            break
        head, last = norms[start:start + n - 1], norms[start + n - 1]
        if head != tokens[:-1]:
            continue
        raw = str(words[line[start + n - 1]].get("text", ""))
        if last == tokens[-1]:
            out.append((start + n - 1, None))
        elif last.startswith(tokens[-1]) and ":" in raw:
            # rótulo colado no valor ("CPF:12345678900"): só o que vem depois do ":" é valor
            cut = raw.index(":") + 1
            if norm_token(raw[:cut]) == tokens[-1] and cut < len(raw):
                out.append((start + n - 1, cut))
    return out


def _starts_label(words, line, pos, stop_tokens):
    if _looks_like_label(words[line[pos]].get("text", "")):
        return True
    # outro rótulo começando aqui, inclusive colado no valor ("CPF:123..."): o valor anterior termina antes dele.
    # Só na forma de rótulo (com ':'): "Avenida Cidade Jardim" e "FULANO Pai DE TAL" não cortam o valor (I-03)
    return any(t and any(p == len(t) - 1 and has_colon(words, line, pos + p, glued)
                         for p, glued in _find_label(words, line[pos:pos + len(t)], t))
               for t in stop_tokens)


def _take(words, line, start, max_words, stop_tokens, min_x=None):
    """Palavras do valor a partir de 'start' até o próximo rótulo. Devolve (ids, truncado)."""
    taken = []
    for pos in range(start, len(line)):
        wid = line[pos]
        if str(words[wid].get("text", "")).strip() == ":":
            continue  # "Fone :" com o dois-pontos separado
        if min_x is not None and words[wid]["box"]["x"] + words[wid]["box"]["w"] < min_x:
            continue
        if _starts_label(words, line, pos, stop_tokens):
            return taken, False
        if len(taken) >= max_words:
            return taken, True
        taken.append(wid)
    return taken, False


def has_colon(words, line, pos, glued):
    """O rótulo termina em ':' (colado, na mesma palavra ou na seguinte): é rótulo, não palavra solta no texto."""
    raw = str(words[line[pos]].get("text", "")).strip()
    nxt = str(words[line[pos + 1]].get("text", "")).strip() if pos + 1 < len(line) else ""
    return glued is not None or raw.endswith(":") or nxt.startswith(":")


def extract(words, field, stop_labels=()):
    """Comandos de tarja {id da palavra: {índices}} do campo nesta página e as ocorrências achadas."""
    tokens = _label_tokens(field["rotulo"])
    stops = [_label_tokens(s) for s in stop_labels if _label_tokens(s) != tokens]
    if not tokens:
        return {}, []
    rows = lines(words)
    commands, found = {}, []
    for li, line in enumerate(rows):
        for pos, glued in _find_label(words, line, tokens):
            label_box = words[line[pos]]["box"]
            ids, truncated = [], False
            if field["direcao"] == "direita" and not has_colon(words, line, pos, glued):
                continue  # "Nome do empreendimento:" não é o rótulo "Nome:"
            if field["direcao"] == "direita":
                if glued is not None:
                    raw = str(words[line[pos]].get("text", ""))
                    commands.setdefault(line[pos], set()).update(range(glued, len(raw)))
                ids, truncated = _take(words, line, pos + 1, field["max_palavras"], stops)
                # valor que quebra para a linha de baixo (endereço): a continuação começa na margem do rótulo ou depois
                line_x = words[line[0]]["box"]["x"]
                for extra in rows[li + 1: li + field["linhas"]]:
                    more, cut = _take(words, extra, 0, field["max_palavras"], stops, min_x=line_x - label_box["h"])
                    ids += more
                    truncated = truncated or cut
            else:
                min_x = label_box["x"] - 2 * label_box["h"]
                for extra in rows[li + 1: li + 1 + field["linhas"]]:
                    more, cut = _take(words, extra, 0, field["max_palavras"], stops, min_x=min_x)
                    ids += more
                    truncated = truncated or cut
            for wid in ids:
                commands.setdefault(wid, set()).update(range(len(str(words[wid].get("text", "")))))
            found.append({"palavras": len(ids) + (1 if glued is not None else 0), "truncado": truncated})
    return commands, found


def apply(template, pages_words):
    """Aplica os campos em cada página. Devolve {página: {"comandos", "campos": {rótulo: [ocorrências]}}} e a lista
    de rótulos obrigatórios não achados (no documento ou na página indicada)."""
    labels = [f["rotulo"] for f in template["campos"]]
    result, missing = {}, []
    for field in template["campos"]:
        pages = field["paginas"] or list(range(1, len(pages_words) + 1))
        located = False
        for page in pages:
            if page > len(pages_words):
                if field["obrigatorio"]:  # página que o documento não tem: campo não achado (documento todo)
                    missing.append((0, field["rotulo"]))
                continue
            commands, found = extract(pages_words[page - 1], field, labels)
            slot = result.setdefault(page, {"comandos": {}, "campos": {}})
            for wid, chars in commands.items():
                slot["comandos"].setdefault(wid, set()).update(chars)
            if found:
                slot["campos"].setdefault(field["rotulo"], []).extend(found)
            # rótulo achado com valor vazio (ex.: o valor caiu na linha de baixo) não é campo achado (I-13)
            empty = any(not o["palavras"] for o in found)
            located = located or any(o["palavras"] for o in found)
            if field["obrigatorio"] and (empty or (field["paginas"] and not found)):
                missing.append((page, field["rotulo"]))
        if field["obrigatorio"] and not field["paginas"] and not located:
            missing.append((0, field["rotulo"]))
    return result, list(dict.fromkeys(missing))


# ------------------------------------------------------------------------------------------- inspeção
@lru_cache(maxsize=1)
def inspection_labels():
    """Rótulos que costumam vir antes de dado pessoal (regras como dados: utils/detect/data/rotulos_inspecao.json)."""
    with open(DATA, encoding="utf-8") as fh:
        return tuple(json.load(fh)["rotulos"])


def covered_ids(words, boxes):
    """Palavras cujo centro está dentro de alguma tarja ({x, y, w, h} em pixels)."""
    out = set()
    for i, w in enumerate(words):
        b = w["box"]
        cx, cy = b["x"] + b["w"] / 2, b["y"] + b["h"] / 2
        if any(r["x"] <= cx <= r["x"] + r["w"] and r["y"] <= cy <= r["y"] + r["h"] for r in boxes):
            out.add(i)
    return out


def touched_ids(words, boxes):
    """Palavras com QUALQUER parte sob uma tarja ('PROPRIETARIO:ANA' numa palavra só, tarja só sobre 'ANA': o centro
    fica fora). Folga de 1/4 da altura (menos de um caractere) para a borda de uma tarja vizinha. Para mascarar o
    texto que vai a uma IA."""
    out = set()
    for i, w in enumerate(words):
        b = w["box"]
        for r in boxes:
            ox = min(b["x"] + b["w"], r["x"] + r["w"]) - max(b["x"], r["x"])
            oy = min(b["y"] + b["h"], r["y"] + r["h"]) - max(b["y"], r["y"])
            if ox > 0.25 * b["h"] and oy > 0.25 * b["h"]:
                out.add(i)
                break
    return out


def inspect_labels(words, covered):
    """Rótulo típico de dado pessoal ("Fone:", "CPF:") com valor ao lado SEM tarja: [(rótulo, [ids sem tarja])]."""
    out = []
    labels = inspection_labels()
    for label in labels:
        field = {"rotulo": label, "direcao": "direita", "max_palavras": 8, "linhas": 1}
        for line in lines(words):
            for pos, glued in _find_label(words, line, _label_tokens(label)):
                if not has_colon(words, line, pos, glued):
                    continue  # a palavra solta "nome" no meio do texto não é rótulo
                ids, _ = _take(words, line, pos + 1, field["max_palavras"], [_label_tokens(x) for x in labels])
                if glued is not None and line[pos] not in covered:
                    ids.append(line[pos])
                loose = [i for i in ids if i not in covered]
                if loose:
                    out.append((label, loose))
    return out


def masked_text(words, covered):
    """Texto da página com as palavras tarjadas trocadas por █ (o que vai ao agente de inspeção)."""
    return "\n".join(" ".join("█████" if i in covered else str(words[i].get("text", "")) for i in ln)
                     for ln in lines(words))

# SPDX-License-Identifier: AGPL-3.0-or-later
"""Formato do modelo de documento, validação estrita e pasta de modelos.

Modelos feitos a partir de documentos reais podem conter texto desses documentos (âncoras): a pasta padrão
(./modelos_documento) fica fora do git e da imagem Docker. Modelo importado ou editado volta a ser rascunho: só a
aprovação explícita (POST /doc-templates/{id}/aprovar) libera dispensar a IA.
"""
import json
import os
import re
import tempfile
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# o id vira nome de arquivo: nomes reservados do Windows ("con.json", "nul.json") travam a leitura/gravação
ID_RE = re.compile(r"^(?!(?:con|prn|aux|nul|com[1-9]|lpt[1-9])\Z)[a-z0-9][a-z0-9_-]{1,63}\Z")
STATUS = ("rascunho", "aprovado")
DIRECTIONS = ("direita", "abaixo")


class TemplateError(ValueError):
    pass


def folder():
    return os.getenv("PRIVIO_DOC_TEMPLATES_DIR") or os.path.join(BASE_DIR, "modelos_documento")


def _text(value, name, maximum, required=True):
    value = str(value if value is not None else "").strip()
    if required and not value:
        raise TemplateError(f"{name}: obrigatório")
    if len(value) > maximum or any(c in value for c in "\r\n\0"):
        raise TemplateError(f"{name}: até {maximum} caracteres, numa linha")
    return value


def _int(value, name, lo, hi):
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise TemplateError(f"{name}: número inteiro")
    if not lo <= number <= hi:
        raise TemplateError(f"{name}: entre {lo} e {hi}")
    return number


def slug(text):
    import unicodedata
    s = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode("ascii").lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")[:60]
    return s if ID_RE.match(s or "") else "modelo"


def free_id(tid):
    """'tid' se ainda não há modelo com ele; senão 'tid-2', 'tid-3'... (rascunho nunca troca um modelo salvo)."""
    for n in range(1, 1000):
        cand = tid if n == 1 else f"{tid[:60]}-{n}"
        if ID_RE.match(cand) and not os.path.exists(_path(cand)):
            return cand
    raise TemplateError("Modelos demais com o mesmo nome")


def validate(data):
    """Devolve o modelo normalizado ou levanta TemplateError. Campos desconhecidos são descartados."""
    if not isinstance(data, dict):
        raise TemplateError("Modelo precisa ser um objeto JSON")
    tid = str(data.get("id") or "").strip().lower()
    if not ID_RE.match(tid):
        raise TemplateError("id: letras minúsculas, números, - e _ (2 a 64)")
    rec = data.get("reconhecimento") or {}
    anchors = [_text(a, "âncora", 200) for a in (rec.get("ancoras") or []) if str(a or "").strip()]
    if not 1 <= len(anchors) <= 30:
        raise TemplateError("reconhecimento.ancoras: de 1 a 30 frases fixas do documento (título, cabeçalho)")
    try:
        minimum = float(rec.get("minimo", 0.8))
    except (TypeError, ValueError):
        raise TemplateError("reconhecimento.minimo: número entre 0,5 e 1")
    if not 0.5 <= minimum <= 1:
        raise TemplateError("reconhecimento.minimo: entre 0,5 e 1")
    pmin = _int(rec.get("paginas_min", 1), "paginas_min", 1, 2000)
    pmax = _int(rec.get("paginas_max", 2000), "paginas_max", pmin, 2000)
    fields = []
    for i, f in enumerate(data.get("campos") or []):
        if not isinstance(f, dict):
            raise TemplateError(f"campo {i + 1}: objeto")
        direction = str(f.get("direcao") or "direita")
        if direction not in DIRECTIONS:
            raise TemplateError(f"campo {i + 1}: direção 'direita' ou 'abaixo'")
        pages = f.get("paginas") or []
        if not isinstance(pages, list):
            raise TemplateError(f"campo {i + 1}: paginas é uma lista")
        fields.append({"rotulo": _text(f.get("rotulo"), f"campo {i + 1}: rótulo", 80),
                       "tipo": _text(f.get("tipo") or "outro", f"campo {i + 1}: tipo", 40),
                       "direcao": direction,
                       "max_palavras": _int(f.get("max_palavras", 12), f"campo {i + 1}: máximo de palavras", 1, 60),
                       "linhas": _int(f.get("linhas", 1), f"campo {i + 1}: linhas", 1, 6),
                       "obrigatorio": bool(f.get("obrigatorio", True)),
                       "paginas": sorted({_int(p, f"campo {i + 1}: página", 1, 2000) for p in pages}),
                       "sugerido_ia": bool(f.get("sugerido_ia", False))})
    if not fields:
        raise TemplateError("campos: ao menos um campo (rótulo seguido do dado pessoal)")
    if len(fields) > 100:
        raise TemplateError("campos: até 100")
    status = str(data.get("status") or "rascunho")
    if status not in STATUS:
        raise TemplateError("status: rascunho ou aprovado")
    return {"id": tid, "nome": _text(data.get("nome") or tid, "nome", 120),
            "descricao": _text(data.get("descricao"), "descrição", 500, required=False),
            "versao": _int(data.get("versao", 1), "versao", 1, 10**6), "status": status,
            "reconhecimento": {"ancoras": anchors, "minimo": round(minimum, 3), "paginas_min": pmin,
                               "paginas_max": pmax},
            "campos": fields, "dispensa_ia": bool(data.get("dispensa_ia", False)),
            "origem": _text(data.get("origem") or "manual", "origem", 40),
            "criado_em": str(data.get("criado_em") or "")[:32], "atualizado_em": str(data.get("atualizado_em") or "")[:32],
            "aprovado_em": str(data.get("aprovado_em") or "")[:32]}


def _path(tid):
    if not ID_RE.match(tid or ""):
        raise TemplateError("id inválido")
    return os.path.join(folder(), f"{tid}.json")


def load_all():
    """Modelos válidos da pasta. Arquivo inválido é ignorado (e listado em 'erros')."""
    out, errors = [], []
    try:
        names = sorted(os.listdir(folder()))
    except OSError:
        return [], []
    for name in names:
        if not name.endswith(".json"):
            continue
        try:
            with open(os.path.join(folder(), name), encoding="utf-8") as fh:
                out.append(validate(json.load(fh)))
        except (OSError, ValueError) as e:
            errors.append(f"{name}: {e}")
    return out, errors


def get(tid):
    try:
        with open(_path(tid), encoding="utf-8") as fh:
            return validate(json.load(fh))
    except FileNotFoundError:
        return None


def save(data, approve=False):
    """Grava o modelo. Edição (ou importação) volta a rascunho e sobe a versão; approve=True só aprova o que já está
    salvo, sem mudar o conteúdo."""
    now = datetime.now().isoformat(timespec="seconds")
    if approve:
        old = get(str((data or {}).get("id") or ""))
        if old is None:
            raise TemplateError("Modelo não existe")
        return _write(dict(old, status="aprovado", aprovado_em=now, atualizado_em=now))
    template = validate(data)
    old = get(template["id"])
    content = lambda t: {k: v for k, v in t.items() if k not in ("status", "versao", "criado_em",  # noqa: E731
                                                                  "atualizado_em", "aprovado_em")}
    changed = old is None or content(old) != content(template)
    template["status"] = "rascunho" if changed else old["status"]
    template["versao"] = (old["versao"] + 1 if changed else old["versao"]) if old else 1
    template["criado_em"] = (old or {}).get("criado_em") or now
    template["aprovado_em"] = "" if template["status"] == "rascunho" else old.get("aprovado_em", "")
    template["atualizado_em"] = now
    return _write(template)


def _write(template):
    os.makedirs(folder(), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=folder(), suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(template, fh, indent=2, ensure_ascii=False)
    os.replace(tmp, _path(template["id"]))
    return template


def delete(tid):
    try:
        os.remove(_path(tid))
        return True
    except FileNotFoundError:
        return False

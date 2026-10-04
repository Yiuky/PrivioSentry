# SPDX-License-Identifier: AGPL-3.0-or-later
"""Detector OPCIONAL de nomes de pessoa (e filiação) por reconhecimento de entidades (GLiNER), 100% local.

Desligado por padrão. Para ligar:
    pip install -e ".[nomes]"         (instala o pacote gliner)
    NER_ENGINE=gliner                 (no .env)
    NER_MODEL / NER_MODEL_REVISION    (opcional: outro modelo; o padrão já vem com commit fixado)

Medido com o modelo padrão (CPU, texto fictício em português): ~0,3 s por página e ~20 s para carregar uma vez.

Nome é o tipo de PII mais difícil por regra: não tem formato. O modelo dá uma CONFIANÇA para cada nome achado e
os limiares ficam em utils/detect/data/parametros.json ("nomes"):
    confiança >= limiar_tarjar     tarja sugerida (se o perfil manda tarjar)
    limiar_alertar <= confiança    só marca a região para revisão
    abaixo                         ignorado
Se o perfil manda apenas "alertar", tudo o que passar do limiar de alerta vira revisão. Se o detector estiver
ligado e falhar, o pipeline marca o documento para revisão (falha fechada); desligado, nomes simplesmente não são
procurados (o catálogo mostra o tipo como "opcional").

Filiação: um nome logo depois de "filho de", "mãe", "genitora"... (contextos.json, "filiacao") é filiação.
"""
import importlib.util
import logging
import os
import re
import threading

from . import config
from .rules import _norm, build_text

logger = logging.getLogger("detect.ner")

TYPES = ("nome_pessoa", "filiacao")
DEFAULT_MODEL = "urchade/gliner_multi_pii-v1"  # multilíngue, treinado para PII (Apache-2.0)
# Cadeia de suprimentos: o modelo baixado nunca "flutua" no Hugging Face (mesma política do Laya)
PINNED_MODEL_REVISIONS = {DEFAULT_MODEL: "1fcf13e85f4eef5394e1fcd406cf2ca9ea82351d"}

_engine = None
_engine_error = None
_lock = threading.Lock()


class NERUnavailable(RuntimeError):
    pass


def engine_name():
    return (os.getenv("NER_ENGINE") or "").strip().lower()


def enabled():
    """Ligado pela configuração (não diz se o pacote está instalado)."""
    return engine_name() == "gliner"


def available():
    """Ligado e com o pacote instalado (barato: não carrega o modelo)."""
    return enabled() and importlib.util.find_spec("gliner") is not None


def revision_for(model_id, explicit=None):
    """Revisão explícita > commit fixado aqui > pasta local (sem revisão). Remoto sem commit = erro."""
    if explicit and explicit.strip():
        return explicit.strip()
    if os.path.isdir(model_id):
        return None
    pinned = {k.lower(): v for k, v in PINNED_MODEL_REVISIONS.items()}.get(model_id.lower())
    if pinned is None:
        raise ValueError(f"modelo {model_id!r} sem commit fixo: defina NER_MODEL_REVISION=<commit> ou use uma pasta local")
    return pinned


class GlinerEngine:
    """Adaptador fino: predict(texto, rótulos, limiar) -> [{"start", "end", "label", "score"}]."""

    def __init__(self, model=None, revision=None):
        try:  # redes com inspeção TLS (proxy corporativo): certificados do sistema
            import truststore
            truststore.inject_into_ssl()
        except ImportError:
            pass
        from gliner import GLiNER
        self.model_id = model or os.getenv("NER_MODEL") or DEFAULT_MODEL
        self.revision = revision_for(self.model_id, revision or os.getenv("NER_MODEL_REVISION"))
        logger.info(f"[ner] carregando {self.model_id} ({self.revision or 'pasta local'})...")
        self.model = GLiNER.from_pretrained(self.model_id, revision=self.revision)

    def predict(self, text, labels, threshold):
        return self.model.predict_entities(text, list(labels), threshold=threshold)


def get_engine():
    """Carrega o modelo uma vez (preguiçoso). Levanta NERUnavailable se não der."""
    global _engine, _engine_error
    if not enabled():
        raise NERUnavailable("NER_ENGINE não está ligado")
    with _lock:
        if _engine is None and _engine_error is None:
            try:
                _engine = GlinerEngine()
            except Exception as e:  # pacote ausente, sem rede no primeiro download, modelo inválido...
                _engine_error = f"{type(e).__name__}: {e}"
        if _engine is None:
            raise NERUnavailable(_engine_error)
        return _engine


def preload():
    """Começa a carregar o modelo em segundo plano (get_engine depois espera o fim, pelo mesmo lock)."""
    if not enabled():
        return None

    def run():
        try:
            get_engine()
        except NERUnavailable:
            pass  # o erro fica guardado e a fase de política o trata (revisão)
    thread = threading.Thread(target=run, name="ner-preload", daemon=True)
    thread.start()
    return thread


def reset():
    """Para testes."""
    global _engine, _engine_error
    with _lock:
        _engine, _engine_error = None, None


def _chunks(text, size):
    """Blocos de até `size` caracteres cortados em espaço (o modelo tem limite de tamanho de entrada)."""
    start = 0
    while start < len(text):
        end = min(len(text), start + size)
        if end < len(text):
            cut = text.rfind(" ", start + size // 2, end)
            end = cut if cut > start else end
        yield start, text[start:end]
        start = end


def _role_matcher():
    """Palavras que nunca são nome (contextos.json, nome_pessoa.nunca_nome; '*' = prefixo) + conectores."""
    exact, prefixes = set(), []
    for item in config.strings("nome_pessoa", "nunca_nome"):
        item = _norm(item)
        if item.endswith("*"):
            prefixes.append(item.rstrip("*"))
        else:
            exact.add(item)
    exact |= {c.lower() for c in config.lexicon()["conectores_sem_acento"]}

    def is_role(token):
        tok = re.sub(r"\((?:s|es|as|os|a|o)\)$", "", _norm(token).strip(".,:;!?\"'")).strip("()")
        if not tok:
            return True  # "(s)", pontuação solta
        return tok in exact or any(tok.startswith(p) for p in prefixes)
    return is_role


def _trim(text, start, end, is_role):
    """Tira das pontas do trecho as palavras de papel/conectores. Devolve (início, fim) ou None se não sobrar nada."""
    tokens = [(start + m.start(), start + m.end()) for m in re.finditer(r"\S+", text[start:end])]
    while tokens and is_role(text[tokens[0][0]:tokens[0][1]]):
        tokens.pop(0)
    while tokens and is_role(text[tokens[-1][0]:tokens[-1][1]]):
        tokens.pop()
    return (tokens[0][0], tokens[-1][1]) if tokens else None


def find_names(grounding, engine=None):
    """
    Nomes no mapa de palavras. Devolve {tipo: {"tarjar": comandos, "alertar": comandos, "valores": set}},
    com comandos no formato das regras ({id da palavra: {índices dos caracteres}}).
    """
    text, char_map = build_text(grounding)
    if not text.strip():
        return {}
    engine = engine or get_engine()
    high = config.param("nomes", "limiar_tarjar")
    low = config.param("nomes", "limiar_alertar")
    size = int(config.param("nomes", "tamanho_bloco"))
    window = int(config.param("nomes", "janela_filiacao"))
    labels = config.strings("nome_pessoa", "rotulos_ner") or ("person",)
    filiation_ctx = config.context("filiacao")[0]
    norm_text = _norm(text)
    is_role = _role_matcher()
    out = {}
    for offset, chunk in _chunks(text, size):
        for ent in engine.predict(chunk, labels, low) or []:
            try:
                start, end, score = offset + int(ent["start"]), offset + int(ent["end"]), float(ent["score"])
            except (KeyError, TypeError, ValueError):
                continue
            if score < low or start >= end:
                continue
            # "analista", "Responsável Técnico Fulano", "o(s) devedor(es)": o modelo marca papéis como pessoa.
            # Só o nome é tarjado; trecho só de papéis é descartado.
            span = _trim(text, start, end, is_role)
            if span is None:
                continue
            start, end = span
            before = norm_text[max(0, start - window):start] if len(norm_text) == len(text) else \
                _norm(text[max(0, start - window):start])
            type_id = "filiacao" if filiation_ctx is not None and filiation_ctx.search(before) else "nome_pessoa"
            slot = out.setdefault(type_id, {"tarjar": {}, "alertar": {}, "valores": set()})
            target = slot["tarjar"] if score >= high else slot["alertar"]
            for pos in range(start, min(end, len(char_map))):
                ref = char_map[pos]
                if ref is not None and not text[pos].isspace():
                    target.setdefault(ref[0], set()).add(ref[1])
            slot["valores"].add(" ".join(text[start:end].split()).lower())
    return out

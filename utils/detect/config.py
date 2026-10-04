# SPDX-License-Identifier: AGPL-3.0-or-later
"""Regras e limiares como DADOS versionados (utils/detect/data/*.json), não como código.

    lexico.json      palavras nunca tarjadas como endereço (termos estruturais e conectores)
    parametros.json  limiares das heurísticas (casamento de endereços, ruído de OCR)
    contextos.json   palavras de contexto de cada detector por regra

Mudou um arquivo? Rode o corpus de avaliação (python -m benchmarks.pii_eval) e os testes: a mudança precisa
manter ou melhorar as métricas. Os arquivos são validados ao carregar (erro claro em vez de comportamento estranho).
"""
import json
import os
import re
import unicodedata
from functools import lru_cache

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")


class ConfigError(ValueError):
    pass


@lru_cache(maxsize=None)
def _load(name):
    path = os.path.join(DATA_DIR, name)
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        raise ConfigError(f"{name}: não foi possível ler ({e})") from e
    if not isinstance(data, dict):
        raise ConfigError(f"{name}: o conteúdo precisa ser um objeto JSON")
    return data


def _strip(text):
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")


@lru_cache(maxsize=None)
def lexicon():
    data = _load("lexico.json")
    out = {}
    for key in ("imunes", "conectores"):
        words = data.get(key)
        if not isinstance(words, list) or not all(isinstance(w, str) and w.strip() for w in words):
            raise ConfigError(f"lexico.json: '{key}' precisa ser uma lista de palavras")
        out[key] = frozenset(w.strip().upper() for w in words)
    out["conectores_sem_acento"] = frozenset(_strip(w) for w in out["conectores"])
    return out


def param(section, key):
    """Limiar numérico de parametros.json (ex.: param("endereco", "cobertura_minima"))."""
    value = _load("parametros.json").get(section, {}).get(key)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ConfigError(f"parametros.json: '{section}.{key}' precisa ser um número")
    return value


def phrase_regex(phrases):
    """Frases simples -> regex. Espaço = qualquer espaçamento; final '*' = prefixo; '.' e '/' são literais."""
    parts = []
    for raw in phrases:
        phrase = _strip(str(raw).strip().lower())
        if not phrase:
            continue
        prefix = phrase.endswith("*")
        phrase = phrase.rstrip("*")
        body = r"\s+".join(re.escape(tok) for tok in phrase.split())
        start = r"\b" if phrase[0].isalnum() else ""
        end = "" if prefix or not phrase[-1].isalnum() else r"\b"
        parts.append(f"{start}{body}{end}")
    if not parts:
        return None
    return re.compile("|".join(f"(?:{p})" for p in parts))


@lru_cache(maxsize=None)
def context(type_id):
    """(regex das palavras de contexto, regex das palavras de 'parar') do detector, ou (None, None)."""
    entry = _load("contextos.json").get(type_id)
    if entry is None:
        return None, None
    if not isinstance(entry, dict) or not isinstance(entry.get("palavras", []), list):
        raise ConfigError(f"contextos.json: '{type_id}' precisa ter a lista 'palavras'")
    return phrase_regex(entry.get("palavras", [])), phrase_regex(entry.get("parar", []))


def strings(type_id, key):
    """Lista de textos extra de um detector em contextos.json (ex.: strings("email", "arroba_ocr"))."""
    entry = _load("contextos.json").get(type_id) or {}
    items = entry.get(key, [])
    if not isinstance(items, list) or not all(isinstance(i, str) and i.strip() for i in items):
        raise ConfigError(f"contextos.json: '{type_id}.{key}' precisa ser uma lista de textos")
    return tuple(i.strip() for i in items)


def clear_cache():
    """Para testes que trocam os arquivos de dados."""
    for fn in (_load, lexicon, context):
        fn.cache_clear()

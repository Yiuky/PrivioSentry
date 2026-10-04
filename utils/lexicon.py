# SPDX-License-Identifier: AGPL-3.0-or-later
"""Termos estruturais de endereço que NUNCA devem ser tarjados (dados em utils/detect/data/lexico.json)."""

from utils.detect import config as _config

# Fonte única: utils/detect/data/lexico.json (edite lá; os testes validam o formato)
IMMUNE_WORDS = set(_config.lexicon()["imunes"])
_SHORT_CONNECTORS = set(_config.lexicon()["conectores"])


def _strip_accents(text):
    import unicodedata
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")


def is_immune(word):
    """True se a palavra é um termo estrutural/conector que não deve ser tarjado."""
    w = word.strip(" \t\r\n.,;:/-()[]{}").upper()
    if not w:
        return True
    # Se contiver números, nunca é imune
    if any(char.isdigit() for char in w):
        return False
    if w in _SHORT_CONNECTORS or _strip_accents(w) in _SHORT_CONNECTORS:  # "À", "ÀS" também são conectores
        return True
    return w in IMMUNE_WORDS

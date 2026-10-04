# SPDX-License-Identifier: AGPL-3.0-or-later
"""Descoberta do Tesseract para benchmarks e testes (sem caminhos fixos de usuario)."""
import os
import shutil

_COMMON_PATHS = [
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files\PDF24\tesseract\tesseract.exe",
    "/usr/bin/tesseract",
    "/usr/local/bin/tesseract",
    "/opt/homebrew/bin/tesseract",
]


def find_tesseract():
    """Caminho do executavel do Tesseract ou None. Ordem: TESSERACT_PATH, PATH, locais comuns."""
    configured = os.getenv("TESSERACT_PATH")
    if configured and os.path.exists(configured):
        return configured
    on_path = shutil.which("tesseract")
    if on_path:
        return on_path
    for p in _COMMON_PATHS:
        if os.path.exists(p):
            return p
    return None


def pick_language(tesseract_path):
    """'por' se instalado, senao 'eng'; None se o Tesseract nao responde/nao tem idiomas."""
    import pytesseract
    pytesseract.pytesseract.tesseract_cmd = tesseract_path
    try:
        langs = set(pytesseract.get_languages(config=""))
    except Exception:
        return None
    for wanted in ("por", "eng"):
        if wanted in langs:
            return wanted
    return None


def get_ocr_config():
    """(tesseract_path, lang) utilizaveis, ou None."""
    path = find_tesseract()
    if not path:
        return None
    lang = pick_language(path)
    return (path, lang) if lang else None

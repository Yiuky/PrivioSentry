# SPDX-License-Identifier: AGPL-3.0-or-later
"""Constantes e utilitarios compartilhados pelos testes (sem dados reais)."""
import os
import re

import fitz

# CPFs FICTICIOS com digitos verificadores validos (nao pertencem a ninguem; uso exclusivo em testes).
CPF_A = "52998224725"
CPF_A_FMT = "529.982.247-25"
CPF_B = "11144477735"
CPF_B_FMT = "111.444.777-35"

# Qualquer CPF completo (formatado ou 11 digitos corridos) -- usado para varrer artefatos.
FULL_CPF_RE = re.compile(r"(?<!\d)\d{3}\.?\d{3}\.?\d{3}-?\d{2}(?!\d)")


def word(i, text, x, y=100, w=None, h=30, conf=90):
    """Palavra de grounding map."""
    return {"id": i, "text": text, "box": {"x": x, "y": y, "w": w or 20 * len(text), "h": h}, "conf": conf}


def make_text_pdf(path, text="pagina", n_pages=1):
    os.makedirs(os.path.dirname(str(path)) or ".", exist_ok=True)
    doc = fitz.open()
    for i in range(n_pages):
        doc.new_page().insert_text((72, 100), f"{text} {i + 1}")
    doc.save(str(path))
    doc.close()
    return str(path)


def make_blank_image(path, size=(200, 280), color=(255, 255, 255)):
    from PIL import Image
    Image.new("RGB", size, color).save(str(path))
    return str(path)


def text_files_under(root, exts=(".txt", ".log", ".json")):
    for dirpath, _, files in os.walk(root):
        for name in files:
            if name.lower().endswith(exts):
                yield os.path.join(dirpath, name)

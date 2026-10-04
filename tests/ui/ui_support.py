# SPDX-License-Identifier: AGPL-3.0-or-later
"""Helpers de dados sintéticos para os testes de UI (módulo normal, importável pelos testes)."""
import os

PAGE_W, PAGE_H = 700, 1000
FAKE_PDF = b"%PDF-1.4\n%fake\n"


def make_png(path, page_no=1, w=PAGE_W, h=PAGE_H):
    from PIL import Image, ImageDraw
    os.makedirs(os.path.dirname(path), exist_ok=True)
    img = Image.new("RGB", (w, h), "white")
    d = ImageDraw.Draw(img)
    d.text((40, 40), f"Pagina sintetica {page_no}", fill="black")
    d.text((40, 80), "CPF ficticio: 111.444.777-35", fill="black")
    img.save(path)


def make_pdf(path, pages=1):
    import fitz
    os.makedirs(os.path.dirname(path), exist_ok=True)
    doc = fitz.open()
    for i in range(pages):
        pg = doc.new_page()
        pg.insert_text((72, 72), f"Pagina sintetica {i + 1}")
    doc.save(path)
    doc.close()


def box(page=1, coords=(100, 100, 300, 180), source="AI", type_="pii"):
    return {"page": page, "coords": list(coords), "source": source, "type": type_,
            "image_width": PAGE_W, "image_height": PAGE_H}



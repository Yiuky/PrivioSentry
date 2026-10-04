# SPDX-License-Identifier: AGPL-3.0-or-later
"""Generate a fully SYNTHETIC sample PDF to try the redaction pipeline.

Everything in the output is fictional: names, addresses and CPF numbers
(the CPFs only satisfy the check-digit algorithm; they are public "test" numbers).
No real personal data is used or should ever be added to this repository.

Usage:  python examples/make_sample_pdf.py [output.pdf]
"""
import math
import os
import sys

import fitz  # PyMuPDF

FICTIONAL_CPFS = ["529.982.247-25", "111.444.777-35"]


def cpf_is_valid(cpf: str) -> bool:
    d = [int(c) for c in cpf if c.isdigit()]
    if len(d) != 11 or len(set(d)) == 1:
        return False
    for n in (9, 10):
        s = sum(d[i] * (n + 1 - i) for i in range(n))
        if (s * 10 % 11) % 10 != d[n]:
            return False
    return True


def draw_signature(page, x, y, w=140, h=40):
    """Draw a scribble that looks vaguely like a handwritten signature."""
    pts = []
    for i in range(60):
        t = i / 59
        px = x + t * w
        py = y + h / 2 + math.sin(t * 14) * h * 0.35 * (1 - t * 0.5) + math.cos(t * 5) * 4
        pts.append(fitz.Point(px, py))
    shape = page.new_shape()
    shape.draw_polyline(pts)
    shape.finish(color=(0.05, 0.05, 0.45), width=1.6, closePath=False)
    shape.commit()


def build(out_path: str):
    assert all(cpf_is_valid(c) for c in FICTIONAL_CPFS)
    doc = fitz.open()

    # Page 1: native-text page
    p = doc.new_page(width=595, height=842)
    p.insert_text((60, 80), "SAMPLE ADMINISTRATIVE FORM (FICTIONAL DATA)", fontsize=14)
    lines = [
        "Applicant: Maria Exemplo da Silva Teste",
        f"CPF: {FICTIONAL_CPFS[0]}",
        "Residential address: Rua das Acacias Ficticias, 123, Bairro Exemplo,",
        "Cidade Ficticia - UF, CEP 00000-000",
        "",
        "Company address (business, should NOT be redacted):",
        "Avenida Comercial Ficticia, 1000, Sala 10 - Centro",
        "",
        "Declaration: I declare that the information above is true.",
    ]
    y = 120
    for ln in lines:
        p.insert_text((60, y), ln, fontsize=11)
        y += 20
    p.insert_text((60, 600), "______________________________", fontsize=11)
    draw_signature(p, 70, 560)
    p.insert_text((60, 620), f"Maria Exemplo da Silva Teste - CPF {FICTIONAL_CPFS[0]}", fontsize=9)

    # Page 2: "scanned" page (rasterized to an image, no native text)
    tmp = fitz.open()
    q = tmp.new_page(width=595, height=842)
    q.insert_text((60, 80), "SAMPLE SCANNED PAGE (FICTIONAL DATA)", fontsize=14)
    q.insert_text((60, 130), "Representative: Joao Ficticio de Teste", fontsize=11)
    q.insert_text((60, 150), f"CPF: {FICTIONAL_CPFS[1]}", fontsize=11)
    q.insert_text((60, 170), "Endereco: Travessa dos Testes, 45, Bairro Imaginario, Cidade Ficticia - UF", fontsize=10)
    draw_signature(q, 70, 520, 160, 45)
    q.insert_text((60, 590), "Assinatura do representante", fontsize=9)
    pix = q.get_pixmap(dpi=200)
    p2 = doc.new_page(width=595, height=842)
    p2.insert_image(p2.rect, stream=pix.tobytes("png"))

    doc.set_metadata({"title": "Synthetic sample", "author": "", "creator": "examples/make_sample_pdf.py"})
    doc.save(out_path, deflate=True)
    doc.close()


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "sample_input.pdf")
    build(out)
    print(f"Wrote {out}")

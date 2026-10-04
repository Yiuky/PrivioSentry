# SPDX-License-Identifier: AGPL-3.0-or-later
"""Gerador de documentos escaneados SINTETICOS (nenhum dado real) com ground truth.

Cada pagina contem: CPFs validos (alvo da tarja), "iscas" que NAO devem ser tarjadas (CPF com digito
verificador errado, CNPJ valido, datas, numero de processo, telefone) e texto corrido. A pagina e
degradada para parecer um scan: ruido gaussiano, desfoque leve, rotacao leve, fontes variadas.

Tudo e deterministico dado o `seed`.
"""
import io
import math
import os
import random
from dataclasses import dataclass, field

import fitz  # PyMuPDF
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from utils.validators import is_valid_cnpj, is_valid_cpf

# A4 a 300 DPI
PAGE_W, PAGE_H = 2480, 3508

_FONT_CANDIDATES = [
    # Windows
    "C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/times.ttf", "C:/Windows/Fonts/cour.ttf",
    "C:/Windows/Fonts/verdana.ttf", "C:/Windows/Fonts/georgia.ttf", "C:/Windows/Fonts/calibri.ttf",
    # Linux
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
    # macOS
    "/Library/Fonts/Arial.ttf", "/System/Library/Fonts/Supplemental/Times New Roman.ttf",
    "/System/Library/Fonts/Supplemental/Courier New.ttf",
]

_LOREM = [
    "Declaro, para os devidos fins, que as informacoes prestadas neste documento sao verdadeiras.",
    "O requerente compromete-se a manter a area em conformidade com a legislacao ambiental vigente.",
    "Anexa-se ao presente processo a planta de situacao e o memorial descritivo do empreendimento.",
    "A vistoria tecnica foi realizada no local e nao foram constatadas irregularidades aparentes.",
    "Este termo foi lavrado em duas vias de igual teor, ficando uma em poder de cada parte.",
    "Os prazos previstos nesta licenca contam-se a partir da data de sua publicacao oficial.",
]
_NAMES = ["Fulano de Tal", "Beltrano Souza", "Ciclana Pereira", "Maria Exemplo", "Joao Ficticio"]


def available_fonts():
    """Caminhos de fontes TrueType realmente existentes (pode ser vazio -> fonte padrao do Pillow)."""
    return [p for p in _FONT_CANDIDATES if os.path.exists(p)]


def load_font(rng, size, fonts=None):
    fonts = available_fonts() if fonts is None else fonts
    if fonts:
        try:
            return ImageFont.truetype(rng.choice(fonts), size)
        except OSError:
            pass
    return ImageFont.load_default(size=size)


# --- numeros (apenas sinteticos) ---------------------------------------------------------------
def _cpf_check_digit(base):
    soma = sum(int(c) * w for c, w in zip(base, range(len(base) + 1, 1, -1)))
    r = (soma * 10) % 11
    return 0 if r in (10, 11) else r


def make_valid_cpf(rng):
    while True:
        base = "".join(str(rng.randint(0, 9)) for _ in range(9))
        d1 = _cpf_check_digit(base)
        d2 = _cpf_check_digit(base + str(d1))
        cpf = f"{base}{d1}{d2}"
        if is_valid_cpf(cpf):  # descarta sequencias repetidas
            return cpf


def make_invalid_cpf(rng):
    cpf = make_valid_cpf(rng)
    wrong = (int(cpf[-1]) + rng.randint(1, 9)) % 10
    return cpf[:-1] + str(wrong)


def make_cnpj(rng):
    def dig(base, weights):
        r = sum(int(c) * w for c, w in zip(base, weights)) % 11
        return 0 if r < 2 else 11 - r
    base = "".join(str(rng.randint(0, 9)) for _ in range(8)) + "0001"
    d1 = dig(base, [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])
    d2 = dig(base + str(d1), [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])
    cnpj = f"{base}{d1}{d2}"
    assert is_valid_cnpj(cnpj)
    return cnpj


def fmt_cpf(d):
    return f"{d[:3]}.{d[3:6]}.{d[6:9]}-{d[9:]}"


def fmt_cnpj(d):
    return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}"


# --- modelo de pagina --------------------------------------------------------------------------
@dataclass
class GroundTruth:
    cpfs: list = field(default_factory=list)        # CPFs validos (11 digitos) que DEVEM ser tarjados
    cpf_boxes: list = field(default_factory=list)   # [(x0, y0, x1, y1)] em px da imagem final (mesma ordem)
    decoys: list = field(default_factory=list)      # textos que NAO devem ser tarjados


def _rotate_box(box, angle_deg, size):
    """Caixa axis-aligned apos girar a imagem em `angle_deg` (anti-horario) em torno do centro."""
    cx, cy = size[0] / 2.0, size[1] / 2.0
    a = math.radians(angle_deg)
    pts = []
    for x, y in ((box[0], box[1]), (box[2], box[1]), (box[2], box[3]), (box[0], box[3])):
        dx, dy = x - cx, y - cy
        pts.append((cx + dx * math.cos(a) + dy * math.sin(a), cy - dx * math.sin(a) + dy * math.cos(a)))
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return (min(xs), min(ys), max(xs), max(ys))


def render_page(seed, n_cpfs=3, noise_sigma=8.0, rotation_deg=None, fonts=None):
    """Retorna (PIL.Image 'L' PAGE_W x PAGE_H, GroundTruth). Deterministico para o mesmo `seed`."""
    rng = random.Random(seed)
    img = Image.new("L", (PAGE_W, PAGE_H), 255)
    draw = ImageDraw.Draw(img)
    truth = GroundTruth()
    boxes_unrot = []
    y = 220

    title_font = load_font(rng, 64, fonts)
    draw.text((200, y), f"TERMO DE REFERENCIA No {rng.randint(100, 999)}/{rng.randint(2019, 2025)}",
              font=title_font, fill=0)
    y += 140

    def line(text, size=42, indent=200, field_text=None):
        """Desenha uma linha; devolve a caixa de `field_text` (o numero) se informado."""
        nonlocal y
        font = load_font(rng, size, fonts)
        draw.text((indent, y), text, font=font, fill=0)
        box = None
        if field_text:
            pos = text.index(field_text)
            x0 = indent + draw.textlength(text[:pos], font=font)
            x1 = indent + draw.textlength(text[:pos + len(field_text)], font=font)
            asc, desc = font.getmetrics()
            box = (x0, y, x1, y + asc + desc)
        y += int(size * 1.9)
        return box

    for _ in range(2):
        line(rng.choice(_LOREM))

    kinds = ["cpf", "cpf_raw", "cpf"]
    for i in range(n_cpfs):
        cpf = make_valid_cpf(rng)
        kind = kinds[i % len(kinds)]
        shown = cpf if kind == "cpf_raw" else fmt_cpf(cpf)
        label = rng.choice(["Proprietario", "Contratante", "Responsavel", "Declarante"])
        box = line(f"{label}: {rng.choice(_NAMES)} - CPF: {shown}", size=rng.choice([38, 42, 46]),
                   field_text=shown)
        truth.cpfs.append(cpf)
        boxes_unrot.append(box)
        line(rng.choice(_LOREM), size=40)

    # iscas: NAO devem ser tarjadas
    invalid = make_invalid_cpf(rng)
    line(f"Documento de referencia (CPF com erro de digito): {fmt_cpf(invalid)}")
    truth.decoys.append(fmt_cpf(invalid))
    cnpj = fmt_cnpj(make_cnpj(rng))
    line(f"Empresa executora CNPJ {cnpj}")
    truth.decoys.append(cnpj)
    line(f"Emitido em {rng.randint(1, 28):02d}/{rng.randint(1, 12):02d}/{rng.randint(2019, 2025)} "
         f"as {rng.randint(0, 23):02d}:{rng.randint(0, 59):02d}:{rng.randint(0, 59):02d}")
    proc = f"{rng.randint(7000000, 7009999)}.{rng.randint(2019, 2025)}"
    line(f"Processo administrativo n {proc}")
    truth.decoys.append(proc)
    while True:  # telefone de 11 digitos que, por azar, NAO valida como CPF
        digits = f"659{rng.randint(1000, 9999)}{rng.randint(1000, 9999)}"
        if not is_valid_cpf(digits):
            break
    phone = f"({digits[:2]}) {digits[2:7]}-{digits[7:]}"
    line(f"Contato: {phone}")
    truth.decoys.append(phone)
    while y < PAGE_H - 600:  # preenche a pagina com texto corrido (carga de OCR realista)
        line(rng.choice(_LOREM), size=rng.choice([38, 40, 44]))

    # degradacao de scan
    angle = rng.uniform(-1.2, 1.2) if rotation_deg is None else rotation_deg
    if angle:
        img = img.rotate(angle, resample=Image.BICUBIC, fillcolor=255)
    truth.cpf_boxes = [_rotate_box(b, angle, img.size) if angle else b for b in boxes_unrot]

    img = img.filter(ImageFilter.GaussianBlur(radius=0.7))
    if noise_sigma > 0:
        import numpy as np
        nrng = np.random.default_rng(seed)
        arr = np.asarray(img, dtype="float32") + nrng.normal(0, noise_sigma, (img.height, img.width))
        speck = nrng.random((img.height, img.width)) < 0.0004  # poeira
        arr[speck] = 0
        img = Image.fromarray(arr.clip(0, 255).astype("uint8"), "L")
    return img, truth


def build_scanned_pdf(path, images, jpeg_quality=80):
    """PDF A4 'escaneado': so imagem raster por pagina (sem camada de texto)."""
    doc = fitz.open()
    for img in images:
        page = doc.new_page(width=595.0, height=842.0)
        buf = io.BytesIO()
        img.convert("RGB").save(buf, "JPEG", quality=jpeg_quality)
        page.insert_image(page.rect, stream=buf.getvalue())
    doc.save(str(path), garbage=3, deflate=True)
    doc.close()
    return str(path)


def make_document(out_dir, name, n_pages=2, seed=0, **render_kwargs):
    """Gera `name`.pdf (escaneado). Retorna (pdf_path, [Image], [GroundTruth])."""
    os.makedirs(out_dir, exist_ok=True)
    images, truths = [], []
    for i in range(n_pages):
        img, truth = render_page(seed * 1000 + i, **render_kwargs)
        images.append(img)
        truths.append(truth)
    pdf_path = build_scanned_pdf(os.path.join(out_dir, f"{name}.pdf"), images)
    return pdf_path, images, truths

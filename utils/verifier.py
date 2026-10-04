# SPDX-License-Identifier: AGPL-3.0-or-later
"""Verificação pós-tarja: relê o PDF FINAL e procura CPFs que sobreviveram.

Princípio: a verificação é independente da detecção original. Usa o texto nativo do PDF
(rápido e exato) e, para páginas sem camada de texto (rasterizadas), OCR em resolução reduzida.
A lógica de CPF (validação do dígito, exclusão de CNPJ/data) é a mesma de OCREngine.
"""
import os
import tempfile

import fitz  # PyMuPDF

from utils.ocr_engine import OCREngine


def _words_to_grounding(words):
    """Converte palavras do PyMuPDF (x0, y0, x1, y1, texto, ...) para o formato de grounding map."""
    grounding = []
    for idx, w in enumerate(words):
        x0, y0, x1, y1, text = w[0], w[1], w[2], w[3], str(w[4]).strip()
        if not text:
            continue
        grounding.append({
            "id": len(grounding),
            "text": text,
            "box": {"x": x0, "y": y0, "w": max(1.0, x1 - x0), "h": max(1.0, y1 - y0)},
            "conf": 100,
        })
    return grounding


def find_cpfs_in_words(words, ocr_engine=None):
    """CPFs válidos encontrados numa lista de palavras do PyMuPDF."""
    engine = ocr_engine or OCREngine(tesseract_path=None)
    _, found = engine.find_cpfs_in_grounding(_words_to_grounding(words))
    return found


def verify_pdf(pdf_path, ocr_engine=None, use_ocr=True, dpi=300, psm="6", logger=None, progress=None):
    """
    Retorna {page_num: set(cpfs)} com os CPFs ainda detectáveis no PDF.
    Páginas sem texto nativo só são checadas por OCR se use_ocr=True e ocr_engine tiver Tesseract.
    Também retorna a lista de páginas que não puderam ser verificadas.
    """
    leftovers = {}
    unverified = []
    engine = ocr_engine or OCREngine(tesseract_path=None)

    with fitz.open(pdf_path) as doc:
        total = len(doc)
        for idx in range(total):
            page_num = idx + 1
            page = doc[idx]
            words = page.get_text("words")
            has_images = bool(page.get_images())
            found_here = set()

            if words:
                found_here |= find_cpfs_in_words(words, engine)

            # Página escaneada: pode ter algumas palavras de texto nativo (carimbo, cabeçalho) e o
            # conteúdo real em imagem. Se há imagens (ou nenhum texto), só o OCR verifica o resto.
            needs_ocr = has_images or not words
            if needs_ocr and use_ocr:
                try:
                    pix = page.get_pixmap(matrix=fitz.Matrix(dpi / 72.0, dpi / 72.0), alpha=False)
                    with tempfile.TemporaryDirectory() as tmp:
                        img_path = os.path.join(tmp, f"verify_{page_num}.png")
                        pix.save(img_path)
                        pix = None
                        failures_before = getattr(engine, "failure_count", 0)
                        _, grounding = engine.get_grounding_map(img_path, psm=psm)
                        if getattr(engine, "failure_count", 0) > failures_before:
                            raise RuntimeError("Tesseract falhou (resultado vazio por erro)")
                    _, found_ocr = engine.find_cpfs_in_grounding(grounding)
                    found_here |= found_ocr
                except Exception as e:
                    if logger:
                        logger.error(f"[!] Verificação por OCR falhou na pág {page_num}: {e}")
                    unverified.append(page_num)
            elif needs_ocr and not words:
                unverified.append(page_num)

            if found_here:
                leftovers[page_num] = found_here

            if progress and (page_num % 10 == 0 or page_num == total):
                progress(page_num, total)

    return leftovers, unverified


def find_uncovered_cpfs(pdf_path, boxes_by_page, ocr_engine, base_dpi=1000, dpi=300, psm="6",
                        tolerance_pt=2.0, logger=None, progress=None):
    """
    Verificação de COBERTURA, independente da detecção original: faz OCR do PDF ORIGINAL em outra
    resolução/configuração e confere se cada CPF achado está dentro de alguma tarja decidida.

    Necessária porque o PDF final rasterizado (~150 DPI) é ilegível até para o OCR: um CPF mal
    lido na detecção (ex.: '6' lido como '8') passa na checagem do PDF final.

    boxes_by_page: {page_num: [{x, y, w, h, source_width?, image_width?}, ...]} em pixels de imagem.
    Retorna {page_num: [cpfs não cobertos]} e a lista de páginas que falharam no OCR.
    """
    uncovered = {}
    failed = []
    with fitz.open(pdf_path) as doc:
        total = len(doc)
        for idx in range(total):
            page_num = idx + 1
            page = doc[idx]
            page_w = page.rect.width
            try:
                pix = page.get_pixmap(matrix=fitz.Matrix(dpi / 72.0, dpi / 72.0), alpha=False)
                with tempfile.TemporaryDirectory() as tmp:
                    img_path = os.path.join(tmp, f"cover_{page_num}.png")
                    pix.save(img_path)
                    pix = None
                    failures_before = getattr(ocr_engine, "failure_count", 0)
                    _, grounding = ocr_engine.get_grounding_map(img_path, psm=psm)
                    if getattr(ocr_engine, "failure_count", 0) > failures_before:
                        raise RuntimeError("Tesseract falhou (resultado vazio por erro)")
                commands, found = ocr_engine.find_cpfs_in_grounding(grounding)
            except Exception as e:
                if logger:
                    logger.error(f"[!] Verificação de cobertura falhou na pág {page_num}: {e}")
                failed.append(page_num)
                continue

            if commands:
                rects = []
                for b in boxes_by_page.get(page_num, []):
                    src_w = b.get("source_width") or b.get("image_width") or (page_w * base_dpi / 72.0)
                    scale = page_w / float(src_w)
                    rects.append((b["x"] * scale - tolerance_pt, b["y"] * scale - tolerance_pt,
                                  (b["x"] + b["w"]) * scale + tolerance_pt, (b["y"] + b["h"]) * scale + tolerance_pt))

                pt_per_px = 72.0 / dpi
                for word_id in commands:
                    box = grounding[word_id]["box"]
                    cx = (box["x"] + box["w"] / 2.0) * pt_per_px
                    cy = (box["y"] + box["h"] / 2.0) * pt_per_px
                    if not any(r[0] <= cx <= r[2] and r[1] <= cy <= r[3] for r in rects):
                        uncovered.setdefault(page_num, set()).update(found)
                        break

            # progresso para TODA pagina (antes so avancava nas paginas com CPF detectado)
            if progress and (page_num % 10 == 0 or page_num == total):
                progress(page_num, total)

    return uncovered, failed

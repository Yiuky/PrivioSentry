# SPDX-License-Identifier: AGPL-3.0-or-later
"""Verificação pós-tarja: relê o PDF FINAL e procura CPFs que sobreviveram.

Princípio: a verificação é independente da detecção original. Usa o texto nativo do PDF
(rápido e exato) e, para páginas sem camada de texto (rasterizadas), OCR em resolução reduzida.
A lógica de CPF (validação do dígito, exclusão de CNPJ/data) é a mesma de OCREngine.
"""
import os
from concurrent.futures import ThreadPoolExecutor
import tempfile

import fitz  # PyMuPDF

from utils.ocr_engine import OCREngine, ocr_workers


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


def _relative_boxes(grounding, commands, width, height):
    """Caixas [x0, y0, x1, y1] relativas (0..1) das palavras marcadas: para mostrar ONDE revisar."""
    boxes = []
    for word_id in commands or []:
        try:
            b = grounding[word_id]["box"]
        except (IndexError, KeyError, TypeError):
            continue
        boxes.append([round(b["x"] / width, 4), round(b["y"] / height, 4),
                      round((b["x"] + b["w"]) / width, 4), round((b["y"] + b["h"]) / height, 4)])
    return boxes


def _thread_failures(engine):
    return engine.thread_failures() if hasattr(engine, "thread_failures") else getattr(engine, "failure_count", 0)


def _ocr_images(engine, jobs, psm, workers):
    """
    OCR de várias imagens em paralelo. jobs: {chave: caminho}. Devolve {chave: (grounding, erro_ou_None)}.
    Falha do Tesseract (resultado vazio por erro) vira erro, nunca "página sem CPF".
    """
    def one(path):
        before = _thread_failures(engine)
        try:
            _, grounding = engine.get_grounding_map(path, psm=psm)
        except Exception as e:
            return None, e
        if _thread_failures(engine) > before:
            return None, RuntimeError("Tesseract falhou (resultado vazio por erro)")
        return grounding, None

    keys = list(jobs)
    if workers <= 1 or len(keys) <= 1:
        return {k: one(jobs[k]) for k in keys}
    with ThreadPoolExecutor(max_workers=workers) as ex:
        return dict(zip(keys, ex.map(one, [jobs[k] for k in keys])))


def find_cpfs_in_words(words, ocr_engine=None, page_size=None, boxes_out=None):
    """CPFs válidos encontrados numa lista de palavras do PyMuPDF.

    page_size=(largura, altura) + boxes_out=lista: acrescenta em boxes_out as caixas relativas encontradas.
    """
    engine = ocr_engine or OCREngine(tesseract_path=None)
    grounding = _words_to_grounding(words)
    commands, found = engine.find_cpfs_in_grounding(grounding)
    if boxes_out is not None and page_size and found:
        boxes_out.extend(_relative_boxes(grounding, commands, *page_size))
    return found


def verify_pdf(pdf_path, ocr_engine=None, use_ocr=True, dpi=300, psm="6", logger=None, progress=None,
               locations=None, workers=None):
    """
    Retorna {page_num: set(cpfs)} com os CPFs ainda detectáveis no PDF.
    Páginas sem texto nativo só são checadas por OCR se use_ocr=True e ocr_engine tiver Tesseract.
    Também retorna a lista de páginas que não puderam ser verificadas.
    locations (dict opcional): recebe {page_num: [[x0, y0, x1, y1], ...]} relativos (0..1) do que foi achado.
    """
    leftovers = {}
    unverified = []
    engine = ocr_engine or OCREngine(tesseract_path=None)

    with fitz.open(pdf_path) as doc, tempfile.TemporaryDirectory() as tmp:
        total = len(doc)
        pages, jobs = [], {}
        # 1) leitura do texto nativo e renderização (sequencial: o documento do PyMuPDF não é thread-safe)
        for idx in range(total):
            page_num = idx + 1
            page = doc[idx]
            words = page.get_text("words")
            has_images = bool(page.get_images())
            found_here, boxes_here = set(), []
            if words:
                found_here |= find_cpfs_in_words(words, engine, (page.rect.width, page.rect.height), boxes_here)
            # Página escaneada: pode ter algumas palavras de texto nativo (carimbo, cabeçalho) e o
            # conteúdo real em imagem. Se há imagens (ou nenhum texto), só o OCR verifica o resto.
            needs_ocr = has_images or not words
            size = (page.rect.width * dpi / 72.0, page.rect.height * dpi / 72.0)
            if needs_ocr and use_ocr:
                try:
                    pix = page.get_pixmap(matrix=fitz.Matrix(dpi / 72.0, dpi / 72.0), alpha=False)
                    img_path = os.path.join(tmp, f"verify_{page_num}.png")
                    pix.save(img_path)
                    pix = None
                    jobs[page_num] = img_path
                except Exception as e:
                    if logger:
                        logger.error(f"[!] Verificação por OCR falhou na pág {page_num}: {e}")
                    unverified.append(page_num)
            elif needs_ocr and not words:
                unverified.append(page_num)
            pages.append((page_num, found_here, boxes_here, size))

        # 2) OCR das páginas em paralelo
        results = _ocr_images(engine, jobs, psm, workers or ocr_workers(dpi, len(jobs)))

        # 3) resultado em ordem de página
        for page_num, found_here, boxes_here, size in pages:
            if page_num in results:
                grounding, error = results[page_num]
                if error is not None:
                    if logger:
                        logger.error(f"[!] Verificação por OCR falhou na pág {page_num}: {error}")
                    unverified.append(page_num)
                else:
                    commands_ocr, found_ocr = engine.find_cpfs_in_grounding(grounding)
                    found_here |= found_ocr
                    if found_ocr:
                        boxes_here.extend(_relative_boxes(grounding, commands_ocr, *size))
            if found_here:
                leftovers[page_num] = found_here
                if locations is not None and boxes_here:
                    locations[page_num] = boxes_here
            if progress and (page_num % 10 == 0 or page_num == total):
                progress(page_num, total)

    return leftovers, sorted(set(unverified))


def find_uncovered_cpfs(pdf_path, boxes_by_page, ocr_engine, base_dpi=300, dpi=300, psm="6",
                        tolerance_pt=2.0, logger=None, progress=None, locations=None, workers=None):
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
    with fitz.open(pdf_path) as doc, tempfile.TemporaryDirectory() as tmp:
        total = len(doc)
        widths, jobs = {}, {}
        for idx in range(total):  # renderização sequencial
            page_num = idx + 1
            page = doc[idx]
            widths[page_num] = (page.rect.width, page.rect.height)
            try:
                pix = page.get_pixmap(matrix=fitz.Matrix(dpi / 72.0, dpi / 72.0), alpha=False)
                img_path = os.path.join(tmp, f"cover_{page_num}.png")
                pix.save(img_path)
                pix = None
                jobs[page_num] = img_path
            except Exception as e:
                if logger:
                    logger.error(f"[!] Verificação de cobertura falhou na pág {page_num}: {e}")
                failed.append(page_num)

        results = _ocr_images(ocr_engine, jobs, psm, workers or ocr_workers(dpi, len(jobs)))  # OCR em paralelo

        for page_num in sorted(results):
            grounding, error = results[page_num]
            if error is not None:
                if logger:
                    logger.error(f"[!] Verificação de cobertura falhou na pág {page_num}: {error}")
                failed.append(page_num)
                continue
            page_w, page_h = widths[page_num]
            commands, found = ocr_engine.find_cpfs_in_grounding(grounding)
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
                        if locations is not None:
                            scale = dpi / 72.0
                            locations.setdefault(page_num, []).extend(_relative_boxes(
                                grounding, [word_id], page_w * scale, page_h * scale))
                        break
            if progress and (page_num % 10 == 0 or page_num == total):
                progress(page_num, total)

    return uncovered, failed

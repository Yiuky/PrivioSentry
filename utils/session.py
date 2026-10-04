# SPDX-License-Identifier: AGPL-3.0-or-later
import os
import sys
import logging
import json
import fitz # PyMuPDF
from PIL import Image

from utils.pii import CpfMaskingFilter, mask_cpf, mask_text

# Global PIL setting
Image.MAX_IMAGE_PIXELS = None

# Qualidade do PDF final (configurável por ambiente; ver apply_final_redactions)
DEFAULT_FINAL_IMAGE_WIDTH = 1240
DEFAULT_FINAL_JPEG_QUALITY = 75


def _env_int(name, default, minimum, maximum=None):
    """Lê um inteiro do ambiente; valor ausente/inválido/fora da faixa volta ao padrão."""
    raw = os.getenv(name)
    if raw is None or str(raw).strip() == "":
        return default
    try:
        value = int(str(raw).strip())
    except ValueError:
        return default
    if value < minimum or (maximum is not None and value > maximum):
        return default
    return value


class Session:
    def __init__(self, pdf_path, output_dir=None, final_dir=None):
        """output_dir/final_dir: pastas de trabalho e de PDFs finais (padrão: env
        PRIVIO_OUTPUT_DIR / PRIVIO_FINAL_DIR, senão 'output' / 'documentos_finais' relativos ao cwd)."""
        self.pdf_path = pdf_path
        self.filename = os.path.splitext(os.path.basename(pdf_path))[0]
        self.base_output_dir = output_dir or os.getenv("PRIVIO_OUTPUT_DIR") or "output"
        self._final_dir = final_dir or os.getenv("PRIVIO_FINAL_DIR") or "documentos_finais"
        self.output_dir = os.path.join(self.base_output_dir, self.filename)
        self.debug_level = getattr(logging, os.getenv("DEBUG_LEVEL", "INFO").upper(), logging.INFO)
        self._prepare_dirs()
        self.logger = self._setup_logging()

    def _prepare_dirs(self):
        self.dirs = {
            "00_raw": os.path.join(self.output_dir, "00_original_images"),
            "01_ocr": os.path.join(self.output_dir, "01_ocr_results"),
            "02_signatures": os.path.join(self.output_dir, "02_signature_crops"),
            "04_signatures_ia": os.path.join(self.output_dir, "04_signatures_crops_ia"),
            "04_signatures_tarjados": os.path.join(self.output_dir, "04_signatures_crops_tarjados"),
            "04_micro_audit": os.path.join(self.output_dir, "04_micro_audit_results"),
            "05_final": os.path.join(self.output_dir, "05_final_export"),
            "05_cpf_only": os.path.join(self.output_dir, "05_final_export", "cpf_only"),
            "05_address_only": os.path.join(self.output_dir, "05_final_export", "address_only"),
            "05_combined": os.path.join(self.output_dir, "05_final_export", "combined"),
            "06_enhanced": os.path.join(self.output_dir, "06_final_enhanced"),
            "07_addresses_ia": os.path.join(self.output_dir, "07_addresses_crops_ia"),
            "08_addresses_tarjados": os.path.join(self.output_dir, "08_addresses_crops_tarjados"),
            "10_final_phase_5": os.path.join(self.output_dir, "05_phase_5_export"),
            "99_ia_interactions": os.path.join(self.output_dir, "99_ia_interactions")
        }
        for d in self.dirs.values():
            os.makedirs(d, exist_ok=True)

        # Global Final Documents Directory
        self.doc_finais_dir = self._final_dir
        os.makedirs(self.doc_finais_dir, exist_ok=True)

    def _setup_logging(self):
        log_path = os.path.join(self.output_dir, "process_log.log")
        logger = logging.getLogger(f"session_{self.filename}")
        logger.setLevel(self.debug_level)

        # Fecha handlers antigos (no Windows o FileHandler aberto trava a exclusão da pasta)
        for old in list(logger.handlers):
            logger.removeHandler(old)
            try:
                old.close()
            except Exception:
                pass

        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        masking = CpfMaskingFilter()  # LGPD: nenhum CPF completo em log

        # File handler (UTF-8)
        fh = logging.FileHandler(log_path, encoding='utf-8')
        fh.setFormatter(formatter)
        fh.addFilter(masking)
        logger.addHandler(fh)

        # Stream handler (console UTF-8)
        sh = logging.StreamHandler(sys.stdout)
        sh.setFormatter(formatter)
        sh.addFilter(masking)
        logger.addHandler(sh)

        return logger

    def close(self):
        """Libera os handlers de log (necessário antes de apagar a pasta da sessão no Windows)."""
        for handler in list(self.logger.handlers):
            self.logger.removeHandler(handler)
            try:
                handler.close()
            except Exception:
                pass

    def export_ocr(self, page_num, grounding_text, grounding_map):
        """Salva o texto indexado (.txt) e o mapa de coordenadas (.json)."""
        txt_path = os.path.join(self.dirs["01_ocr"], f"page_{page_num}.txt")
        json_path = os.path.join(self.dirs["01_ocr"], f"page_{page_num}.json")

        with open(txt_path, "w", encoding='utf-8') as f:
            f.write(mask_text(grounding_text))

        with open(json_path, "w", encoding='utf-8') as f:
            f.write(mask_text(json.dumps(grounding_map, ensure_ascii=False, indent=4)))

        self.logger.debug(f"[+] Grounding Exportado para página {page_num}")

    def export_grounding_viz(self, page_num, img_path, grounding_map):
        """Gera uma imagem de diagnóstico com caixas e IDs desenhados."""
        from PIL import ImageDraw, ImageFont

        self.logger.info(f"[*] Gerando visualização de grounding para página {page_num}...")
        img = Image.open(img_path).convert("RGB")
        draw = ImageDraw.Draw(img)

        try:
            font = ImageFont.truetype("arial.ttf", 40)
        except:
            font = None

        for item in grounding_map:
            b = item["box"]
            id_str = str(item["id"])
            shape = [b["x"], b["y"], b["x"] + b["w"], b["y"] + b["h"]]
            draw.rectangle(shape, outline="red", width=4)
            draw.text((b["x"], b["y"] - 45), id_str, fill="blue", font=font)

        viz_path = os.path.join(self.dirs["01_ocr"], f"page_{page_num}_grounding.jpg")
        img.save(viz_path, "JPEG", quality=80)
        self.logger.info(f"[+] Visualização salva em: {viz_path}")

    def save_ai_interaction(self, phase_key, prefix, prompt, response, metrics=None, data=None, img_bytes=None):
        """Unified method to save AI debug triplet (Prompt, Response, JSON) + Image."""
        debug_dir = self.dirs.get("99_ia_interactions", self.output_dir)

        if img_bytes:
            img_path = os.path.join(debug_dir, f"{prefix}_source.jpg")
            with open(img_path, "wb") as f:
                f.write(img_bytes)

        # LGPD: prompts/respostas podem conter CPFs (dica ao modelo, eco da resposta) -> mascara ao salvar.
        prompt_path = os.path.join(debug_dir, f"{prefix}_prompt.txt")
        with open(prompt_path, "w", encoding='utf-8') as f:
            f.write(mask_text(str(prompt)))

        txt_path = os.path.join(debug_dir, f"{prefix}_response.txt")
        with open(txt_path, "w", encoding='utf-8') as f:
            if metrics:
                f.write("="*40 + "\n")
                f.write(mask_text(f"METRICS: {json.dumps(metrics, indent=2, default=str)}") + "\n")
                f.write("="*40 + "\n\n")
            f.write(mask_text(str(response)))

        json_path = os.path.join(debug_dir, f"{prefix}_data.json")
        with open(json_path, "w", encoding='utf-8') as f:
            f.write(mask_text(json.dumps({
                "phase": phase_key,
                "prefix": prefix,
                "metrics": metrics,
                "extra": data
            }, indent=4, ensure_ascii=False, default=str)))

        self.logger.debug(f"[DEBUG] AI Interaction saved with metrics: {metrics}")

    def export_yolo_results(self, page_num, img_path, candidates):
        """Salva o JSON das detecções YOLO e a imagem de grounding."""
        if not candidates:
            return

        from PIL import ImageDraw, ImageFont
        img = Image.open(img_path).convert("RGB")
        w, h = img.size
        draw = ImageDraw.Draw(img)

        json_results = []
        try:
            font = ImageFont.truetype("arial.ttf", 45)
        except:
            font = None

        for cand in candidates:
            x1, y1, x2, y2 = cand["bbox"]
            normalized_bbox = [
                round((y1 / h) * 1000, 2),
                round((x1 / w) * 1000, 2),
                round((y2 / h) * 1000, 2),
                round((x2 / w) * 1000, 2)
            ]
            json_results.append({
                "label": cand["label"],
                "conf": round(cand["conf"], 4),
                "bbox_raw": cand["bbox"],
                "bbox_normalized": normalized_bbox
            })
            draw.rectangle([x1, y1, x2, y2], outline="green", width=8)
            draw.text((x1, y1 - 55), f"{cand['label']} ({cand['conf']:.2f})", fill="green", font=font)

        json_path = os.path.join(self.dirs["02_signatures"], f"page_{page_num}_yolo.json")
        with open(json_path, "w", encoding='utf-8') as f:
            json.dump(json_results, f, indent=4, ensure_ascii=False)

        viz_path = os.path.join(self.dirs["02_signatures"], f"page_{page_num}_yolo_grounding.jpg")
        img.save(viz_path, "JPEG", quality=85)
        self.logger.info(f"[+] YOLO Grounding exportado para página {page_num}")

    def export_micro_audit_results(self, crop_name, crop_path, grounding_map, origin_bbox, found_cpfs):
        """Salva o grounding do recorte e mapeia coordenadas locais para globais."""
        from PIL import ImageDraw
        crop_img = Image.open(crop_path).convert("RGB")
        draw = ImageDraw.Draw(crop_img)
        x_offset, y_offset, _, _ = origin_bbox

        global_redaction_points = []
        for item in grounding_map:
            b = item["box"]
            draw.rectangle([b["x"], b["y"], b["x"]+b["w"], b["y"]+b["h"]], outline="blue", width=4)
            global_redaction_points.append({
                "text": mask_text(item["text"]),
                "local_box": b,
                "global_box": {
                    "x": b["x"] + x_offset,
                    "y": b["y"] + y_offset,
                    "w": b["w"],
                    "h": b["h"]
                }
            })

        viz_path = os.path.join(self.dirs["04_micro_audit"], f"viz_{crop_name}")
        crop_img.save(viz_path)

        meta_name = f"meta_{os.path.splitext(crop_name)[0]}.json"
        json_path = os.path.join(self.dirs["04_micro_audit"], meta_name)

        export_data = {
            "crop_source": crop_name,
            "origin_page_coords": origin_bbox,
            "detected_cpfs": sorted(mask_cpf(c) for c in found_cpfs),
            "mappings": global_redaction_points
        }
        with open(json_path, "w", encoding='utf-8') as f:
            json.dump(export_data, f, indent=4, ensure_ascii=False)

        return global_redaction_points

    def save_detected_cpfs(self, cpfs, filename="detected_cpfs.txt"):
        """Grava só a versão MASCARADA dos CPFs (ex.: ***.***.247-25). O CPF completo nunca vai a disco."""
        path = os.path.join(self.output_dir, filename)
        with open(path, "w", encoding='utf-8') as f:
            for masked in sorted(mask_cpf(cpf) for cpf in cpfs):
                f.write(f"{masked}\n")
        self.logger.info(f"[+] Saved {len(cpfs)} CPFs to {path}")

    def get_redaction_boxes(self, grounding_map, redaction_commands, padding=10):
        """Calcula coordenadas geométricas finais com substring e padding."""
        boxes = []
        for w_id, char_indices in redaction_commands.items():
            if w_id < len(grounding_map):
                item = grounding_map[w_id]
                text_len = len(item["text"])
                if text_len == 0: continue
                b = item["box"]
                start_char = min(char_indices)
                end_char = max(char_indices)
                char_w = b["w"] / text_len
                sub_x = b["x"] + (start_char * char_w)
                sub_w = ((end_char - start_char + 1) * char_w)

                boxes.append({
                    "x": max(0, int(sub_x - padding)),
                    "y": max(0, int(b["y"] - padding)),
                    "w": int(sub_w + (2 * padding)),
                    "h": int(b["h"] + (2 * padding))
                })
        return boxes

    def apply_final_redactions(self, page_num, img_path, box_list, dir_key="10_final_phase_5", suffix="_REDACTED"):
        """Aplica tarjas e salva na pasta correspondente ao tipo (CPF, Address ou Combined)."""
        from PIL import ImageDraw
        img = Image.open(img_path).convert("RGB")
        draw = ImageDraw.Draw(img)

        # Mesmo se não houver tarjas para aplicar (box_list vazio),
        # PROCESSAMOS a imagem (redimensionamento + conversão JPEG) para o PDF final
        # para garantir que o arquivo final não contenha PNGs gigantes (renderização em alta resolução).

        if box_list:
            for b in box_list:
                # Tratamento de escala para tarjas manuais
                source_w = b.get("source_width")
                if source_w and source_w > 0:
                    scale = img.width / source_w
                    x0, y0 = b["x"] * scale, b["y"] * scale
                    x1, y1 = (b["x"] + b["w"]) * scale, (b["y"] + b["h"]) * scale
                else:
                    # Fallback para escala 1:1 (ou lógica antiga de tarjas IA)
                    scale = 1.0
                    x0, y0 = b["x"], b["y"]
                    x1, y1 = b["x"] + b["w"], b["y"] + b["h"]

                shape = [x0, y0, x1, y1]
                self.logger.info(f"[DRAW] Pag {page_num} | Escala: {scale:.2f} | Box: {shape}")
                draw.rectangle(shape, fill="black", outline="black")

        # --- OTIMIZAÇÃO DE PESO DE ARQUIVO (COMPRESSÃO) ---
        # A IA (Tesseract) pede alta resolução. Para o olho humano num PDF, ~150 DPI basta
        # (A4 -> 1240px). Ambos configuráveis: FINAL_IMAGE_WIDTH (px) e FINAL_JPEG_QUALITY (1-95).
        MAX_WIDTH = _env_int("FINAL_IMAGE_WIDTH", DEFAULT_FINAL_IMAGE_WIDTH, 1)
        jpeg_quality = _env_int("FINAL_JPEG_QUALITY", DEFAULT_FINAL_JPEG_QUALITY, 1, 95)
        if img.width > MAX_WIDTH:
            ratio = MAX_WIDTH / float(img.width)
            new_height = int(float(img.height) * ratio)
            img = img.resize((MAX_WIDTH, new_height), Image.Resampling.LANCZOS)

        dest_dir = self.dirs.get(dir_key, self.dirs["10_final_phase_5"])
        final_path = os.path.join(dest_dir, f"page_{page_num}{suffix}.jpg")

        # Qualidade Web (padrão 75) diminui o tamanho brutalmente (Ex: 15MB -> 400kb)
        img.save(final_path, "JPEG", quality=jpeg_quality, optimize=True)

        if box_list:
            self.logger.info(f"[+] Versão tarjada e exportada ({dir_key}): {final_path}")
        else:
            self.logger.debug(f"[+] Versão otimizada (sem tarja) exportada ({dir_key}): {final_path}")

        return final_path

    def reconstitute_pdf(self, image_paths, output_suffix="_FINAL.pdf"):
        """
        Reconstrói o PDF a partir de imagens tarjadas,
        preservando as dimensões exatas das páginas originais.
        """
        if not image_paths:
            self.logger.error("[!] Nenhuma imagem para reconstruir o PDF.")
            return None

        self.logger.info(f"[*] Iniciando reconstituição fiel do PDF: {self.pdf_path}")

        try:
            # 1. Abre o PDF original para ler dimensões
            doc_orig = fitz.open(self.pdf_path)
            doc_new = fitz.open()

            failed_pages = []
            for i, img_path in enumerate(image_paths):
                if i >= len(doc_orig): break

                if not img_path or not os.path.exists(img_path):
                    self.logger.error(f"[!] Imagem ausente para pág {i+1}: {img_path}.")
                    failed_pages.append(i + 1)
                    continue

                try:
                    # Obtém dimensões da página original (em pontos)
                    orig_page = doc_orig[i]
                    rect = orig_page.rect

                    # Cria nova página no PDF novo com mesmo tamanho
                    new_page = doc_new.new_page(width=rect.width, height=rect.height)

                    # Workaround crítico para performance do PyMuPDF:
                    # insert_image costuma descomprimir JPEGs em bitmaps pesados.
                    # Ao converter a imagem direto para um strem de PDF e injetar a página,
                    # forçamos a preservação da compressão nativa do JPEG.
                    img_doc = fitz.open(img_path)
                    pdf_bytes = img_doc.convert_to_pdf()
                    img_pdf = fitz.open("pdf", pdf_bytes)

                    # Injeta a página comprimida na nossa nova página formatada
                    new_page.show_pdf_page(rect, img_pdf, 0)

                    img_pdf.close()
                    img_doc.close()
                except Exception as e:
                    self.logger.error(f"[!] Falha ao inserir imagem {img_path} no PDF: {e}")
                    failed_pages.append(i + 1)

            # FALHAR FECHADO: nunca entregar um PDF com menos páginas ou com páginas em branco.
            if failed_pages or len(doc_new) != len(doc_orig):
                self.logger.error(
                    f"[!] PDF final incompleto (páginas com falha: {failed_pages}; "
                    f"{len(doc_new)} de {len(doc_orig)} páginas). Arquivo NÃO gerado."
                )
                doc_new.close()
                doc_orig.close()
                return None

            output_name = f"{self.filename}{output_suffix}"
            output_final_path = os.path.join(self.doc_finais_dir, output_name)

            # Salvamento ultra-otimizado (sem descomprimir as streams de PDF nativas)
            doc_new.save(output_final_path, garbage=3, deflate=True)
            doc_new.close()
            doc_orig.close()

            self.logger.info(f"[+++] PDF RECONSTITUÍDO COM SUCESSO E COMPRIMIDO: {output_final_path}")
            return output_final_path

        except Exception as e:
            self.logger.error(f"[!] Erro ao reconstituir PDF: {e}")
            return None

    def apply_native_pdf_redactions(self, global_redactions, output_suffix="_NATIVO_FINAL.pdf"):
        """Aplica as tarjas em vetor/pixel diretamente sobre o documento PDF original.
        Ignora completamente os JPEGs intermediários, sendo exponencialmente mais rápido e mantendo
        a exata qualidade, tamanho estrutural e proporções do arquivo original.
        """
        import fitz
        if not os.path.exists(self.pdf_path):
            self.logger.error(f"[!] PDF original não encontrado: {self.pdf_path}")
            return None

        self.logger.info(f"[*] Iniciando RETARJAMENTO NATIVO do PDF: {self.pdf_path}")
        output_name = f"{self.filename}{output_suffix}"
        output_final_path = os.path.join(self.doc_finais_dir, output_name)

        try:
            doc = fitz.open(self.pdf_path)

            for page_num, boxes in global_redactions.items():
                page_idx = int(page_num) - 1
                if page_idx < 0 or page_idx >= len(doc): continue

                page = doc[page_idx]
                pdf_w = page.rect.width

                for b in boxes:
                    src_w = b.get("source_width") or b.get("image_width")
                    if not src_w or src_w <= 0:
                        # Sem a largura da imagem de origem: assume a resolução de renderização (BASE_DPI)
                        src_w = pdf_w * (_env_int("BASE_DPI", 300, 72, 2400) / 72.0)

                    scale = pdf_w / float(src_w)

                    x0 = b["x"] * scale
                    y0 = b["y"] * scale
                    x1 = (b["x"] + b["w"]) * scale
                    y1 = (b["y"] + b["h"]) * scale

                    rect = fitz.Rect(x0, y0, x1, y1)
                    # Adiciona área de bloqueio visual (tinta preta sem bordas)
                    page.add_redact_annot(rect, fill=(0,0,0))

            self.logger.info("[+] Executando queima real de pixels nas páginas...")
            for page in doc:
                # Efetivamente limpa a meta e "queima" pixels subjacentes na imagem original
                page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_PIXELS)

            doc.save(output_final_path, garbage=3, deflate=True)
            doc.close()

            self.logger.info(f"[+++] PDF NATIVO GERADO COM SUCESSO EM SEGUNDOS: {output_final_path}")
            return output_final_path

        except Exception as e:
            self.logger.error(f"[!] Erro crítico no Retarjamento Nativo: {e}")
            return None

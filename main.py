# SPDX-License-Identifier: AGPL-3.0-or-later
import argparse
import glob
import os
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dotenv import load_dotenv

from utils.transform_pdf_to_img import transform_pdf_to_img
from utils.session import Session, render_dpi
from utils.ocr_engine import OCREngine, ocr_workers
from utils.yolo_engine import YOLOEngine
from utils.address_redactor import AddressRedactor
from utils.lexicon import is_immune
from utils.pii import mask_text
from utils import decisions
from utils import detect as pii_detect
from utils.decisions import feedback as decision_feedback
from utils.decisions.questions import normalize_state

load_dotenv()

# Limita o uso de threads internas por bibliotecas C (como Tesseract/OpenCV) 
# para não saturar todos os cores e travar a API web.
os.environ["OMP_NUM_THREADS"] = "4"
os.environ["MKL_NUM_THREADS"] = "4"

def _cluster_boxes(boxes):
    """Agrupa caixas [x, y, w, h] da mesma linha e próximas em retângulos [x0, y0, x1, y1]."""
    rects = sorted(([b[0], b[1], b[0] + b[2], b[1] + b[3]] for b in boxes), key=lambda r: (r[1], r[0]))
    clusters = []
    for r in rects:
        for c in clusters:
            height = max(c[3] - c[1], r[3] - r[1], 1)
            same_line = min(c[3], r[3]) - max(c[1], r[1]) > -0.3 * height
            close = r[0] - c[2] < 2.5 * height and c[0] - r[2] < 2.5 * height
            if same_line and close:
                c[0], c[1], c[2], c[3] = min(c[0], r[0]), min(c[1], r[1]), max(c[2], r[2]), max(c[3], r[3])
                break
        else:
            clusters.append(r)
    return clusters


class SentryApp:
    def __init__(self, pdf_path, output_dir=None, final_dir=None):
        # 1. Initialize Management
        self.session = Session(pdf_path, output_dir=output_dir, final_dir=final_dir)
        self.logger = self.session.logger
        self.progress_callback = None
        
        # 2. Engines Setup
        self.ocr = OCREngine(
            tesseract_path=os.getenv("TESSERACT_PATH"),
            lang=os.getenv("TESSERACT_LANG", "por"),
            logger=self.logger
        )
        self.address_redactor = AddressRedactor(self.session, self.logger)
        
        # 3. Armazenamento de Estado
        # 300 DPI: melhor revocação E mais rápido nas medições (docs/benchmarks.md, 2026-10-04)
        self.base_dpi = render_dpi()
        self.image_paths = [] 
        self.grounding_maps = []
        self.grounding_maps_sparse = []
        self.indexed_texts = []
        
        # Redações categorizadas
        self.global_redactions = defaultdict(list)  # Combinado
        self.cpf_redactions = defaultdict(list)     # Só CPFs
        self.address_redactions = defaultdict(list) # Só Endereços
        
        self.alerts = []
        # FALHAR FECHADO: páginas/itens que exigem revisão humana (page_num -> [motivos])
        self.review_pages = defaultdict(list)
        self.review_marks = []  # regiões a revisar: {"page", "reason", "box": [x0, y0, x1, y1] relativos}
        self.timings = {}  # segundos por etapa (para acompanhar o desempenho)
        self.grounding_maps_native = []  # palavras do texto digital do PDF (passada extra de CPF), por página
        self.policy_profile = pii_detect.active_profile_id()  # perfil de política (utils/detect/profiles.py)
        self.pii_summary = {}   # tipo do catálogo -> quantidade de valores distintos achados (sem os valores)
        self.box_labels = defaultdict(dict)  # página -> {assinatura da caixa: rótulo do tipo} (mostrado no editor)

    def add_review(self, page_num, reason, boxes=None):
        """Marca uma página como 'requer revisão' e registra o alerta (sem duplicar).

        boxes: regiões [x0, y0, x1, y1] relativas (0..1) na página, para o editor mostrar ONDE revisar.
        """
        if reason not in self.review_pages[page_num]:
            self.review_pages[page_num].append(reason)
        for box in boxes or []:
            mark = {"page": page_num, "reason": mask_text(reason),
                    "box": [round(min(1.0, max(0.0, float(v))), 4) for v in box]}
            if mark not in self.review_marks:
                self.review_marks.append(mark)
        msg = mask_text(f"Pág {page_num}: {reason}")
        if msg not in self.alerts:
            self.alerts.append(msg)

    def add_document_review(self, reason):
        """Alerta que vale para o documento inteiro (sem página): também exige revisão."""
        if reason not in self.review_pages[0]:
            self.review_pages[0].append(reason)
        msg = mask_text(reason)
        if msg not in self.alerts:
            self.alerts.append(msg)

    def _ocr_failures(self):
        """Falhas do Tesseract da thread atual (o OCR das páginas roda em paralelo)."""
        if hasattr(self.ocr, "thread_failures"):
            return self.ocr.thread_failures()
        return getattr(self.ocr, "failure_count", 0)

    @property
    def needs_review(self):
        return bool(self.review_pages)

    def final_state(self):
        """Estado final reportado ao serviço: só é 'Concluído' se nada exige revisão."""
        state = self._final_state()
        if getattr(self, "manual_mode", False):
            # Finalização (tarjas do revisor): o resumo de tipos, o perfil e os tempos continuam os do processamento
            for key in ("pii_summary", "pii_found", "policy_profile", "timings"):
                state.pop(key, None)
        return state

    def _final_state(self):
        if self.needs_review:
            return {
                "status": "Requer revisão",
                "percentage": 100,
                "completed": True,
                "needs_review": True,
                "alerts": self.alerts,
                "review_marks": self.review_marks,
                "timings": self.timings,
                "policy_profile": self.policy_profile,
                "pii_summary": self.pii_summary,
                "pii_found": self.pii_found(),
            }
        return {"status": "Concluído", "percentage": 100, "completed": True, "needs_review": False,
                "alerts": self.alerts, "review_marks": self.review_marks, "timings": self.timings,
                "policy_profile": self.policy_profile, "pii_summary": self.pii_summary, "pii_found": self.pii_found()}

    def run(self, progress_callback=None, manual_redactions=None, native_mode=False):
        """Executa o pipeline completo com suporte a notificações de progresso."""
        self.progress_callback = progress_callback
        
        self.manual_mode = manual_redactions is not None  # finalização: não sobrescreve resumo/tempos do processamento
        if native_mode and manual_redactions is not None:
            self.logger.info("[!] RETARJAMENTO TOTAL ATIVADO: Aplicando Tarjas diretamente no PDF Nativo.")
            self._load_metadata_safely(manual_redactions)
            # Automelhoramento: as tarjas confirmadas pelo revisor viram exemplos (LEARNING_ENABLED=1)
            decision_feedback.capture_review(self.session.output_dir, manual_redactions)
            phases = [
                (self.run_native_phase, "Retarjamento PDF Nativo...", 90),
                (self.run_verification, "Verificação pós-tarja...", 98)
            ]
        elif manual_redactions is not None:
            self.logger.info("[!] MODO EDITOR ATIVADO: Executando apenas a Fase 5 com tarjas manuais (modo Legacy).")
            self._load_metadata_safely(manual_redactions)
            phases = [
                (self.run_phase_5, "Processando Tarjas Finais...", 90),
                (self.run_verification, "Verificação pós-tarja...", 98)
            ]
        else:
            phases = [
                (self.run_phase_0, "Renderizando PDF", 10),
                (self.run_phase_1, "OCR Scanning", 20),
                (self.run_phase_2, "Busca de CPFs", 30),
                (self.run_policy_phase, "Outros dados pessoais (perfil)", 35),
                (self.run_phase_3, "Busca Visual (YOLO)", 40),
                (self.run_phase_4, "Micro-Auditoria", 50),
                (self.run_address_discovery, "Análise Semântica (IA)", 65),
                (self.run_phase_6, "Tarjamento Cirúrgico", 75),
                (self.run_signature_audit, "Auditoria de Assinaturas (IA)", 85),
                (self.run_phase_5, "Finalização e Exportação", 95),
                (self.run_verification, "Verificação pós-tarja...", 98)
            ]
        
        for func, status, pct in phases:
            self.update_progress(status, pct)
            started = time.time()
            func()
            self.timings[status] = round(time.time() - started, 1)  # chave = nome legível da etapa
            self.logger.info(f"[TEMPO] {status}: {self.timings[status]} s")
            
        final = self.final_state()
        self.update_progress(final["status"], 100)
        
        # Retornamos o caminho do PDF final para conveniência
        return os.path.join(self.session.doc_finais_dir, f"{self.session.filename}_TARJADO_FINAL.pdf")

    def _extract_page_num(self, path):
        """Extrai o número da página do caminho do arquivo (ex: image_page_1.png)."""
        try:
            name = os.path.splitext(os.path.basename(path))[0]
            # O padrão é ..._page_X.png
            if "_page_" in name:
                return int(name.split("_page_")[-1])
            return 0
        except:
            return 0

    def update_progress(self, status, percentage):
        """Reporta progresso para o callback, se existir."""
        if self.progress_callback:
            self.progress_callback({
                "status": status,
                "percentage": percentage,
                "alerts": self.alerts,
                "review_marks": self.review_marks,
                "total": len(self.image_paths) if hasattr(self, 'image_paths') else 0,
                "doc_out_dir": self.session.output_dir if self.session else None
            })
        self.logger.info(f"[PROGRESS] {status}: {percentage}%")

    def run_phase_0(self):
        """Fase 0: Renderização do PDF para imagens."""
        try:
            self.logger.info(f"--- PHASE 0: RENDERING PAGES (00_ORIGINAL) @ {self.base_dpi} DPI ---")
            self.image_paths = transform_pdf_to_img(self.session.pdf_path, self.session.dirs["00_raw"], dpi=self.base_dpi)
            self.logger.info(f"[+] Fase 0 concluída: {len(self.image_paths)} imagens geradas.")
        except Exception as e:
            self.logger.error(f"[FATAL] Erro na Fase 0: {e}")
            raise Exception(f"Erro na Fase 0: {e}")
    
    def _ocr_page(self, img_path):
        """As DUAS passadas de OCR de uma página (padrão + esparsa). Roda em paralelo com outras páginas."""
        failures_before = self._ocr_failures()
        indexed_text, coordinate_map = self.ocr.get_grounding_map(img_path, psm=os.getenv("TESSERACT_STD_PSM", "3"))
        sparse_map = []
        sparse_psm = os.getenv("TESSERACT_SPARSE_PSM", "")
        if sparse_psm:
            _, sparse_map = self.ocr.get_grounding_map(img_path, psm=sparse_psm)
        return indexed_text, coordinate_map, sparse_map, self._ocr_failures() > failures_before

    def run_phase_1(self):
        """Fase 1: OCR (duas passadas por página, páginas em paralelo) + texto digital do PDF, se houver."""
        self.logger.info("--- PHASE 1: OCR SCANNING (01_OCR_RESULTS) ---")
        total = len(self.image_paths)
        workers = ocr_workers(self.base_dpi, total)
        sparse_psm = os.getenv("TESSERACT_SPARSE_PSM", "")
        self.logger.info(f"[*] OCR de {total} página(s) com {workers} em paralelo"
                         f"{' + varredura suplementar (PSM ' + sparse_psm + ')' if sparse_psm else ''}...")
        results = [None] * total
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futures = {ex.submit(self._ocr_page, path): i for i, path in enumerate(self.image_paths)}
            for done, future in enumerate(as_completed(futures), start=1):
                results[futures[future]] = future.result()
                if done % max(1, total // 10) == 0 or total < 10:
                    self.update_progress(f"OCR: Pagina {done}/{total}", int(10 + (done / total * 30)))

        for i, (indexed_text, coordinate_map, sparse_map, failed) in enumerate(results):
            if failed:
                # Resultado vazio por erro do Tesseract não pode virar "página sem CPF" (falha fechado)
                self.add_review(i + 1, "OCR (Tesseract) falhou nesta página: CPFs podem não ter sido detectados. Revisar manualmente.")
            self.grounding_maps.append(coordinate_map)
            self.indexed_texts.append(indexed_text)
            self.grounding_maps_sparse.append(sparse_map)

        self.grounding_maps_native = self._native_text_maps(total)
        self.logger.info("[+] Fase 1 concluída: Grounding e Visualizações exportados.")

    def _native_text_maps(self, total):
        """
        Passada EXTRA: palavras do texto digital do PDF (quando existe), já na escala de pixels das imagens.
        Não substitui o OCR; soma a ele (texto digital não tem erro de leitura).
        """
        from utils.verifier import _words_to_grounding, page_words
        maps = [[] for _ in range(total)]
        try:
            import fitz
            scale = self.base_dpi / 72.0
            with fitz.open(self.session.pdf_path) as doc:
                for i in range(min(total, len(doc))):
                    grounding = _words_to_grounding(page_words(doc[i]))  # coordenadas da página girada
                    for w in grounding:
                        b = w["box"]
                        w["box"] = {"x": b["x"] * scale, "y": b["y"] * scale, "w": b["w"] * scale, "h": b["h"] * scale}
                    maps[i] = grounding
        except Exception as e:
            self.logger.warning(f"[!] Texto digital do PDF não lido (segue só com o OCR): {e}")
        n = sum(1 for m in maps if m)
        if n:
            self.logger.info(f"[*] Texto digital encontrado em {n} página(s): usado como passada extra de CPF.")
        return maps

    def run_phase_2(self):
        """Fase 2: Descoberta de CPFs (OCR Standard + OCR Esparso)."""
        self.logger.info("--- PHASE 2: CPF DISCOVERY (DUAL-PASS OCR) ---")
        all_found_cpfs = set()
        for i, img_path in enumerate(self.image_paths):
            page_num = i + 1
            
            # Cooperação no loop de CPFs
            time.sleep(0.01)
            
            # Passada 1 (Standard PSM 3)
            coordinate_map = self.grounding_maps[i]
            command_map, page_cpfs = self.ocr.find_cpfs_in_grounding(coordinate_map)
            if command_map:
                boxes = self.session.get_redaction_boxes(coordinate_map, command_map)
                self.global_redactions[page_num].extend(boxes)
                self.cpf_redactions[page_num].extend(boxes)
                all_found_cpfs.update(page_cpfs)
                
            # Passada 2 (Sparse PSM 11) e passada 3 (texto digital do PDF, quando existe)
            extra_maps = []
            if i < len(self.grounding_maps_sparse) and self.grounding_maps_sparse[i]:
                extra_maps.append(self.grounding_maps_sparse[i])
            if i < len(self.grounding_maps_native) and self.grounding_maps_native[i]:
                extra_maps.append(self.grounding_maps_native[i])
            for extra_map in extra_maps:
                cmd_map_s, cpfs_s = self.ocr.find_cpfs_in_grounding(extra_map)
                if cmd_map_s:
                    boxes_s = self.session.get_redaction_boxes(extra_map, cmd_map_s)
                    self.global_redactions[page_num].extend(boxes_s)
                    self.cpf_redactions[page_num].extend(boxes_s)
                    all_found_cpfs.update(cpfs_s)
            
        self.session.save_detected_cpfs(all_found_cpfs)
        self.known_cpfs = list(all_found_cpfs)
        if all_found_cpfs:
            self.pii_summary["cpf"] = len(all_found_cpfs)
        self.logger.info(f"[+] Fase 2 concluída: {len(all_found_cpfs)} CPFs identificados.")

    def pii_found(self):
        """Resumo legível por tipo do catálogo: nome, nível e quantidade (nunca os valores)."""
        out = []
        for type_id, count in self.pii_summary.items():
            t = pii_detect.catalog.BY_ID.get(type_id)
            if t:
                out.append({"id": type_id, "nome": t.nome, "nivel": t.nivel, "quantidade": count})
        return out

    def run_policy_phase(self):
        """
        Demais tipos de PII do perfil ativo (SENTRY Detect): regras sobre as três leituras de cada página
        (OCR padrão, OCR esparso e texto digital). "tarjar" vira tarja sugerida; "alertar" marca a região.
        CPF e endereço residencial têm fases próprias.
        """
        actions = {t: a for t, a in pii_detect.runnable_actions(self.policy_profile).items()
                   if t not in ("cpf", "endereco_residencial")}
        self.logger.info(f"--- POLÍTICA: perfil '{self.policy_profile}' ({len(actions)} tipo(s) com detector) ---")
        if not actions:
            return
        found_values = defaultdict(set)
        for i in range(len(self.grounding_maps)):
            page_num = i + 1
            maps = [m for m in (self.grounding_maps[i],
                                self.grounding_maps_sparse[i] if i < len(self.grounding_maps_sparse) else [],
                                self.grounding_maps_native[i] if i < len(self.grounding_maps_native) else []) if m]
            for gmap in maps:
                for type_id, (commands, values) in pii_detect.find_in_grounding(gmap, list(actions)).items():
                    found_values[type_id] |= {f"{page_num}:{v}" for v in values}
                    boxes = self.session.get_redaction_boxes(gmap, commands)
                    label = pii_detect.catalog.get(type_id).nome
                    if actions[type_id] == pii_detect.TARJAR:
                        for b in boxes:
                            self.global_redactions[page_num].append(b)
                            self.box_labels[page_num][f"{b['x']}_{b['y']}_{b['w']}_{b['h']}"] = label
                    else:
                        self.add_review(page_num, f"{label}: possível dado pessoal (perfil manda alertar). Revisar.",
                                        self._relative_boxes(page_num, [[b["x"], b["y"], b["w"], b["h"]] for b in boxes]))
        for type_id, vals in found_values.items():
            self.pii_summary[type_id] = len(vals)
        if found_values:
            resumo = ", ".join(f"{pii_detect.catalog.get(t).nome}: {n}" for t, n in self.pii_summary.items() if t in actions)
            self.logger.info(f"[+] Política: {resumo}.")

    def run_phase_3(self):
        """Fase 3: Mapeador Visual YOLO (02_DISCOVERY & CROPPING)"""
        self.logger.info("--- PHASE 3: YOLO DISCOVERY ---")
        self.yolo = YOLOEngine(model_path=os.getenv("YOLO_MODEL_PATH"), logger=self.logger)
        if not self.yolo.model:
            # Degrada com aviso (não bloqueia), mas registra: assinaturas não foram detectadas visualmente.
            # Sem detector, nenhuma assinatura foi auditada: falha fechado (o documento exige revisão).
            reason = getattr(self.yolo, "integrity_error", None) or "Modelo YOLO ausente"
            self.add_document_review(f"{reason}: assinaturas não foram detectadas visualmente (revisar assinaturas manualmente).")
            return
        self.all_crops_metadata = []
        for i, img_path in enumerate(self.image_paths):
            candidates, crop_meta = self.yolo.get_candidates(img_path, crop_dir=self.session.dirs["02_signatures"], page_num=i+1)
            if getattr(self.yolo, "last_error", None):
                # FALHAR FECHADO: inferência falhou -> sem recortes de assinatura nesta página.
                self.add_review(i + 1, f"detecção de assinaturas (YOLO) falhou ({str(self.yolo.last_error)[:120]})")
            self.all_crops_metadata.extend(crop_meta)
            self.session.export_yolo_results(i+1, img_path, candidates)
        self.logger.info(f"[+] Fase 3 concluída: {len(self.all_crops_metadata)} recortes gerados.")

    def run_phase_4(self):
        """Fase 4: Micro-Audit (Tesseract nos Recortes do YOLO)"""
        self.logger.info("--- PHASE 4: MICRO-AUDIT ---")
        if not hasattr(self, 'all_crops_metadata') or not self.all_crops_metadata: return

        for crop in self.all_crops_metadata:
            failures_before = self._ocr_failures()
            _, grounding_map = self.ocr.get_grounding_map(crop["path"], psm=os.getenv("TESSERACT_CROP_PSM", "6"))
            if self._ocr_failures() > failures_before:
                self.add_review(crop["page_num"], "OCR falhou num recorte de assinatura. Revisar a assinatura manualmente.")
            redaction_commands, found_cpfs = self.ocr.find_cpfs_in_grounding(grounding_map)
            
            audit_boxes = self.session.get_redaction_boxes(grounding_map, redaction_commands)
            page_num = crop["page_num"]
            x_off, y_off, _, _ = crop["origin_bbox"]
            
            for b in audit_boxes:
                box = {
                    "x": b["x"] + x_off, "y": b["y"] + y_off, 
                    "w": b["w"], "h": b["h"]
                }
                self.global_redactions[page_num].append(box)
                self.cpf_redactions[page_num].append(box)
        self.logger.info("[+] Fase 4 concluída: Micro-Audit finalizado.")

    def run_address_discovery(self):
        """Fase de Endereços: Descoberta via AI Semântica (Visão)."""
        self.logger.info("--- INICIANDO ELEMENTO: ADDRESS REDACTOR (VISÃO) ---")
        service = decisions.get_engine()
        if service is not None:
            service.preload()  # o decisor carrega o modelo enquanto o LLM analisa as páginas
        self.address_redactor.run_discovery(self.image_paths)
        for page_num, reason in self.address_redactor.failed_pages.items():
            self.add_review(page_num, f"IA não analisou endereços ({reason[:120]}). Revisar manualmente.")
        for page_num, reason in getattr(self.address_redactor, "review_notes", {}).items():
            self.add_review(page_num, f"Endereços: {reason}. Revisar manualmente.")
        self.apply_address_decisions()

    def apply_address_decisions(self):
        """
        Decisor local (utils/decisions): pergunta ao modelo calibrado se cada endereço é residencial e
        combina com o LLM pela regra de policy.py (nunca reduz proteção). Grava decisions.json, que o
        automelhoramento usa para aprender com as correções do revisor. Desligado: não faz nada.
        """
        service = decisions.get_engine()
        results = self.address_redactor.results
        items = [(page, addr) for page in sorted(results) for addr in results[page]]
        if service is None or not items:
            return
        verdicts = service.decide_many([addr["text"] for _, addr in items])
        log = []
        for (page, addr), verdict in zip(items, verdicts):
            llm_personal = addr.get("type") == "pessoal"
            is_personal, reason = decisions.combine_address_decision(
                llm_personal, verdict.p_personal, service.mode, service.thresholds)
            if is_personal and not llm_personal:
                addr["type"] = "pessoal"
                addr["decided_by"] = verdict.engine
            word_boxes = self._address_word_boxes(page, addr["text"])
            if reason:
                self.add_review(page, f"Endereços: {reason}. Revisar manualmente.",
                                self._relative_boxes(page, word_boxes))
            log.append({"page": page, "text": normalize_state(addr["text"]), "llm_type": addr.get("type_original"),
                        "final_type": addr["type"], "p_personal": verdict.p_personal, "mode": service.mode,
                        "profile": verdict.profile_version, "word_boxes": word_boxes})
        try:
            decision_feedback.write_decision_log(self.session.output_dir, log)
        except OSError as e:
            self.logger.warning(f"[decisions] não foi possível gravar decisions.json: {e}")
        self.logger.info(f"[decisions] {len(log)} endereço(s) avaliados pelo decisor local (modo {service.mode}).")

    def _relative_boxes(self, page_num, boxes):
        """[x, y, w, h] em pixels da imagem da página -> regiões [x0, y0, x1, y1] relativas, uma por ocorrência
        (palavras vizinhas na mesma linha formam uma região; ocorrências distantes ficam separadas)."""
        if not boxes or page_num > len(self.image_paths):
            return []
        try:
            from PIL import Image
            with Image.open(self.image_paths[page_num - 1]) as im:
                width, height = im.size
        except Exception:
            return []
        clamp = lambda v: min(1.0, max(0.0, v))  # noqa: E731  (nunca desenhar fora da página)
        return [[clamp(x0 / width), clamp(y0 / height), clamp(x1 / width), clamp(y1 / height)]
                for x0, y0, x1, y1 in _cluster_boxes(boxes)]

    def _address_word_boxes(self, page_num, text):
        """Caixas [x, y, w, h] das palavras do endereço na página (para aprender com a revisão)."""
        if page_num > len(self.grounding_maps):
            return []
        cmap = self.grounding_maps[page_num - 1]
        ids = self.address_redactor.refine_redaction_with_text_ai(
            page_num, self.indexed_texts[page_num - 1], [{"text": text, "type": "pessoal"}], cmap) or []
        boxes = []
        for word_id in ids:
            try:
                b = cmap[int(word_id)]["box"]
                boxes.append([b["x"], b["y"], b["w"], b["h"]])
            except (ValueError, IndexError, KeyError, TypeError):
                continue
        return boxes

    def run_phase_6(self):
        """Fase 6: Tarjamento Cirúrgico via Auditoria de Texto (LLM)."""
        self.logger.info("--- PHASE 6: SEMANTIC ADDRESS REDACTION ---")
        address_findings = self.address_redactor.results
        
        for page_num, addresses in address_findings.items():
            if page_num > len(self.indexed_texts): continue
            
            indexed_text = self.indexed_texts[page_num - 1]
            coordinate_map = self.grounding_maps[page_num - 1]
            
            redaction_mappings = self.address_redactor.refine_redaction_with_text_ai(
                page_num, indexed_text, addresses, coordinate_map
            )
            
            if redaction_mappings:
                if "FALLBACK_ALL" in redaction_mappings:
                    msg = f"Protocolo de Pânico (Endereços) ativado na pág {page_num} devido à estafa da IA local."
                    self.logger.error(f"[!] ERRO CRÍTICO NA IA SEMÂNTICA. {msg}")
                    self.add_review(page_num, "Protocolo de Pânico (Endereços): IA local falhou; tarja ampla aplicada. Revisar manualmente.")
                    self.update_progress("Queda na IA (Endereço). Tarjando Bruto.", 75)
                    
                    pessoais = [a["text"].upper() for a in addresses if a.get("type") == "pessoal"]
                    for w_idx, word_data in enumerate(coordinate_map):
                        raw_wordText = word_data.get("text", "")
                        word_text = raw_wordText.upper()
                        
                        if is_immune(word_text):
                            continue
                            
                        # String matching pornográfico: se a palavra está dentre os blocos da visão.
                        if any(word_text in p for p in pessoais):
                            box = word_data["box"]
                            self.global_redactions[page_num].append(box)
                            self.address_redactions[page_num].append(box)
                    continue

                self.logger.info(f"[+] Auditoria confirmou {len(redaction_mappings)} IDs para tarjar na página {page_num}.")
                for word_id in redaction_mappings:
                    try:
                        w_idx = int(word_id)
                        if 0 <= w_idx < len(coordinate_map):
                            word_data = coordinate_map[w_idx]
                            word_text = word_data.get("text", "")
                            
                            if is_immune(word_text):
                                self.logger.warning(f"[!] Proteção Lexical ativada: Ignorando termo estrutural '{word_text}' no ID {w_idx}.")
                                continue
                            
                            # SAFETY FILTER: Nunca tarjar labels explícitos que terminam com ":"
                            if word_text.endswith(":"):
                                self.logger.warning(f"[!] Ignorando tarja no ID {w_idx} ('{word_text}') - Detectado como Rótulo explícito.")
                                continue
                                
                            box = word_data["box"]
                            self.global_redactions[page_num].append(box)
                            self.address_redactions[page_num].append(box)
                    except: continue
        
        self._apply_address_policy()
        self.logger.info("[+] Fase 6 concluída.")

    def _apply_address_policy(self):
        """Endereço residencial segue o perfil: tarjar (padrão), alertar (vira região a revisar) ou ignorar."""
        action = pii_detect.runnable_actions(self.policy_profile).get("endereco_residencial")
        found = {p: list(b) for p, b in self.address_redactions.items() if b}
        # Conta ENDEREÇOS (não as palavras tarjadas) das páginas onde algum foi localizado
        n_addresses = sum(1 for page, addrs in self.address_redactor.results.items() if page in found
                          for a in addrs if a.get("type") == "pessoal")
        if found:
            self.pii_summary["endereco_residencial"] = n_addresses or len(found)
        if action == pii_detect.TARJAR:
            return
        for page_num, boxes in found.items():
            ids = {id(b) for b in boxes}
            self.global_redactions[page_num] = [b for b in self.global_redactions[page_num] if id(b) not in ids]
            if action == pii_detect.ALERTAR:
                self.add_review(page_num, "Endereço residencial: possível dado pessoal (perfil manda alertar). Revisar.",
                                self._relative_boxes(page_num, [[b["x"], b["y"], b["w"], b["h"]] for b in boxes]))
        self.address_redactions = defaultdict(list)

    def run_signature_audit(self):
        """Fase 7: Auditoria de Assinaturas (IA Visual) para verificar CPFs não tarjados."""
        self.logger.info("--- PHASE 7: SIGNATURE AUDIT (VISION AI) ---")
        if not hasattr(self, 'all_crops_metadata') or not self.all_crops_metadata:
            self.logger.info("[-] Nenhum crop de assinatura para auditar.")
            return
        
        self.unredacted_cpfs = defaultdict(list)
        from PIL import Image, ImageDraw
        
        cpfs_str = ", ".join(self.known_cpfs) if hasattr(self, 'known_cpfs') and self.known_cpfs else "nenhum número em memória"
        prompt = f"""
        OBJETIVO: Verifique rigorosamente se existe algum número de CPF não tarjado (visível) nesta imagem.
        Considere que a imagem é um recorte de assinatura. Procure por números que pareçam CPFs (formato XXX.XXX.XXX-XX ou sequências de 11 dígitos).
        
        DICA CONTEXTUAL: Os CPFs atrelados a este documento na memória do OCR são: [{cpfs_str}].
        Se você notar qualquer rastro legível, borrão ou caligrafia que se aproxime a QUALQUER DESSES números (mesmo parcialmente legível), denuncie ele imediatamente.
        
        FORMATO DE SAÍDA EXIGIDO (APENAS JSON):
        {{
            "unredacted_cpfs": ["123.456.789-00"]
        }}
        Deixe a lista "unredacted_cpfs" vazia [] se não encontrar NENHUM cpf visível.
        """

        # Garante a pasta de crops tarjados
        crop_dir = self.session.dirs.get("04_signatures_tarjados")
        if not crop_dir:
            crop_dir = os.path.join(self.session.output_dir, "04_signatures_crops_tarjados")
            os.makedirs(crop_dir, exist_ok=True)

        for crop in self.all_crops_metadata:
            page_num = crop["page_num"]
            crop_path = crop["path"]
            x1_off, y1_off, x2_off, y2_off = crop["origin_bbox"]
            w_crop = x2_off - x1_off
            h_crop = y2_off - y1_off
            
            try:
                img = Image.open(crop_path).convert("RGB")
            except Exception as e:
                self.logger.error(f"[!] Erro ao abrir imagem do crop {crop_path}: {e}")
                continue

            draw = ImageDraw.Draw(img)
            
            filename = os.path.basename(crop_path).replace(".jpg", "_redacted_audit.jpg")
            
            # Aplica tarjas já existentes na página para a IA validar o resultado "já tarjado"
            for redaction in self.global_redactions[page_num]:
                rx, ry, rw, rh = redaction["x"], redaction["y"], redaction["w"], redaction["h"]
                
                # Check overlap between redaction box and crop origin on the whole page
                if rx < x2_off and rx + rw > x1_off and ry < y2_off and ry + rh > y1_off:
                    local_x1 = max(0, rx - x1_off)
                    local_y1 = max(0, ry - y1_off)
                    local_x2 = min(w_crop, (rx + rw) - x1_off)
                    local_y2 = min(h_crop, (ry + rh) - y1_off)
                    draw.rectangle([local_x1, local_y1, local_x2, local_y2], fill="black")
            
            redacted_crop_path = os.path.join(crop_dir, filename)
            img.save(redacted_crop_path, "JPEG")
            
            self.logger.info(f"[*] Auditando crop tarjado da pág {page_num}: {filename}...")
            response, img_bytes, metrics = self.address_redactor.ai.analyze_image(redacted_crop_path, prompt)
            keys = sorted(response) if isinstance(response, dict) else type(response).__name__
            self.logger.info(f"    -> resposta da visão recebida (campos: {keys}); conteúdo só em 99_ia_interactions")
            
            self.session.save_ai_interaction(
                phase_key="Signature_Audit",
                prefix=f"page_{page_num}_{filename.replace('.jpg', '')}",
                prompt=prompt,
                response=response,
                metrics=metrics,
                img_bytes=img_bytes
            )
            
            if isinstance(response, dict):
                if "error" in response:
                    msg = f"Protocolo de Pânico (Assinaturas) ativo na pág {page_num}: IA esgotada/Timeout."
                    self.logger.error(f"[!] ERRO CRÍTICO NA IA DE VISÃO. {msg}")
                    self.add_review(page_num, "Protocolo de Pânico (Assinaturas): IA esgotada/timeout; recorte inteiro tarjado. Revisar manualmente.")
                    self.update_progress("Queda da IA (Visão). Tarjando Total.", 85)
                    
                    emergency_box = {"x": x1_off, "y": y1_off, "w": w_crop, "h": h_crop}
                    if emergency_box not in self.global_redactions[page_num]:
                        self.global_redactions[page_num].append(emergency_box)
                        self.cpf_redactions[page_num].append(emergency_box)
                    self.add_review(page_num, "IA de visão falhou na auditoria de assinatura (recorte tarjado por segurança)")
                    continue
                
                found = response.get("unredacted_cpfs", [])
                if found and isinstance(found, list):
                     for item in found:
                         cpf_val = item if isinstance(item, str) else item.get("cpf", "")
                         if cpf_val:
                             self.logger.warning(f"[!] CPF NÃO TARJADO identificado pela Visão: {mask_text(str(cpf_val))}")
                             self.logger.warning("    -> APLICANDO TARJA BRUTA NO CROP DIRETO.")
                             
                             emergency_box = {
                                 "x": x1_off,
                                 "y": y1_off,
                                 "w": w_crop,
                                 "h": h_crop
                             }
                             
                             # Como podemos ter multiplos cpfs previstos, garantimos não duplicar as tarjas gigantes
                             if emergency_box not in self.global_redactions[page_num]:
                                 self.global_redactions[page_num].append(emergency_box)
                                 self.cpf_redactions[page_num].append(emergency_box)

        self.logger.info("[+] Fase 7 concluída.")

    def _load_metadata_safely(self, manual_redactions):
        """Prepara o estado interno com base nas redações fornecidas (Manual ou IA)."""
        # Setup image_paths lendo da pasta 00_original_images
        orig_dir = os.path.join(self.session.output_dir, "00_original_images")
        if os.path.exists(orig_dir):
            import glob
            imgs = glob.glob(os.path.join(orig_dir, "*_page_*.png"))
            imgs.sort(key=self._extract_page_num)
            self.image_paths = imgs
            
        self.global_redactions = defaultdict(list)
        self.cpf_redactions = defaultdict(list)
        self.address_redactions = defaultdict(list)
        
        for red in manual_redactions:
            try:
                page_num = int(red.get("page", 1))
                rtype = red.get("type", "pii")
                coords = red.get("coords")
                source = red.get("source", "Manual")
                source_w = red.get("image_width")
                if coords and len(coords) == 4:
                    box = { "x": coords[0], "y": coords[1], "w": coords[2]-coords[0], "h": coords[3]-coords[1] }
                    if source_w: box["source_width"] = float(source_w)
                    self.global_redactions[page_num].append(box)
                    label = red.get("label")
                    if label:
                        self.box_labels[page_num][f"{box['x']}_{box['y']}_{box['w']}_{box['h']}"] = str(label)
                    if rtype == "pii" and label == "Endereço residencial": self.address_redactions[page_num].append(box)
                    elif rtype == "signature": self.cpf_redactions[page_num].append(box)
            except Exception as e:
                self.logger.error(f"Erro ao analisar tarja ({source}): {e}")

    def run_native_phase(self):
        """Nova fase: Retarjamento direto e nativo no arquivo PDF."""
        self.logger.info("--- NATIVE PDF REDACTION ---")
        final_path = self.session.apply_native_pdf_redactions(
            global_redactions=self.global_redactions, 
            output_suffix="_TARJADO_FINAL.pdf"
        )
        if final_path:
            self.logger.info("[+++] PROCESSO NATIVO COMPLETO FINALIZADO.")
        else:
            self.logger.error("[-] Falha ao gerar arquivo nativo.")
            raise RuntimeError("Falha ao gerar o PDF nativo tarjado.")

    def run_phase_5(self):
        """Fase 5: Exportação em 3 níveis + Reconstituição de PDF Final (Legado)."""
        self.logger.info("--- PHASE 5: FINAL REDACTION & EXPORT ---")
        if not self.image_paths:
            # FALHAR FECHADO: sem imagens originais (ex.: removidas por /purge) não há como aplicar as
            # tarjas; seguir adiante verificaria um PDF final ANTIGO como se fosse o novo.
            raise RuntimeError("Imagens originais ausentes (00_original_images): não é possível aplicar as "
                               "tarjas neste modo. Use o retarjamento nativo ou reprocesse o documento.")

        # EXPORTA OS METADADOS PARA O FRONTEND VIZUALIZAR E EDITAR
        frontend_redactions = []
        for page_num in range(1, len(self.image_paths) + 1):
            
            # Map address redactions for typing
            addr_boxes = [f"{b['x']}_{b['y']}_{b['w']}_{b['h']}" for b in self.address_redactions.get(page_num, [])]
            cpf_boxes = [f"{b['x']}_{b['y']}_{b['w']}_{b['h']}" for b in self.cpf_redactions.get(page_num, [])]
            
            # Load actual image dimensions to fix off-screen rendering in frontend
            orig_w, orig_h = 1240, 1754 # Fallback
            try:
                img_path = self.image_paths[page_num - 1]
                from PIL import Image
                with Image.open(img_path) as tmp:
                    orig_w, orig_h = tmp.size
            except Exception: pass

            for box in self.global_redactions.get(page_num, []):
                bx = box['x']
                by = box['y']
                bw = box['w']
                bh = box['h']
                box_sig = f"{bx}_{by}_{bw}_{bh}"
                
                known = self.box_labels.get(page_num, {}).get(box_sig)  # rótulo explícito vence a inferência
                if box_sig in cpf_boxes:
                    rtype, label = 'signature', known or "CPF"
                elif box_sig in addr_boxes:
                    rtype, label = 'pii', known or "Endereço residencial"
                else:
                    rtype, label = 'pii', known

                frontend_redactions.append({
                    "page": page_num,
                    "type": rtype,
                    "label": label,
                    "coords": [bx, by, bx + bw, by + bh],
                    "source": "AI_Engine",
                    "image_width": orig_w,
                    "image_height": orig_h
                })
        
        metadata_path = os.path.join(self.session.output_dir, "redactions_metadata.json")
        try:
            import json
            with open(metadata_path, 'w', encoding='utf-8') as f:
                json.dump(frontend_redactions, f, indent=2)
            self.logger.info(f"[+] Metadados do frontend salvos em {metadata_path}")
        except Exception as e:
            self.logger.error(f"[-] Erro ao salvar metadados do frontend: {e}")
        
        final_images = []
        
        for i, img_path in enumerate(self.image_paths):
            page_num = i + 1
            
            # 1. Exporta Versão SÓ CPF
            self.session.apply_final_redactions(page_num, img_path, self.cpf_redactions[page_num], 
                                                dir_key="05_cpf_only", suffix="_CPF_ONLY")
            
            # 2. Exporta Versão SÓ ENDEREÇO
            self.session.apply_final_redactions(page_num, img_path, self.address_redactions[page_num], 
                                                dir_key="05_address_only", suffix="_ADDRESS_ONLY")
            
            # 3. Exporta Versão COMBINADA (Final)
            final_img = self.session.apply_final_redactions(page_num, img_path, self.global_redactions[page_num], 
                                                           dir_key="05_combined", suffix="_REDACTED")
            final_images.append(final_img)

        # 4. GERA PDF FINAL RECONSTITUÍDO
        if final_images:
            if not self.session.reconstitute_pdf(final_images, output_suffix="_TARJADO_FINAL.pdf"):
                raise RuntimeError("Falha ao reconstituir o PDF final (veja o log do processo).")

        self.logger.info("[+++] PROCESSO COMPLETO FINALIZADO.")

    def run_verification(self):
        """Verificação pós-tarja: relê o PDF FINAL e reprova páginas com CPF ainda detectável."""
        from utils.verifier import verify_pdf
        self.logger.info("--- VERIFICAÇÃO PÓS-TARJA (PDF FINAL) ---")
        final_pdf = os.path.join(self.session.doc_finais_dir, f"{self.session.filename}_TARJADO_FINAL.pdf")
        if not os.path.exists(final_pdf):
            raise RuntimeError(f"PDF final não encontrado para verificação: {final_pdf}")

        use_ocr = os.getenv("VERIFY_OCR", "1") == "1"
        found_at = {}
        leftovers, unverified = verify_pdf(
            final_pdf,
            ocr_engine=self.ocr,
            use_ocr=use_ocr,
            dpi=int(os.getenv("VERIFY_DPI", "300")),
            psm=os.getenv("TESSERACT_CROP_PSM", "6"),
            logger=self.logger,
            progress=lambda done, total: self.update_progress(
                f"Verificação pós-tarja: {done}/{total}", 98),
            locations=found_at,
        )
        for page_num, cpfs in leftovers.items():
            self.logger.error(f"[!!!] CPF AINDA VISÍVEL na pág {page_num} do PDF final ({len(cpfs)} ocorrência(s)).")
            self.add_review(page_num, f"{len(cpfs)} CPF(s) ainda detectável(is) no PDF final", found_at.get(page_num))
        for page_num in unverified:
            self.add_review(page_num, "página sem texto e não verificada por OCR")

        if use_ocr:
            # Cobertura: OCR independente do ORIGINAL (outra resolução) vs. tarjas decididas.
            # Pega CPFs que a detecção principal leu errado e que o PDF final (baixa resolução) não revela.
            from utils.verifier import find_uncovered_cpfs
            uncovered_at = {}
            uncovered, failed = find_uncovered_cpfs(
                self.session.pdf_path, self.global_redactions, self.ocr,
                base_dpi=self.base_dpi,
                dpi=int(os.getenv("VERIFY_DPI", "300")),
                psm=os.getenv("TESSERACT_CROP_PSM", "6"),
                logger=self.logger,
                progress=lambda done, total: self.update_progress(
                    f"Verificação de cobertura: {done}/{total}", 98),
                locations=uncovered_at,
            )
            for page_num, cpfs in uncovered.items():
                self.logger.error(f"[!!!] CPF no ORIGINAL sem tarja correspondente na pág {page_num} ({len(cpfs)} distinto(s)).")
                self.add_review(page_num, "CPF detectado no original sem tarja correspondente", uncovered_at.get(page_num))
            for page_num in failed:
                self.add_review(page_num, "verificação de cobertura por OCR falhou")
        self.logger.info(f"[+] Verificação concluída: {len(leftovers)} página(s) reprovada(s), {len(unverified)} não verificada(s).")

def collect_pdfs(input_path):
    """PDF único ou todos os *.pdf (ordenados) de uma pasta."""
    if os.path.isdir(input_path):
        return sorted(glob.glob(os.path.join(input_path, "*.pdf")))
    if os.path.isfile(input_path):
        return [input_path]
    return []


def build_arg_parser():
    parser = argparse.ArgumentParser(
        prog="main.py",
        description="SENTRY Redact: tarja CPF e endereços pessoais em PDFs (processamento 100% local).")
    parser.add_argument("--input", "-i", required=True, help="PDF ou pasta com PDFs a processar.")
    parser.add_argument("--output", "-o", default=None,
                        help="Pasta dos PDFs finais tarjados (arquivos intermediários ficam em <output>/work). "
                             "Padrão: ./documentos_finais e ./output (ou PRIVIO_FINAL_DIR / PRIVIO_OUTPUT_DIR).")
    return parser


def cli(argv=None):
    """Executa o pipeline em lote. Código de saída: 0 = tudo concluído; 1 = erro/entrada vazia;
    3 = ao menos um documento 'Requer revisão' (revisão humana obrigatória)."""
    args = build_arg_parser().parse_args(argv)
    pdf_files = collect_pdfs(args.input)
    if not pdf_files:
        print(f"[ERRO] Nenhum PDF encontrado em: {args.input}", file=sys.stderr)
        return 1

    final_dir = os.path.abspath(args.output) if args.output else None
    work_dir = os.path.join(final_dir, "work") if final_dir else None

    errors = 0
    needs_review = 0
    for i, pdf_path in enumerate(pdf_files):
        print(f"[{i+1}/{len(pdf_files)}] PROCESSANDO: {os.path.basename(pdf_path)}")
        try:
            app = SentryApp(pdf_path, output_dir=work_dir, final_dir=final_dir)
            app.run()
            state = app.final_state()
            print(f"[{state['status'].upper()}] {os.path.basename(pdf_path)}")
            if state["needs_review"]:
                needs_review += 1
                for alert in state["alerts"]:
                    print(f"    - {alert}")
        except Exception as e:
            errors += 1
            print(f"[ERRO] Falha ao processar {os.path.basename(pdf_path)}: {e}", file=sys.stderr)
            import traceback
            traceback.print_exc()
    if errors:
        return 1
    return 3 if needs_review else 0


if __name__ == "__main__":
    sys.exit(cli())

# SPDX-License-Identifier: AGPL-3.0-or-later
import hashlib
import logging
import os

from PIL import Image

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_MODEL_RELATIVE = os.path.join("models", "signature_stamp_detector.pt")
DEFAULT_MODEL_PATH = os.path.join(REPO_ROOT, DEFAULT_MODEL_RELATIVE)
# SHA-256 do modelo distribuído no repositório. O formato .pt é um pickle (pode executar código ao ser
# carregado): um arquivo diferente deste NÃO é carregado. Trocou o modelo de propósito? Atualize aqui e no
# models/MODEL_CARD.md, ou use YOLO_MODEL_PATH + YOLO_MODEL_SHA256.
DEFAULT_MODEL_SHA256 = "bbdf0d6833ef6db7afa24c0fe98423fc011f8692e6bdf0279cfe827db0d93d63"


def file_sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def resolve_model_path(model_path=None):
    """Caminho efetivo do modelo YOLO.

    Sem valor -> models/signature_stamp_detector.pt na raiz do projeto. Caminho relativo é
    procurado primeiro a partir do diretório atual e, depois, da raiz do projeto.
    """
    if not model_path:
        return DEFAULT_MODEL_PATH
    if os.path.isabs(model_path) or os.path.exists(model_path):
        return model_path
    return os.path.join(REPO_ROOT, model_path)


class YOLOEngine:
    def __init__(self, model_path=None, logger=None):
        self.logger = logger or logging.getLogger("YOLOEngine")
        self.model = None
        self.names = {}
        self.last_error = None  # erro da última inferência (None = ok); o chamador deve falhar fechado
        self.integrity_error = None  # modelo recusado por não bater com o SHA-256 esperado
        model_path = resolve_model_path(model_path)
        if not os.path.exists(model_path):
            self.logger.warning(
                f"[!] YOLO model not found at {model_path}. A fase de detecção visual de assinaturas "
                f"será PULADA (coloque o modelo em {DEFAULT_MODEL_RELATIVE} ou defina YOLO_MODEL_PATH)."
            )
        elif not self._integrity_ok(model_path):
            pass  # recusado: self.model fica None e o pipeline exige revisão
        else:
            self.logger.info(f"[*] Loading YOLO model from {model_path}...")
            from ultralytics import YOLO  # import tardio: pesado e opcional sem modelo
            self.model = YOLO(model_path)
            self.names = self.model.names  # {id: name}

    def _integrity_ok(self, model_path):
        """Confere o SHA-256 antes de carregar. Modelo padrão: hash fixo. Outro caminho: YOLO_MODEL_SHA256."""
        expected = (os.getenv("YOLO_MODEL_SHA256") or "").strip().lower()
        if not expected and os.path.realpath(model_path) == os.path.realpath(DEFAULT_MODEL_PATH):
            expected = DEFAULT_MODEL_SHA256
        if not expected:
            self.logger.warning("[!] Modelo YOLO personalizado sem YOLO_MODEL_SHA256: integridade não verificada "
                                "(arquivos .pt podem executar código ao carregar; use só modelos de confiança).")
            return True
        actual = file_sha256(model_path)
        if actual != expected:
            self.integrity_error = (f"Modelo YOLO recusado: SHA-256 {actual[:12]}... difere do esperado "
                                    f"{expected[:12]}... (arquivo alterado ou corrompido)")
            self.logger.error(f"[!!] {self.integrity_error}")
            return False
        return True

    def get_candidates(self, img_path, conf_threshold=0.25, crop_dir=None, page_num=0):
        """
        Returns (candidates, crop_metadata).
        - candidates: List of detected objects with bboxes.
        - crop_metadata: List of dicts mapping crop paths to their origin on the page.
        """
        self.last_error = None
        if not self.model:
            return [], []

        try:
            results = self.model(img_path, conf=conf_threshold, verbose=False)
            candidates = []
            crop_metadata = []

            with Image.open(img_path) as img:
                w, h = img.size

                for r in results:
                    for i, box in enumerate(r.boxes):
                        coords = box.xyxy[0].tolist()  # [x1, y1, x2, y2]
                        conf = box.conf[0].item()
                        cls = int(box.cls[0].item())
                        label = self.names.get(cls, "unknown").lower()

                        candidates.append({
                            "bbox": coords,
                            "conf": conf,
                            "cls": cls,
                            "label": label
                        })

                        # If it's a signature and we have a crop_dir, save a sample
                        if crop_dir and ("signature" in label or "assinatura" in label):
                            pad = int(os.getenv("YOLO_CROP_PADDING", "50"))
                            x1, y1, x2, y2 = coords
                            crop_box = (
                                max(0, x1 - pad),
                                max(0, y1 - pad),
                                min(w, x2 + pad),
                                min(h, y2 + pad)
                            )
                            crop = img.crop(crop_box)
                            crop_filename = f"page_{page_num}_yolo_sig_{i+1}.jpg"
                            crop_path = os.path.join(crop_dir, crop_filename)
                            crop.save(crop_path, "JPEG", quality=95)

                            self.logger.info(f"[+] YOLO Signature Crop saved: {crop_filename}")

                            # Metadados para o mapeamento de coordenadas na Fase 4
                            crop_metadata.append({
                                "path": crop_path,
                                "page_num": page_num,
                                "origin_bbox": crop_box,  # [left, top, right, bottom]
                                "tight_bbox": coords  # Caixa exata sem padding
                            })

            self.logger.info(f"[*] YOLO found {len(candidates)} candidate regions.")
            return candidates, crop_metadata
        except Exception as e:
            self.logger.error(f"[!] YOLO inference failed: {e}")
            self.last_error = str(e)
            return [], []

# SPDX-License-Identifier: AGPL-3.0-or-later
"""Leitura EXTRA de OCR (opcional), somada às duas passadas do Tesseract e ao texto digital do PDF.

    pip install -e ".[ocr-extra]"     (rapidocr + onnxruntime: modelos PP-OCR latinos do PaddleOCR, Apache-2.0)
    OCR_EXTRA_ENGINE=rapidocr         (no .env)

Medido (benchmarks/ocr_compare.py, docs/benchmarks.md): no corpus fictício, em digitalização péssima, o OCR duplo do
Tesseract perdeu e-mails que a soma com o RapidOCR achou (98,3% -> 100% de revocação); nos documentos reais testados,
achou um telefone e um e-mail que o Tesseract leu deformados (ficariam sem tarja). Custo: ~1,3 a 3,4 s por página na
CPU, em paralelo. Nenhuma leitura sozinha chegou a 100%: as leituras SE SOMAM, nunca se substituem.

A leitura extra roda ao mesmo tempo que o Tesseract (outra thread). Se estiver ligada e falhar numa página, a
página vai para revisão (falha fechada): a chance a mais de achar um dado foi perdida.
"""
import importlib.util
import logging
import os
import threading

logger = logging.getLogger("ocr_extra")

_engine = None
_error = None
_lock = threading.Lock()   # carga única
_run_lock = threading.Lock()  # uma página por vez no mesmo motor


def engine_name():
    return (os.getenv("OCR_EXTRA_ENGINE") or "").strip().lower()


def enabled():
    return engine_name() == "rapidocr"


def available():
    return enabled() and importlib.util.find_spec("rapidocr") is not None


def lines_to_words(lines):
    """[(caixa de 4 pontos, texto da linha)] -> mapa de palavras; a caixa da linha é dividida pelo número de
    caracteres de cada palavra (o motor devolve linhas, o pipeline trabalha com palavras)."""
    words = []
    for box, txt in lines:
        xs, ys = [p[0] for p in box], [p[1] for p in box]
        x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
        toks = str(txt).split()
        if not toks:
            continue
        total = sum(len(t) for t in toks) + len(toks) - 1
        unit = (x1 - x0) / max(1, total)
        cx = x0
        for t in toks:
            w = unit * len(t)
            words.append({"id": len(words), "text": t,
                          "box": {"x": int(cx), "y": int(y0), "w": max(1, int(w)), "h": max(1, int(y1 - y0))}})
            cx += w + unit
    return words


class RapidOCREngine:
    def __init__(self):
        from rapidocr import LangRec, ModelType, OCRVersion, RapidOCR
        self.engine = RapidOCR(params={"Rec.lang_type": LangRec.LATIN, "Rec.ocr_version": OCRVersion.PPOCRV5,
                                       "Rec.model_type": ModelType.MOBILE, "Global.log_level": "error"})

    def __call__(self, image_path):
        out = self.engine(image_path)
        boxes = out.boxes if out is not None and getattr(out, "boxes", None) is not None else []
        return lines_to_words(list(zip(boxes, getattr(out, "txts", None) or [])))


def get_engine():
    global _engine, _error
    with _lock:
        if _engine is None and _error is None:
            try:
                try:  # redes com inspeção TLS: o primeiro uso baixa os modelos
                    import truststore
                    truststore.inject_into_ssl()
                except ImportError:
                    pass
                _engine = RapidOCREngine()
            except Exception as e:
                _error = f"{type(e).__name__}: {e}"
        if _engine is None:
            raise RuntimeError(_error)
        return _engine


def read(image_path):
    """Mapa de palavras da leitura extra. Levanta exceção se falhar (quem chama decide a revisão)."""
    engine = get_engine()
    with _run_lock:
        return engine(image_path)


def reset():
    """Para testes."""
    global _engine, _error
    with _lock:
        _engine, _error = None, None

# SPDX-License-Identifier: AGPL-3.0-or-later
"""Compara motores de OCR (clássicos e modelos de visão) no corpus FICTÍCIO, sob condições de imagem cada vez piores.

    python -m benchmarks.ocr_compare --engines tesseract3,tesseract11,rapidocr,doctr,vlm:glm-ocr \
        --conditions limpa,padrao,ruim,pessima --docs 18 --out resultado.json

Motores (os que não estiverem instalados são pulados com aviso):
    tesseract3 / tesseract11   Tesseract (PSM 3 e PSM 11), o que o pipeline usa hoje
    rapidocr                   modelos PP-OCR (PaddleOCR) latinos em ONNX: pip install rapidocr onnxruntime
    doctr                      docTR (Mindee): pip install python-doctr
    vlm:<modelo>               modelo de visão no Ollama local (ex.: vlm:glm-ocr, vlm:deepseek-ocr, vlm:gemma4:12b)

Combinações: "a+b" soma as leituras (ex.: tesseract3+tesseract11 = o OCR duplo atual; tesseract3+tesseract11+rapidocr).
Mede, por tipo, quantos valores do gabarito cada combinação achou e quantos falsos positivos produziu, e o tempo médio
por página de cada motor. Os modelos de visão devolvem texto sem coordenadas: medem a QUALIDADE DA LEITURA (o valor
aparece no texto?); para tarjar, a leitura precisa ser casada com as caixas de um OCR com coordenadas.
"""
import argparse
import base64
import io
import json
import os
import random
import re
import sys
import time
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmarks import pii_corpus  # noqa: E402
from benchmarks.pii_eval import norm, same_value  # noqa: E402

# condições de imagem: (desfoque, ruído sal-e-pimenta por 1/N pixels, rotação em graus, qualidade JPEG, escala)
CONDITIONS = {
    "limpa": (0.0, 0, 0.0, 95, 1.0),
    "padrao": (0.6, 400, 0.0, 90, 1.0),
    "ruim": (1.0, 120, 1.2, 45, 0.6),
    "pessima": (1.4, 60, 2.5, 25, 0.45),
}

VLM_PROMPTS = {
    "glm-ocr": "Text Recognition:",
    "deepseek-ocr": "Free OCR.",
}
VLM_DEFAULT_PROMPT = ("Transcreva fielmente TODO o texto desta imagem, linha por linha, exatamente como está "
                      "escrito (números, pontuação, e-mails). Não resuma, não corrija, não explique. Responda só com o texto.")


def render(text, condition, seed):
    """Desenha o documento numa página e aplica a condição. Devolve imagem PIL (escala de cinza)."""
    from PIL import Image, ImageDraw, ImageFilter, ImageFont
    blur, noise, angle, quality, scale = CONDITIONS[condition]
    try:
        font = ImageFont.truetype("arial.ttf", 30)
    except OSError:
        font = ImageFont.load_default()
    lines = text.split("\n")
    img = Image.new("L", (2480, 160 + 60 * len(lines)), 255)
    draw = ImageDraw.Draw(img)
    for i, line in enumerate(lines):
        draw.text((80, 80 + 60 * i), line, fill=0, font=font)
    rng = random.Random(seed)
    if noise:
        px = img.load()
        for _ in range(img.size[0] * img.size[1] // noise):
            px[rng.randrange(img.size[0]), rng.randrange(img.size[1])] = rng.choice((0, 255))
    if angle:
        img = img.rotate(rng.uniform(-angle, angle), expand=True, fillcolor=255)
    if blur:
        img = img.filter(ImageFilter.GaussianBlur(blur))
    if scale != 1.0:
        small = img.resize((int(img.size[0] * scale), int(img.size[1] * scale)))
        img = small.resize(img.size)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=quality)
    buf.seek(0)
    return Image.open(buf).convert("L")


def words_from_text(text):
    """Texto sem coordenadas -> mapa de palavras sintético (uma linha por altura), para as mesmas regras."""
    words, y = [], 0
    for line in str(text).splitlines():
        x = 0
        for tok in line.split():
            words.append({"id": len(words), "text": tok, "box": {"x": x, "y": y, "w": 10 * len(tok), "h": 20}})
            x += 10 * len(tok) + 10
        y += 40
    return words


# ------------------------------------------------------------------------------------------------- motores
class Tesseract:
    def __init__(self, psm):
        from utils.ocr_engine import OCREngine
        self.psm = psm
        self.engine = OCREngine(os.getenv("TESSERACT_PATH"), lang=os.getenv("TESSERACT_LANG", "por"))

    def __call__(self, image_path):
        return self.engine.get_grounding_map(image_path, psm=self.psm)[1]


class RapidOCR:
    def __init__(self):
        from rapidocr import LangRec, ModelType, OCRVersion, RapidOCR as _R
        last = None
        for version, mtype in ((OCRVersion.PPOCRV5, ModelType.MOBILE), (OCRVersion.PPOCRV4, ModelType.MOBILE)):
            try:
                self.engine = _R(params={"Rec.lang_type": LangRec.LATIN, "Rec.ocr_version": version,
                                         "Rec.model_type": mtype, "Global.log_level": "error"})
                return
            except Exception as e:  # versão sem modelo latino: tenta a anterior
                last = e
        raise last

    def __call__(self, image_path):
        out = self.engine(image_path)
        words = []
        for box, txt in zip(getattr(out, "boxes", None) if out is not None and out.boxes is not None else [],
                            getattr(out, "txts", None) or []):
            xs, ys = [p[0] for p in box], [p[1] for p in box]
            x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
            toks = str(txt).split()
            total = sum(len(t) for t in toks) + max(0, len(toks) - 1) or 1
            cx = x0
            for t in toks:  # divide a linha em palavras proporcionalmente ao número de caracteres
                w = (x1 - x0) * len(t) / total
                words.append({"id": len(words), "text": t, "box": {"x": int(cx), "y": int(y0), "w": int(w), "h": int(y1 - y0)}})
                cx += w + (x1 - x0) / total
        return words


class DocTR:
    def __init__(self):
        # Sem isto o docTR vaza ~140 threads do sistema por página (medido: 13 mil threads em minutos)
        os.environ.setdefault("DOCTR_MULTIPROCESSING_DISABLE", "TRUE")
        from doctr.models import ocr_predictor
        self.model = ocr_predictor(pretrained=True)

    def __call__(self, image_path):
        from doctr.io import DocumentFile
        page = self.model(DocumentFile.from_images(image_path)).pages[0]
        h, w = page.dimensions
        words = []
        for block in page.blocks:
            for line in block.lines:
                for word in line.words:
                    (x0, y0), (x1, y1) = word.geometry
                    words.append({"id": len(words), "text": word.value,
                                  "box": {"x": int(x0 * w), "y": int(y0 * h), "w": int((x1 - x0) * w), "h": int((y1 - y0) * h)}})
        return words


class OllamaVision:
    def __init__(self, model, timeout=300):
        import requests
        self.requests = requests
        self.model = model
        self.timeout = timeout
        self.url = os.getenv("OLLAMA_API_URL", "http://localhost:11434").rstrip("/") + "/api/chat"
        # pelo nome da família, também em repositórios do Hugging Face (ex.: hf.co/42ailab/DeepSeek-OCR-2-GGUF)
        name = model.lower()
        self.prompt = next((p for key, p in VLM_PROMPTS.items() if key in name), VLM_DEFAULT_PROMPT)

    def __call__(self, image_path):
        from PIL import Image
        img = Image.open(image_path)
        limit = int(os.getenv("VLM_MAX_SIDE", "1600"))
        if max(img.size) > limit:  # modelos de visão trabalham em resolução menor; evita estourar a memória
            k = limit / max(img.size)
            img = img.resize((int(img.size[0] * k), int(img.size[1] * k)))
        buf = io.BytesIO()
        img.convert("RGB").save(buf, "PNG")
        body = {"model": self.model, "stream": False, "think": False, "keep_alive": "10m",
                "options": {"temperature": 0, "num_ctx": 8192},
                "messages": [{"role": "user", "content": self.prompt,
                              "images": [base64.b64encode(buf.getvalue()).decode()]}]}
        r = self.requests.post(self.url, json=body, timeout=self.timeout)
        if r.status_code == 400 and "think" in r.text:  # modelo sem suporte a "think"
            body.pop("think")
            r = self.requests.post(self.url, json=body, timeout=self.timeout)
        r.raise_for_status()
        text = r.json().get("message", {}).get("content", "")
        text = re.sub(r"<\|[^|>]*\|>", "\n", text)  # marcações do deepseek-ocr (<|md_start|>, <|ref|>...)
        return words_from_text(text)


def make_engine(name):
    if name == "tesseract3":
        return Tesseract("3")
    if name == "tesseract11":
        return Tesseract("11")
    if name == "rapidocr":
        return RapidOCR()
    if name == "doctr":
        return DocTR()
    if name.startswith("vlm:"):
        return OllamaVision(name[4:])
    raise ValueError(f"motor desconhecido: {name}")


# ------------------------------------------------------------------------------------------------- avaliação
def detect(groundings, engine_cpf):
    from utils.detect import rules
    found = defaultdict(set)
    for g in groundings:
        if not g:
            continue
        _, cpfs = engine_cpf.find_cpfs_in_grounding(g)
        found["cpf"] |= {norm(c) for c in cpfs}
        for t, (_c, vals) in rules.find_in_grounding(g, list(rules.RULES_BY_TYPE)).items():
            found[t] |= {norm(v) for v in vals}
    return found


def score(docs, readings, combo, engine_cpf):
    """readings[(doc_idx, engine)] = grounding. Devolve métricas por tipo da combinação."""
    stats = defaultdict(lambda: {"esperados": 0, "achados": 0, "falsos_positivos": 0})
    parts = combo.split("+")
    for i, doc in enumerate(docs):
        found = detect([readings.get((i, p)) for p in parts], engine_cpf)
        truth = defaultdict(set)
        for t, v in doc.gabarito:
            truth[t].add(norm(v))
        for t in set(truth) | set(found):
            s = stats[t]
            s["esperados"] += len(truth[t])
            s["achados"] += sum(1 for tv in truth[t] if any(same_value(t, fv, tv) for fv in found[t]))
            s["falsos_positivos"] += sum(1 for fv in found[t] if not any(same_value(t, fv, tv) or fv in tv or tv in fv
                                                                          for tv in truth[t]))
    out = {}
    for t, s in sorted(stats.items()):
        det = s["achados"] + s["falsos_positivos"]
        out[t] = {**s, "revocacao": round(s["achados"] / s["esperados"], 3) if s["esperados"] else None,
                  "precisao": round(s["achados"] / det, 3) if det else None}
    tot_e = sum(s["esperados"] for s in stats.values())
    tot_a = sum(s["achados"] for s in stats.values())
    tot_fp = sum(s["falsos_positivos"] for s in stats.values())
    out["_total"] = {"esperados": tot_e, "achados": tot_a, "falsos_positivos": tot_fp,
                     "revocacao": round(tot_a / tot_e, 3) if tot_e else None,
                     "precisao": round(tot_a / (tot_a + tot_fp), 3) if tot_a + tot_fp else None}
    return out


def run(engine_names, combos, conditions, n_docs, seed, log=print):
    import tempfile
    from utils.ocr_engine import OCREngine
    docs = pii_corpus.generate(n_docs, seed)
    engine_cpf = OCREngine(None)
    engines, skipped = {}, {}
    for name in engine_names:
        try:
            engines[name] = make_engine(name)
        except Exception as e:  # não instalado / modelo ausente
            skipped[name] = f"{type(e).__name__}: {e}"[:200]
            log(f"[pulado] {name}: {skipped[name]}")
    report = {"docs": n_docs, "seed": seed, "pulados": skipped, "condicoes": {}}
    with tempfile.TemporaryDirectory() as tmp:
        for cond in conditions:
            readings, times, errors = {}, defaultdict(list), defaultdict(int)
            paths = []
            for i, doc in enumerate(docs):
                p = os.path.join(tmp, f"{cond}_{i}.png")
                render(doc.text, cond, seed * 1000 + i).save(p)
                paths.append(p)
            for name, eng in engines.items():  # um motor por vez (modelos de visão não disputam a GPU)
                for i, p in enumerate(paths):
                    t0 = time.time()
                    try:
                        readings[(i, name)] = eng(p)
                    except Exception as e:
                        errors[name] += 1
                        readings[(i, name)] = []
                        log(f"[erro] {name} doc {i}: {type(e).__name__}: {str(e)[:120]}")
                    times[name].append(time.time() - t0)
                log(f"  {cond}: {name} pronto ({sum(times[name]) / len(paths):.1f} s/pág)")
            valid = [c for c in combos if all(p in engines for p in c.split("+"))]
            report["condicoes"][cond] = {
                "tempo_por_pagina": {n: round(sum(v) / len(v), 2) for n, v in times.items()},
                "erros": dict(errors),
                "combinacoes": {c: score(docs, readings, c, engine_cpf) for c in valid},
            }
    return report


def to_markdown(report):
    lines = []
    for cond, data in report["condicoes"].items():
        lines += [f"\n### Condição: {cond}", "", "| Combinação | Revocação | Precisão | Achados/Esperados | FP | por tipo (revocação) |",
                  "|---|---:|---:|---:|---:|---|"]
        for combo, res in sorted(data["combinacoes"].items(), key=lambda kv: -(kv[1]["_total"]["revocacao"] or 0)):
            tot = res["_total"]
            per = ", ".join(f"{t} {r['revocacao']:.0%}" for t, r in res.items()
                            if not t.startswith("_") and r["revocacao"] is not None)
            lines.append(f"| {combo} | {tot['revocacao']:.1%} | {tot['precisao']:.1%} | {tot['achados']}/{tot['esperados']} | "
                         f"{tot['falsos_positivos']} | {per} |")
        lines.append("")
        lines.append("Tempo médio por página: " + ", ".join(f"{n} {t:.1f} s" for n, t in data["tempo_por_pagina"].items()))
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--engines", default="tesseract3,tesseract11,rapidocr,doctr")
    ap.add_argument("--combos", default="", help="combinações a medir (padrão: cada motor + OCR duplo + duplo com cada extra)")
    ap.add_argument("--conditions", default="limpa,padrao,ruim,pessima")
    ap.add_argument("--docs", type=int, default=18)
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--out")
    args = ap.parse_args(argv)
    try:
        from dotenv import load_dotenv
        load_dotenv(os.path.join(ROOT, ".env"))
    except ImportError:
        pass
    names = [e for e in args.engines.split(",") if e]
    combos = [c for c in args.combos.split(",") if c]
    if not combos:
        combos = list(names)
        if {"tesseract3", "tesseract11"} <= set(names):
            combos.append("tesseract3+tesseract11")
            combos += [f"tesseract3+tesseract11+{e}" for e in names if not e.startswith("tesseract")]
    report = run(names, combos, [c for c in args.conditions.split(",") if c], args.docs, args.seed)
    print(to_markdown(report))
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())

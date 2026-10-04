# SPDX-License-Identifier: AGPL-3.0-or-later
"""Avalia os detectores de PII no corpus fictício (benchmarks/pii_corpus.py): revocação e precisão por tipo.

    python -m benchmarks.pii_eval                 rápido: texto direto (sem OCR)
    python -m benchmarks.pii_eval --ocr           texto desenhado em imagem com ruído + OCR real (2 passadas)
    python -m benchmarks.pii_eval --docs 100 --seed 7 --out relatorio.json

Mede por VALOR: um valor do gabarito conta como achado se o detector do tipo o encontrou; um valor achado que não
está no gabarito daquele tipo é falso positivo (as iscas ajudam a explicar de onde ele veio). Use antes e depois
de mexer em regras, listas ou limiares (utils/detect/data/*.json): a mudança precisa manter ou melhorar.
"""
import argparse
import json
import os
import re
import sys
import tempfile
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmarks import pii_corpus  # noqa: E402
from utils.detect import rules  # noqa: E402
from utils.ocr_engine import OCREngine  # noqa: E402


def norm(value):
    """Forma comparável: e-mail mantém os pontos; o resto fica só com letras e dígitos (CPF "529.982..." = dígitos)."""
    value = str(value).lower()
    return re.sub(r"[^0-9a-z@.]", "", value) if "@" in value else re.sub(r"[^0-9a-z]", "", value)


def same_value(type_id, found, truth):
    """Mesmo valor? Para e-mail, aceita o "@" que o OCR trocou por 1 ou 2 caracteres ("nome.84Dexample.com")."""
    if found == truth:
        return True
    if type_id != "email" or "@" not in truth:
        return False
    local, domain = (re.sub(r"[^0-9a-z]", "", part) for part in truth.split("@", 1))
    got = re.sub(r"[^0-9a-z]", "", found)
    return got.startswith(local) and got.endswith(domain) and len(got) - len(local) - len(domain) in (0, 1, 2)


def text_grounding(text):
    """Mapa de palavras sintético (uma palavra por token, linhas separadas por altura) para o modo rápido."""
    words, y = [], 0
    for line in text.split("\n"):
        x = 0
        for tok in line.split():
            words.append({"id": len(words), "text": tok, "box": {"x": x, "y": y, "w": 10 * len(tok), "h": 20}})
            x += 10 * len(tok) + 10
        y += 40
    return words


def ocr_groundings(text, engine, tmp):
    """Desenha o texto numa página (ruído leve) e devolve os mapas das duas passadas do OCR."""
    from PIL import Image, ImageDraw, ImageFilter, ImageFont
    import random
    try:
        font = ImageFont.truetype("arial.ttf", 30)
    except OSError:
        font = ImageFont.load_default()
    lines = text.split("\n")
    img = Image.new("L", (2480, 120 + 60 * len(lines)), 255)
    draw = ImageDraw.Draw(img)
    for i, line in enumerate(lines):
        draw.text((80, 60 + 60 * i), line, fill=0, font=font)
    rng = random.Random(len(text))
    px = img.load()
    for _ in range(img.size[0] * img.size[1] // 400):  # sal e pimenta leve
        px[rng.randrange(img.size[0]), rng.randrange(img.size[1])] = rng.choice((0, 255))
    img = img.filter(ImageFilter.GaussianBlur(0.6))
    path = os.path.join(tmp, "p.png")
    img.save(path)
    return [engine.get_grounding_map(path, psm=psm)[1] for psm in ("3", "11")]


def detect_values(groundings, type_ids, engine):
    found = defaultdict(set)
    for g in groundings:
        _, cpfs = engine.find_cpfs_in_grounding(g)
        found["cpf"] |= {norm(c) for c in cpfs}
        for type_id, (_cmds, values) in rules.find_in_grounding(g, type_ids).items():
            found[type_id] |= {norm(v) for v in values}
    return found


def evaluate(docs, use_ocr=False):
    type_ids = list(rules.RULES_BY_TYPE)
    engine = OCREngine(os.getenv("TESSERACT_PATH"), lang=os.getenv("TESSERACT_LANG", "por"))
    stats = defaultdict(lambda: {"esperados": 0, "achados": 0, "falsos_positivos": 0, "exemplos_fp": []})
    with tempfile.TemporaryDirectory() as tmp:
        for doc in docs:
            groundings = ocr_groundings(doc.text, engine, tmp) if use_ocr else [text_grounding(doc.text)]
            found = detect_values(groundings, type_ids, engine)
            truth = defaultdict(set)
            for t, val in doc.gabarito:
                truth[t].add(norm(val))
            decoys = {norm(val): kind for kind, val in doc.iscas}
            for t in set(truth) | set(found):
                s = stats[t]
                s["esperados"] += len(truth[t])
                hits = {tv for tv in truth[t] if any(same_value(t, fv, tv) for fv in found[t])}
                s["achados"] += len(hits)
                for fp in {fv for fv in found[t] if not any(same_value(t, fv, tv) for tv in truth[t])}:
                    if any(fp in tv or tv in fp for tv in truth[t]):  # pedaço do mesmo valor (OCR) não é FP novo
                        continue
                    s["falsos_positivos"] += 1
                    origem = next((k for dv, k in decoys.items() if fp in dv or dv in fp), "outro")
                    if len(s["exemplos_fp"]) < 5:
                        s["exemplos_fp"].append(f"{doc.kind}:{origem}")
    report = {}
    for t, s in sorted(stats.items()):
        rec = s["achados"] / s["esperados"] if s["esperados"] else None
        detected = s["achados"] + s["falsos_positivos"]
        prec = s["achados"] / detected if detected else None
        report[t] = {**s, "revocacao": None if rec is None else round(rec, 3),
                     "precisao": None if prec is None else round(prec, 3)}
    return report


def to_markdown(report, use_ocr):
    lines = ["| Tipo | Esperados | Achados | Falsos positivos | Revocação | Precisão |",
             "|---|---:|---:|---:|---:|---:|"]
    for t, r in report.items():
        fmt = lambda v: "—" if v is None else f"{v:.0%}"  # noqa: E731
        lines.append(f"| {t} | {r['esperados']} | {r['achados']} | {r['falsos_positivos']} | {fmt(r['revocacao'])} | "
                     f"{fmt(r['precisao'])} |")
    return f"Modo: {'OCR real' if use_ocr else 'texto direto'}\n\n" + "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--docs", type=int, default=50)
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--ocr", action="store_true", help="desenha o texto em imagem com ruído e usa o OCR real")
    ap.add_argument("--out", help="grava o relatório em JSON")
    args = ap.parse_args(argv)
    try:
        from dotenv import load_dotenv
        load_dotenv(os.path.join(ROOT, ".env"))
    except ImportError:
        pass
    report = evaluate(pii_corpus.generate(args.docs, args.seed), use_ocr=args.ocr)
    print(to_markdown(report, args.ocr))
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump({"modo": "ocr" if args.ocr else "texto", "docs": args.docs, "seed": args.seed, "tipos": report},
                      f, ensure_ascii=False, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())

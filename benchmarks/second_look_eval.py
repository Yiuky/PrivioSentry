# SPDX-License-Identifier: AGPL-3.0-or-later
"""Benchmark do segundo olhar (utils/second_look.py) no corpus FICTÍCIO, com OCR real sob condições ruins.

    python -m benchmarks.second_look_eval --models gemma4:e4b,qwen3.5:4b --conditions ruim,pessima --docs 24

Para cada página: OCR duplo (Tesseract PSM 3 + 11) -> detectores do pipeline -> o agente do segundo olhar lê a mesma
página (texto da leitura PSM 3) e o que ele achar é LOCALIZADO nas palavras do OCR (o que não existir é descartado).
Mede: gabarito achado pelo pipeline, recuperado só pelo segundo olhar, acréscimos fora do gabarito, descartados por
não localizar, falhas e tempo por página.
"""
import argparse
import json
import os
import sys
import tempfile
import time
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmarks import pii_corpus  # noqa: E402
from benchmarks.ocr_compare import render  # noqa: E402
from benchmarks.pii_eval import norm, same_value  # noqa: E402

TYPES = ["cpf", "rg", "cns", "pis_nis", "telefone", "email", "data_nascimento", "placa_veiculo", "nome_pessoa"]
GAB_TYPE = {"cpf": "cpf", "rg": "rg", "cns": "cns", "pis_nis": "pis_nis", "telefone": "telefone", "email": "email",
            "data_nascimento": "data_nascimento", "placa_veiculo": "placa_veiculo"}


def _lines(words):
    from main import SentryApp
    return SentryApp._lines_from_words(words)


def _pipeline_values(maps):
    from utils.detect import rules
    from utils.ocr_engine import OCREngine
    eng = OCREngine(None)
    found = []
    for g in maps:
        if not g:
            continue
        found += [("cpf", norm(c)) for c in eng.find_cpfs_in_grounding(g)[1]]
        for t, (_c, vals) in rules.find_in_grounding(g, list(rules.RULES_BY_TYPE)).items():
            found += [(t, norm(v)) for v in vals]
    from utils.detect import ner
    if ner.available() and maps and maps[0]:  # pipeline completo: nomes com GLiNER, como no app
        for _t, slot in ner.find_names(maps[0]).items():
            found += [("nome_pessoa", norm(v)) for v in slot["valores"]]
    return found


def _matches(type_id, found_value, truth_value):
    return found_value == truth_value or same_value(type_id, found_value, truth_value) or \
        (len(found_value) >= 6 and (found_value in truth_value or truth_value in found_value))


def run(models, conditions, n_docs, seed, log=print):
    from utils import second_look
    from utils.ocr_engine import OCREngine
    os.environ["SECOND_LOOK"] = "1"
    ocr = OCREngine(os.getenv("TESSERACT_PATH"), lang=os.getenv("TESSERACT_LANG", "por"))
    docs = pii_corpus.generate(n_docs, seed)
    report, examples = {}, {}
    with tempfile.TemporaryDirectory() as tmp:
        for cond in conditions:
            pages = []
            for i, d in enumerate(docs):
                path = os.path.join(tmp, f"{cond}_{i}.png")
                render(d.text, cond, seed * 100 + i).save(path)
                std = ocr.get_grounding_map(path, psm="3")[1]
                sparse = ocr.get_grounding_map(path, psm="11")[1]
                truth = [(GAB_TYPE[t], norm(v)) for t, v in d.gabarito if t in GAB_TYPE]
                names = {f"{a} {b}" for a in pii_corpus.NOMES for b in pii_corpus.SOBRENOMES if f"{a} {b}" in d.text}
                truth += [("nome_pessoa", norm(n)) for n in names]
                pages.append((std, sparse, truth))
            for model in models:
                os.environ["SECOND_LOOK_MODEL"] = model
                c, secs = Counter(), 0.0
                for std, sparse, truth in pages:
                    base = _pipeline_values([std, sparse])
                    covered = {tv for t, tv in truth if any(_matches(t, fv, tv) for ft, fv in base if ft == t)}
                    for t, tv in truth:
                        group = "nomes" if t == "nome_pessoa" else "identificadores"
                        c[f"gabarito_{group}"] += 1
                        c[f"pipeline_{group}"] += int(tv in covered)
                    t0 = time.time()
                    items, info = second_look.run_agent(_lines(std), TYPES)
                    secs += time.time() - t0
                    if items is None:
                        c["falhas"] += 1
                        continue
                    for label, value in items:
                        type_id = second_look.type_id_for(label)
                        if type_id not in TYPES:
                            continue
                        value = second_look.core_value(type_id, value)
                        context = next((ln for ln in _lines(std).splitlines() if value[:6] in ln), "")
                        if not second_look.plausible(type_id, value, context):
                            c["recusados_implausiveis"] += 1
                            continue
                        if not second_look.locate(value, std):
                            c["descartados_nao_localizados"] += 1
                            continue
                        nv = norm(value)
                        hit = [tv for t, tv in truth if t == type_id and _matches(t, nv, tv)]
                        if not hit:
                            c["acrescimos_fora_do_gabarito"] += 1
                            other = [t for t, tv in truth if _matches(t, nv, tv)]
                            kind = f"tipo trocado ({type_id} -> {other[0]})" if other else f"{type_id}: {value}"
                            examples.setdefault(f"{cond} | {model}", []).append(kind)  # corpus fictício
                        for tv in hit:
                            if tv not in covered:
                                covered.add(tv)
                                group = "nomes" if type_id == "nome_pessoa" else "identificadores"
                                c[f"recuperados_{group}"] += 1
                c["s_por_pagina"] = round(secs / max(1, len(pages)), 1)
                key = f"{cond} | {model}"
                report[key] = dict(c)
                report[key]["exemplos_fora_do_gabarito"] = examples.get(key, [])[:12]
                log(f"  {key}: {dict(c)}")
                for e in examples.get(key, [])[:12]:
                    log(f"      fora do gabarito: {e}")
    return report


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--models", default="gemma4:e4b")
    ap.add_argument("--conditions", default="ruim,pessima")
    ap.add_argument("--docs", type=int, default=24)
    ap.add_argument("--seed", type=int, default=2027)
    ap.add_argument("--out")
    args = ap.parse_args(argv)
    try:
        from dotenv import load_dotenv
        load_dotenv(os.path.join(ROOT, ".env"))
    except ImportError:
        pass
    report = run([m for m in args.models.split(",") if m], [c for c in args.conditions.split(",") if c],
                 args.docs, args.seed)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())

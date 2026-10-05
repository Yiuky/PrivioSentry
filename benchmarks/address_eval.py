# SPDX-License-Identifier: AGPL-3.0-or-later
"""Avalia o LLM de descoberta de endereços (modelo × pedido) num corpus FICTÍCIO com resposta conhecida.

    python -m benchmarks.address_eval --models "gemma4:12b,hf.co/unsloth/Qwen3.5-9B-GGUF:Q6_K" \
        --variants legado,copia,copia_texto,copia_texto_schema --conditions padrao,ruim --docs 12

Cada página tem endereços pessoais, profissionais e secundários (benchmarks/pii_corpus.generate_addresses), com
abreviações, endereço partido entre linhas e iscas ("à Secretaria", "às 19:00", datas, valores). As respostas do LLM
passam pelo MESMO casamento do pipeline (locate_address_spans) sobre as palavras exatas da página, isolando a
qualidade do LLM da qualidade do OCR. Mede:
    cobertura_pessoal  fração das palavras dos endereços PESSOAIS que seriam tarjadas (o que protege)
    tarja_a_mais       palavras tarjadas fora de endereço pessoal (profissional/secundário confundido, ou outra coisa)
    inventados         endereços devolvidos que não existem na página (não localizados)
    classificacao      endereços do gabarito com tipo pessoal × não pessoal certo
    json_invalido      respostas que não viraram a lista esperada (o pipeline manda a página para revisão)
"""
import argparse
import base64
import io
import json
import os
import sys
import tempfile
import time
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmarks import pii_corpus  # noqa: E402
from benchmarks.ocr_compare import render  # noqa: E402
from benchmarks.pii_eval import text_grounding  # noqa: E402
from utils.address_redactor import (DISCOVERY_PROMPT, DISCOVERY_PROMPT_LEGACY, DISCOVERY_SCHEMA,  # noqa: E402
                                    classify_address_type, locate_address_spans, with_ocr_text)


def _prompt(variant, ocr_text):
    if variant == "legado":
        return DISCOVERY_PROMPT_LEGACY
    if variant == "copia":
        return DISCOVERY_PROMPT
    return with_ocr_text(DISCOVERY_PROMPT, ocr_text)


def ask(model, image, prompt, schema, timeout):
    """Mesma chamada do pipeline (utils/ai_client.py), com o formato estruturado opcional."""
    import requests
    from utils.ai_client import OllamaClient
    img = image.copy()
    size = int(os.getenv("AI_IMAGE_RESOLUTION", "2048"))
    img.thumbnail((size, size))
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "JPEG", quality=90)
    body = {"model": model, "stream": False, "think": False,
            "options": {"num_ctx": int(os.getenv("AI_CONTEXT_WINDOW", "32768")), "num_predict": 2048,
                        "temperature": 0.1, "top_p": 0.9},
            "messages": [{"role": "system", "content": "Você é um especialista em análise visual de documentos. "
                                                       "Extraia informações em JSON puro, sem explicações."},
                         {"role": "user", "content": prompt, "images": [base64.b64encode(buf.getvalue()).decode()]}]}
    if schema:
        body["format"] = DISCOVERY_SCHEMA
    url = os.getenv("OLLAMA_API_URL", "http://localhost:11434").rstrip("/") + "/api/chat"
    r = requests.post(url, json=body, timeout=timeout)
    r.raise_for_status()
    content = r.json().get("message", {}).get("content", "")
    return OllamaClient()._clean_json_response(content)


def evaluate_page(doc, response):
    words = text_grounding(doc.text)
    truth_personal, truth_other = set(), set()
    for text, kind in doc.enderecos:
        ids = {i for span in locate_address_spans(text, words) for i in span}
        (truth_personal if kind == "pessoal" else truth_other).update(ids)
    out = {"json_invalido": 0, "devolvidos": 0, "inventados": 0, "tarjadas": set(), "class_ok": 0, "class_total": 0}
    items = response.get("addresses") if isinstance(response, dict) else None
    if not isinstance(items, list):
        out["json_invalido"] = 1
        return out, truth_personal
    located = []
    for item in items:
        if not isinstance(item, dict) or not str(item.get("text") or "").strip():
            continue
        out["devolvidos"] += 1
        kind = classify_address_type(item.get("type"))
        ids = {i for span in locate_address_spans(str(item["text"]), words) for i in span}
        if not ids:
            out["inventados"] += 1
            continue
        personal = kind in ("pessoal", "desconhecido")  # desconhecido = tarja conservadora no pipeline
        located.append((ids, personal))
        if personal:
            out["tarjadas"] |= ids
    for text, kind in doc.enderecos:
        gold = {i for span in locate_address_spans(text, words) for i in span}
        if not gold:
            continue
        out["class_total"] += 1
        best = max(located, key=lambda x: len(x[0] & gold), default=None)
        if best and best[0] & gold and best[1] == (kind == "pessoal"):
            out["class_ok"] += 1
    out["tarja_a_mais"] = len(out["tarjadas"] - truth_personal)
    return out, truth_personal


def run(models, variants, conditions, n_docs, seed, timeout=300, log=print):
    from utils.ocr_engine import OCREngine
    docs = pii_corpus.generate_addresses(n_docs, seed)
    ocr = OCREngine(os.getenv("TESSERACT_PATH"), lang=os.getenv("TESSERACT_LANG", "por"))
    report = {"docs": n_docs, "seed": seed, "resultados": {}}
    with tempfile.TemporaryDirectory() as tmp:
        for cond in conditions:
            pages = []
            for i, doc in enumerate(docs):
                img = render(doc.text, cond, seed * 1000 + i)
                path = os.path.join(tmp, f"{cond}_{i}.png")
                img.save(path)
                ocr_text = " ".join(w["text"] for w in ocr.get_grounding_map(path, psm="3")[1])
                pages.append((doc, img, ocr_text))
            for model in models:
                for variant in variants:
                    agg = defaultdict(float)
                    times = []
                    for doc, img, ocr_text in pages:
                        t0 = time.time()
                        try:
                            resp = ask(model, img, _prompt(variant, ocr_text), variant.endswith("schema"), timeout)
                        except Exception as e:
                            resp = {"error": str(e)}
                            log(f"[erro] {model} {variant}: {str(e)[:100]}")
                        times.append(time.time() - t0)
                        res, truth = evaluate_page(doc, resp)
                        agg["pessoais"] += len(truth)
                        agg["cobertas"] += len(res["tarjadas"] & truth)
                        for k in ("json_invalido", "devolvidos", "inventados", "class_ok", "class_total"):
                            agg[k] += res[k]
                        agg["tarja_a_mais"] += res.get("tarja_a_mais", 0)
                    key = f"{cond} | {model} | {variant}"
                    report["resultados"][key] = {
                        "cobertura_pessoal": round(agg["cobertas"] / agg["pessoais"], 3) if agg["pessoais"] else None,
                        "tarja_a_mais": int(agg["tarja_a_mais"]),
                        "inventados": f"{int(agg['inventados'])}/{int(agg['devolvidos'])}",
                        "classificacao": f"{int(agg['class_ok'])}/{int(agg['class_total'])}",
                        "json_invalido": int(agg["json_invalido"]),
                        "s_por_pagina": round(sum(times) / len(times), 1),
                    }
                    log(f"  {key}: {report['resultados'][key]}")
    return report


def to_markdown(report):
    lines = ["| Condição | Modelo | Pedido | Cobertura pessoal | Tarja a mais | Inventados | Classificação | JSON inválido | s/pág |",
             "|---|---|---|---:|---:|---:|---:|---:|---:|"]
    for key, r in report["resultados"].items():
        cond, model, variant = key.split(" | ")
        cov = "—" if r["cobertura_pessoal"] is None else f"{r['cobertura_pessoal']:.0%}"
        lines.append(f"| {cond} | {model.split('/')[-1]} | {variant} | {cov} | {r['tarja_a_mais']} | {r['inventados']} | "
                     f"{r['classificacao']} | {r['json_invalido']} | {r['s_por_pagina']} |")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--models", default=os.getenv("OLLAMA_VISION_MODEL", ""))
    ap.add_argument("--variants", default="legado,copia,copia_texto,copia_texto_schema")
    ap.add_argument("--conditions", default="padrao,ruim")
    ap.add_argument("--docs", type=int, default=12)
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--out")
    args = ap.parse_args(argv)
    report = run([m for m in args.models.split(",") if m], [v for v in args.variants.split(",") if v],
                 [c for c in args.conditions.split(",") if c], args.docs, args.seed)
    print(to_markdown(report))
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
    return 0


if __name__ == "__main__":
    try:
        from dotenv import load_dotenv
        load_dotenv(os.path.join(ROOT, ".env"))
    except ImportError:
        pass
    sys.exit(main())

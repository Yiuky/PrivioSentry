# SPDX-License-Identifier: AGPL-3.0-or-later
"""Benchmark SINTETICO e reproduzivel da deteccao e da verificacao de CPF.

Uso (na raiz do projeto, com o venv ativo):
    python -m benchmarks.run_benchmark --pages 8 --dpis 200 300 400 --psms 3 6 11 --workers 4 --seed 42

O que mede (tudo sobre PDFs escaneados GERADOS por benchmarks/synthetic.py; nenhum dado real):
  1. DETECCAO: renderiza o PDF original em cada DPI, roda OCR (psm) + find_cpfs_in_grounding e compara
     com o ground truth: recall/precisao dos CPFs (valor) e cobertura geometrica das caixas de tarja.
  2. VERIFICACAO: monta PDFs "finais" (imagem 1240px, JPEG q75, como o pipeline) em dois cenarios:
     "leaky" (tarja so no 1o CPF de cada pagina; os demais vazam) e "clean" (todos tarjados), e roda
     utils.verifier.verify_pdf em cada DPI/psm: recall de vazamentos e falsos positivos em paginas limpas.
Tempos sao de parede por pagina (OCR single-thread por processo; com --workers > 1 ha contencao de CPU).
"""
import argparse
import json
import os
import platform
import shutil
import statistics
import sys
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor

from dotenv import load_dotenv

from benchmarks.env import get_ocr_config
from benchmarks.synthetic import PAGE_H, PAGE_W, available_fonts, build_scanned_pdf, render_page

DEFAULT_DPIS = (200, 300, 400)
DEFAULT_PSMS = (3, 6, 11)
BOX_PADDING = 10


def _engine():
    from utils.ocr_engine import OCREngine
    path, lang = get_ocr_config()
    return OCREngine(tesseract_path=path, lang=lang)


def _worker_init():
    os.environ["OMP_THREAD_LIMIT"] = "1"  # Tesseract single-thread por processo


def _covered(truth_box, boxes, render_size):
    """Centro da caixa-verdade (px a 300 DPI) cai dentro de alguma caixa detectada (px do render)?"""
    cx = (truth_box[0] + truth_box[2]) / 2.0 / PAGE_W
    cy = (truth_box[1] + truth_box[3]) / 2.0 / PAGE_H
    rw, rh = render_size
    for b in boxes:
        if b["x"] / rw <= cx <= (b["x"] + b["w"]) / rw and b["y"] / rh <= cy <= (b["y"] + b["h"]) / rh:
            return True
    return False


def detection_task(args):
    pdf_path, page_idx, dpi, psm, truth_cpfs, truth_boxes, workdir = args
    import fitz
    from utils.session import Session
    engine = _engine()
    t0 = time.perf_counter()
    with fitz.open(pdf_path) as doc:
        pix = doc[page_idx].get_pixmap(matrix=fitz.Matrix(dpi / 72.0, dpi / 72.0), alpha=False)
        img_path = os.path.join(workdir, f"det_{page_idx}_{dpi}_{psm}.png")
        pix.save(img_path)
        render_size = (pix.width, pix.height)
    t_render = time.perf_counter() - t0
    t1 = time.perf_counter()
    _, grounding = engine.get_grounding_map(img_path, psm=str(psm))
    commands, found = engine.find_cpfs_in_grounding(grounding)
    t_ocr = time.perf_counter() - t1
    session = Session(pdf_path, output_dir=os.path.join(workdir, "work_det"), final_dir=os.path.join(workdir, "fin_det"))
    boxes = session.get_redaction_boxes(grounding, commands, padding=BOX_PADDING)
    session.close()
    truth = set(truth_cpfs)
    covered = sum(1 for tb in truth_boxes if _covered(tb, boxes, render_size))
    os.remove(img_path)
    return {
        "kind": "detection", "page": page_idx, "dpi": dpi, "psm": psm,
        "tp": len(found & truth), "fp": len(found - truth), "fn": len(truth - found),
        "boxes_total": len(truth_boxes), "boxes_covered": covered,
        "seconds_ocr": round(t_ocr, 3), "seconds_render": round(t_render, 3),
    }


def verification_task(args):
    final_pdf, scenario, dpi, psm, leaked_by_page = args
    from utils.verifier import verify_pdf
    engine = _engine()
    t0 = time.perf_counter()
    leftovers, unverified = verify_pdf(final_pdf, ocr_engine=engine, use_ocr=True, dpi=dpi, psm=str(psm))
    elapsed = time.perf_counter() - t0
    n_pages = len(leaked_by_page)
    leaked_total = found_leaks = unexpected = flagged_pages = 0
    for page_num in range(1, n_pages + 1):
        leaked = set(leaked_by_page[page_num - 1])
        found = set(leftovers.get(page_num, set()))
        leaked_total += len(leaked)
        found_leaks += len(found & leaked)
        unexpected += len(found - leaked)
        if found:
            flagged_pages += 1
    return {
        "kind": "verification", "scenario": scenario, "dpi": dpi, "psm": psm, "pages": n_pages,
        "leaked_total": leaked_total, "leaks_found": found_leaks, "unexpected_found": unexpected,
        "pages_flagged": flagged_pages, "unverified_pages": len(unverified),
        "seconds_per_page": round(elapsed / max(1, n_pages), 3),
    }


def build_corpus(workdir, n_pages, seed, noise_sigma):
    """Gera PDF escaneado original + PDFs finais 'leaky' e 'clean' (como o pipeline os produz)."""
    from utils.session import Session
    images, truths = [], []
    for i in range(n_pages):
        img, truth = render_page(seed * 1000 + i, noise_sigma=noise_sigma)
        images.append(img)
        truths.append(truth)
    original = build_scanned_pdf(os.path.join(workdir, "original.pdf"), images)

    finals = {}
    for scenario in ("leaky", "clean"):
        pdf_copy = os.path.join(workdir, f"{scenario}.pdf")
        shutil.copy(original, pdf_copy)
        session = Session(pdf_copy, output_dir=os.path.join(workdir, "work_" + scenario),
                          final_dir=os.path.join(workdir, "final_" + scenario))
        out_images = []
        for i, (img, truth) in enumerate(zip(images, truths)):
            png = os.path.join(workdir, f"{scenario}_page_{i + 1}.png")
            img.convert("RGB").save(png)
            covered = truth.cpf_boxes[:1] if scenario == "leaky" else truth.cpf_boxes
            boxes = [{"x": int(b[0]) - BOX_PADDING, "y": int(b[1]) - BOX_PADDING,
                      "w": int(b[2] - b[0]) + 2 * BOX_PADDING, "h": int(b[3] - b[1]) + 2 * BOX_PADDING}
                     for b in covered]
            out_images.append(session.apply_final_redactions(i + 1, png, boxes, dir_key="05_combined"))
        final = session.reconstitute_pdf(out_images, output_suffix="_FINAL.pdf")
        session.close()
        if not final:
            raise RuntimeError(f"Falha ao montar o PDF final do cenario {scenario}")
        finals[scenario] = final
    return original, finals, truths


def _agg(rows, key):
    vals = [r[key] for r in rows]
    return round(statistics.mean(vals), 3) if vals else None


def summarize(results, dpis, psms):
    summary = {"detection": [], "verification": []}
    for dpi in dpis:
        for psm in psms:
            det = [r for r in results if r["kind"] == "detection" and r["dpi"] == dpi and r["psm"] == psm]
            if det:
                tp, fp, fn = (sum(r[k] for r in det) for k in ("tp", "fp", "fn"))
                bt, bc = sum(r["boxes_total"] for r in det), sum(r["boxes_covered"] for r in det)
                summary["detection"].append({
                    "dpi": dpi, "psm": psm, "cpfs": tp + fn, "tp": tp, "fp": fp, "fn": fn,
                    "recall": round(tp / (tp + fn), 4) if tp + fn else None,
                    "precision": round(tp / (tp + fp), 4) if tp + fp else None,
                    "box_coverage": round(bc / bt, 4) if bt else None,
                    "seconds_per_page": round(_agg(det, "seconds_ocr") + _agg(det, "seconds_render"), 3),
                    "pages": len(det),
                })
            ver = [r for r in results if r["kind"] == "verification" and r["dpi"] == dpi and r["psm"] == psm]
            if ver:
                leaky = next((r for r in ver if r["scenario"] == "leaky"), None)
                clean = next((r for r in ver if r["scenario"] == "clean"), None)
                summary["verification"].append({
                    "dpi": dpi, "psm": psm,
                    "leaks": leaky["leaked_total"] if leaky else None,
                    "leaks_found": leaky["leaks_found"] if leaky else None,
                    "leak_recall": round(leaky["leaks_found"] / leaky["leaked_total"], 4)
                    if leaky and leaky["leaked_total"] else None,
                    "clean_pages": clean["pages"] if clean else None,
                    "clean_pages_flagged": clean["pages_flagged"] if clean else None,
                    "clean_unexpected_cpfs": clean["unexpected_found"] if clean else None,
                    "unverified_pages": sum(r["unverified_pages"] for r in ver),
                    "seconds_per_page": round(statistics.mean(r["seconds_per_page"] for r in ver), 3),
                })
    return summary


def to_markdown(summary):
    lines = ["### Deteccao (OCR do PDF original)", "",
             "| DPI | psm | CPFs | recall | precisao | cobertura de caixas | s/pagina |",
             "|---:|---:|---:|---:|---:|---:|---:|"]
    for r in summary["detection"]:
        lines.append(f"| {r['dpi']} | {r['psm']} | {r['cpfs']} | {r['recall']:.1%} | "
                     f"{(r['precision'] if r['precision'] is not None else float('nan')):.1%} | "
                     f"{r['box_coverage']:.1%} | {r['seconds_per_page']:.1f} |")
    lines += ["", "### Verificacao (PDF final 1240 px / JPEG q75)", "",
              "| DPI | psm | vazamentos | encontrados | recall | paginas limpas sinalizadas | s/pagina |",
              "|---:|---:|---:|---:|---:|---:|---:|"]
    for r in summary["verification"]:
        lines.append(f"| {r['dpi']} | {r['psm']} | {r['leaks']} | {r['leaks_found']} | {r['leak_recall']:.1%} | "
                     f"{r['clean_pages_flagged']}/{r['clean_pages']} | {r['seconds_per_page']:.1f} |")
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--pages", type=int, default=8)
    parser.add_argument("--dpis", type=int, nargs="+", default=list(DEFAULT_DPIS))
    parser.add_argument("--psms", type=int, nargs="+", default=list(DEFAULT_PSMS))
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--noise", type=float, default=8.0, help="sigma do ruido gaussiano (0 desliga)")
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--out", default=os.path.join("benchmarks", "results", "synthetic_benchmark.json"))
    args = parser.parse_args(argv)

    load_dotenv()
    if not get_ocr_config():
        print("Tesseract nao encontrado (defina TESSERACT_PATH). Abortando.", file=sys.stderr)
        return 2
    path, lang = get_ocr_config()

    workdir = tempfile.mkdtemp(prefix="sentry_bench_")
    try:
        print(f"[bench] gerando corpus sintetico ({args.pages} paginas, seed={args.seed}) em {workdir}")
        original, finals, truths = build_corpus(workdir, args.pages, args.seed, args.noise)

        tasks = []
        for dpi in args.dpis:
            for psm in args.psms:
                for i, tr in enumerate(truths):
                    tasks.append((detection_task, (original, i, dpi, psm, tr.cpfs, tr.cpf_boxes, workdir)))
                for scenario, final in finals.items():
                    leaked = [tr.cpfs[1:] if scenario == "leaky" else [] for tr in truths]
                    tasks.append((verification_task, (final, scenario, dpi, psm, leaked)))

        print(f"[bench] {len(tasks)} tarefas, workers={args.workers}")
        results = []
        t0 = time.perf_counter()
        if args.workers > 1:
            with ProcessPoolExecutor(max_workers=args.workers, initializer=_worker_init) as pool:
                futures = [pool.submit(fn, a) for fn, a in tasks]
                for n, fut in enumerate(futures, 1):
                    results.append(fut.result())
                    if n % 10 == 0:
                        print(f"[bench] {n}/{len(futures)}")
        else:
            _worker_init()
            for n, (fn, a) in enumerate(tasks, 1):
                results.append(fn(a))
                if n % 10 == 0:
                    print(f"[bench] {n}/{len(tasks)}")
        wall = time.perf_counter() - t0

        summary = summarize(results, args.dpis, args.psms)
        report = {
            "meta": {
                "seed": args.seed, "pages": args.pages, "noise_sigma": args.noise, "workers": args.workers,
                "tesseract": path, "lang": lang, "fonts": [os.path.basename(f) for f in available_fonts()],
                "platform": platform.platform(), "python": platform.python_version(),
                "wall_seconds": round(wall, 1), "cpf_total": sum(len(t.cpfs) for t in truths),
            },
            "summary": summary,
            "raw": results,
        }
        os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        print(to_markdown(summary))
        print(f"\n[bench] resultados em {args.out} ({wall:.0f}s)")
        return 0
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())

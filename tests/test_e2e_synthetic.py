# SPDX-License-Identifier: AGPL-3.0-or-later
"""Ponta a ponta SINTETICO: PDF escaneado -> pipeline (Tesseract real, IA falsa) -> PDF final -> verificador.

Requer Tesseract (skip se ausente). Marcado integration/slow:
    pytest -m integration            # so estes
    pytest -m "not slow"             # exclui-os
"""
import os

import fitz
import pytest

from benchmarks.synthetic import PAGE_H, PAGE_W, make_document
from sentry_testkit import FULL_CPF_RE, text_files_under

pytestmark = [pytest.mark.integration, pytest.mark.slow]


@pytest.fixture(scope="module")
def run(tmp_path_factory, ocr_config):
    """Executa o pipeline uma unica vez e devolve tudo o que os testes precisam inspecionar."""
    base = tmp_path_factory.mktemp("e2e")
    path, lang = ocr_config
    pdf, images, truths = make_document(str(base / "in"), "doc_sintetico", n_pages=2, seed=7, noise_sigma=6.0)

    mp = pytest.MonkeyPatch()
    mp.setenv("TESSERACT_PATH", path)
    mp.setenv("TESSERACT_LANG", lang)
    mp.setenv("BASE_DPI", "300")
    mp.setenv("VERIFY_DPI", "200")
    mp.setenv("VERIFY_OCR", "1")
    mp.setenv("TESSERACT_SPARSE_PSM", "")
    mp.setenv("YOLO_MODEL_PATH", str(base / "sem_modelo.pt"))   # sem YOLO: degrada com aviso
    from main import SentryApp
    app = SentryApp(pdf, output_dir=str(base / "work"), final_dir=str(base / "final"))
    # IA de visao falsa: "sem enderecos" (nao ha IA local neste teste)
    ai_calls = []
    app.address_redactor.ai.analyze_image = lambda p, prompt: (ai_calls.append(p) or {"addresses": []}, b"", {})
    progress = []
    final_pdf = app.run(progress_callback=progress.append)
    state = app.final_state()
    app.session.close()
    mp.undo()
    return {"app": app, "pdf": pdf, "final": final_pdf, "truths": truths, "state": state,
            "progress": progress, "ai_calls": ai_calls, "base": base}


def test_pipeline_completes_and_produces_final_pdf(run):
    assert os.path.exists(run["final"])
    with fitz.open(run["final"]) as d, fitz.open(run["pdf"]) as orig:
        assert len(d) == len(orig) == 2
        assert d[0].rect == orig[0].rect
    assert [p["percentage"] for p in run["progress"]][-1] == 100
    assert len(run["ai_calls"]) == 2   # 1 chamada de descoberta de enderecos por pagina


def test_all_known_cpfs_are_redacted_geometrically(run):
    """Prova independente do OCR: a regiao de cada CPF do ground truth esta preta no PDF final."""
    with fitz.open(run["final"]) as doc:
        for page_idx, truth in enumerate(run["truths"]):
            page = doc[page_idx]
            for box in truth.cpf_boxes:
                x0, y0, x1, y1 = (box[0] / PAGE_W * page.rect.width, box[1] / PAGE_H * page.rect.height,
                                  box[2] / PAGE_W * page.rect.width, box[3] / PAGE_H * page.rect.height)
                # centro da caixa (evita as bordas, onde o JPEG suaviza)
                cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
                clip = fitz.Rect(cx - 5, cy - 2, cx + 5, cy + 2)
                pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), clip=clip, alpha=False)
                lum = sum(pix.samples) / len(pix.samples)
                assert lum < 40, f"pag {page_idx + 1}: CPF nao tarjado em {box} (luminancia {lum:.0f})"


def test_verifier_finds_no_cpf_left_in_final_pdf(run, real_ocr):
    from utils.verifier import verify_pdf
    leftovers, unverified = verify_pdf(run["final"], ocr_engine=real_ocr, use_ocr=True, dpi=300, psm="6")
    assert leftovers == {}
    assert unverified == []


def test_decoys_are_not_blackened_over_redaction(run):
    """Nao ha tarja excessiva: a maior parte da pagina continua clara (iscas e texto preservados)."""
    with fitz.open(run["final"]) as doc:
        pix = doc[0].get_pixmap(matrix=fitz.Matrix(0.5, 0.5), alpha=False)
        dark = sum(1 for v in pix.samples[::3] if v < 40) / (len(pix.samples) / 3)
    assert dark < 0.05


def test_state_is_never_silently_completed(run):
    state = run["state"]
    # Sem modelo YOLO ha aviso explicito; qualquer revisao pendente vem acompanhada de alertas
    assert any("YOLO" in a for a in state["alerts"])
    if state["needs_review"]:
        assert state["status"] == "Requer revisão" and state["alerts"]
    else:
        assert state["status"] == "Concluído"


def test_no_full_cpf_in_any_text_artifact(run):
    """Nenhum CPF completo (formatado ou nao) em logs, JSON, prompts, respostas: so o PDF/imagens o contem."""
    checked = 0
    for path in text_files_under(str(run["base"] / "work")):
        text = open(path, encoding="utf-8", errors="replace").read()
        assert not FULL_CPF_RE.search(text), os.path.relpath(path, run["base"])
        for truth in run["truths"]:
            for cpf in truth.cpfs:
                assert cpf not in text
        checked += 1
    assert checked >= 4    # log, metadados, detected_cpfs, interacoes de IA...
    masks = open(str(run["base"] / "work" / "doc_sintetico" / "detected_cpfs.txt"), encoding="utf-8").read().split()
    assert len(masks) == sum(len(t.cpfs) for t in run["truths"]) and all(m.startswith("***.***.") for m in masks)


def test_benchmark_script_smoke(tmp_path):
    """O script de benchmark roda ponta a ponta numa configuracao minima e gera o JSON de resultados."""
    import json
    from benchmarks.env import get_ocr_config
    from benchmarks.run_benchmark import main as bench_main
    if not get_ocr_config():
        pytest.skip("Tesseract nao encontrado")
    out = tmp_path / "bench.json"
    assert bench_main(["--pages", "1", "--dpis", "200", "--psms", "6", "--out", str(out)]) == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    det = report["summary"]["detection"][0]
    assert det["cpfs"] == 3 and det["recall"] is not None
    assert report["summary"]["verification"][0]["leaks"] == 2

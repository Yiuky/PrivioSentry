# SPDX-License-Identifier: AGPL-3.0-or-later
"""Fases do pipeline (main.SentryApp) isoladas, com engines falsos (sem Tesseract/YOLO/Ollama)."""
import json
import os

import fitz
import pytest

import main
from main import SentryApp
from sentry_testkit import (CPF_A, CPF_A_FMT, CPF_B, CPF_B_FMT, FULL_CPF_RE, make_blank_image,
                              make_text_pdf, text_files_under, word)
from utils.ocr_engine import OCREngine


class FakeOCR(OCREngine):
    """OCR falso: get_grounding_map devolve mapas canned; a deteccao de CPF e a real."""

    def __init__(self, provider):
        super().__init__(tesseract_path=None)
        self.provider = provider
        self.calls = []

    def get_grounding_map(self, img_path, psm=3):
        self.calls.append((os.path.basename(img_path), str(psm)))
        return self.provider(img_path, str(psm))


def cpf_page_map(img_path, psm):
    gm = [word(0, "CPF:", 0, y=100), word(1, CPF_A_FMT, 200, y=100, w=280, h=30)]
    return "[0] CPF: [1] " + CPF_A_FMT, gm


@pytest.fixture()
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("BASE_DPI", "50")
    pdf = make_text_pdf(tmp_path / "doc.pdf", n_pages=2)
    a = SentryApp(pdf)
    yield a
    a.session.close()


def render(app):
    app.run_phase_0()
    return app.image_paths


# --- fase 0 ------------------------------------------------------------------------------------
def test_phase0_renders_pages(app):
    paths = render(app)
    assert [os.path.basename(p) for p in paths] == ["doc_page_1.png", "doc_page_2.png"]
    assert all(os.path.exists(p) for p in paths)


def test_phase0_failure_raises_wrapped_error(tmp_path):
    a = SentryApp(str(tmp_path / "nao_existe.pdf"))
    with pytest.raises(Exception, match="Erro na Fase 0"):
        a.run_phase_0()
    a.session.close()


# --- fases 1 e 2 (OCR + CPFs) ------------------------------------------------------------------
def test_phase1_runs_standard_and_sparse_passes(app, monkeypatch):
    monkeypatch.setenv("TESSERACT_STD_PSM", "4")
    monkeypatch.setenv("TESSERACT_SPARSE_PSM", "11")
    render(app)
    app.ocr = FakeOCR(cpf_page_map)
    seen = []
    app.progress_callback = seen.append
    app.run_phase_1()
    assert [c[1] for c in app.ocr.calls] == ["4", "11", "4", "11"]
    assert len(app.grounding_maps) == len(app.grounding_maps_sparse) == len(app.indexed_texts) == 2
    assert seen and seen[-1]["status"].startswith("OCR: Pagina 2/2")


def test_phase1_without_sparse_pass_stores_empty_sparse_maps(app):
    render(app)
    app.ocr = FakeOCR(cpf_page_map)
    app.run_phase_1()
    assert app.grounding_maps_sparse == [[], []]
    assert [c[1] for c in app.ocr.calls] == ["3", "3"]


def test_phase2_collects_cpfs_from_both_passes_and_stores_only_masks(app):
    render(app)
    std = {1: [word(0, CPF_A_FMT, 100, y=100, w=280, h=30)], 2: [word(0, "sem cpf", 0)]}
    sparse = {1: [], 2: [word(0, CPF_B_FMT, 100, y=400, w=280, h=30)]}
    app.grounding_maps = [std[1], std[2]]
    app.grounding_maps_sparse = [sparse[1], sparse[2]]
    app.run_phase_2()
    assert set(app.known_cpfs) == {CPF_A, CPF_B}
    assert len(app.cpf_redactions[1]) == 1 and len(app.cpf_redactions[2]) == 1
    assert app.global_redactions[1] == app.cpf_redactions[1]
    saved = open(os.path.join(app.session.output_dir, "detected_cpfs.txt"), encoding="utf-8").read()
    assert not FULL_CPF_RE.search(saved)
    assert sorted(saved.split()) == ["***.***.247-25", "***.***.777-35"]


def test_phase2_handles_sparse_list_shorter_than_pages(app):
    render(app)
    app.grounding_maps = [[word(0, CPF_A_FMT, 0, w=280)], []]
    app.grounding_maps_sparse = [[]]
    app.run_phase_2()
    assert app.known_cpfs == [CPF_A]


# --- fases 3 e 4 (YOLO + micro-auditoria) -------------------------------------------------------
class FakeYOLO:
    instances = []

    def __init__(self, model_path=None, logger=None, model=True, crops=None, error=None):
        self.model = model
        self.crops = crops or []
        self.last_error = None
        self.error = error
        FakeYOLO.instances.append(self)

    def get_candidates(self, img_path, crop_dir=None, page_num=0, **kw):
        self.last_error = self.error if page_num == 2 else None
        if page_num == 1:
            return [{"label": "signature", "conf": 0.9, "bbox": [10, 10, 60, 40]}], list(self.crops)
        return [], []


def test_phase3_without_model_warns_but_does_not_block(app, monkeypatch):
    monkeypatch.setattr(main, "YOLOEngine", lambda **kw: FakeYOLO(model=None))
    render(app)
    app.run_phase_3()
    assert not hasattr(app, "all_crops_metadata")
    assert any("YOLO" in a for a in app.alerts)
    assert not app.needs_review  # degradacao com aviso, nao reprova


def test_phase3_collects_crops_and_fails_closed_on_yolo_error(app, monkeypatch):
    crop = {"path": "c.jpg", "page_num": 1, "origin_bbox": (0, 0, 50, 50), "tight_bbox": [1, 1, 2, 2]}
    monkeypatch.setattr(main, "YOLOEngine", lambda **kw: FakeYOLO(crops=[crop], error="CUDA OOM"))
    render(app)
    exported = []
    monkeypatch.setattr(app.session, "export_yolo_results", lambda *a: exported.append(a[0]))
    app.run_phase_3()
    assert app.all_crops_metadata == [crop]
    assert exported == [1, 2]
    assert 2 in app.review_pages and "YOLO" in app.review_pages[2][0]
    assert 1 not in app.review_pages


def test_phase4_micro_audit_offsets_boxes_by_crop_origin(app, tmp_path):
    crop_img = make_blank_image(tmp_path / "crop.jpg", size=(400, 100))
    app.ocr = FakeOCR(lambda p, psm: ("", [word(0, CPF_A_FMT, 20, y=10, w=280, h=30)]))
    app.all_crops_metadata = [{"path": crop_img, "page_num": 2, "origin_bbox": (500, 700, 900, 800)}]
    app.run_phase_4()
    boxes = app.cpf_redactions[2]
    assert len(boxes) == 1
    assert boxes[0]["x"] == 500 + 10 and boxes[0]["y"] == 700 + 0  # x-pad(10) / y-pad(10) do get_redaction_boxes
    assert app.global_redactions[2] == boxes
    assert app.ocr.calls[0][1] == "6"  # TESSERACT_CROP_PSM padrao


def test_phase4_noop_without_crops(app):
    app.run_phase_4()
    app.all_crops_metadata = []
    app.run_phase_4()
    assert not app.global_redactions


# --- enderecos (fase 6) ------------------------------------------------------------------------
def setup_address_page(app, words, addresses, page=1):
    gm = [word(i, t, 100 * i) for i, t in enumerate(words)]
    app.grounding_maps = [gm]
    app.indexed_texts = [" ".join(f"[{i}] {t}" for i, t in enumerate(words))]
    app.address_redactor.results = {page: addresses}
    return gm


def test_phase6_redacts_personal_address_words_only(app):
    gm = setup_address_page(app, ["Rua", "das", "Flores", "123", "Bairro:", "Centro", "Obra"],
                            [{"text": "Rua das Flores 123, Centro", "type": "pessoal"}])
    app.run_phase_6()
    redacted = {b["x"] for b in app.address_redactions[1]}
    # Flores, 123, Centro tarjados; Rua/das/Bairro:/Obra nao
    assert redacted == {gm[2]["box"]["x"], gm[3]["box"]["x"], gm[5]["box"]["x"]}
    assert app.global_redactions[1] == app.address_redactions[1]


def test_phase6_ignores_professional_addresses_and_missing_pages(app):
    setup_address_page(app, ["Avenida", "Brasil", "500"], [{"text": "Avenida Brasil 500", "type": "profissional"}])
    app.address_redactor.results[9] = [{"text": "Rua X 1", "type": "pessoal"}]  # pagina inexistente
    app.run_phase_6()
    assert not app.address_redactions


def test_phase6_panic_fallback_redacts_everything_matching_and_alerts(app, monkeypatch):
    gm = setup_address_page(app, ["Rua", "Flores", "10"], [{"text": "Rua Flores 10", "type": "pessoal"}])
    monkeypatch.setattr(app.address_redactor, "refine_redaction_with_text_ai", lambda *a, **k: ["FALLBACK_ALL"])
    seen = []
    app.progress_callback = seen.append
    app.run_phase_6()
    assert {b["x"] for b in app.address_redactions[1]} == {gm[1]["box"]["x"], gm[2]["box"]["x"]}
    assert any("Pânico" in a for a in app.alerts)


def test_phase6_skips_label_immune_and_bad_ids(app, monkeypatch):
    gm = setup_address_page(app, ["Rua", "Endereco:", "Flores", "10"], [{"text": "x", "type": "pessoal"}])
    monkeypatch.setattr(app.address_redactor, "refine_redaction_with_text_ai",
                        lambda *a, **k: [0, 1, 2, "nao-int", 99, -1, None])
    app.run_phase_6()
    assert [b["x"] for b in app.address_redactions[1]] == [gm[2]["box"]["x"]]


# --- auditoria de assinatura (fase 7) ----------------------------------------------------------
def make_crop(app, tmp_path, name="sig.jpg", origin=(100, 200, 300, 260), page=1):
    path = make_blank_image(tmp_path / name, size=(origin[2] - origin[0], origin[3] - origin[1]))
    return {"path": path, "page_num": page, "origin_bbox": origin}


def set_ai(app, monkeypatch, response):
    prompts = []

    def fake(path, prompt):
        prompts.append(prompt)
        return response, b"\xff\xd8bytes", {"total_duration_ms": 1}

    monkeypatch.setattr(app.address_redactor.ai, "analyze_image", fake)
    return prompts


def test_signature_audit_without_crops_is_noop(app):
    app.run_signature_audit()
    assert not hasattr(app, "unredacted_cpfs")


def test_signature_audit_flags_unredacted_cpf_with_emergency_box_and_masks_artifacts(app, tmp_path, monkeypatch):
    crop = make_crop(app, tmp_path)
    app.all_crops_metadata = [crop]
    app.known_cpfs = [CPF_A]
    prompts = set_ai(app, monkeypatch, {"unredacted_cpfs": [CPF_A_FMT, {"cpf": CPF_B_FMT}, ""]})
    app.global_redactions[1].append({"x": 110, "y": 210, "w": 50, "h": 20})  # tarja existente sobre o crop
    app.run_signature_audit()
    emergency = {"x": 100, "y": 200, "w": 200, "h": 60}
    assert app.global_redactions[1].count(emergency) == 1  # sem duplicar mesmo com 2 CPFs reportados
    assert emergency in app.cpf_redactions[1]
    assert CPF_A in prompts[0] or CPF_A_FMT in prompts[0] or CPF_A in prompts[0]  # dica vai ao modelo local
    redacted_crop = os.path.join(app.session.dirs["04_signatures_tarjados"], "sig_redacted_audit.jpg")
    assert os.path.exists(redacted_crop)
    # artefatos de texto e log: nenhum CPF completo
    for path in text_files_under(app.session.output_dir):
        assert not FULL_CPF_RE.search(open(path, encoding="utf-8").read()), path


def test_signature_audit_clean_response_adds_nothing(app, tmp_path, monkeypatch):
    app.all_crops_metadata = [make_crop(app, tmp_path)]
    set_ai(app, monkeypatch, {"unredacted_cpfs": []})
    app.run_signature_audit()
    assert not app.global_redactions[1]
    assert not app.needs_review


def test_signature_audit_ai_error_redacts_whole_crop_and_requires_review(app, tmp_path, monkeypatch):
    app.all_crops_metadata = [make_crop(app, tmp_path)]
    set_ai(app, monkeypatch, {"error": "timeout"})
    app.run_signature_audit()
    assert app.global_redactions[1] == [{"x": 100, "y": 200, "w": 200, "h": 60}]
    assert 1 in app.review_pages
    assert any("Pânico (Assinaturas)" in a for a in app.alerts)


def test_signature_audit_non_dict_response_is_ignored_safely(app, tmp_path, monkeypatch):
    app.all_crops_metadata = [make_crop(app, tmp_path)]
    set_ai(app, monkeypatch, ["lista", "inesperada"])
    app.run_signature_audit()
    assert not app.global_redactions[1]


def test_signature_audit_skips_unreadable_crop(app, tmp_path, monkeypatch):
    bad = tmp_path / "bad.jpg"
    bad.write_bytes(b"nao-e-imagem")
    app.all_crops_metadata = [{"path": str(bad), "page_num": 1, "origin_bbox": (0, 0, 10, 10)}]
    prompts = set_ai(app, monkeypatch, {"unredacted_cpfs": []})
    app.run_signature_audit()
    assert prompts == []


# --- metadados / modos de execucao -------------------------------------------------------------
def test_extract_page_num():
    a = SentryApp.__new__(SentryApp)
    assert a._extract_page_num("x/doc_page_12.png") == 12
    assert a._extract_page_num("x/semnumero.png") == 0
    assert a._extract_page_num("x/doc_page_abc.png") == 0


def test_load_metadata_orders_images_and_maps_redaction_types(app):
    orig = app.session.dirs["00_raw"]
    for n in (10, 2, 1):
        make_blank_image(os.path.join(orig, f"doc_page_{n}.png"), size=(10, 10))
    reds = [
        {"page": 1, "type": "pii", "coords": [10, 20, 110, 70], "source": "AI_Engine", "image_width": 800},
        {"page": "2", "type": "signature", "coords": [0, 0, 5, 5]},
        {"page": 1, "type": "outro", "coords": [1, 1, 2, 2]},
        {"page": 1, "type": "pii", "coords": [1, 2, 3]},          # coords invalidas: ignorada
        {"page": "x", "type": "pii", "coords": [1, 1, 2, 2]},     # pagina invalida: erro tratado
    ]
    app._load_metadata_safely(reds)
    assert [os.path.basename(p) for p in app.image_paths] == ["doc_page_1.png", "doc_page_2.png", "doc_page_10.png"]
    assert app.address_redactions[1] == [{"x": 10, "y": 20, "w": 100, "h": 50, "source_width": 800.0}]
    assert app.cpf_redactions[2] == [{"x": 0, "y": 0, "w": 5, "h": 5}]
    assert len(app.global_redactions[1]) == 2 and len(app.global_redactions[2]) == 1


def test_load_metadata_without_original_images_dir(app):
    import shutil
    shutil.rmtree(app.session.dirs["00_raw"])
    app._load_metadata_safely([])
    assert app.image_paths == []


def test_run_selects_phases_per_mode(app, monkeypatch):
    order = []
    for name in ("run_phase_0", "run_phase_1", "run_phase_2", "run_phase_3", "run_phase_4",
                 "run_address_discovery", "run_phase_6", "run_signature_audit", "run_phase_5",
                 "run_native_phase", "run_verification"):
        monkeypatch.setattr(app, name, lambda n=name: order.append(n))
    progress = []
    out = app.run(progress_callback=progress.append)
    assert order == ["run_phase_0", "run_phase_1", "run_phase_2", "run_phase_3", "run_phase_4",
                     "run_address_discovery", "run_phase_6", "run_signature_audit", "run_phase_5",
                     "run_verification"]
    assert out.endswith("doc_TARJADO_FINAL.pdf")
    assert [p["percentage"] for p in progress][-1] == 100 and progress[-1]["status"] == "Concluído"

    order.clear()
    app.run(manual_redactions=[])                      # modo editor legado
    assert order == ["run_phase_5", "run_verification"]
    order.clear()
    app.run(manual_redactions=[], native_mode=True)    # retarjamento nativo
    assert order == ["run_native_phase", "run_verification"]
    order.clear()
    app.run(native_mode=True)                          # native sem redacoes = pipeline completo
    assert order[0] == "run_phase_0"


def test_run_reports_review_state_in_final_progress(app, monkeypatch):
    monkeypatch.setattr(app, "run_phase_0", lambda: app.add_review(1, "motivo"))
    for name in ("run_phase_1", "run_phase_2", "run_phase_3", "run_phase_4", "run_address_discovery",
                 "run_phase_6", "run_signature_audit", "run_phase_5", "run_verification"):
        monkeypatch.setattr(app, name, lambda: None)
    progress = []
    app.run(progress_callback=progress.append)
    assert progress[-1]["status"] == "Requer revisão"


def test_update_progress_without_callback_does_not_fail(app):
    app.update_progress("x", 1)


# --- fase 5 / nativa ---------------------------------------------------------------------------
def test_phase5_exports_variants_metadata_and_final_pdf(app):
    render(app)
    box_cpf = {"x": 5, "y": 5, "w": 20, "h": 10}
    box_addr = {"x": 30, "y": 30, "w": 20, "h": 10}
    app.cpf_redactions[1].append(box_cpf)
    app.address_redactions[2].append(box_addr)
    app.global_redactions[1].append(box_cpf)
    app.global_redactions[2].append(box_addr)
    app.global_redactions[2].append({"x": 1, "y": 1, "w": 2, "h": 2})  # nem cpf nem endereco -> pii
    app.run_phase_5()
    meta = json.load(open(os.path.join(app.session.output_dir, "redactions_metadata.json"), encoding="utf-8"))
    assert [(m["page"], m["type"]) for m in meta] == [(1, "signature"), (2, "pii"), (2, "pii")]
    assert all(m["image_width"] == meta[0]["image_width"] > 0 for m in meta)
    final = os.path.join(app.session.doc_finais_dir, "doc_TARJADO_FINAL.pdf")
    with fitz.open(final) as d:
        assert len(d) == 2
    d = app.session.dirs
    for key in ("05_cpf_only", "05_address_only", "05_combined"):
        assert len(os.listdir(d[key])) == 2


def test_phase5_without_images_fails_closed_instead_of_keeping_stale_pdf(app):
    """Regressao: apos /purge nao ha imagens; nao pode 'concluir' deixando o PDF final antigo."""
    stale = os.path.join(app.session.doc_finais_dir, "doc_TARJADO_FINAL.pdf")
    make_text_pdf(stale)
    app.image_paths = []
    with pytest.raises(RuntimeError, match="Imagens originais ausentes"):
        app.run_phase_5()


def test_phase5_raises_when_pdf_cannot_be_rebuilt(app, monkeypatch):
    render(app)
    monkeypatch.setattr(app.session, "reconstitute_pdf", lambda *a, **k: None)
    with pytest.raises(RuntimeError, match="reconstituir"):
        app.run_phase_5()


def test_phase5_survives_unwritable_metadata(app, monkeypatch):
    render(app)
    real_open = open

    def guarded(path, *a, **k):
        if str(path).endswith("redactions_metadata.json"):
            raise OSError("disco cheio")
        return real_open(path, *a, **k)

    monkeypatch.setattr("builtins.open", guarded)
    app.run_phase_5()  # apenas registra o erro no log


def test_native_phase_success_and_failure(app, monkeypatch):
    app.global_redactions[1].append({"x": 72, "y": 90, "w": 60, "h": 20, "source_width": 595})
    app.run_native_phase()
    assert os.path.exists(os.path.join(app.session.doc_finais_dir, "doc_TARJADO_FINAL.pdf"))
    monkeypatch.setattr(app.session, "apply_native_pdf_redactions", lambda **k: None)
    with pytest.raises(RuntimeError, match="PDF nativo"):
        app.run_native_phase()


# --- verificacao -------------------------------------------------------------------------------
def test_verification_requires_final_pdf(app):
    with pytest.raises(RuntimeError, match="PDF final não encontrado"):
        app.run_verification()


def test_verification_flags_leftover_text_cpf_without_ocr(app, monkeypatch):
    monkeypatch.setenv("VERIFY_OCR", "0")
    leaky = os.path.join(app.session.doc_finais_dir, "doc_TARJADO_FINAL.pdf")
    make_text_pdf(leaky, text=f"CPF {CPF_A_FMT}", n_pages=2)
    app.run_verification()
    assert set(app.review_pages) == {1, 2}
    assert any("CPF(s) ainda detectável" in a for a in app.alerts)
    for path in text_files_under(app.session.output_dir):
        assert not FULL_CPF_RE.search(open(path, encoding="utf-8").read()), path


def test_verification_with_ocr_reports_uncovered_and_failed_pages(app, monkeypatch):
    clean = os.path.join(app.session.doc_finais_dir, "doc_TARJADO_FINAL.pdf")
    make_text_pdf(clean, text="limpo", n_pages=2)
    import utils.verifier as verifier
    monkeypatch.setattr(verifier, "find_uncovered_cpfs",
                        lambda *a, **k: ({1: {CPF_A}}, [2]))
    app.run_verification()
    assert app.review_pages[1] == ["CPF detectado no original sem tarja correspondente"]
    assert app.review_pages[2] == ["verificação de cobertura por OCR falhou"]
    for path in text_files_under(app.session.output_dir):
        assert not FULL_CPF_RE.search(open(path, encoding="utf-8").read()), path


def test_verification_marks_unreadable_scanned_pages(app, monkeypatch):
    monkeypatch.setenv("VERIFY_OCR", "0")
    blank = os.path.join(app.session.doc_finais_dir, "doc_TARJADO_FINAL.pdf")
    d = fitz.open()
    d.new_page()
    d.new_page()
    d.save(blank)
    d.close()
    app.run_verification()
    assert set(app.review_pages) == {1, 2}
    assert "não verificada" in app.review_pages[1][0]

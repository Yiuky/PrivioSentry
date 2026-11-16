# SPDX-License-Identifier: AGPL-3.0-or-later
"""Modelos de documento no pipeline (main.SentryApp): tarja pelo modelo, IA de visão dispensada só com modelo
APROVADO, inspeção depois. Contra testes (I-03): endereço fora dos campos nunca termina em "Concluído"."""
import pytest

from main import SentryApp
from test_doc_templates import CPF_A_FMT, make_pdf, template
from utils import second_look
from utils.doc_templates import schema


@pytest.fixture()
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("PRIVIO_DOC_TEMPLATES_DIR", str(tmp_path / "modelos"))
    monkeypatch.setenv("BASE_DPI", "72")
    pdf = make_pdf(tmp_path / "licenca.pdf")
    a = SentryApp(pdf, output_dir=str(tmp_path / "out"), final_dir=str(tmp_path / "final"))
    a.run_phase_0()
    n = len(a.image_paths)
    a.grounding_maps = [[] for _ in range(n)]
    a.grounding_maps_sparse = [[] for _ in range(n)]
    a.grounding_maps_native = a._native_text_maps(n)
    yield a
    a.session.close()


def save(approved, **over):
    t = schema.save(template(dispensa_ia=True, **over))
    return schema.save(t, approve=True) if approved else t


def redacted_text(a, page=1):
    from utils.doc_templates import engine
    words = a._page_words(page - 1)
    ids = engine.covered_ids(words, a.global_redactions[page])
    return " ".join(words[i]["text"] for i in sorted(ids))


def test_no_template_changes_nothing(app):
    app.run_template_phase()
    assert app.doc_template is None and not app.global_redactions[1] and not app.template_skip_pages


def test_template_redacts_fields_without_ai_and_records_it(app):
    save(approved=False)
    app.run_template_phase()
    text = redacted_text(app)
    assert "Maria" in text and CPF_A_FMT in text and "Travessa" in text
    assert app.doc_template["id"] == "licenca-teste" and app.doc_template["tarjas"] > 0
    assert app.template_skip_pages == set()                          # rascunho nunca dispensa a IA
    assert app.final_state()["modelo_documento"]["id"] == "licenca-teste"


def test_approved_template_skips_vision_ai_on_its_pages(app, monkeypatch):
    save(approved=True)
    app.run_template_phase()
    assert app.template_skip_pages == {1}
    seen = {}
    monkeypatch.setattr(app.address_redactor, "run_discovery", lambda paths, page_texts=None, skip_pages=(): seen.update(skip=set(skip_pages)))
    app.run_address_discovery()
    assert seen["skip"] == {1}


def test_missing_required_field_keeps_the_vision_ai(app):
    save(approved=True, campos=[{"rotulo": "PROPRIETARIO"}, {"rotulo": "CAMPO QUE NAO EXISTE"}])
    app.run_template_phase()
    assert app.template_skip_pages == set() and app.needs_review


def test_rules_only_inspection_never_ends_clean_when_ai_was_skipped(app, monkeypatch):
    """Zero token: o endereço solto no texto ("Reside na Rua...") não está em campo nenhum -> revisão."""
    monkeypatch.setenv("DOC_TEMPLATE_INSPECTION", "regras")
    save(approved=True)
    app.run_template_phase()
    app.run_template_inspection()
    assert app.needs_review and any("sem IA" in a for a in app.alerts)
    assert app.final_state()["status"] == "Requer revisão"


def test_agent_inspection_redacts_what_the_template_missed(app, monkeypatch):
    sent = []

    def fake_agent(text, types, post=None):
        sent.append(text)
        return [("endereço residencial", "Rua das Flores Ficticias, 10"), ("nome", "Maria Silvana Teste")], {}
    monkeypatch.setattr(second_look, "run_agent", fake_agent)
    save(approved=True)
    app.run_template_phase()
    app.run_template_inspection()
    assert "Flores" in redacted_text(app)                            # acrescentou o que ficou de fora
    assert any("Inspeção do modelo (agente) acrescentou" in a for a in app.alerts)
    assert "Maria" not in sent[0] and CPF_A_FMT not in sent[0]        # o agente só vê o texto já tarjado
    assert app.doc_template["inspecao"]["acrescentadas"] >= 1
    assert app.final_state()["status"] == "Requer revisão"


def test_agent_cannot_point_at_text_that_is_already_redacted_or_invented(app, monkeypatch):
    monkeypatch.setattr(second_look, "run_agent",
                        lambda text, types, post=None: ([("cpf", CPF_A_FMT), ("nome", "Pessoa Inventada Silva")], {}))
    save(approved=False)
    app.run_template_phase()
    before = len(app.global_redactions[1])
    app.run_template_inspection()
    assert len(app.global_redactions[1]) == before
    assert app.doc_template["inspecao"]["nao_localizadas"] >= 1      # o CPF já tarjado não é "achado" de novo


def test_agent_failure_sends_the_page_to_review(app, monkeypatch):
    monkeypatch.setattr(second_look, "run_agent", lambda text, types, post=None: (None, {"erro": "fora do ar"}))
    save(approved=True)
    app.run_template_phase()
    app.run_template_inspection()
    assert any("Inspeção do modelo (agente) falhou" in a for a in app.alerts)


def test_label_inspection_flags_a_field_the_template_does_not_cover(app, monkeypatch):
    monkeypatch.setenv("DOC_TEMPLATE_INSPECTION", "regras")
    save(approved=False, campos=[{"rotulo": "PROPRIETARIO"}])          # o modelo esqueceu "Fone"
    app.run_template_phase()
    app.run_template_inspection()
    assert any("'Fone' tem valor sem tarja" in a for a in app.alerts)
    assert any(m["reason"].startswith("Inspeção do modelo") for m in app.review_marks)


def test_similar_templates_apply_neither_and_ask_for_review(app):
    save(approved=True)
    schema.save(template(id="licenca-gemea"))
    app.run_template_phase()
    assert app.doc_template is None and not app.global_redactions[1] and app.needs_review


def test_switched_off(app, monkeypatch):
    monkeypatch.setenv("DOC_TEMPLATES", "0")
    save(approved=True)
    app.run_template_phase()
    assert app.doc_template is None


# ------------------------------------------------------------------ várias páginas (a IA só some onde o modelo achou)
def multi_page_pdf(path):
    """Pág. 1: o formulário. Pág. 2: anexo em texto corrido com um endereço. Pág. 3: só imagem (sem texto)."""
    import fitz
    from test_doc_templates import LINES
    doc = fitz.open()
    p = doc.new_page(width=595, height=842)
    for i, (x, text, size) in enumerate(LINES):
        p.insert_text((x, 70 + 26 * i), text, fontsize=size)
    q = doc.new_page(width=595, height=842)
    q.insert_text((60, 80), "ANEXO I - Memorial descritivo do imovel", fontsize=11)
    q.insert_text((60, 110), "O interessado reside na Rua das Flores Ficticias, 10, Bairro Teste.", fontsize=10)
    r = doc.new_page(width=595, height=842)
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 60, 60), False)
    pix.clear_with(200)
    r.insert_image(fitz.Rect(50, 50, 300, 300), pixmap=pix)
    doc.save(str(path))
    doc.close()
    return str(path)


@pytest.fixture()
def app3(tmp_path, monkeypatch):
    monkeypatch.setenv("PRIVIO_DOC_TEMPLATES_DIR", str(tmp_path / "modelos"))
    monkeypatch.setenv("BASE_DPI", "72")
    a = SentryApp(multi_page_pdf(tmp_path / "tres.pdf"), output_dir=str(tmp_path / "out"),
                  final_dir=str(tmp_path / "final"))
    a.run_phase_0()
    n = len(a.image_paths)
    a.grounding_maps = [[] for _ in range(n)]
    a.grounding_maps_sparse = [[] for _ in range(n)]
    a.grounding_maps_native = a._native_text_maps(n)
    yield a
    a.session.close()


def test_vision_ai_is_skipped_only_on_pages_where_fields_were_found(app3):
    save(approved=True, reconhecimento={"ancoras": [template()["reconhecimento"]["ancoras"][0]], "minimo": 1,
                                        "paginas_min": 1, "paginas_max": 5})
    app3.run_template_phase()
    assert app3.doc_template is not None
    assert app3.template_skip_pages == {1}             # anexo (pág. 2) e página só de imagem (pág. 3) ficam com a IA


def test_thin_native_layer_is_read_by_ocr(app3):
    native = app3.grounding_maps_native[0]
    app3.grounding_maps[0] = native + [dict(native[0]) for _ in range(len(native) * 3)]   # OCR vê bem mais
    app3.grounding_maps_native[0] = native[:3]                                            # camada de texto rala
    assert app3._page_words(0) is app3.grounding_maps[0]
    app3.grounding_maps_native[0] = native
    app3.grounding_maps[0] = []
    assert app3._page_words(0) is native


# ------------------------------------------------------------------ ponta a ponta: run() com modelo aprovado
def test_full_run_with_an_approved_template(tmp_path, monkeypatch):
    """run() inteiro (OCR e IA simulados, I-08): a IA de visão não é chamada na página do modelo, as tarjas e os
    rótulos do modelo chegam ao editor, a inspeção roda e o documento NÃO fica aprovado."""
    import json
    monkeypatch.setenv("PRIVIO_DOC_TEMPLATES_DIR", str(tmp_path / "modelos"))
    monkeypatch.setenv("BASE_DPI", "72")
    monkeypatch.setenv("VERIFY_OCR", "0")
    monkeypatch.setenv("YOLO_MODEL_PATH", str(tmp_path / "sem_modelo.pt"))
    save(approved=True)
    a = SentryApp(make_pdf(tmp_path / "licenca.pdf"), output_dir=str(tmp_path / "out"),
                  final_dir=str(tmp_path / "final"))

    def fake_ocr(img_path):  # "OCR" = o texto digital (sem Tesseract nos testes)
        page = a._extract_page_num(img_path)
        words = a._native_text_maps(len(a.image_paths))[page - 1]
        return "", words, [], False
    monkeypatch.setattr(a, "_ocr_page", fake_ocr)
    vision_calls = []
    a.address_redactor.ai.analyze_image = lambda p, prompt, only=None: (vision_calls.append(p) or {"addresses": []}, b"", {})
    agent_texts = []
    monkeypatch.setattr(second_look, "run_agent",
                        lambda text, types, post=None: (agent_texts.append(text) or [], {}))
    a.run()
    state = a.final_state()
    a.session.close()
    assert vision_calls == []                                   # página reconhecida: sem IA de visão
    assert len(agent_texts) == 1 and "Maria" not in agent_texts[0]
    assert state["modelo_documento"]["id"] == "licenca-teste" and state["modelo_documento"]["paginas_sem_ia"] == 1
    assert "finalizado" not in state                            # tarja por modelo nunca aprova
    meta = json.load(open(tmp_path / "out" / "licenca" / "redactions_metadata.json", encoding="utf-8"))
    labels = {r["label"] for r in meta}
    assert "Nome de pessoa" in labels and "CPF" in labels


def test_required_label_with_value_on_the_next_row_keeps_the_vision_ai(app, monkeypatch):
    """'Endereço:' achado e o valor na linha de baixo (linhas=1): nada achado -> revisão e a IA de visão roda (I-13)."""
    from test_doc_templates import grid
    schema.save(schema.save({"id": "ficha", "dispensa_ia": True,
                             "reconhecimento": {"ancoras": ["FICHA CADASTRAL FICTICIA"]},
                             "campos": [{"rotulo": "Nome"}, {"rotulo": "Endereço", "tipo": "endereco_residencial"}]}),
                approve=True)
    words = grid([(10, "FICHA CADASTRAL FICTICIA"), (60, "Nome: FULANO DE TAL"), (110, "Endereço:"),
                  (140, "Rua das Acácias Fictícias 77")])
    monkeypatch.setattr(app, "_page_words", lambda i: words)
    monkeypatch.setattr(second_look, "run_agent", lambda text, types: ([], {}))
    app.run_template_phase()
    app.run_template_inspection()
    assert app.template_skip_pages == set() and app.needs_review
    assert any("Endereço" in a for a in app.alerts)

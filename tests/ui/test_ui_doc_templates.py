# SPDX-License-Identifier: AGPL-3.0-or-later
"""UI do gerenciador de modelos de documento: rascunho a partir de um documento revisado, teste, salvar, aprovar;
atalho no menu da tarefa; cartão mostra o modelo usado. PDF fictício gerado aqui (I-01)."""
import fitz
import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.ui

TITLE = "SECRETARIA FICTICIA DE TESTES AMBIENTAIS"
LINES = [TITLE, "LICENCA DE EXEMPLO PARA TESTES AUTOMATIZADOS", "Coordenadoria de Modelos e Documentos",
         "PROPRIETARIO: Maria Silvana Teste       CPF/CNPJ: 529.982.247-25", "Fone: (65) 99999-0000"]


def reviewed_task(live_app):
    """Tarefa concluída cujo PDF de entrada é um formulário fictício, com o nome e o CPF tarjados pelo revisor."""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    for i, line in enumerate(LINES):
        page.insert_text((60, 70 + 26 * i), line, fontsize=11)
    words = page.get_text("words")
    reds = [{"page": 1, "type": "pii", "label": "Nome de pessoa", "image_width": 595, "image_height": 842,
             "coords": [w[0], w[1], w[2], w[3]]}
            for w in words if w[4] in ("Maria", "Silvana", "Teste", "529.982.247-25")]
    tid = live_app.seed_task("licenca.pdf", redactions=reds)
    import json
    with open(live_app.manual_path(tid), "w", encoding="utf-8") as fh:   # o revisor salvou no editor
        json.dump(reds, fh)
    doc.save(live_app.mod.tasks[tid]["input_path"])
    doc.close()
    return tid


def test_draft_test_save_and_approve_a_template(page, live_app, dialogs):
    tid = reviewed_task(live_app)
    page.goto(f"{live_app.url}/admin#modelos")
    page.wait_for_selector("#view-modelos.active")
    expect(page.get_by_test_id("tpl-task")).to_have_value(tid)
    page.get_by_test_id("tpl-draft").click()
    editor = page.get_by_test_id("tpl-editor")
    expect(editor).to_be_visible()
    assert TITLE in page.locator("#te-anchors").input_value()
    assert "Maria" not in page.locator("#te-anchors").input_value()
    labels = [x.input_value() for x in page.locator('#te-fields [data-k="rotulo"]').all()]
    assert "PROPRIETARIO" in labels and "CPF/CNPJ" in labels
    page.get_by_test_id("tpl-test").click()
    expect(page.get_by_test_id("tpl-test-result")).to_contain_text("Reconhecido")
    page.get_by_test_id("tpl-save").click()
    body = page.get_by_test_id("tpl-body")
    expect(body).to_contain_text("rascunho")
    page.locator("[data-testid^=tpl-approve-]").click()
    expect(body).to_contain_text("aprovado")
    assert any("Aprovar este modelo" in m for m in dialogs.messages)


def test_task_menu_opens_the_template_manager_with_the_document(page, live_app, open_app):
    tid = reviewed_task(live_app)
    open_app()
    page.locator(f"#t-{tid} .task-menu-btn").click()
    page.locator(f"#m-{tid} [data-action=template]").click()
    page.wait_for_selector("#view-modelos.active")
    expect(page.get_by_test_id("tpl-editor")).to_be_visible()     # rascunho gerado sozinho


def test_card_shows_the_template_used(page, live_app, open_app):
    tid = live_app.seed_task("d.pdf", needs_review=True, status="Requer revisão",
                             extra={"modelo_documento": {"id": "licenca", "nome": "Licença fictícia", "versao": 1}})
    open_app()
    expect(page.locator(f"#t-{tid}").get_by_test_id("task-template")).to_contain_text("Modelo: Licença fictícia")

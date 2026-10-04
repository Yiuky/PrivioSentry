# SPDX-License-Identifier: AGPL-3.0-or-later
"""UI: tipo do dado em cada tarja sugerida e resumo dos tipos encontrados no cartão da tarefa."""
from playwright.sync_api import expect

from ui_support import box


def test_typed_suggestion_shows_its_type(page, live_app, open_task):
    typed = dict(box(1), label="Telefone")
    tid = live_app.seed_task("tipos.pdf", redactions=[typed, box(1, (300, 300, 400, 340))])
    open_task(tid)
    labelled = page.locator(".redaction-box.type-labelled")
    expect(labelled).to_have_count(1)
    expect(labelled).to_have_attribute("data-label", "Telefone")
    expect(labelled).to_have_attribute("title", "Possível Telefone — verifique antes de proteger")
    titles = page.eval_on_selector_all("[data-testid=redaction-box]", "els => els.map(e => e.title)")
    assert "Possível dado pessoal — verifique antes de proteger" in titles


def test_type_label_is_text_not_html(page, live_app, open_task):
    evil = dict(box(1), label="<img src=x onerror=window.__xss=1>")
    tid = live_app.seed_task("xss2.pdf", redactions=[evil])
    open_task(tid)
    assert page.locator("#layer-1 img").count() == 0 and page.evaluate("window.__xss") is None


def test_task_card_summarizes_pii_found(page, live_app, open_app):
    live_app.seed_task("resumo.pdf", extra={"pii_found": [
        {"id": "cpf", "nome": "CPF", "nivel": "identificador direto", "quantidade": 3},
        {"id": "telefone", "nome": "Telefone", "nivel": "dado pessoal", "quantidade": 1}]})
    open_app()
    summary = page.locator("[data-testid=task-pii]")
    expect(summary).to_have_text("🔎 CPF 3 · Telefone 1")
    expect(summary).to_have_attribute("title", "CPF (identificador direto): 3\nTelefone (dado pessoal): 1")

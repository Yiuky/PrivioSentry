# SPDX-License-Identifier: AGPL-3.0-or-later
"""UI: regiões a revisar desenhadas na página e atualização automática do documento aberto."""
import json

from playwright.sync_api import expect

from ui_support import box

MARK = {"page": 2, "reason": "1 CPF(s) ainda detectável(is) no PDF final", "box": [0.5, 0.25, 0.75, 0.3]}


def test_review_mark_is_drawn_where_the_problem_is(page, live_app, open_task):
    tid = live_app.seed_task("marcas.pdf", pages=3, status="Requer revisão", needs_review=True,
                             alerts=["Pág 2: 1 CPF(s) ainda detectável(is) no PDF final"], redactions=[],
                             extra={"review_marks": [MARK]})
    open_task(tid)
    mark = page.locator("#layer-2 [data-testid=review-mark]")
    page.locator("#page-wrapper-2").scroll_into_view_if_needed()
    page.wait_for_function("() => { const i = document.querySelector('#page-wrapper-2 img'); return i && i.naturalWidth > 0; }")
    expect(mark).to_have_count(1)
    expect(mark).to_have_attribute("title", MARK["reason"])
    expect(mark).to_contain_text("Revisar aqui")
    # posição relativa: começa a ~50% da largura e ~25% da altura da página
    pos = page.evaluate("""() => {
        const m = document.querySelector('#layer-2 [data-testid=review-mark]').getBoundingClientRect();
        const p = document.querySelector('#page-wrapper-2 img').getBoundingClientRect();
        return [(m.left - p.left) / p.width, (m.top - p.top) / p.height, m.width / p.width];
    }""")
    assert 0.47 < pos[0] < 0.51 and 0.22 < pos[1] < 0.26 and 0.24 < pos[2] < 0.28
    assert page.locator("#layer-1 [data-testid=review-mark], #layer-3 [data-testid=review-mark]").count() == 0


def test_pending_chip_takes_you_to_the_region_and_highlights_it(page, live_app, open_task):
    tid = live_app.seed_task("ir.pdf", pages=3, status="Requer revisão", needs_review=True,
                             alerts=["Pág 2: 1 CPF(s) ainda detectável(is) no PDF final"], redactions=[],
                             extra={"review_marks": [MARK]})
    open_task(tid)
    page.locator("#page-wrapper-2").scroll_into_view_if_needed()
    page.wait_for_function("() => { const i = document.querySelector('#page-wrapper-2 img'); return i && i.naturalWidth > 0; }")
    page.locator("#page-wrapper-1").scroll_into_view_if_needed()
    page.locator(".pending-chip[data-page='2']").click()
    expect(page.locator("#layer-2 [data-testid=review-mark]")).to_have_class("review-mark flash")
    expect(page.locator("#layer-2 [data-testid=review-mark]")).to_be_in_viewport()


def test_review_mark_reason_is_text_not_html(page, live_app, open_task):
    evil = {"page": 1, "reason": "<img src=x onerror=window.__xss=1>", "box": [0.1, 0.1, 0.2, 0.2]}
    tid = live_app.seed_task("xss.pdf", pages=1, status="Requer revisão", needs_review=True,
                             alerts=["Pág 1: teste"], redactions=[], extra={"review_marks": [evil, {"page": 1, "box": "x"}]})
    open_task(tid)
    expect(page.locator("#layer-1 [data-testid=review-mark]")).to_have_count(1)   # caixa inválida ignorada
    assert page.locator("#layer-1 img").count() == 0 and page.evaluate("window.__xss") is None


def test_open_document_reloads_by_itself_when_processing_finishes(page, live_app, open_task):
    tid = live_app.seed_task("processando.pdf", pages=2, status="OCR: Pagina 1/2", percentage=30, completed=False,
                             redactions=[])
    open_task(tid)
    expect(page.locator(".redaction-box")).to_have_count(0)
    # o "worker" termina: grava as sugestões e marca a tarefa como concluída com uma região a revisar
    meta = live_app.output_dir / live_app.base(tid) / "redactions_metadata.json"
    meta.write_text(json.dumps([box(1), box(2)]), encoding="utf-8")
    live_app.update_task(tid, status="Requer revisão", percentage=100, completed=True, needs_review=True,
                         alerts=["Pág 2: 1 CPF(s) ainda detectável(is) no PDF final"], review_marks=[MARK])
    expect(page.locator("#toast")).to_contain_text("Processamento concluído", timeout=10000)
    expect(page.locator(".redaction-box")).to_have_count(2)
    page.locator("#page-wrapper-2").scroll_into_view_if_needed()
    expect(page.locator("#layer-2 [data-testid=review-mark]")).to_have_count(1)


def test_unsaved_edits_are_never_discarded_when_processing_finishes(page, live_app, open_task):
    tid = live_app.seed_task("editando.pdf", pages=1, status="Processando", percentage=50, completed=False,
                             redactions=[box(1)])
    open_task(tid)
    page.evaluate("() => { redactions.push({page: 1, coords: [10, 10, 60, 40], type: 'pii', source: 'Manual', "
                  "image_width: 700, image_height: 1000}); renderRedactions(); }")
    expect(page.locator(".redaction-box")).to_have_count(2)
    live_app.update_task(tid, status="Concluído", percentage=100, completed=True)
    expect(page.locator("#toast")).to_contain_text("Salve suas edições", timeout=10000)
    expect(page.locator(".redaction-box")).to_have_count(2)   # a edição do revisor continua lá


def test_task_card_shows_processing_time(page, live_app, open_app):
    live_app.seed_task("tempo.pdf", pages=1, extra={"timings": {"OCR Scanning": 61.4, "Renderizando PDF": 4.2}})
    open_app()
    t = page.locator("[data-testid=task-time]")
    expect(t).to_have_text("⏱ 1 min 6 s")
    expect(t).to_have_attribute("title", "OCR Scanning: 61.4 s\nRenderizando PDF: 4.2 s")


# --- regressões da revisão independente -----------------------------------------------------------------
def test_r3_boxes_under_a_review_mark_stay_editable(page, live_app, open_task):
    # região a revisar exatamente sobre uma tarja: clicar na tarja precisa selecioná-la
    mark = {"page": 1, "reason": "CPF ainda detectável", "box": [0.1, 0.08, 0.5, 0.2]}
    tid = live_app.seed_task("sob.pdf", status="Requer revisão", needs_review=True, alerts=["Pág 1: CPF"],
                             redactions=[box(1)], extra={"review_marks": [mark]})
    open_task(tid)
    target = page.locator("#layer-1 [data-testid=redaction-box]")
    target.click()
    expect(target).to_have_class(__import__("re").compile(r"\bselected\b"))


def test_r4_switching_documents_does_not_fake_a_finished_refresh(page, live_app, open_task):
    running = live_app.seed_task("rodando.pdf", status="OCR: Pagina 1/2", percentage=30, completed=False, redactions=[])
    done = live_app.seed_task("pronto.pdf", redactions=[box(1)])
    open_task(running)
    page.locator(f"#t-{done}").click()
    page.wait_for_timeout(4000)                                   # mais que um ciclo de atualização (3 s)
    assert "Processamento concluído" not in (page.locator("#toast").text_content() or "")
    assert "Salve suas edições" not in (page.locator("#toast").text_content() or "")


def test_r10_failed_processing_is_not_reported_as_success(page, live_app, open_task):
    tid = live_app.seed_task("falha.pdf", status="Processando", percentage=40, completed=False, redactions=[])
    open_task(tid)
    live_app.update_task(tid, status="Erro: Tesseract", error=True)
    expect(page.locator("#toast")).to_contain_text("terminou com erro", timeout=10000)
    assert "Processamento concluído" not in (page.locator("#toast").text_content() or "")

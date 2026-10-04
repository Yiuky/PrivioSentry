# SPDX-License-Identifier: AGPL-3.0-or-later
"""UI: estado "Requer revisão" (badge na lista) e lista/filtro de páginas pendentes no editor."""
import pytest
from playwright.sync_api import expect

from ui_support import box

pytestmark = pytest.mark.ui

ALERTS = ["Pág 2: verificação residual detectou possível CPF", "Pág 3: cobertura de tarja baixa", "Pág 2: texto ilegível"]


def review_task(live_app, **kw):
    return live_app.seed_task("revisar.pdf", pages=3, status="Requer revisão", needs_review=True,
                              alerts=ALERTS, redactions=[box(1), box(2)], final_pdf=True, **kw)


def test_needs_review_badge_in_task_list(page, live_app, open_app):
    rev = review_task(live_app)
    ok = live_app.seed_task("limpo.pdf", age_minutes=1000)
    open_app()
    badge = page.locator(f"#t-{rev} [data-testid=badge-review]")
    expect(badge).to_be_visible()
    expect(badge).to_have_text("Requer revisão")
    expect(page.locator(f"#t-{ok} [data-testid=badge-review]")).to_have_count(0)
    # tarefa para revisão continua podendo ser baixada
    expect(page.locator(f"#t-{rev} .btn-download")).to_be_visible()
    # badge some quando a revisão deixa de ser necessária (reprocessamento limpo)
    live_app.update_task(rev, needs_review=False, alerts=[], status="Concluído")
    page.evaluate("fetchTasks()")
    expect(page.locator(f"#t-{rev} [data-testid=badge-review]")).to_have_count(0)


def test_pending_bar_lists_pages_grouped_and_hidden_for_clean_task(page, live_app, open_task):
    rev = review_task(live_app)
    open_task(rev)
    bar = page.locator("#pending-bar")
    expect(bar).to_be_visible()
    chips = bar.locator(".pending-chip")
    expect(chips).to_have_count(2)  # Pág 2 (2 motivos agrupados) e Pág 3
    expect(chips.nth(0)).to_contain_text("Pág 2")
    expect(chips.nth(0)).to_contain_text("verificação residual")
    expect(chips.nth(0)).to_contain_text("texto ilegível")
    expect(chips.nth(1)).to_contain_text("Pág 3")
    # páginas pendentes recebem destaque
    expect(page.locator("#page-wrapper-2")).to_have_class("page-wrapper pending")
    expect(page.locator("#page-wrapper-3")).to_have_class("page-wrapper pending")
    assert "pending" not in page.get_attribute("#page-wrapper-1", "class")


def test_pending_bar_absent_without_review(page, live_app, open_task):
    tid = live_app.seed_task("limpo.pdf", pages=2, redactions=[])
    open_task(tid)
    expect(page.locator("#pending-bar")).to_be_hidden()
    assert page.locator(".page-wrapper.pending").count() == 0


def test_pending_chip_jumps_to_page(page, live_app, open_task):
    rev = review_task(live_app)
    open_task(rev)
    expect(page.locator("#page-info")).to_have_text("1 / 3")
    page.locator("#pending-bar .pending-chip[data-page='3']").click()
    expect(page.locator("#page-info")).to_have_text("3 / 3")
    page.locator("#pending-bar .pending-chip[data-page='2']").click()
    expect(page.locator("#page-info")).to_have_text("2 / 3")


def test_pending_only_filter_hides_clean_pages_and_navigation_skips_them(page, live_app, open_task):
    rev = review_task(live_app)
    open_task(rev)
    page.get_by_label("Só páginas pendentes").check()
    expect(page.locator("#page-wrapper-1")).to_be_hidden()
    expect(page.locator("#page-wrapper-2")).to_be_visible()
    expect(page.locator("#page-wrapper-3")).to_be_visible()
    expect(page.locator("#page-info")).to_have_text("2 / 3")
    page.locator("#btn-next").click()
    expect(page.locator("#page-info")).to_have_text("3 / 3")
    page.get_by_label("Só páginas pendentes").uncheck()
    expect(page.locator("#page-wrapper-1")).to_be_visible()


def test_pending_bar_updates_with_polling_and_general_alerts(page, live_app, open_task):
    rev = review_task(live_app)
    open_task(rev)
    live_app.update_task(rev, alerts=["Pág 1: nova pendência", "Sem texto OCR no documento"])
    page.evaluate("fetchTasks()")
    chips = page.locator("#pending-bar .pending-chip")
    expect(chips).to_have_count(1)
    expect(chips.first).to_contain_text("Pág 1")
    expect(page.locator("#pending-bar .pending-note")).to_have_text("Sem texto OCR no documento")
    expect(page.locator("#page-wrapper-1")).to_have_class("page-wrapper pending")
    assert "pending" not in page.get_attribute("#page-wrapper-2", "class")
    live_app.update_task(rev, needs_review=False, alerts=[])
    page.evaluate("fetchTasks()")
    expect(page.locator("#pending-bar")).to_be_hidden()


def test_review_task_full_edit_flow_still_works(page, live_app, open_task):
    """Tarefa em revisão pode ser editada e salva normalmente."""
    rev = review_task(live_app)
    open_task(rev)
    expect(page.locator(".redaction-box")).to_have_count(2)
    page.locator("#layer-2 .redaction-box").hover()
    page.locator("#layer-2 .box-delete").click()
    with page.expect_request(lambda r: "/update-redactions/" in r.url):
        page.locator("#btn-save").click()
    expect(page.locator("#btn-save")).to_contain_text("Salvo!")
    assert len(live_app.manual_path(rev).read_text(encoding="utf-8")) > 2

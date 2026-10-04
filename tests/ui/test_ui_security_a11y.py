# SPDX-License-Identifier: AGPL-3.0-or-later
"""UI: XSS (texto vindo do servidor nunca vira HTML), acessibilidade básica e erros de console."""
import pytest
from playwright.sync_api import expect

from ui_support import box

pytestmark = pytest.mark.ui

PAYLOAD_IMG = "<img src=x onerror=window.__xss=1>"
PAYLOAD_SCRIPT = "<script>window.__xss=2</script>"
QUOTES = "\"'><svg onload=window.__xss=3>"


def no_injection(page):
    assert page.evaluate("window.__xss") is None, "script do servidor foi executado"
    for sel in ("img[src='x']", "svg[onload]", "#task-list script", "#pending-bar script", "#pending-bar img",
                "#task-list img", "#doc-name img"):
        assert page.locator(sel).count() == 0, f"elemento injetado: {sel}"


def test_xss_in_filename_status_and_alerts_is_escaped(page, live_app, open_app):
    tid = live_app.seed_task(f"{PAYLOAD_IMG}{QUOTES}.pdf", status=f"Concluído {PAYLOAD_SCRIPT}",
                             needs_review=True, alerts=[f"Pág 1: {PAYLOAD_IMG}", f"{PAYLOAD_SCRIPT}", f"Pág 2: {QUOTES}"],
                             pages=2, redactions=[])
    open_app()
    title = page.locator(f"#t-{tid} .task-title")
    expect(title).to_contain_text(PAYLOAD_IMG)          # aparece como TEXTO
    expect(page.locator(f"#t-{tid} .task-status")).to_contain_text(PAYLOAD_SCRIPT)
    no_injection(page)
    # tooltip com alertas contém o texto cru, não HTML interpretado
    assert PAYLOAD_IMG in page.locator(f"#t-{tid} .alert-icon").get_attribute("title")
    # abrir a tarefa: nome no cabeçalho + barra de pendências
    page.locator(f"#t-{tid}").click()
    page.wait_for_selector("#pending-bar .pending-chip")
    expect(page.locator("#doc-name")).to_contain_text(PAYLOAD_IMG)
    expect(page.locator("#pending-bar")).to_contain_text(PAYLOAD_IMG)
    expect(page.locator("#pending-bar .pending-note")).to_contain_text(PAYLOAD_SCRIPT)
    no_injection(page)
    # menus/ações continuam funcionando com nome malicioso (aria-label escapado)
    label = page.locator(f"#t-{tid} .task-menu-btn").get_attribute("aria-label")
    assert label == f"Ações de {PAYLOAD_IMG}{QUOTES}.pdf"
    page.locator(f"#t-{tid} .task-menu-btn").click()
    expect(page.locator(f"#m-{tid}")).to_be_visible()


def test_xss_filename_through_real_upload_route(page, live_app, open_app):
    from ui_support import FAKE_PDF
    open_app()
    page.set_input_files("#file-input", {"name": f"{PAYLOAD_IMG}.pdf", "mimeType": "application/pdf", "buffer": FAKE_PDF})
    expect(page.locator(".task-item")).to_have_count(1)
    no_injection(page)


# ------------------------------------------------------------------ acessibilidade básica
def accessible_name(el):
    return el.evaluate("""e => (e.getAttribute('aria-label') || e.innerText || e.textContent || e.title || '').trim()""")


def test_all_buttons_have_accessible_names(page, live_app, open_task):
    rev = live_app.seed_task("a11y.pdf", pages=2, status="Requer revisão", needs_review=True,
                             alerts=["Pág 2: motivo"], redactions=[box(1)], final_pdf=True)
    open_task(rev)
    problems = []
    for b in page.locator("button").all():
        name = accessible_name(b)
        # nome precisa conter ao menos uma letra/dígito (ícones puros como "×" ou "‹" exigem aria-label)
        label = b.get_attribute("aria-label") or ""
        has_text_chars = any(ch.isalnum() for ch in name)
        if not (label.strip() or has_text_chars):
            problems.append(b.evaluate("e => e.outerHTML.slice(0, 120)"))
    assert problems == [], problems


def test_icon_only_buttons_use_aria_label(page, live_app, open_task):
    tid = live_app.seed_task("a11y.pdf", redactions=[])
    open_task(tid)
    for sel, label in (("#btn-prev", "Página anterior"), ("#btn-next", "Próxima página"),
                       ("#btn-zoom-in", "Aumentar zoom"), ("#btn-zoom-out", "Diminuir zoom"),
                       ("#menu-toggle", "Abrir menu lateral"), ("#readme-close", "Fechar documentação"),
                       ("#logs-close", "Fechar logs")):
        assert page.get_attribute(sel, "aria-label") == label, sel


def test_page_images_have_alt_and_document_language(page, live_app, open_task):
    tid = live_app.seed_task("a11y.pdf", pages=2, redactions=[])
    open_task(tid)
    assert page.get_attribute("html", "lang")
    assert page.title().strip()
    alts = page.eval_on_selector_all(".page-img", "els => els.map(e => e.alt)")
    assert len(alts) == 2 and all(a.strip() for a in alts)


def test_keyboard_can_operate_menu_and_dialogs(page, live_app, open_app):
    tid = live_app.seed_task("teclado.pdf", log="INFO ok")
    open_app()
    page.locator(f"#t-{tid} .task-menu-btn").focus()
    page.keyboard.press("Enter")
    expect(page.locator(f"#m-{tid}")).to_be_visible()
    page.get_by_role("menuitem", name="Ver logs").focus()
    page.keyboard.press("Enter")
    expect(page.locator("#logs-overlay")).to_be_visible()
    assert page.get_attribute("#logs-overlay", "role") == "dialog"


# ------------------------------------------------------------------ console limpo
def test_no_console_errors_across_main_flows(page, live_app, open_task, console_errors, dialogs):
    live_app.finish_worker_later(delay=0.3)
    tid = live_app.seed_task("fluxo.pdf", pages=2, status="Requer revisão", needs_review=True,
                             alerts=["Pág 2: motivo"], redactions=[box(1), box(2)], log="INFO a\nERRO b", final_pdf=True)
    open_task(tid)
    page.locator("#btn-draw").click()
    r = page.locator("#page-wrapper-1 img").bounding_box()
    page.mouse.move(r["x"] + 100, r["y"] + 300)
    page.mouse.down()
    page.mouse.move(r["x"] + 220, r["y"] + 360, steps=5)
    page.mouse.up()
    page.locator("#decision-menu").get_by_role("button", name="PII").click()
    page.locator("#btn-toggle").click()
    page.locator("#btn-toggle").click()
    page.locator("#btn-zoom-in").click()
    page.locator("#btn-save").click()
    expect(page.locator("#btn-save")).to_contain_text("Salvo!")
    page.locator("#btn-reset-ai").click()
    page.locator(f"#t-{tid} .task-menu-btn").click()
    page.locator(f"#m-{tid}").get_by_role("menuitem", name="Ver logs").click()
    expect(page.locator("#logs-content .log-line")).to_have_count(2)
    page.locator("#logs-close").click()
    page.get_by_role("button", name="Documentação").click()
    page.locator("#readme-close").click()
    page.locator(f"#t-{tid} .task-menu-btn").click()
    page.locator(f"#m-{tid}").get_by_role("menuitem", name="Excluir").click()
    expect(page.locator("#empty-state")).to_be_visible()
    assert console_errors == []

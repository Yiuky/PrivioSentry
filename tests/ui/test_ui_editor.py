# SPDX-License-Identifier: AGPL-3.0-or-later
"""UI: editor de tarjas (ferramentas, salvar, resetar, gerar PDF final)."""
import json
import re

import pytest
from playwright.sync_api import expect

from ui_support import PAGE_H, PAGE_W, box

pytestmark = pytest.mark.ui
SELECTED = re.compile(r"selected")


def settle(page):
    """Espera transições/animações CSS (o zoom anima 0.2s) terminarem antes de medir geometria."""
    page.evaluate("Promise.all(document.getAnimations().map(a => a.finished.catch(() => null)))")


def img_rect(page, n=1):
    settle(page)
    r = page.locator(f"#page-wrapper-{n} img").bounding_box()
    assert r, "imagem da página não visível"
    return r


def redactions(page):
    return page.evaluate("JSON.parse(JSON.stringify(redactions))")


def drag(page, x0, y0, x1, y1, steps=6):
    page.mouse.move(x0, y0)
    page.mouse.down()
    page.mouse.move((x0 + x1) / 2, (y0 + y1) / 2, steps=steps)
    page.mouse.move(x1, y1, steps=steps)
    page.mouse.up()


def draw_box(page, dx0=100, dy0=150, dx1=260, dy1=210, n=1):
    """Desenha com a ferramenta 'Nova Tarja' em coordenadas relativas ao canto da imagem."""
    page.locator("#btn-draw").click()
    r = img_rect(page, n)
    drag(page, r["x"] + dx0, r["y"] + dy0, r["x"] + dx1, r["y"] + dy1)
    return r


@pytest.fixture()
def editor(page, live_app, open_task):
    tid = live_app.seed_task("editor.pdf", pages=3, redactions=[box(1), box(2, (50, 50, 200, 120), type_="signature")])
    open_task(tid)
    return tid


# ------------------------------------------------------------------ modos
def test_mode_buttons_toggle_active_and_cursor(page, editor):
    expect(page.locator("#btn-select")).to_have_class(re.compile(r"active"))
    page.locator("#btn-draw").click()
    expect(page.locator("#btn-draw")).to_have_class(re.compile(r"active"))
    expect(page.locator("#btn-select")).not_to_have_class(re.compile(r"active"))
    assert page.eval_on_selector("#document-viewer", "e => e.style.cursor") == "crosshair"
    page.locator("#btn-select").click()
    expect(page.locator("#btn-select")).to_have_class(re.compile(r"active"))
    assert page.eval_on_selector("#document-viewer", "e => e.style.cursor") == "default"


def test_signature_box_styled_differently(page, editor):
    assert page.locator("#layer-1 .redaction-box.type-signature").count() == 0
    assert page.locator("#layer-2 .redaction-box.type-signature").count() == 1


# ------------------------------------------------------------------ selecionar / mover / redimensionar
def test_select_move_and_resize_box(page, editor):
    b = page.locator("#layer-1 .redaction-box")
    settle(page)
    b.click()
    expect(b).to_have_class(SELECTED)
    before = redactions(page)[0]["coords"]
    z = page.evaluate("zoom")

    bb = b.bounding_box()
    cx, cy = bb["x"] + bb["width"] / 2, bb["y"] + bb["height"] / 2
    drag(page, cx, cy, cx + 40, cy + 24)
    after = redactions(page)[0]["coords"]
    assert after[0] == pytest.approx(before[0] + 40 / z, abs=3)
    assert after[1] == pytest.approx(before[1] + 24 / z, abs=3)
    # tamanho preservado ao mover
    assert after[2] - after[0] == pytest.approx(before[2] - before[0], abs=0.5)

    bb = page.locator("#layer-1 .redaction-box").bounding_box()
    handle = page.locator("#layer-1 .resize-handle")
    hb = handle.bounding_box()
    hx, hy = hb["x"] + hb["width"] / 2, hb["y"] + hb["height"] / 2
    drag(page, hx, hy, hx + 30, hy + 30)
    resized = redactions(page)[0]["coords"]
    assert resized[2] - resized[0] > after[2] - after[0] + 10
    assert resized[3] - resized[1] > after[3] - after[1] + 10
    assert resized[0] == pytest.approx(after[0], abs=0.5)


def test_click_outside_deselects(page, editor):
    b = page.locator("#layer-1 .redaction-box")
    b.click()
    expect(b).to_have_class(SELECTED)
    page.locator("#doc-name").click()
    expect(page.locator("#layer-1 .redaction-box")).not_to_have_class(SELECTED)


def test_delete_box_with_x_button(page, editor):
    b = page.locator("#layer-1 .redaction-box")
    b.hover()
    page.locator("#layer-1 .box-delete").click()
    expect(page.locator("#layer-1 .redaction-box")).to_have_count(0)
    assert len(redactions(page)) == 1
    expect(page.locator("#layer-2 .redaction-box")).to_have_count(1)


# ------------------------------------------------------------------ desenhar + menu de decisão
def test_draw_new_box_as_pii(page, editor):
    draw_box(page)
    menu = page.locator("#decision-menu")
    expect(menu).to_be_visible()
    expect(page.locator("#ghost")).to_be_visible()
    menu.get_by_role("button", name="PII").click()
    expect(menu).to_be_hidden()
    expect(page.locator("#ghost")).to_be_hidden()
    expect(page.locator("#layer-1 .redaction-box")).to_have_count(2)
    new = redactions(page)[-1]
    z = page.evaluate("zoom")
    assert new["type"] == "pii" and new["source"] == "Manual" and new["page"] == 1
    assert new["image_width"] == PAGE_W and new["image_height"] == PAGE_H
    assert new["coords"][0] == pytest.approx(100 / z, abs=3)
    assert new["coords"][2] == pytest.approx(260 / z, abs=3)
    assert new["coords"][3] == pytest.approx(210 / z, abs=3)
    assert page.locator("#layer-1 .redaction-box.type-signature").count() == 0


def test_draw_new_box_as_signature(page, editor):
    draw_box(page)
    page.locator("#decision-menu").get_by_role("button", name="Assinatura").click()
    new = redactions(page)[-1]
    assert new["type"] == "signature"
    assert page.locator("#layer-1 .redaction-box.type-signature").count() == 1


def test_draw_cancel_discards_box(page, editor):
    draw_box(page)
    page.locator("#decision-menu").get_by_role("button", name="Cancelar").click()
    expect(page.locator("#decision-menu")).to_be_hidden()
    expect(page.locator("#ghost")).to_be_hidden()
    assert len(redactions(page)) == 2


def test_tiny_drag_does_not_open_menu(page, editor):
    page.locator("#btn-draw").click()
    r = img_rect(page)
    drag(page, r["x"] + 100, r["y"] + 400, r["x"] + 101, r["y"] + 402, steps=1)
    expect(page.locator("#decision-menu")).to_be_hidden()
    assert len(redactions(page)) == 2


def test_draw_on_second_page(page, editor):
    page.locator("#page-wrapper-2").scroll_into_view_if_needed()
    page.wait_for_function("() => document.querySelector('#page-wrapper-2 img').naturalWidth > 0")
    draw_box(page, n=2)
    page.locator("#decision-menu").get_by_role("button", name="PII").click()
    assert redactions(page)[-1]["page"] == 2
    expect(page.locator("#layer-2 .redaction-box")).to_have_count(2)


# ------------------------------------------------------------------ ocultar / zoom / navegação
def test_hide_and_show_redactions(page, editor):
    btn = page.locator("#btn-toggle")
    expect(btn).to_contain_text("Ocultar tarjas")
    btn.click()
    expect(btn).to_contain_text("Mostrar tarjas")
    assert page.eval_on_selector("#layer-1", "e => getComputedStyle(e).opacity") == "0"
    btn.click()
    expect(btn).to_contain_text("Ocultar tarjas")
    assert page.eval_on_selector("#layer-1", "e => getComputedStyle(e).opacity") == "1"


def test_zoom_buttons_and_limits(page, editor):
    z = page.locator("#zoom-text")
    expect(z).to_have_text("80%")
    page.locator("#btn-zoom-in").click()
    expect(z).to_have_text("100%")
    assert "scale(1)" in page.eval_on_selector("#document-viewer", "e => e.style.transform")
    page.locator("#btn-zoom-out").click()
    page.locator("#btn-zoom-out").click()
    expect(z).to_have_text("60%")
    for _ in range(40):
        page.locator("#btn-zoom-out").click()
    expect(z).to_have_text("10%")
    for _ in range(40):
        page.locator("#btn-zoom-in").click()
    expect(z).to_have_text("400%")


def test_zoom_keeps_box_geometry_consistent(page, editor):
    """Mover a tarja continua correto depois de mudar o zoom."""
    page.locator("#btn-zoom-in").click()  # 100%
    settle(page)
    b = page.locator("#layer-1 .redaction-box")
    before = redactions(page)[0]["coords"]
    bb = b.bounding_box()
    cx, cy = bb["x"] + bb["width"] / 2, bb["y"] + bb["height"] / 2
    drag(page, cx, cy, cx + 50, cy)
    assert redactions(page)[0]["coords"][0] == pytest.approx(before[0] + 50, abs=3)


def test_page_navigation_buttons_and_keyboard(page, editor):
    info = page.locator("#page-info")
    expect(info).to_have_text("1 / 3")
    expect(page.locator("#btn-prev")).to_be_disabled()
    page.locator("#btn-next").click()
    expect(info).to_have_text("2 / 3")
    expect(page.locator("#btn-prev")).to_be_enabled()
    page.locator("#btn-next").click()
    expect(info).to_have_text("3 / 3")
    expect(page.locator("#btn-next")).to_be_disabled()
    page.locator("#btn-prev").click()
    expect(info).to_have_text("2 / 3")
    page.keyboard.press("ArrowLeft")
    expect(info).to_have_text("1 / 3")
    page.keyboard.press("ArrowRight")
    expect(info).to_have_text("2 / 3")


# ------------------------------------------------------------------ salvar / resetar
def test_save_posts_redactions_and_persists(page, live_app, editor):
    draw_box(page)
    page.locator("#decision-menu").get_by_role("button", name="PII").click()
    with page.expect_request(lambda r: r.method == "POST" and f"/update-redactions/{editor}" in r.url) as req:
        page.locator("#btn-save").click()
    body = json.loads(req.value.post_data)
    assert len(body) == 3 and body[-1]["source"] == "Manual"
    expect(page.locator("#btn-save")).to_contain_text("Salvo!")
    expect(page.locator("#loader")).to_be_hidden()
    saved = json.loads(live_app.manual_path(editor).read_text(encoding="utf-8"))
    assert saved == body
    # reabrir a página: as tarjas manuais têm prioridade sobre as da IA
    page.reload()
    page.locator(f"#t-{editor}").click()
    expect(page.locator(".redaction-box")).to_have_count(3)


def test_save_failure_is_reported(page, live_app, editor, monkeypatch):
    # a tarefa some do servidor -> 404 no salvar
    with live_app.mod.tasks_lock:
        del live_app.mod.tasks[editor]
    page.locator("#btn-save").click()
    expect(page.locator("#toast")).to_contain_text("Erro ao salvar")
    expect(page.locator("#loader")).to_be_hidden()
    expect(page.locator("#btn-save")).not_to_contain_text("Salvo!")


def test_reset_to_ai_discards_manual_changes(page, live_app, editor, dialogs):
    draw_box(page)
    page.locator("#decision-menu").get_by_role("button", name="PII").click()
    page.locator("#btn-save").click()
    expect(page.locator("#btn-save")).to_contain_text("Salvo!")
    assert live_app.manual_path(editor).exists()
    assert len(redactions(page)) == 3

    with page.expect_request(lambda r: r.method == "POST" and f"/reprocess-metadata/{editor}" in r.url):
        page.locator("#btn-reset-ai").click()
    assert "apagará" in dialogs.messages[-1]
    expect(page.locator(".redaction-box")).to_have_count(2)
    assert not live_app.manual_path(editor).exists()


def test_reset_to_ai_cancelled_keeps_changes(page, live_app, editor, dialogs):
    draw_box(page)
    page.locator("#decision-menu").get_by_role("button", name="PII").click()
    dialogs.accept = False
    page.locator("#btn-reset-ai").click()
    page.wait_for_timeout(200)
    assert len(redactions(page)) == 3


# ------------------------------------------------------------------ gerar PDF final (nativo)
def test_generate_native_pdf_full_flow(page, live_app, editor, dialogs):
    live_app.finish_worker_later(delay=0.5)
    draw_box(page)
    page.locator("#decision-menu").get_by_role("button", name="PII").click()
    reqs = []
    page.on("request", lambda r: reqs.append((r.method, r.url.split("/", 3)[-1])) if r.method == "POST" else None)
    with page.expect_download(timeout=20000) as dl:
        page.locator("#btn-generate").click()
        expect(page.locator("#loader")).to_be_visible()
        expect(page.locator("#loader-text")).not_to_be_empty()
    d = dl.value
    assert d.suggested_filename == "editor_TARJADO.pdf"
    with open(d.path(), "rb") as f:
        assert f.read(5) == b"%PDF-"
    assert "PDF nativo" in dialogs.messages[0]
    posts = [u for m, u in reqs]
    assert posts.index(f"update-redactions/{editor}") < posts.index(f"finalize-native/{editor}")
    # o worker recebeu as tarjas salvas (3) em modo nativo
    tid, manual, native = live_app.worker_calls[-1]
    assert tid == editor and native is True and len(manual) == 3
    expect(page.locator("#loader")).to_be_hidden()
    assert live_app.mod.tasks[editor]["completed"] is True


def test_generate_native_pdf_cancelled(page, live_app, editor, dialogs):
    dialogs.accept = False
    page.locator("#btn-generate").click()
    page.wait_for_timeout(200)
    assert live_app.worker_calls == []
    expect(page.locator("#loader")).to_be_hidden()


def test_generate_native_pdf_worker_error_shown(page, live_app, editor):
    live_app.finish_worker_later(delay=0.3, error="Erro: falha sintetica")
    page.locator("#btn-generate").click()
    expect(page.locator("#toast")).to_contain_text("Erro ao gerar PDF Nativo", timeout=15000)
    expect(page.locator("#toast")).to_contain_text("falha sintetica")
    expect(page.locator("#loader")).to_be_hidden()
    # pode tentar de novo (activePolls liberado)
    assert page.evaluate("activePolls.size") == 0


def test_generate_native_pdf_server_conflict_shown(page, live_app, editor):
    from fastapi import HTTPException

    def hook(*a):
        raise HTTPException(status_code=409, detail="Tarefa já está em execução.")
    live_app.worker_hook = hook
    page.locator("#btn-generate").click()
    expect(page.locator("#toast")).to_contain_text("já está em execução")
    expect(page.locator("#loader")).to_be_hidden()
    assert page.evaluate("activePolls.size") == 0

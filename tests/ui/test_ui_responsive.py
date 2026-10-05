# SPDX-License-Identifier: AGPL-3.0-or-later
"""UI responsiva (relatado com print: botões do editor grudados no topo). Em várias larguras: botões com respiro no
cabeçalho, dentro da tela, sem sobreposição e sem texto cortado; sem rolagem horizontal; o ☰ não cobre o nome do
documento; no celular o zoom não colide com o paginador."""
import pytest
from playwright.sync_api import expect

from ui_support import box

pytestmark = pytest.mark.ui
WIDTHS = [(1911, 958), (1366, 768), (1024, 768), (900, 700), (760, 700), (640, 800), (390, 800)]
LONG_NAME = "CONTRATO DE FINANCIAMENTO HABITACIONAL FICTICIO - EXEMPLO DE NOME MUITO LONGO 000.000.000-00.pdf"


@pytest.fixture()
def opened(page, live_app, open_app):
    def _open(width, height):
        tid = live_app.seed_task(LONG_NAME, redactions=[box(1)])
        page.set_viewport_size({"width": width, "height": height})
        open_app()
        if width <= 1024:
            page.locator("#menu-toggle").click()
        page.locator(f"#t-{tid}").click()
        if width <= 1024:
            page.evaluate("() => document.querySelector('.sidebar').classList.remove('open')")
        expect(page.locator("#toolbar")).to_be_visible()
        page.wait_for_function("() => { const i = document.querySelector('#page-wrapper-1 img'); return i && i.naturalWidth > 0; }")
        return page
    return _open


def rects(page, selector):
    return page.evaluate(f"""() => [...document.querySelectorAll({selector!r})].filter(e => e.getClientRects().length > 0 && getComputedStyle(e).visibility !== 'hidden')
        .map(e => {{ const r = e.getBoundingClientRect(); return {{t: r.top, b: r.bottom, l: r.left, r: r.right,
                    sw: e.scrollWidth, cw: e.clientWidth, txt: e.innerText.trim()}}; }})""")


def overlap(a, b):
    return max(0, min(a["r"], b["r"]) - max(a["l"], b["l"])) * max(0, min(a["b"], b["b"]) - max(a["t"], b["t"]))


@pytest.mark.parametrize("width, height", WIDTHS)
def test_editor_toolbar_layout(opened, width, height):
    page = opened(width, height)
    header = rects(page, ".header")[0]
    buttons = rects(page, "#toolbar .tool-btn")
    assert len(buttons) == 6
    for b in buttons:
        assert b["t"] >= header["t"] + 6, f"botão grudado no topo: {b['txt']} ({width}px)"
        assert b["b"] <= header["b"] - 4, f"botão vazando o cabeçalho: {b['txt']} ({width}px)"
        assert b["l"] >= 0 and b["r"] <= width, f"botão fora da tela: {b['txt']} ({width}px)"
        assert b["sw"] <= b["cw"] + 1, f"texto cortado: {b['txt']} ({width}px)"
        assert b["b"] - b["t"] <= 44, f"texto do botão quebrado em várias linhas: {b['txt']} ({width}px)"
    for i, a in enumerate(buttons):
        for c in buttons[i + 1:]:
            assert overlap(a, c) == 0, f"botões sobrepostos: {a['txt']} / {c['txt']} ({width}px)"
    assert page.evaluate("() => document.documentElement.scrollWidth") <= width + 1, f"rolagem horizontal ({width}px)"


@pytest.mark.parametrize("width, height", [w for w in WIDTHS if w[0] <= 1024])
def test_menu_button_never_covers_the_document_name(opened, width, height):
    page = opened(width, height)
    menu = rects(page, "#menu-toggle")[0]
    name = rects(page, "#doc-name")[0]
    assert overlap(menu, name) == 0, (width, menu, name)


def test_zoom_and_pager_do_not_collide_on_a_phone(opened):
    page = opened(390, 800)
    zoom = rects(page, "#zoom-ui")[0]
    pager = rects(page, ".page-nav")[0]
    assert overlap(zoom, pager) == 0, (zoom, pager)


def test_tags_on_a_phone_only_on_the_selected_box(page, opened, live_app):
    page = opened(390, 800)
    vis = page.evaluate("() => getComputedStyle(document.querySelector('#layer-1 .redaction-box'), '::before').display")
    assert vis == "none"

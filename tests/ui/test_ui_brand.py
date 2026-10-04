# SPDX-License-Identifier: AGPL-3.0-or-later
"""UI: identidade PRIVIO SENTRY, regras de copy, local-first (sem rede externa), contraste e foco."""
import json
import re
from pathlib import Path

import pytest
from playwright.sync_api import expect

from ui_support import box

pytestmark = pytest.mark.ui

TEMPLATES = Path(__file__).resolve().parents[2] / "templates"
FORBIDDEN = re.compile(r"compliant|guaranteed|garantid|100\s*%|no network access|sem acesso à rede|"
                       r"conformidade total|totalmente seguro|zero vazamento", re.I)


def luminance(rgb):
    def ch(v):
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = rgb
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def contrast(fg, bg):
    a, b = sorted((luminance(fg), luminance(bg)), reverse=True)
    return (a + 0.05) / (b + 0.05)


def colors(page, selector):
    """(cor do texto, cor de fundo efetiva) como tuplas RGB; sobe na árvore até achar fundo opaco."""
    return page.eval_on_selector(selector, """el => {
        const parse = s => { const m = s.match(/rgba?\\(([^)]+)\\)/); const p = m[1].split(',').map(x => parseFloat(x));
                             return { r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1 }; };
        const fg = parse(getComputedStyle(el).color);
        let n = el, bg = null;
        while (n) { const c = parse(getComputedStyle(n).backgroundColor); if (c.a > 0.99) { bg = c; break; } n = n.parentElement; }
        if (!bg) bg = { r: 255, g: 255, b: 255 };
        return [[fg.r, fg.g, fg.b], [bg.r, bg.g, bg.b]];
    }""")


# ------------------------------------------------------------------ identidade
def test_title_brand_logo_and_no_legacy_names(page, open_app):
    open_app()
    assert page.title() == "PRIVIO SENTRY — SENTRY Redact"
    expect(page.get_by_test_id("brand-name")).to_have_text("PRIVIO SENTRY")
    expect(page.get_by_test_id("brand-product")).to_have_text("SENTRY Redact")
    logo = page.get_by_test_id("brand-logo")
    expect(logo).to_be_visible()
    box_ = logo.bounding_box()
    assert box_["width"] >= 24 and box_["height"] >= 24          # tamanho mínimo da marca (BRAND §5)
    assert page.get_attribute("[data-testid=brand-logo]", "aria-label") == "PRIVIO SENTRY"
    body = page.content()
    for legacy in ("Antigravity", "Tarjador Inteligente", "Guardião de Dados"):
        assert legacy not in body
    assert page.get_attribute("link[rel=icon]", "href").startswith("data:image/svg+xml")


def test_local_processing_badge_exact_text(page, open_app):
    open_app()
    badge = page.get_by_test_id("local-badge")
    expect(badge).to_be_visible()
    expect(badge).to_have_text("LOCAL PROCESSING")


def test_ai_disclaimer_is_permanent(page, live_app, open_app, open_task):
    open_app()
    note = page.get_by_test_id("ai-disclaimer")
    expect(note).to_be_visible()
    expect(note).to_contain_text("probabilística")
    tid = live_app.seed_task("d.pdf", redactions=[box(1)])
    page.locator(f"#t-{tid}").click()
    page.wait_for_selector("#page-wrapper-1 img")
    expect(note).to_be_visible()                               # continua visível com um documento aberto


def test_empty_state_copy(page, open_app):
    open_app()
    es = page.get_by_test_id("empty-state")
    expect(es).to_contain_text("Nenhum documento ainda")
    expect(es).to_contain_text("Adicione um PDF para iniciar a detecção.")
    expect(es).to_contain_text("Proteja os dados antes que sejam expostos.")
    expect(es).to_contain_text("não assegura conformidade")


def test_completion_copy_only_for_clean_tasks(page, live_app, open_app):
    ok = live_app.seed_task("limpo.pdf", final_pdf=True, age_minutes=1)
    rev = live_app.seed_task("revisar.pdf", status="Requer revisão", needs_review=True, alerts=["Pág 1: x"],
                             final_pdf=True, age_minutes=2)
    open_app()
    done = page.locator(f"#t-{ok} [data-testid=task-complete]")
    expect(done).to_have_text("Proteção concluída · Processado localmente")
    expect(page.locator(f"#t-{rev} [data-testid=task-complete]")).to_have_count(0)
    expect(page.locator(f"#t-{rev} [data-testid=badge-review]")).to_have_text("Requer revisão")


def test_detections_are_labelled_as_suggestions(page, live_app, open_task):
    tid = live_app.seed_task("sug.pdf", redactions=[box(1), box(1, (300, 300, 400, 340), source="YOLO_Vision", type_="signature"),
                                                    box(1, (500, 500, 560, 540), source="Manual")])
    open_task(tid)
    titles = page.eval_on_selector_all("[data-testid=redaction-box]", "els => els.map(e => e.title)")
    assert len(titles) == 3
    assert any("Possível CPF ou endereço — verifique antes de proteger" == x for x in titles)
    assert any("Possível assinatura — verifique antes de proteger" == x for x in titles)
    assert any("manualmente" in x for x in titles)
    # assinatura tem rótulo textual (não depende só de cor)
    label = page.eval_on_selector(".redaction-box.type-signature", "e => e.dataset.label")
    assert "ASSINATURA" in label


# ------------------------------------------------------------------ i18n
def test_default_locale_is_pt_br_and_switch_to_en_us(page, open_app):
    open_app()
    assert page.get_attribute("html", "lang") == "pt-BR"
    page.get_by_test_id("lang-select").select_option("en-US")
    assert page.get_attribute("html", "lang") == "en-US"
    es = page.get_by_test_id("empty-state")
    expect(es).to_contain_text("No documents yet")
    expect(es).to_contain_text("Add a PDF to begin detection.")
    expect(es).to_contain_text("Protect data before it is exposed.")
    expect(page.get_by_test_id("local-badge")).to_have_text("LOCAL PROCESSING")   # marca, não traduzida
    expect(page.get_by_test_id("ai-disclaimer")).to_contain_text("probabilistic")
    expect(page.get_by_role("button", name="Add PDFs")).to_be_visible()
    page.get_by_test_id("lang-select").select_option("pt-BR")
    expect(page.get_by_role("button", name="Adicionar PDFs")).to_be_visible()


def test_language_choice_is_remembered_and_dynamic_text_follows(page, live_app, open_app):
    ok = live_app.seed_task("limpo.pdf", final_pdf=True)
    open_app()
    page.get_by_test_id("lang-select").select_option("en-US")
    expect(page.locator(f"#t-{ok} [data-testid=task-complete]")).to_have_text("Protection complete · Processed locally")
    page.reload()
    page.wait_for_selector("#task-list")
    assert page.get_attribute("html", "lang") == "en-US"
    expect(page.locator(f"#t-{ok} .btn-download")).to_have_text("Download PDF")


# ------------------------------------------------------------------ copy proibida
def test_no_forbidden_claims_in_templates_source():
    for name in ("index.html", "gatekeeper.html"):
        src = (TEMPLATES / name).read_text(encoding="utf-8")
        text = re.sub(r"<style.*?</style>", "", src, flags=re.S)          # CSS tem width:100%
        bad = FORBIDDEN.findall(text)
        assert bad == [], f"{name}: texto proibido {bad}"


def test_no_forbidden_claims_in_rendered_ui(page, live_app, open_app, open_task):
    rev = live_app.seed_task("r.pdf", pages=2, status="Requer revisão", needs_review=True, alerts=["Pág 2: motivo"],
                             redactions=[box(1)], final_pdf=True, age_minutes=1)
    live_app.seed_task("ok.pdf", final_pdf=True, age_minutes=2)
    open_app()
    texts = []

    def snapshot():
        texts.append(page.evaluate("document.body.innerText"))
        texts.append(page.evaluate("""Array.from(document.querySelectorAll('[title],[aria-label],[alt]'))
            .map(e => [e.title, e.getAttribute('aria-label'), e.getAttribute('alt')].join(' ')).join(' ')"""))

    snapshot()                                                      # estado vazio + lista
    for lang in ("pt-BR", "en-US"):
        page.get_by_test_id("lang-select").select_option(lang)
        page.locator(f"#t-{rev}").click()
        page.wait_for_selector("#page-wrapper-1 img")
        snapshot()                                                  # editor aberto
        texts.append(page.evaluate("JSON.stringify(I18N)"))        # todo o dicionário de textos
    blob = "\n".join(texts)
    assert FORBIDDEN.findall(blob) == [], FORBIDDEN.findall(blob)
    assert "LOCAL PROCESSING" in blob


# ------------------------------------------------------------------ local-first
def test_template_sources_have_no_external_resources():
    for name in ("index.html", "gatekeeper.html"):
        src = (TEMPLATES / name).read_text(encoding="utf-8")
        assert not re.search(r"""(src|href)\s*=\s*["']\s*(https?:)?//""", src, re.I), f"{name}: recurso externo"
        assert not re.search(r"@import|url\(\s*[\"']?(https?:)?//", src, re.I), f"{name}: CSS externo"
        assert "googleapis" not in src and "unpkg" not in src and "jsdelivr" not in src and "cdnjs" not in src


def test_no_external_requests_during_load_and_use(page, live_app, open_task, dialogs):
    """A fixture `page` aborta qualquer host não-local; aqui exercitamos carga + uso e conferimos o registro."""
    live_app.finish_worker_later(delay=0.3)
    tid = live_app.seed_task("local.pdf", pages=2, status="Requer revisão", needs_review=True,
                             alerts=["Pág 2: m"], redactions=[box(1)], log="INFO ok", final_pdf=True)
    open_task(tid)
    page.get_by_role("button", name="Documentação").click()
    expect(page.locator("#readme-content")).to_contain_text("Texto de ajuda")
    page.locator("#readme-close").click()
    page.locator(f"#t-{tid} .task-menu-btn").click()
    page.locator(f"#m-{tid}").get_by_role("menuitem", name="Ver logs").click()
    expect(page.locator("#logs-content .log-line")).to_have_count(1)
    page.locator("#logs-close").click()
    page.get_by_test_id("lang-select").select_option("en-US")
    page.locator("#btn-save").click()
    expect(page.locator("#btn-save")).to_contain_text("Saved!")
    page.wait_for_timeout(300)
    assert page.external_requests == []


def test_gatekeeper_page_is_local_and_branded(page):
    html = (TEMPLATES / "gatekeeper.html").read_text(encoding="utf-8")
    base = "http://127.0.0.1:9"

    def serve(route):
        url = route.request.url
        if url.endswith("/api/status"):
            return route.fulfill(status=200, content_type="application/json", body=json.dumps({"app_running": True}))
        return route.fulfill(status=200, content_type="text/html", body=html)

    page.route(f"{base}/**", serve)
    page.goto(f"{base}/gatekeeper")
    assert page.title() == "PRIVIO SENTRY — Gatekeeper"
    expect(page.get_by_test_id("brand-logo")).to_be_visible()
    expect(page.get_by_test_id("local-badge")).to_have_text("LOCAL PROCESSING")
    expect(page.locator("#app-status")).to_have_text("Online")
    expect(page.locator("#app-access")).to_be_visible()
    body = page.evaluate("document.body.innerText")
    assert FORBIDDEN.findall(body) == []
    assert page.external_requests == []


# ------------------------------------------------------------------ contraste e foco
def test_primary_buttons_meet_contrast_aa(page, live_app, open_task):
    tid = live_app.seed_task("c.pdf", status="Requer revisão", needs_review=True, alerts=["Pág 1: x"],
                             redactions=[box(1)], final_pdf=True)
    open_task(tid)
    selectors = ["button[data-i18n='btn.add']", "#btn-generate", "#btn-reset-ai", f"#t-{tid} .btn-download",
                 "button[data-i18n='btn.processAll']", "#btn-save", ".badge-review", ".local-badge",
                 "#doc-name", ".ai-notice", ".task-status", ".pending-bar strong"]
    for sel in selectors:
        fg, bg = colors(page, sel)
        ratio = contrast(fg, bg)
        assert ratio >= 4.5, f"{sel}: contraste {ratio:.2f} < 4.5 (fg={fg}, bg={bg})"


def test_empty_state_and_sidebar_text_contrast(page, open_app):
    open_app()
    for sel in (".empty-sub", ".empty-tagline", ".legal-note", ".step-card p", ".brand-descriptor", ".brand-name"):
        fg, bg = colors(page, sel)
        assert contrast(fg, bg) >= 4.5, sel


def test_keyboard_focus_is_visible(page, live_app, open_app):
    live_app.seed_task("foco.pdf")
    open_app()
    seen = 0
    for _ in range(8):
        page.keyboard.press("Tab")
        outline = page.evaluate("""() => { const e = document.activeElement; const s = getComputedStyle(e);
            return { tag: e.tagName, style: s.outlineStyle, width: parseFloat(s.outlineWidth) }; }""")
        if outline["tag"] in ("BODY", "HTML"):
            continue
        assert outline["style"] != "none" and outline["width"] >= 2, outline
        seen += 1
    assert seen >= 5


def test_task_card_is_keyboard_operable(page, live_app, open_app):
    tid = live_app.seed_task("tecla.pdf", pages=2, redactions=[])
    open_app()
    page.locator(f"#t-{tid}").focus()
    page.keyboard.press("Enter")
    page.wait_for_selector("#page-wrapper-1 img")
    expect(page.locator("#doc-name")).to_have_text("tecla.pdf")


# ------------------------------------------------------------------ atalhos e README local
def test_next_previous_page_shortcuts_and_escape(page, live_app, open_task):
    tid = live_app.seed_task("atalhos.pdf", pages=3, redactions=[])
    open_task(tid)
    expect(page.locator("#page-info")).to_have_text("1 / 3")
    page.keyboard.press("n")
    expect(page.locator("#page-info")).to_have_text("2 / 3")
    page.keyboard.press("p")
    expect(page.locator("#page-info")).to_have_text("1 / 3")
    page.get_by_role("button", name="Documentação").click()
    expect(page.locator("#readme-overlay")).to_be_visible()
    page.keyboard.press("Escape")
    expect(page.locator("#readme-overlay")).to_be_hidden()


def test_readme_renderer_is_local_and_escapes_html(page, live_app, open_app):
    (live_app.tmp / "README.md").write_text(
        "# Titulo\n\n<img src=x onerror=window.__xss=1>\n\n- item **forte** e `codigo`\n\n"
        "```\n<script>window.__xss=2</script>\n```\n\n[ok](https://example.org) [ruim](javascript:window.__xss=3)\n",
        encoding="utf-8")
    open_app()
    page.get_by_role("button", name="Documentação").click()
    rc = page.locator("#readme-content")
    expect(rc.locator("h1")).to_have_text("Titulo")
    expect(rc.locator("li strong")).to_have_text("forte")
    expect(rc.locator("li code")).to_have_text("codigo")
    expect(rc).to_contain_text("<img src=x onerror=window.__xss=1>")      # texto, não HTML
    assert rc.locator("img").count() == 0 and rc.locator("script").count() == 0
    hrefs = rc.locator("a").evaluate_all("els => els.map(a => a.href)")
    assert hrefs == ["https://example.org/"]                              # javascript: nunca vira link
    assert page.evaluate("window.__xss") is None

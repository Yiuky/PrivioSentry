# SPDX-License-Identifier: AGPL-3.0-or-later
"""UI da Administração: abre pelo editor, salva sem recarregar, chave nunca aparece, IA externa exige confirmação
e o selo/cartões deixam de dizer "local" quando há IA externa (I-04, I-05)."""
import os

import pytest
from playwright.sync_api import expect

pytestmark = pytest.mark.ui


def open_admin(page, live_app, view="visao"):
    page.goto(f"{live_app.url}/admin#{view}")
    page.wait_for_selector(f"#view-{view}.active")
    page.wait_for_selector("[data-group=ia] .fields", state="attached")
    return page


def test_editor_links_to_admin_and_back(page, live_app, open_app):
    open_app()
    page.get_by_test_id("btn-admin").click()
    expect(page).to_have_title("PRIVIO SENTRY — Administração")
    page.wait_for_selector("#stats .stat")
    expect(page.get_by_test_id("local-badge")).to_have_text("LOCAL PROCESSING")
    expect(page.get_by_test_id("egress-banner")).to_contain_text("IA local")
    page.get_by_test_id("back-to-editor").click()
    page.wait_for_selector("#task-list")


def test_save_a_setting_and_restore_default(page, live_app, dialogs):
    open_admin(page, live_app, "ocr")
    page.fill("#f-BASE_DPI", "250")
    page.get_by_test_id("save-ocr").click()
    expect(page.locator("#toast")).to_contain_text("salva")
    assert os.environ["BASE_DPI"] == "250"
    page.locator("#f-BASE_DPI").locator("xpath=..").get_by_role("button", name="restaurar padrão").click()
    expect(page.locator("#f-BASE_DPI")).to_have_value("")
    assert "BASE_DPI" not in os.environ


def test_api_key_is_never_shown_back(page, live_app, dialogs):
    open_admin(page, live_app, "ia")
    page.fill("#f-AI_API_KEY", "sk-teste-nao-mostrar")
    page.get_by_test_id("save-ia").click()
    expect(page.locator("#toast")).to_contain_text("salva")
    expect(page.locator("#f-AI_API_KEY")).to_have_value("")
    assert "sk-teste-nao-mostrar" not in page.content()
    page.reload()
    page.wait_for_selector("[data-group=ia] .fields", state="attached")
    assert "sk-teste-nao-mostrar" not in page.content()
    expect(page.get_by_test_id("group-ia")).to_contain_text("Definida")


def test_external_ai_needs_explicit_confirmation(page, live_app, dialogs, monkeypatch):
    from utils import egress
    monkeypatch.setattr(egress, "is_external", lambda url: "openai.com" in url)   # sem DNS de verdade (I-08)
    open_admin(page, live_app, "ia")
    page.get_by_role("button", name="OpenAI").click()
    expect(page.locator("#f-AI_BASE_URL")).to_have_value("https://api.openai.com/v1")
    page.check("#f-AI_ALLOW_EXTERNAL")
    dialogs.accept = False                                   # o administrador desiste
    page.get_by_test_id("save-ia").click()
    assert any("api.openai.com" in m for m in dialogs.messages)
    assert os.environ.get("AI_ALLOW_EXTERNAL") != "1"
    dialogs.accept = True
    page.get_by_test_id("save-ia").click()
    expect(page.get_by_test_id("local-badge")).to_have_text("EXTERNAL AI")
    expect(page.get_by_test_id("egress-banner")).to_contain_text("api.openai.com")
    assert os.environ["AI_ALLOW_EXTERNAL"] == "1"


def test_editor_badge_and_cards_stop_saying_local(page, live_app, open_app, monkeypatch):
    from utils import egress
    monkeypatch.setattr(egress, "is_external", lambda url: "nuvem" in url)
    monkeypatch.setenv("AI_PROVIDER", "openai")
    monkeypatch.setenv("AI_BASE_URL", "https://api.nuvem.example/v1")
    monkeypatch.setenv("AI_ALLOW_EXTERNAL", "1")
    tid = live_app.seed_task("d.pdf", status="Concluído")
    live_app.update_task(tid, ia_externa=["api.nuvem.example"])
    open_app()
    badge = page.get_by_test_id("local-badge")
    expect(badge).to_have_text("EXTERNAL AI")
    expect(badge).to_have_attribute("title", "Imagens e texto das páginas vão para: api.nuvem.example")
    card = page.locator(f"#t-{tid}")
    expect(card.get_by_test_id("task-complete")).to_have_text("Proteção concluída · com IA externa")
    expect(card.get_by_test_id("task-external")).to_contain_text("api.nuvem.example")
    assert "Processado localmente" not in card.inner_text()


def test_pending_card_says_when_it_will_retry_and_offers_no_pdf(page, live_app, open_app):
    tid = live_app.seed_task("p.pdf", status="Pendente: limite de uso da IA", percentage=0, completed=False)
    live_app.update_task(tid, pendente=True, pendente_ate=4102444800)  # horário fixo: sem depender do relógio
    other = live_app.seed_task("ok.pdf", status="Concluído")
    open_app()
    card = page.locator(f"#t-{tid}")
    expect(card.get_by_test_id("task-pending")).to_contain_text("Pendente: limite de uso da IA. Nova tentativa às")
    expect(card.locator(".btn-download")).to_have_count(0)
    expect(card.get_by_test_id("task-complete")).to_have_count(0)
    expect(page.locator(f"#t-{other}").get_by_test_id("task-pending")).to_have_count(0)  # contra-teste


def test_api_view_shows_mcp_config(page, live_app):
    open_admin(page, live_app, "api")
    expect(page.locator("#mcp-ex")).to_contain_text("sentry_mcp.py")
    expect(page.locator("#mcp-ex")).to_contain_text(live_app.url)
    expect(page.locator("#curl-ex")).to_contain_text("final=true")


def test_deep_link_opens_the_document(page, live_app, open_app):
    tid = live_app.seed_task("link.pdf")
    page.goto(f"{live_app.url}/?task={tid}")
    page.wait_for_selector("#page-wrapper-1 img")
    expect(page.locator("#doc-name")).to_contain_text("link.pdf")

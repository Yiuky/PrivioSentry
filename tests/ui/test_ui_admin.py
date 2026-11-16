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
    page.get_by_test_id("adv-ocr").locator("summary").click()          # DPI fica nas opções avançadas
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


# ------------------------------------------------------------------ administração mais natural
def test_switches_show_the_value_in_use_and_saving_writes_only_what_changed(page, live_app, dialogs, monkeypatch):
    for key in ("VERIFY_OCR", "DOC_TEMPLATES", "BASE_DPI"):
        monkeypatch.delenv(key, raising=False)
    open_admin(page, live_app, "ocr")
    expect(page.locator("#f-VERIFY_OCR")).to_be_checked()                 # ligado por padrão: aparece ligado
    page.get_by_test_id("adv-ocr").locator("summary").click()
    page.fill("#f-BASE_DPI", "250")
    page.get_by_test_id("save-ocr").click()
    expect(page.locator("#toast")).to_contain_text("salva")
    import json
    with open(os.environ["PRIVIO_SETTINGS_FILE"], encoding="utf-8") as fh:
        assert json.load(fh)["values"] == {"BASE_DPI": "250"}            # o interruptor não mexido não foi gravado
    assert "VERIFY_OCR" not in os.environ
    page.goto(f"{live_app.url}/admin#deteccao")
    page.wait_for_selector("#view-deteccao.active")
    expect(page.locator("#f-DOC_TEMPLATES")).to_be_checked()


def test_switch_that_is_off_in_env_shows_off(page, live_app, monkeypatch):
    monkeypatch.setenv("VERIFY_OCR", "0")
    open_admin(page, live_app, "ocr")
    expect(page.locator("#f-VERIFY_OCR")).not_to_be_checked()             # contra-teste
    expect(page.get_by_test_id("group-ocr")).to_contain_text("do .env")


def test_unsaved_changes_are_flagged_and_can_be_discarded(page, live_app):
    open_admin(page, live_app, "operacao")
    save, flag = page.get_by_test_id("save-operacao"), page.get_by_test_id("unsaved-operacao")
    expect(save).to_be_disabled()
    expect(flag).to_be_hidden()
    page.fill("#f-MAX_UPLOAD_MB", "123")
    expect(save).to_be_enabled()
    expect(flag).to_be_visible()
    leaving = page.evaluate("() => { const e = new Event('beforeunload', { cancelable: true }); "
                            "window.dispatchEvent(e); return e.defaultPrevented; }")
    assert leaving                                                        # sair da página pede confirmação
    page.get_by_role("button", name="Descartar").click()
    expect(page.locator("#f-MAX_UPLOAD_MB")).to_have_value("")
    expect(save).to_be_disabled()
    assert not page.evaluate("() => { const e = new Event('beforeunload', { cancelable: true }); "
                             "window.dispatchEvent(e); return e.defaultPrevented; }")


def test_restoring_one_item_keeps_other_edits_unsaved(page, live_app, dialogs):
    from utils import settings
    settings.save({"MAX_UPLOAD_MB": "200"})
    open_admin(page, live_app, "operacao")
    page.fill("#f-MAX_PARALLEL_TASKS", "3")
    page.locator("#f-MAX_UPLOAD_MB").locator("xpath=..").get_by_role("button", name="restaurar padrão").click()
    expect(page.locator("#f-MAX_UPLOAD_MB")).to_have_value("")
    expect(page.locator("#f-MAX_PARALLEL_TASKS")).to_have_value("3")     # continua na tela...
    assert "MAX_PARALLEL_TASKS" not in settings.load()["values"]           # ...e não foi salvo junto


def test_choices_use_readable_names(page, live_app):
    open_admin(page, live_app, "deteccao")
    options = page.locator("#f-POLICY_PROFILE option").all_inner_texts()
    assert "LGPD: publicação (transparência / LAI)" in options and "lgpd_publicacao" not in options
    assert page.locator("#f-NER_ENGINE option").all_inner_texts()[:1] == ["Desligado"]


def test_advanced_options_open_by_themselves_when_changed(page, live_app, monkeypatch):
    for key in ("BASE_DPI", "VERIFY_DPI", "TESSERACT_LANG"):
        monkeypatch.delenv(key, raising=False)
    open_admin(page, live_app, "ocr")
    assert page.get_by_test_id("adv-ocr").get_attribute("open") is None   # padrão: recolhido
    monkeypatch.setenv("BASE_DPI", "200")
    page.reload()
    page.wait_for_selector("[data-group=ocr] .fields", state="attached")
    assert page.get_by_test_id("adv-ocr").get_attribute("open") is not None   # mudado: não fica escondido


def test_overview_lists_what_needs_attention_and_the_queue(page, live_app, monkeypatch):
    from utils import admin_status
    monkeypatch.setattr(admin_status, "tesseract", lambda: {"encontrado": False, "versao": None, "do_path": True})
    monkeypatch.setattr(admin_status, "yolo", lambda: {"pacote": True, "modelo": True})
    live_app.seed_task("r.pdf", status="Requer revisão", needs_review=True)
    live_app.seed_task("ok.pdf", status="Concluído", extra={"finalizado": True})
    open_admin(page, live_app, "visao")
    expect(page.get_by_test_id("hero")).to_contain_text("pede(m) atenção")
    ocr = page.get_by_test_id("check-ocr")
    expect(ocr).to_contain_text("Não encontrado")
    ocr.get_by_role("link", name="Ajustar").click()
    page.wait_for_selector("#view-ocr.active")
    page.goto(f"{live_app.url}/admin#visao")
    expect(page.get_by_test_id("q-requer_revisao")).to_contain_text("1")
    expect(page.get_by_test_id("q-aprovado")).to_contain_text("1")
    assert "r.pdf" not in page.get_by_test_id("queue").inner_text()       # só contagens


def test_overview_says_all_set_when_nothing_is_missing(page, live_app, monkeypatch):
    from utils import admin_status
    monkeypatch.setattr(admin_status, "tesseract", lambda: {"encontrado": True, "versao": "5.3.0", "do_path": True})
    monkeypatch.setattr(admin_status, "yolo", lambda: {"pacote": True, "modelo": True})
    monkeypatch.delenv("VERIFY_OCR", raising=False)
    open_admin(page, live_app, "visao")
    expect(page.get_by_test_id("hero")).to_contain_text("Tudo pronto")    # contra-teste
    expect(page.get_by_test_id("check-ocr")).to_contain_text("versão 5.3.0")


def test_cloud_preset_explains_the_next_steps(page, live_app):
    open_admin(page, live_app, "ia")
    page.get_by_role("button", name="Google Gemini").click()
    expect(page.locator("#preset-hint")).to_contain_text("Permitir IA fora desta rede")
    expect(page.get_by_test_id("save-ia")).to_be_enabled()

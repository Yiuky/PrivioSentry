# SPDX-License-Identifier: AGPL-3.0-or-later
"""UI: opções por documento (perfil, nomes, baixa qualidade). Testes e contratestes: o que não está disponível
fica desativado com o motivo, escolha impossível forçada pelo navegador é recusada pelo servidor, conteúdo do
servidor nunca vira HTML, falha ao carregar as opções não impede o envio."""
import pytest
from playwright.sync_api import expect

from ui_support import FAKE_PDF

pytestmark = pytest.mark.ui
PDF = {"name": "doc.pdf", "mimeType": "application/pdf", "buffer": FAKE_PDF}


@pytest.fixture()
def installed(monkeypatch):
    from utils import task_options
    for name in ("POLICY_PROFILE", "NER_ENGINE", "SECOND_LOOK", "OCR_EXTRA_ENGINE"):  # padrões previsíveis
        monkeypatch.delenv(name, raising=False)
    state = {"gliner": True, "rapidocr": True}
    monkeypatch.setattr(task_options, "_installed", lambda pkg: state.get(pkg, False))
    return state


def wait_options(page):
    page.wait_for_function("() => document.querySelectorAll('#opt-profile option').length > 0")


def only_task(live_app):
    assert len(live_app.mod.tasks) == 1
    return next(iter(live_app.mod.tasks.items()))


# ------------------------------------------------------------------ testes
def test_panel_lists_profiles_with_server_defaults(page, open_app, installed):
    open_app()
    wait_options(page)
    expect(page.locator("#opt-profile option")).to_have_count(5)
    expect(page.get_by_label("Perfil de proteção")).to_have_value("cpf_endereco")
    # perfil padrão não procura nomes: opção desativada com o motivo à vista
    expect(page.get_by_test_id("opt-names")).to_be_disabled()
    expect(page.get_by_test_id("opt-names-hint")).to_have_text("Este perfil não procura nomes.")
    page.get_by_test_id("opt-profile").select_option("lgpd_publicacao")
    expect(page.get_by_test_id("opt-names")).to_be_enabled()
    expect(page.get_by_test_id("opt-names-hint")).to_be_hidden()


def test_upload_sends_the_chosen_options_and_the_card_shows_them(page, live_app, open_app, installed):
    open_app()
    wait_options(page)
    page.get_by_test_id("opt-profile").select_option("lgpd_publicacao")
    page.get_by_test_id("opt-names").check()
    page.get_by_test_id("opt-lowq").check()
    page.set_input_files("#file-input", PDF)
    expect(page.get_by_test_id("task-opts")).to_be_visible()
    tid, task = only_task(live_app)
    assert task["options"] == {"perfil": "lgpd_publicacao", "nomes": True, "baixa_qualidade": True,
                               "segundo_olhar": True, "leitura_extra": True}
    assert live_app.worker_calls and live_app.worker_calls[0][0] == tid
    chips = page.locator("[data-testid=task-opts] .opt-chip").all_inner_texts()
    assert chips == ["LGPD: publicação (transparência / LAI)", "Nomes", "Baixa qualidade"]


def test_low_quality_without_extra_ocr_explains_and_uses_second_look_only(page, live_app, open_app, installed):
    installed["rapidocr"] = False
    open_app()
    wait_options(page)
    expect(page.get_by_test_id("opt-lowq-hint")).to_be_hidden()
    page.get_by_test_id("opt-lowq").check()
    expect(page.get_by_test_id("opt-lowq-hint")).to_contain_text("só o segundo olhar")
    page.set_input_files("#file-input", PDF)
    expect(page.locator(".task-item")).to_have_count(1)
    _, task = only_task(live_app)
    assert task["options"]["segundo_olhar"] is True and task["options"]["leitura_extra"] is False


def test_labels_follow_the_language(page, open_app, installed):
    open_app()
    wait_options(page)
    page.get_by_test_id("lang-select").select_option("en-US")
    expect(page.get_by_text("Options for the next upload")).to_be_visible()
    expect(page.get_by_label("Protection profile")).to_be_visible()
    expect(page.get_by_test_id("opt-names-hint")).to_have_text("This profile does not look for names.")


# ------------------------------------------------------------------ contratestes
def test_names_unavailable_stays_disabled_on_every_profile(page, open_app, installed):
    installed["gliner"] = False
    open_app()
    wait_options(page)
    for pid in ("lgpd_publicacao", "gdpr", "saude_hipaa"):
        page.get_by_test_id("opt-profile").select_option(pid)
        expect(page.get_by_test_id("opt-names")).to_be_disabled()
        expect(page.get_by_test_id("opt-names-hint")).to_have_text("Detector de nomes não instalado neste servidor.")


def test_forcing_a_disabled_option_is_rejected_by_the_server(page, live_app, open_app, installed):
    installed["gliner"] = False
    open_app()
    wait_options(page)
    page.get_by_test_id("opt-profile").select_option("lgpd_publicacao")
    # alguém contorna a interface (DevTools): o servidor precisa recusar
    page.evaluate("() => { const c = document.getElementById('opt-names'); c.disabled = false; c.checked = true; }")
    page.set_input_files("#file-input", PDF)
    expect(page.locator("#toast")).to_contain_text("detector de nomes")
    assert live_app.mod.tasks == {} and live_app.worker_calls == []


def test_switching_to_a_profile_without_names_unchecks_names(page, live_app, open_app, installed):
    open_app()
    wait_options(page)
    page.get_by_test_id("opt-profile").select_option("gdpr")
    page.get_by_test_id("opt-names").check()
    page.get_by_test_id("opt-profile").select_option("cpf_endereco")
    expect(page.get_by_test_id("opt-names")).not_to_be_checked()
    page.set_input_files("#file-input", PDF)
    expect(page.locator(".task-item")).to_have_count(1)
    _, task = only_task(live_app)
    assert task["options"]["nomes"] is False and task["options"]["perfil"] == "cpf_endereco"


def test_upload_still_works_if_options_fail_to_load(page, live_app, open_app, installed):
    page.route("**/options", lambda route: route.fulfill(status=500, body='{"detail": "falhou"}',
                                                          content_type="application/json"))
    open_app()
    expect(page.locator("#toast")).to_contain_text("Não foi possível carregar as opções de envio")
    page.set_input_files("#file-input", PDF)
    expect(page.locator(".task-item")).to_have_count(1)
    _, task = only_task(live_app)
    assert task["options"]["perfil"] == "cpf_endereco"          # padrões do servidor (nenhum campo enviado)


def test_server_text_is_never_rendered_as_html(page, live_app, open_app, installed, dialogs, monkeypatch):
    from utils.detect import profiles
    evil = "<img src=x onerror=alert('xss')>"
    monkeypatch.setitem(profiles.PROFILES["gdpr"], "nome", evil)
    open_app()
    wait_options(page)
    assert page.locator("#opt-profile option[value=gdpr]").inner_text() == evil
    page.get_by_test_id("opt-profile").select_option("gdpr")
    page.set_input_files("#file-input", PDF)
    expect(page.get_by_test_id("task-opts")).to_be_visible()
    assert page.locator("[data-testid=task-opts] .opt-chip").first.inner_text() == evil
    assert page.locator("#upload-options img, .task-opts img").count() == 0 and dialogs.messages == []


def test_old_tasks_without_options_show_no_chips(page, live_app, open_app, installed):
    live_app.seed_task(name="antiga.pdf")
    open_app()
    expect(page.locator(".task-title")).to_have_text("antiga.pdf")
    expect(page.get_by_test_id("task-opts")).to_have_count(0)

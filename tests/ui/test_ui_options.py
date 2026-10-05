# SPDX-License-Identifier: AGPL-3.0-or-later
"""UI: opções por documento em botões (perfil em pílulas, "Procurar nomes" e "Baixa qualidade" liga/desliga), num
painel recolhível com resumo. Testes e contratestes: o que não está disponível fica desativado com o motivo, escolha
impossível forçada pelo navegador é recusada pelo servidor, texto do servidor nunca vira HTML, falha ao carregar as
opções não impede o envio, e a lista de tarefas não fica espremida (bug relatado com print)."""
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


def open_panel(page):
    page.wait_for_function("() => document.querySelectorAll('#opt-profile .opt-pill').length > 0")
    if not page.evaluate("() => document.getElementById('upload-options').open"):
        page.get_by_test_id("opt-toggle").click()
    expect(page.get_by_test_id("opt-profile")).to_be_visible()


def profile(page, pid):
    return page.get_by_test_id(f"opt-profile-{pid}")


def only_task(live_app):
    assert len(live_app.mod.tasks) == 1
    return next(iter(live_app.mod.tasks.items()))


def summary(page):
    return page.locator("[data-testid=opt-summary] .opt-chip").all_inner_texts()


# ------------------------------------------------------------------ testes
def test_closed_panel_shows_a_summary_of_the_choices(page, open_app, installed):
    open_app()
    page.wait_for_function("() => document.querySelectorAll('[data-testid=opt-summary] .opt-chip').length > 0")
    expect(page.get_by_test_id("opt-profile")).to_be_hidden()          # recolhido por padrão: mais espaço à lista
    assert summary(page) == ["CPF e endereço"]


def test_profiles_are_buttons_with_server_defaults(page, open_app, installed):
    open_app()
    open_panel(page)
    expect(page.get_by_role("radiogroup", name="Perfil de proteção")).to_be_visible()
    expect(page.locator("#opt-profile [role=radio]")).to_have_count(5)
    expect(profile(page, "cpf_endereco")).to_have_attribute("aria-checked", "true")
    expect(profile(page, "gdpr")).to_have_attribute("aria-checked", "false")
    # perfil padrão não procura nomes: botão desativado com o motivo à vista
    expect(page.get_by_test_id("opt-names")).to_be_disabled()
    expect(page.get_by_test_id("opt-names-hint")).to_have_text("Este perfil não procura nomes.")
    profile(page, "lgpd_publicacao").click()
    expect(profile(page, "lgpd_publicacao")).to_have_attribute("aria-checked", "true")
    expect(profile(page, "cpf_endereco")).to_have_attribute("aria-checked", "false")
    expect(page.get_by_test_id("opt-names")).to_be_enabled()
    expect(page.get_by_test_id("opt-names-hint")).to_be_hidden()
    # o nome completo e a descrição ficam na dica
    assert "transparência" in profile(page, "lgpd_publicacao").get_attribute("title")


def test_upload_sends_the_chosen_options_and_the_card_shows_them(page, live_app, open_app, installed):
    open_app()
    open_panel(page)
    profile(page, "lgpd_publicacao").click()
    page.get_by_test_id("opt-names").click()
    page.get_by_test_id("opt-lowq").click()
    expect(page.get_by_test_id("opt-names")).to_have_attribute("aria-pressed", "true")
    expect(page.get_by_test_id("opt-lowq")).to_have_attribute("aria-pressed", "true")
    assert summary(page) == ["LGPD publicação", "Nomes", "Baixa qualidade"]
    page.set_input_files("#file-input", PDF)
    expect(page.get_by_test_id("task-opts")).to_be_visible()
    tid, task = only_task(live_app)
    assert task["options"] == {"perfil": "lgpd_publicacao", "nomes": True, "baixa_qualidade": True,
                               "segundo_olhar": True, "leitura_extra": True}
    assert live_app.worker_calls and live_app.worker_calls[0][0] == tid
    assert page.locator("[data-testid=task-opts] .opt-chip").all_inner_texts() == [
        "LGPD publicação", "Nomes", "Baixa qualidade"]


def test_toggle_buttons_switch_off_again(page, open_app, installed):
    open_app()
    open_panel(page)
    lowq = page.get_by_test_id("opt-lowq")
    lowq.click()
    expect(lowq).to_have_attribute("aria-pressed", "true")
    lowq.click()
    expect(lowq).to_have_attribute("aria-pressed", "false")


def test_keyboard_arrows_move_between_profiles(page, open_app, installed):
    open_app()
    open_panel(page)
    profile(page, "cpf_endereco").focus()
    page.keyboard.press("ArrowRight")
    expect(profile(page, "lgpd_publicacao")).to_have_attribute("aria-checked", "true")
    expect(profile(page, "lgpd_publicacao")).to_be_focused()
    page.keyboard.press("ArrowLeft")
    page.keyboard.press("ArrowLeft")                                    # dá a volta para o último
    expect(profile(page, "saude_hipaa")).to_have_attribute("aria-checked", "true")


def test_panel_remembers_being_open(page, live_app, open_app, installed):
    open_app()
    open_panel(page)
    page.reload()
    page.wait_for_function("() => document.querySelectorAll('#opt-profile .opt-pill').length > 0")
    expect(page.get_by_test_id("opt-profile")).to_be_visible()


def test_low_quality_without_extra_ocr_explains_and_uses_second_look_only(page, live_app, open_app, installed):
    installed["rapidocr"] = False
    open_app()
    open_panel(page)
    expect(page.get_by_test_id("opt-lowq-hint")).to_be_hidden()
    page.get_by_test_id("opt-lowq").click()
    expect(page.get_by_test_id("opt-lowq-hint")).to_contain_text("só o segundo olhar")
    page.set_input_files("#file-input", PDF)
    expect(page.locator(".task-item")).to_have_count(1)
    _, task = only_task(live_app)
    assert task["options"]["segundo_olhar"] is True and task["options"]["leitura_extra"] is False


def test_labels_follow_the_language(page, open_app, installed):
    open_app()
    open_panel(page)
    page.get_by_test_id("lang-select").select_option("en-US")
    expect(page.get_by_text("Options for the next upload")).to_be_visible()
    expect(page.get_by_role("radiogroup", name="Protection profile")).to_be_visible()
    expect(profile(page, "cpf_endereco")).to_have_text("CPF + address")
    expect(page.get_by_test_id("opt-names-hint")).to_have_text("This profile does not look for names.")


def test_task_list_keeps_room_with_many_tasks(page, live_app, open_app, installed):
    # Regressão do print: painel de opções e botões espremiam a lista de tarefas
    for i in range(6):
        live_app.seed_task(name=f"tarefa_{i}.pdf", extra={"options": {"perfil": "gdpr", "nomes": False,
                                                                       "baixa_qualidade": False}})
    page.set_viewport_size({"width": 1911, "height": 958})
    open_app()
    page.wait_for_function("() => document.querySelectorAll('#opt-profile .opt-pill').length > 0")
    list_h = page.evaluate("() => document.getElementById('task-list').getBoundingClientRect().height")
    assert list_h >= 0.6 * 958                                           # fechado: a lista fica com a maior parte
    page.set_viewport_size({"width": 1280, "height": 480})               # tela baixa, painel aberto
    open_panel(page)
    footer_h = page.evaluate("() => document.querySelector('.sidebar-footer').getBoundingClientRect().height")
    list_h = page.evaluate("() => document.getElementById('task-list').getBoundingClientRect().height")
    assert footer_h <= 0.6 * 480 + 2 and list_h >= 0.15 * 480, (footer_h, list_h)  # o rodapé tem teto
    # os três botões de ação cabem lado a lado, sem texto cortado
    widths = page.evaluate("""() => [...document.querySelectorAll('.sidebar-actions .tool-btn')]
                               .map(b => [b.scrollWidth, b.clientWidth])""")
    assert all(sw <= cw + 1 for sw, cw in widths), widths


# ------------------------------------------------------------------ contratestes
def test_names_unavailable_stays_disabled_on_every_profile(page, open_app, installed):
    installed["gliner"] = False
    open_app()
    open_panel(page)
    for pid in ("lgpd_publicacao", "gdpr", "saude_hipaa"):
        profile(page, pid).click()
        expect(page.get_by_test_id("opt-names")).to_be_disabled()
        expect(page.get_by_test_id("opt-names-hint")).to_have_text("Detector de nomes não instalado neste servidor.")


def test_clicking_a_disabled_names_button_does_nothing(page, open_app, installed):
    open_app()
    open_panel(page)
    page.get_by_test_id("opt-names").click(force=True)                  # perfil padrão não procura nomes
    expect(page.get_by_test_id("opt-names")).to_have_attribute("aria-pressed", "false")
    assert summary(page) == ["CPF e endereço"]


def test_forcing_a_disabled_option_is_rejected_by_the_server(page, live_app, open_app, installed):
    installed["gliner"] = False
    open_app()
    open_panel(page)
    profile(page, "lgpd_publicacao").click()
    # alguém contorna a interface (DevTools): o servidor precisa recusar
    page.evaluate("() => { document.getElementById('opt-names').disabled = false; optState.nomes = true; }")
    page.set_input_files("#file-input", PDF)
    expect(page.locator("#toast")).to_contain_text("detector de nomes")
    assert live_app.mod.tasks == {} and live_app.worker_calls == []


def test_switching_to_a_profile_without_names_switches_names_off(page, live_app, open_app, installed):
    open_app()
    open_panel(page)
    profile(page, "gdpr").click()
    page.get_by_test_id("opt-names").click()
    expect(page.get_by_test_id("opt-names")).to_have_attribute("aria-pressed", "true")
    profile(page, "cpf_endereco").click()
    expect(page.get_by_test_id("opt-names")).to_have_attribute("aria-pressed", "false")
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
    # Um perfil novo que a interface não conhece usa o nome curto do servidor: precisa aparecer como TEXTO
    from utils.detect import profiles
    evil = "<img src=x onerror=alert('xss')>"
    monkeypatch.setitem(profiles.PROFILES, "teste_xss", {**profiles.PROFILES["gdpr"], "curto": evil, "nome": evil})
    open_app()
    open_panel(page)
    assert profile(page, "teste_xss").inner_text() == evil
    profile(page, "teste_xss").click()
    page.set_input_files("#file-input", PDF)
    expect(page.get_by_test_id("task-opts")).to_be_visible()
    assert page.locator("[data-testid=task-opts] .opt-chip").first.inner_text() == evil
    assert page.locator("#upload-options img, .task-opts img").count() == 0 and dialogs.messages == []


def test_old_tasks_without_options_show_no_chips(page, live_app, open_app, installed):
    live_app.seed_task(name="antiga.pdf")
    open_app()
    expect(page.locator(".task-title")).to_have_text("antiga.pdf")
    expect(page.get_by_test_id("task-opts")).to_have_count(0)


def test_cards_show_the_profile_name_not_the_internal_code(page, live_app, open_app, installed):
    # Bug visto ao reproduzir o print: se os cartões chegam antes das opções, mostravam "lgpd_publicacao" até o
    # próximo ciclo de atualização. Segura a resposta de /options até o cartão aparecer (a ordem ruim, de propósito).
    live_app.seed_task(name="x.pdf", extra={"options": {"perfil": "lgpd_publicacao", "nomes": False,
                                                        "baixa_qualidade": False}})
    held = []
    page.route("**/options", lambda route: held.append(route))
    open_app()
    chip = page.locator("[data-testid=task-opts] .opt-chip").first
    expect(chip).to_have_text("lgpd_publicacao")                         # opções ainda não chegaram
    held[0].continue_()
    expect(chip).to_have_text("LGPD publicação", timeout=1500)           # antes do ciclo de 3 s

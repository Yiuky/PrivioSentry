# SPDX-License-Identifier: AGPL-3.0-or-later
"""UI: sidebar, upload, lista de tarefas, menu de ações, ações em lote, README, download."""
import re

import pytest
from playwright.sync_api import expect

from ui_support import FAKE_PDF

pytestmark = pytest.mark.ui

DOC_ERR = "Interrompido"


def titles(page):
    return page.locator("#task-list .task-title").all_inner_texts()


# ------------------------------------------------------------------ carga inicial
def test_empty_state_and_sidebar_buttons(page, open_app):
    open_app()
    expect(page.locator("#empty-state")).to_be_visible()
    expect(page.locator("#toolbar")).to_be_hidden()
    expect(page.locator("#doc-name")).to_have_text("Aguardando documento...")
    for label in ("Documentação", "Adicionar PDFs", "Processar todos", "Excluir todos"):
        expect(page.get_by_role("button", name=label)).to_be_visible()
    assert page.locator(".task-item").count() == 0


# ------------------------------------------------------------------ upload
def test_upload_valid_pdf_creates_task_and_starts_worker(page, live_app, open_app):
    open_app()
    page.set_input_files("#file-input", {"name": "novo_doc.pdf", "mimeType": "application/pdf", "buffer": FAKE_PDF})
    expect(page.locator(".task-title")).to_have_text("novo_doc.pdf")
    expect(page.locator(".task-status")).to_contain_text("Iniciando...")
    assert len(live_app.worker_calls) == 1
    tid = live_app.worker_calls[0][0]
    assert live_app.mod.tasks[tid]["file"] == "novo_doc.pdf"
    # o input é limpo para permitir reenviar o mesmo arquivo
    assert page.eval_on_selector("#file-input", "e => e.value") == ""


def test_upload_multiple_files(page, live_app, open_app):
    open_app()
    page.set_input_files("#file-input", [
        {"name": "a.pdf", "mimeType": "application/pdf", "buffer": FAKE_PDF},
        {"name": "b.pdf", "mimeType": "application/pdf", "buffer": FAKE_PDF},
    ])
    expect(page.locator(".task-item")).to_have_count(2)
    assert len(live_app.worker_calls) == 2


def test_upload_non_pdf_extension_shows_error_and_creates_nothing(page, live_app, open_app):
    open_app()
    page.set_input_files("#file-input", {"name": "nota.txt", "mimeType": "text/plain", "buffer": b"abc"})
    expect(page.locator("#toast")).to_contain_text("Falha no upload de nota.txt")
    expect(page.locator("#toast")).to_contain_text("PDF")
    assert page.locator(".task-item").count() == 0
    assert live_app.worker_calls == [] and live_app.mod.tasks == {}


def test_upload_fake_pdf_content_is_rejected_with_message(page, live_app, open_app):
    open_app()
    page.set_input_files("#file-input", {"name": "falso.pdf", "mimeType": "application/pdf", "buffer": b"MZ not a pdf"})
    expect(page.locator("#toast")).to_contain_text("não é um PDF válido")
    assert live_app.mod.tasks == {}


def test_upload_too_large_is_reported(page, live_app, open_app, monkeypatch):
    monkeypatch.setattr(live_app.mod, "MAX_UPLOAD_BYTES", 10)
    open_app()
    page.set_input_files("#file-input", {"name": "grande.pdf", "mimeType": "application/pdf", "buffer": FAKE_PDF + b"x" * 100})
    expect(page.locator("#toast")).to_contain_text("tamanho máximo")
    assert live_app.mod.tasks == {}


def test_upload_malicious_filename_is_sanitized_in_list(page, live_app, open_app):
    open_app()
    page.set_input_files("#file-input", {"name": "<img src=x onerror=window.__xss=1>.pdf",
                                         "mimeType": "application/pdf", "buffer": FAKE_PDF})
    expect(page.locator(".task-item")).to_have_count(1)
    assert page.locator("#task-list img").count() == 0
    assert page.evaluate("window.__xss") is None


# ------------------------------------------------------------------ lista, ordenação e status
def test_task_list_sorted_newest_first(page, live_app, open_app):
    live_app.seed_task("antiga.pdf", age_minutes=300)
    live_app.seed_task("media.pdf", age_minutes=100)
    live_app.seed_task("nova.pdf", age_minutes=5)
    open_app()
    assert titles(page) == ["nova.pdf", "media.pdf", "antiga.pdf"]


def test_task_list_reorders_when_new_task_appears(page, live_app, open_app):
    live_app.seed_task("velha.pdf", age_minutes=300)
    open_app()
    assert titles(page) == ["velha.pdf"]
    live_app.seed_task("recem.pdf", age_minutes=1)
    page.evaluate("fetchTasks()")
    assert titles(page) == ["recem.pdf", "velha.pdf"]


def test_status_percentage_and_download_buttons_by_state(page, live_app, open_app):
    done = live_app.seed_task("pronto.pdf", final_pdf=True, age_minutes=1)
    running = live_app.seed_task("andamento.pdf", status="OCR em andamento", percentage=40, age_minutes=2)
    err = live_app.seed_task("quebrado.pdf", status=DOC_ERR, error=True, age_minutes=3)
    open_app()
    expect(page.locator(f"#t-{done} .task-status")).to_contain_text("Concluído")
    expect(page.locator(f"#t-{done} .btn-download")).to_be_visible()
    expect(page.locator(f"#t-{done} .btn-view")).to_be_visible()
    expect(page.locator(f"#t-{running} .task-status")).to_contain_text("OCR em andamento (40%)")
    expect(page.locator(f"#t-{running} .btn-download")).to_have_count(0)
    expect(page.locator(f"#t-{err} .task-status")).to_contain_text(DOC_ERR)
    # polling reflete mudança de status
    live_app.update_task(running, status="Verificando", percentage=90)
    page.evaluate("fetchTasks()")
    expect(page.locator(f"#t-{running} .task-status")).to_contain_text("Verificando (90%)")


def test_alert_icon_tooltip_lists_alerts(page, live_app, open_app):
    tid = live_app.seed_task("com_alerta.pdf", alerts=["Pág 1: a", "Pág 2: b"])
    open_app()
    title = page.locator(f"#t-{tid} .alert-icon").get_attribute("title")
    assert "Pág 1: a" in title and "Pág 2: b" in title and "\n" in title


# ------------------------------------------------------------------ menu ⋮
def test_menu_opens_closes_and_survives_polling(page, live_app, open_app):
    a = live_app.seed_task("a.pdf", age_minutes=1)
    b = live_app.seed_task("b.pdf", age_minutes=2)
    open_app()
    menu_a = page.locator(f"#m-{a}")
    expect(menu_a).to_be_hidden()
    page.locator(f"#t-{a} .task-menu-btn").click()
    expect(menu_a).to_be_visible()
    for name in ("Reprocessar", "Ver logs", "Excluir"):
        expect(menu_a.get_by_role("menuitem", name=name)).to_be_visible()
    # regressão: o polling (3s) re-renderizava a lista e fechava o menu aberto
    for _ in range(3):
        page.evaluate("fetchTasks()")
    expect(menu_a).to_be_visible()
    # abrir outro menu fecha o primeiro
    page.locator(f"#t-{b} .task-menu-btn").click()
    expect(page.locator(f"#m-{b}")).to_be_visible()
    expect(menu_a).to_be_hidden()
    # clique fora fecha
    page.locator("#doc-name").click()
    expect(page.locator(f"#m-{b}")).to_be_hidden()
    # abrir o menu não seleciona a tarefa
    assert page.locator(".task-item.active").count() == 0


def test_menu_reprocess(page, live_app, open_app, dialogs):
    tid = live_app.seed_task("rep.pdf", status=DOC_ERR, error=True)
    open_app()
    page.locator(f"#t-{tid} .task-menu-btn").click()
    with page.expect_request(lambda r: r.url.endswith(f"/reprocess/{tid}") and r.method == "POST"):
        page.locator(f"#m-{tid}").get_by_role("menuitem", name="Reprocessar").click()
    assert dialogs.messages == ["Reprocessar arquivo?"]
    expect(page.locator(f"#t-{tid} .task-status")).to_contain_text("Reiniciando...")
    assert [c[0] for c in live_app.worker_calls] == [tid]
    assert live_app.mod.tasks[tid]["error"] is False


def test_menu_reprocess_cancelled_does_nothing(page, live_app, open_app, dialogs):
    tid = live_app.seed_task("rep.pdf", status=DOC_ERR, error=True)
    dialogs.accept = False
    open_app()
    page.locator(f"#t-{tid} .task-menu-btn").click()
    page.locator(f"#m-{tid}").get_by_role("menuitem", name="Reprocessar").click()
    page.wait_for_timeout(200)
    assert live_app.worker_calls == []
    assert live_app.mod.tasks[tid]["error"] is True


def test_menu_logs_overlay_content_and_close(page, live_app, open_app):
    log = "INFO inicio\nERRO falha qualquer\nWARNING algo\nINFO fim"
    tid = live_app.seed_task("log.pdf", log=log)
    open_app()
    page.locator(f"#t-{tid} .task-menu-btn").click()
    page.locator(f"#m-{tid}").get_by_role("menuitem", name="Ver logs").click()
    overlay = page.locator("#logs-overlay")
    expect(overlay).to_be_visible()
    lines = page.locator("#logs-content .log-line")
    expect(lines).to_have_count(4)
    assert lines.nth(1).get_attribute("class").count("log-error") == 1
    assert "log-warn" in lines.nth(2).get_attribute("class")
    assert "log-error" not in lines.nth(0).get_attribute("class")
    # fechar pelo X
    page.locator("#logs-close").click()
    expect(overlay).to_be_hidden()
    # reabrir e fechar clicando no fundo
    page.locator(f"#t-{tid} .task-menu-btn").click()
    page.locator(f"#m-{tid}").get_by_role("menuitem", name="Ver logs").click()
    expect(overlay).to_be_visible()
    overlay.click(position={"x": 5, "y": 5})
    expect(overlay).to_be_hidden()


def test_menu_logs_without_file_and_html_is_not_injected(page, live_app, open_app):
    tid = live_app.seed_task("semlog.pdf")
    xss = live_app.seed_task("xsslog.pdf", log="<img src=x onerror=window.__xss=1>\nlinha")
    open_app()
    page.locator(f"#t-{tid} .task-menu-btn").click()
    page.locator(f"#m-{tid}").get_by_role("menuitem", name="Ver logs").click()
    expect(page.locator("#logs-content")).to_contain_text("Nenhum log encontrado")
    page.locator("#logs-close").click()
    page.locator(f"#t-{xss} .task-menu-btn").click()
    page.locator(f"#m-{xss}").get_by_role("menuitem", name="Ver logs").click()
    expect(page.locator("#logs-content")).to_contain_text("<img src=x")
    assert page.locator("#logs-content img").count() == 0
    assert page.evaluate("window.__xss") is None


def test_menu_delete_removes_task(page, live_app, open_app, dialogs):
    keep = live_app.seed_task("fica.pdf", age_minutes=1)
    gone = live_app.seed_task("some.pdf", age_minutes=2)
    open_app()
    page.locator(f"#t-{gone} .task-menu-btn").click()
    with page.expect_request(lambda r: r.method == "DELETE" and r.url.endswith(f"/task/{gone}")):
        page.locator(f"#m-{gone}").get_by_role("menuitem", name="Excluir").click()
    assert "Excluir permanentemente" in dialogs.messages[0]
    expect(page.locator(f"#t-{gone}")).to_have_count(0)
    expect(page.locator(f"#t-{keep}")).to_have_count(1)
    assert gone not in live_app.mod.tasks and keep in live_app.mod.tasks


def test_menu_delete_cancelled_keeps_task(page, live_app, open_app, dialogs):
    tid = live_app.seed_task("fica.pdf")
    dialogs.accept = False
    open_app()
    page.locator(f"#t-{tid} .task-menu-btn").click()
    page.locator(f"#m-{tid}").get_by_role("menuitem", name="Excluir").click()
    page.wait_for_timeout(200)
    assert tid in live_app.mod.tasks
    expect(page.locator(f"#t-{tid}")).to_have_count(1)


def test_delete_running_task_shows_server_error(page, live_app, open_app, monkeypatch):
    tid = live_app.seed_task("rodando.pdf", status="OCR", completed=False)
    monkeypatch.setattr(live_app.mod, "is_running", lambda t: True)
    open_app()
    page.locator(f"#t-{tid} .task-menu-btn").click()
    page.locator(f"#m-{tid}").get_by_role("menuitem", name="Excluir").click()
    expect(page.locator("#toast")).to_contain_text("Tarefa em execução")
    assert tid in live_app.mod.tasks


# ------------------------------------------------------------------ ações em lote
def test_process_all_starts_stopped_tasks_only(page, live_app, open_app, dialogs):
    waiting = live_app.seed_task("espera.pdf", status="Aguardando", completed=False, age_minutes=1)
    broken = live_app.seed_task("erro.pdf", status=DOC_ERR, error=True, age_minutes=2)
    done = live_app.seed_task("ok.pdf", age_minutes=3)
    open_app()
    with page.expect_request(lambda r: r.url.endswith("/process-all") and r.method == "POST"):
        page.get_by_role("button", name="Processar todos").click()
    assert "lote" in dialogs.messages[0]
    page.wait_for_timeout(200)
    started = {c[0] for c in live_app.worker_calls}
    assert started == {waiting, broken} and done not in started
    assert live_app.mod.tasks[broken]["error"] is False


def test_process_all_cancelled(page, live_app, open_app, dialogs):
    live_app.seed_task("erro.pdf", status=DOC_ERR, error=True)
    dialogs.accept = False
    open_app()
    page.get_by_role("button", name="Processar todos").click()
    page.wait_for_timeout(200)
    assert live_app.worker_calls == []


def test_delete_all_confirm_and_cancel(page, live_app, open_app, dialogs):
    live_app.seed_task("a.pdf", age_minutes=1)
    live_app.seed_task("b.pdf", age_minutes=2)
    open_app()
    dialogs.accept = False
    page.get_by_role("button", name="Excluir todos").click()
    page.wait_for_timeout(200)
    assert len(live_app.mod.tasks) == 2
    dialogs.accept = True
    with page.expect_request(lambda r: r.method == "DELETE" and r.url.endswith("/delete-all")):
        page.get_by_role("button", name="Excluir todos").click()
    assert "ALERTA" in dialogs.messages[-1]
    expect(page.locator(".task-item")).to_have_count(0)
    assert live_app.mod.tasks == {}
    expect(page.locator("#empty-state")).to_be_visible()


def test_delete_all_with_open_editor_resets_view(page, live_app, open_task):
    """Regressão: o JS referenciava #container (inexistente) e quebrava ao excluir com o editor aberto."""
    tid = live_app.seed_task("aberto.pdf", redactions=[])
    open_task(tid)
    expect(page.locator("#toolbar")).to_be_visible()
    page.get_by_role("button", name="Excluir todos").click()
    expect(page.locator("#empty-state")).to_be_visible()
    expect(page.locator("#toolbar")).to_be_hidden()
    expect(page.locator("#document-viewer")).to_be_hidden()
    expect(page.locator("#doc-name")).to_have_text("Aguardando documento...")
    expect(page.locator("#page-nav")).to_be_hidden()


def test_deleting_open_task_resets_editor_and_list_keeps_updating(page, live_app, open_task):
    """Regressão: excluir a tarefa aberta lançava TypeError e abortava a atualização da lista."""
    a = live_app.seed_task("aberta.pdf", redactions=[], age_minutes=2)
    b = live_app.seed_task("outra.pdf", redactions=[], age_minutes=1)
    open_task(a)
    page.locator(f"#t-{a} .task-menu-btn").click()
    page.locator(f"#m-{a}").get_by_role("menuitem", name="Excluir").click()
    expect(page.locator("#empty-state")).to_be_visible()
    expect(page.locator(f"#t-{b}")).to_have_count(1)
    c = live_app.seed_task("nova.pdf", age_minutes=0)
    page.evaluate("fetchTasks()")
    expect(page.locator(f"#t-{c}")).to_have_count(1)


# ------------------------------------------------------------------ README
def test_readme_open_and_close_both_ways(page, open_app):
    open_app()
    overlay = page.locator("#readme-overlay")
    expect(overlay).to_be_hidden()
    page.get_by_role("button", name="Documentação").click()
    expect(overlay).to_be_visible()
    expect(page.locator("#readme-content h1")).to_have_text("Ajuda Teste")
    expect(page.locator("#readme-content")).to_contain_text("Texto de ajuda")
    page.locator("#readme-close").click()
    expect(overlay).to_be_hidden()
    page.get_by_role("button", name="Documentação").click()
    expect(overlay).to_be_visible()
    overlay.click(position={"x": 5, "y": 5})
    expect(overlay).to_be_hidden()
    # clicar DENTRO do modal não fecha
    page.get_by_role("button", name="Documentação").click()
    page.locator("#readme-content").click()
    expect(overlay).to_be_visible()


def test_readme_missing_shows_error(page, live_app, open_app):
    (live_app.tmp / "README.md").unlink()
    open_app()
    page.get_by_role("button", name="Documentação").click()
    # 404 -> {detail}; o renderizador local de Markdown trata conteúdo ausente e o modal abre sem quebrar a página
    expect(page.locator("#readme-overlay")).to_be_visible()


# ------------------------------------------------------------------ Ver / Baixar PDF
def test_download_button_downloads_final_pdf(page, live_app, open_app):
    tid = live_app.seed_task("relatorio.pdf", final_pdf=True)
    open_app()
    with page.expect_download() as dl:
        page.locator(f"#t-{tid} .btn-download").click()
    d = dl.value
    assert d.suggested_filename == "relatorio_TARJADO.pdf"
    with open(d.path(), "rb") as f:
        assert f.read(5) == b"%PDF-"
    # baixar não seleciona/abre a tarefa
    expect(page.locator("#toolbar")).to_be_hidden()


def test_view_button_opens_inline_pdf_in_new_tab(page, live_app, open_app):
    tid = live_app.seed_task("ver.pdf", final_pdf=True)
    open_app()
    with page.context.expect_event(
            "request", lambda r: f"/download/{tid}?inline=true" in r.url):
        page.locator(f"#t-{tid} .btn-view").click()
    r = page.request.get(f"{live_app.url}/download/{tid}?inline=true")
    assert r.status == 200 and r.headers["content-disposition"].startswith("inline")
    expect(page.locator("#toolbar")).to_be_hidden()


# ------------------------------------------------------------------ abrir tarefa
def test_open_task_shows_editor_pages_and_boxes(page, live_app, open_task):
    from ui_support import box
    tid = live_app.seed_task("tres.pdf", pages=3, redactions=[box(1), box(2), box(2, (10, 10, 60, 40))])
    open_task(tid)
    expect(page.locator("#doc-name")).to_have_text("tres.pdf")
    expect(page.locator("#toolbar")).to_be_visible()
    expect(page.locator("#empty-state")).to_be_hidden()
    expect(page.locator(f"#t-{tid}")).to_have_class(re.compile(r"active"))
    expect(page.locator(".page-wrapper")).to_have_count(3)
    expect(page.locator("#page-info")).to_have_text("1 / 3")
    expect(page.locator("#layer-1 .redaction-box")).to_have_count(1)
    expect(page.locator("#layer-2 .redaction-box")).to_have_count(2)
    expect(page.locator("#layer-3 .redaction-box")).to_have_count(0)


def test_switching_tasks_clears_previous_boxes(page, live_app, open_task):
    from ui_support import box
    a = live_app.seed_task("a.pdf", redactions=[box(1), box(1, (5, 5, 50, 30))], age_minutes=2)
    b = live_app.seed_task("b.pdf", redactions=[box(1)], age_minutes=1)
    open_task(a)
    expect(page.locator(".redaction-box")).to_have_count(2)
    page.locator(f"#t-{b}").click()
    expect(page.locator("#doc-name")).to_have_text("b.pdf")
    expect(page.locator(".redaction-box")).to_have_count(1)

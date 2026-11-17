# SPDX-License-Identifier: AGPL-3.0-or-later
"""UI: página de demonstração da API (/api-demo): envio, fila, mensagens e download só do PDF aprovado.
Sem rede externa (fixture `page`), sem worker de verdade (start_worker simulado)."""
import pytest
from playwright.sync_api import expect

from ui_support import FAKE_PDF

pytestmark = pytest.mark.ui


@pytest.fixture()
def open_demo(page, live_app, console_errors):
    def _open():
        page.goto(live_app.url + "/api-demo")
        expect(page.locator("#live-text")).to_have_text("conectado")
        return page
    yield _open
    # o 409 do download não aprovado é a resposta esperada; o Chromium sempre o registra no console
    assert [e for e in console_errors if "status of 409" not in e] == []


def test_page_is_local_and_shows_the_queue(open_demo, live_app):
    live_app.seed_task("relatorio_fulano.pdf", status="Requer revisão", needs_review=True)
    live_app.seed_task("b.pdf", status="Na fila (1º)", completed=False, extra={"queued": True})
    page = open_demo()
    expect(page.locator("#local-badge")).to_have_text("LOCAL PROCESSING")
    expect(page.locator("#tasks tr")).to_have_count(2)
    expect(page.locator("[data-state=revisao]")).to_have_count(1)
    expect(page.locator("[data-state=fila]")).to_have_text("Na fila (1º)")
    expect(page.locator("#q-review")).to_have_text("1")
    expect(page.locator("#feed [data-topic='fila.conectada']")).to_have_count(1)


def test_file_names_are_hidden_until_asked(open_demo, live_app):
    live_app.seed_task("relatorio_fulano.pdf")
    page = open_demo()
    expect(page.locator("#tasks")).not_to_contain_text("fulano")
    page.locator("#show-names").check()
    expect(page.locator("#tasks")).to_contain_text("relatorio_fulano.pdf")                    # contra-teste


def test_alerts_never_reach_the_page(open_demo, live_app):
    live_app.seed_task("x.pdf", status="Requer revisão", needs_review=True,
                       alerts=["Página 1: CPF 529.982.247-25 sem tarja"])
    page = open_demo()
    expect(page.locator("[data-state=revisao]")).to_have_count(1)
    assert "529.982" not in page.content() and "sem tarja" not in page.content()


def test_upload_through_the_api_and_messages(open_demo, live_app, tmp_path):
    page = open_demo()
    pdf = tmp_path / "enviado.pdf"
    pdf.write_bytes(FAKE_PDF)
    page.locator("#file").set_input_files(str(pdf))
    page.locator("#send").click()
    expect(page.locator("#feed [data-topic='tarefa.criada']")).to_have_count(1)
    assert len(live_app.worker_calls) == 1
    tid = live_app.worker_calls[0][0]
    expect(page.locator("#curl")).to_contain_text(f"/download/{tid}?final=true")
    page.locator("#only-mine").check()
    expect(page.locator("#tasks tr")).to_have_count(1)
    # processamento termina com pontos de revisão: vira mensagem
    live_app.update_task(tid, status="Requer revisão", completed=True, needs_review=True, percentage=100)
    expect(page.locator("#feed [data-topic='tarefa.requer_revisao']")).to_have_count(1)
    page.locator("#tab-http").click()
    expect(page.locator("#http")).to_contain_text("POST")


def test_not_approved_download_is_refused(open_demo, live_app):
    tid = live_app.seed_task("x.pdf", status="Concluído", final_pdf=True)   # preliminar: há PDF, sem aprovação
    page = open_demo()
    page.locator(f"[data-download='{tid}']").click()
    expect(page.locator("#feed [data-topic='download.recusado']")).to_contain_text("HTTP 409")


def test_approved_pdf_is_downloaded(open_demo, live_app):
    tid = live_app.seed_task("x.pdf", status="Concluído", final_pdf=True, extra={"finalizado": True})
    page = open_demo()
    expect(page.locator("[data-state=aprovado]")).to_have_count(1)
    with page.expect_download() as dl:
        page.locator(f"[data-download='{tid}']").click()
    assert dl.value.suggested_filename == f"{tid[:8]}_protegido.pdf"
    expect(page.locator("#feed [data-topic='download.entregue']")).to_have_count(1)


def test_external_ai_changes_the_badge(open_demo, live_app, monkeypatch):
    monkeypatch.setattr(live_app.mod, "external_ai_now", lambda: ["api.exemplo-nuvem.test"])
    page = open_demo()
    expect(page.locator("#local-badge")).to_have_text("EXTERNAL AI")

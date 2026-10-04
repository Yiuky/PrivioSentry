# SPDX-License-Identifier: AGPL-3.0-or-later
"""Infraestrutura dos testes de UI (Playwright + servidor FastAPI real).

O app é o `app_service.app` de verdade, servido por uvicorn numa thread, porta livre, com:
- estado isolado em tmp_path (tasks.json, WEB_INPUT, output/, documentos_finais/, README.md);
- `start_worker` substituído por um stub (sem Tesseract/Ollama), que registra as chamadas e
  permite simular a conclusão/erro do worker;
- qualquer requisição a host não-local é BLOQUEADA e faz o teste falhar (app local-first: sem CDN/fontes externas).

Dados são todos sintéticos (imagens PIL, PDFs PyMuPDF). Se o playwright/chromium não estiver
disponível, os testes são PULADOS (skip) em vez de falhar.
"""
import importlib
import json
import os
import socket
import threading
import time
import uuid
from datetime import datetime, timedelta
from urllib.parse import urlparse

import pytest

from ui_support import FAKE_PDF, PAGE_H, PAGE_W, make_pdf, make_png  # noqa: F401

try:  # pragma: no cover - depende do ambiente
    import playwright  # noqa: F401
    HAVE_PLAYWRIGHT = True
except Exception:  # pragma: no cover
    HAVE_PLAYWRIGHT = False

def pytest_configure(config):
    config.addinivalue_line("markers", "ui: testes de interface com Playwright (navegador real)")


def pytest_collection_modifyitems(config, items):
    if HAVE_PLAYWRIGHT:
        return
    skip = pytest.mark.skip(reason="playwright não instalado")
    for item in items:
        if "tests/ui" in item.nodeid.replace("\\", "/"):
            item.add_marker(skip)


# ---------------------------------------------------------------- navegador
@pytest.fixture(scope="session")
def chromium_ok():
    if not HAVE_PLAYWRIGHT:
        pytest.skip("playwright não instalado")
    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as p:
            b = p.chromium.launch()
            b.close()
    except Exception as e:  # chromium ausente / sem permissão
        pytest.skip(f"chromium indisponível: {str(e)[:120]}")
    return True


@pytest.fixture(scope="session")
def browser_context_args(browser_context_args):
    return {**browser_context_args, "viewport": {"width": 1400, "height": 900}, "accept_downloads": True}


# ---------------------------------------------------------------- dados sintéticos
def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class AppHandle:
    """Referência ao app em execução: URL, módulo, diretórios e helpers de seed."""

    def __init__(self, mod, tmp_path, url):
        self.mod = mod
        self.tmp = tmp_path
        self.url = url
        self.output_dir = tmp_path / "output"
        self.final_dir = tmp_path / "documentos_finais"
        self.worker_calls = []        # [(task_id, manual_redactions, native_mode)]
        self.worker_hook = None       # callable(task_id, manual_redactions, native_mode)
        self._seq = 0

    # --- seed -------------------------------------------------------
    def seed_task(self, name="doc.pdf", pages=1, status="Concluído", percentage=None, completed=None,
                  error=False, needs_review=False, alerts=None, redactions=None, log=None,
                  final_pdf=False, with_images=True, age_minutes=None, extra=None):
        """Cria uma tarefa no estado do app + arquivos em output/<base>/ . Devolve task_id."""
        self._seq += 1
        tid = str(uuid.uuid4())
        base = f"{tid}_doc{self._seq}"  # independe do nome (pode ter HTML)
        input_path = str(self.tmp / "in" / f"{base}.pdf")
        os.makedirs(os.path.dirname(input_path), exist_ok=True)
        with open(input_path, "wb") as f:
            f.write(FAKE_PDF)
        if completed is None:
            completed = status in ("Concluído", "Requer revisão") and not error
        if percentage is None:
            percentage = 100 if completed else 0
        # created_at crescente por ordem de criação (a mais nova por último), salvo age_minutes
        created = datetime.now() - timedelta(minutes=age_minutes if age_minutes is not None else 100 - self._seq)
        task = {
            "file": name, "input_path": input_path, "created_at": created.isoformat(),
            "status": status, "percentage": percentage, "completed": completed, "error": error,
            "needs_review": needs_review, "alerts": list(alerts or []), "total": pages,
        }
        task.update(extra or {})
        out = self.output_dir / base
        os.makedirs(out, exist_ok=True)
        if with_images:
            for n in range(1, pages + 1):
                make_png(str(out / "00_original_images" / f"{base}_page_{n}.png"), n)
        if redactions is not None:
            with open(out / "redactions_metadata.json", "w", encoding="utf-8") as f:
                json.dump(redactions, f)
        if log is not None:
            with open(out / "process_log.log", "w", encoding="utf-8") as f:
                f.write(log)
        if final_pdf:
            make_pdf(str(self.final_dir / f"{base}_TARJADO_FINAL.pdf"), pages)
        with self.mod.tasks_lock:
            self.mod.tasks[tid] = task
            self.mod.save_tasks()
        return tid

    def base(self, tid):
        return self.mod.task_base(self.mod.tasks[tid])

    def manual_path(self, tid):
        return self.output_dir / self.base(tid) / "manual_redactions.json"

    def update_task(self, tid, **fields):
        with self.mod.tasks_lock:
            self.mod.tasks[tid].update(fields)
            self.mod.save_tasks()

    def finish_worker_later(self, delay=0.6, error=None):
        """Hook de worker: após `delay` s, conclui a tarefa gerando o PDF final (ou marca erro)."""
        def hook(tid, manual, native):
            def run():
                time.sleep(delay)
                if error:
                    self.update_task(tid, status=error, error=True, completed=False)
                    return
                make_pdf(str(self.final_dir / f"{self.base(tid)}_TARJADO_FINAL.pdf"))
                self.update_task(tid, status="Concluído", percentage=100, completed=True, error=False)
            threading.Thread(target=run, daemon=True).start()
        self.worker_hook = hook


@pytest.fixture()
def live_app(tmp_path, monkeypatch, chromium_ok):
    for k in ("API_TOKEN",):
        monkeypatch.setenv(k, "")  # evita que o .env ative o token
    monkeypatch.setenv("PRIVIO_TASKS_FILE", str(tmp_path / "tasks.json"))
    monkeypatch.setenv("PRIVIO_INPUT_DIR", str(tmp_path / "in"))
    monkeypatch.setenv("PRIVIO_OUTPUT_DIR", str(tmp_path / "output"))
    monkeypatch.setenv("PRIVIO_FINAL_DIR", str(tmp_path / "documentos_finais"))
    import app_service
    mod = importlib.reload(app_service)
    out, final = tmp_path / "output", tmp_path / "documentos_finais"
    out.mkdir(exist_ok=True)
    final.mkdir(exist_ok=True)
    (tmp_path / "README.md").write_text("# Ajuda Teste\n\nTexto de ajuda sintetico.", encoding="utf-8")
    # versões antigas do app não liam OUTPUT_DIR/FINAL_DIR do ambiente: garante o isolamento nos dois casos
    monkeypatch.setattr(mod, "OUTPUT_DIR", str(out))
    monkeypatch.setattr(mod, "FINAL_DIR", str(final), raising=False)
    monkeypatch.setattr(mod, "BASE_DIR", str(tmp_path))
    monkeypatch.setattr(mod, "API_TOKEN", "")

    port = free_port()
    handle = AppHandle(mod, tmp_path, f"http://127.0.0.1:{port}")

    def fake_start_worker(task_id, manual_redactions=None, native_mode=False):
        handle.worker_calls.append((task_id, manual_redactions, native_mode))
        if handle.worker_hook:
            handle.worker_hook(task_id, manual_redactions, native_mode)

    monkeypatch.setattr(mod, "start_worker", fake_start_worker)

    import uvicorn
    server = uvicorn.Server(uvicorn.Config(mod.app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 15
    while not server.started and time.time() < deadline:
        time.sleep(0.05)
    if not server.started:
        pytest.fail("uvicorn não subiu")
    try:
        yield handle
    finally:
        server.should_exit = True
        thread.join(timeout=10)


# ---------------------------------------------------------------- página
@pytest.fixture()
def page(live_app, page):  # sobrescreve o `page` do pytest-playwright adicionando isolamento de rede
    external = []

    def handler(route):
        host = urlparse(route.request.url).hostname
        if host in ("127.0.0.1", "localhost"):
            return route.continue_()
        external.append(route.request.url)
        return route.abort()

    page.route("**/*", handler)
    page.set_default_timeout(8000)
    page.external_requests = external
    yield page
    assert external == [], f"requisições externas feitas pela UI: {external}"


class Dialogs:
    def __init__(self):
        self.accept = True
        self.messages = []


@pytest.fixture()
def dialogs(page):
    d = Dialogs()

    def on_dialog(dlg):
        d.messages.append(dlg.message)
        dlg.accept() if d.accept else dlg.dismiss()

    page.on("dialog", on_dialog)
    return d


@pytest.fixture()
def console_errors(page):
    errors = []
    page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
    page.on("console", lambda m: errors.append(f"console: {m.text}")
            if m.type == "error" and "favicon" not in (m.location.get("url") or "") else None)
    return errors


@pytest.fixture()
def open_app(page, live_app, dialogs):
    def _open():
        page.goto(live_app.url)
        page.wait_for_selector("#task-list")
        return page
    return _open


@pytest.fixture()
def open_task(page, live_app, open_app):
    """Abre o app e clica na tarefa; espera a primeira página carregar."""
    def _open(tid):
        open_app()
        page.locator(f"#t-{tid}").click()
        page.wait_for_function(
            "() => { const i = document.querySelector('#page-wrapper-1 img'); return i && i.naturalWidth > 0; }")
        page.evaluate("Promise.all(document.getAnimations().map(a => a.finished.catch(() => null)))")
        return page
    return _open

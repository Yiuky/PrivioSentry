#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Gera as capturas de tela do README e do manual (docs/img/) com dados 100% fictícios.

Sobe o app de verdade numa porta livre, com estado numa pasta temporária, sem worker (nada de Tesseract, YOLO ou
IA): as tarefas e as caixas de tarja são semeadas a partir de um formulário fictício gerado aqui. Precisa do
Playwright com o Chromium (`playwright install chromium`).

Uso:  python scripts/make_screenshots.py [pasta_de_saida]     (padrão: docs/img)
"""
import json
import os
import socket
import sys
import tempfile
import threading
import time
import uuid

import fitz  # PyMuPDF

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
DPI = 110
CPF = "529.982.247-25"                       # CPF de teste permitido (scripts/audit_public_tree.py)

FORM = [  # (texto, tamanho da fonte, rótulo da tarja das palavras marcadas com *)
    ("FICHA DE CADASTRO - DADOS FICTÍCIOS", 15, None),
    ("Secretaria Fictícia de Exemplos e Testes", 10, None),
    ("", 10, None),
    ("Requerente: *Maria *Exemplo *da *Silva *Teste", 11, "Nome de pessoa"),
    (f"CPF: *{CPF}", 11, "CPF"),
    ("Endereço residencial: *Rua *das *Acácias *Fictícias, *123, *Bairro *Exemplo", 11, "Endereço residencial"),
    ("*Cidade *Fictícia *- *UF, *CEP *00000-000", 11, "Endereço residencial"),
    ("Telefone: *(65) *99999-0000      E-mail: *maria.teste@example.com", 11, None),
    ("", 10, None),
    ("Endereço da empresa (profissional, não é tarjado):", 11, None),
    ("Avenida Comercial Fictícia, 1000, Sala 10 - Centro", 11, None),
    ("", 10, None),
    ("Declaro que as informações acima são verdadeiras.", 11, None),
]
LABEL_BY_WORD = {"(65)": "Telefone", "99999-0000": "Telefone", "maria.teste@example.com": "E-mail"}


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _scribble(page, x, y, w=150, h=40):
    import math
    pts = [fitz.Point(x + t / 59 * w, y + h / 2 + math.sin(t / 59 * 14) * h * 0.35 * (1 - t / 118))
           for t in range(60)]
    shape = page.new_shape()
    shape.draw_polyline(pts)
    shape.finish(color=(0.05, 0.05, 0.45), width=1.6, closePath=False)
    shape.commit()
    return fitz.Rect(x - 6, y - 4, x + w + 6, y + h + 4)


def build_form(pdf_path):
    """Formulário fictício + as caixas que o pipeline sugeriria (em pixels da imagem renderizada)."""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    marked, y = [], 80
    for text, size, label in FORM:
        if text:
            page.insert_text((60, y), text.replace("*", ""), fontsize=size)
            marked += [(tok[1:], LABEL_BY_WORD.get(tok[1:], label), y) for tok in text.split() if tok.startswith("*")]
        y += 24 if size > 11 else 20
    sig = _scribble(page, 70, y + 10)
    page.insert_text((60, y + 70), "______________________________", fontsize=11)
    page.insert_text((60, y + 86), "Maria Exemplo da Silva Teste", fontsize=9)
    doc.save(pdf_path)
    scale = DPI / 72
    pix = page.get_pixmap(dpi=DPI)
    words = page.get_text("words")
    boxes, used = [], set()
    for word, label, line_y in marked:                     # a palavra certa: mesmo texto e mesma linha
        i = next(i for i, w in enumerate(words) if i not in used and w[4] == word and abs(w[3] - line_y) < 6)
        used.add(i)
        w = words[i]
        boxes.append({"page": 1, "type": "pii", "label": label, "source": "AI_Engine",
                      "coords": [round(w[0] * scale) - 2, round(w[1] * scale) - 2,
                                 round(w[2] * scale) + 2, round(w[3] * scale) + 2],
                      "image_width": pix.width, "image_height": pix.height})
    boxes.append({"page": 1, "type": "signature", "source": "YOLO_Vision",
                  "coords": [round(v * scale) for v in sig], "image_width": pix.width, "image_height": pix.height})
    doc.close()
    return pix, boxes


def main(out_dir):
    tmp = tempfile.mkdtemp(prefix="privio_shots_")
    env = {"PRIVIO_TASKS_FILE": "tasks.json", "PRIVIO_INPUT_DIR": "in", "PRIVIO_OUTPUT_DIR": "output",
           "PRIVIO_FINAL_DIR": "documentos_finais", "PRIVIO_SETTINGS_FILE": "privio_settings.json",
           "PRIVIO_DOC_TEMPLATES_DIR": "modelos_documento"}
    for k, v in env.items():
        os.environ[k] = os.path.join(tmp, v)
    # configuração fixa e fictícia: nada do .env desta máquina aparece nas capturas
    os.environ.update({"API_TOKEN": "", "AI_PROVIDER": "ollama", "OLLAMA_API_URL": "http://127.0.0.1:11434",
                       "OLLAMA_MODEL": "qwen2.5vl:7b", "OLLAMA_VISION_MODEL": "qwen2.5vl:7b", "AI_BASE_URL": "",
                       "AI_API_KEY": "", "AI_ALLOW_EXTERNAL": "0", "AI_SECONDARY_BASE_URL": "",
                       "POLICY_PROFILE": "lgpd_publicacao", "SECOND_LOOK": "0"})
    import app_service as mod
    mod.OUTPUT_DIR, mod.FINAL_DIR, mod.BASE_DIR, mod.API_TOKEN = (os.environ["PRIVIO_OUTPUT_DIR"],
                                                                 os.environ["PRIVIO_FINAL_DIR"], tmp, "")
    mod.start_worker = lambda *a, **k: None
    mod._ensure_dispatcher = lambda: None
    for d in ("in", "output", "documentos_finais"):
        os.makedirs(os.path.join(tmp, d), exist_ok=True)

    def seed(name, status, minutes_ago, redactions=None, **extra):
        tid = str(uuid.uuid4())
        base = f"{tid}_{os.path.splitext(name)[0][:40]}"
        input_path = os.path.join(tmp, "in", base + ".pdf")
        pix, boxes = build_form(input_path)
        img_dir = os.path.join(mod.OUTPUT_DIR, base, "00_original_images")
        os.makedirs(img_dir, exist_ok=True)
        pix.save(os.path.join(img_dir, f"{base}_page_1.png"))
        with open(os.path.join(mod.OUTPUT_DIR, base, "redactions_metadata.json"), "w", encoding="utf-8") as f:
            json.dump(boxes if redactions is None else redactions, f)
        done = status in ("Concluído", "Requer revisão")
        task = {"file": name, "input_path": input_path, "status": status, "total": 1,
                "created_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time() - 60 * minutes_ago)),
                "percentage": 100 if done else 0, "completed": done, "error": False, "needs_review": False,
                "alerts": []}
        task.update(extra)
        with mod.tasks_lock:
            mod.tasks[tid] = task
            mod.save_tasks()
        return tid

    seed("cadastro_exemplo_03.pdf", "Na fila (1º)", 1, queued=True)
    seed("requerimento_ficticio.pdf", "Pendente: limite de uso da IA", 3, pendente=True,
         pendente_ate=time.time() + 3600)
    seed("licenca_ficticia.pdf", "Concluído", 9, finalizado=True,
         modelo_documento={"id": "licenca", "nome": "Licença fictícia", "versao": 1})
    main_tid = seed("ficha_cadastro_ficticia.pdf", "Requer revisão", 5, needs_review=True,
                    alerts=["Página 1: endereço localizado só em parte; confira as tarjas."])
    with open(os.path.join(mod.OUTPUT_DIR, mod.task_base(mod.tasks[main_tid]), "manual_redactions.json"), "w",
              encoding="utf-8") as f:                        # revisado: base para o rascunho de modelo
        json.dump(json.load(open(os.path.join(mod.OUTPUT_DIR, mod.task_base(mod.tasks[main_tid]),
                                              "redactions_metadata.json"), encoding="utf-8")), f)

    import uvicorn
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(mod.app, host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    while not server.started:
        time.sleep(0.05)
    url = f"http://127.0.0.1:{port}"

    from playwright.sync_api import sync_playwright
    os.makedirs(out_dir, exist_ok=True)
    shots = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900}, device_scale_factor=1)
        page.route("**/*", lambda r: r.continue_() if r.request.url.startswith(url) else r.abort())

        page.goto(f"{url}/?task={main_tid}")
        page.wait_for_function("() => { const i = document.querySelector('#page-wrapper-1 img');"
                               " return i && i.naturalWidth > 0; }")
        page.evaluate("Promise.all(document.getAnimations().map(a => a.finished.catch(() => null)))")
        page.wait_for_timeout(400)
        shots.append(("editor.png", page.screenshot()))

        page.goto(f"{url}/admin#ia")
        page.wait_for_selector("#view-ia.active")
        page.wait_for_selector("[data-group=ia] .fields", state="attached")
        page.wait_for_timeout(400)
        shots.append(("admin.png", page.screenshot()))

        page.goto(f"{url}/admin#modelos")
        page.wait_for_selector("#view-modelos.active")
        page.get_by_test_id("tpl-task").select_option(main_tid)
        page.get_by_test_id("tpl-draft").click()
        page.get_by_test_id("tpl-editor").wait_for()
        page.get_by_test_id("tpl-test").click()
        page.get_by_test_id("tpl-test-result").wait_for()
        page.wait_for_timeout(400)
        shots.append(("modelos.png", page.screenshot()))
        browser.close()
    server.should_exit = True
    for name, data in shots:
        with open(os.path.join(out_dir, name), "wb") as f:
            f.write(data)
        print("gravado", os.path.join(out_dir, name))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "docs", "img"))

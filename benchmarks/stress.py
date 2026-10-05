# SPDX-License-Identifier: AGPL-3.0-or-later
"""Teste de PRESSÃO do procedimento completo, pela API do app em execução, só com PDFs FICTÍCIOS.

    python -m benchmarks.stress --url http://127.0.0.1:8001 --scenarios simultaneos,grande,pessima,hostis

Cenários:
    simultaneos  N uploads ao mesmo tempo (padrão 8): todas terminam? memória máxima, processos, tempo
    grande       um documento com muitas páginas (padrão 40)
    pessima      digitalização péssima: o documento NUNCA pode sair "Concluído" com CPF do gabarito sem detecção
    hostis       PDF truncado, protegido por senha, PDF falso, página gigante: recusa ou falha fechada, sem travar

Invariantes conferidas: toda tarefa termina (sem ficar presa), estado final é "Concluído" / "Requer revisão" / erro,
e "Concluído" só quando todos os CPFs do gabarito foram detectados. As tarefas criadas são APAGADAS no fim.
Não use em produção com documentos reais na fila: o teste cria e apaga tarefas no mesmo app.
"""
import argparse
import io
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from benchmarks import pii_corpus  # noqa: E402
from benchmarks.ocr_compare import render  # noqa: E402

FINAL_OK = ("Concluído", "Requer revisão")


def raster_pdf(texts, condition="padrao", seed=0):
    """PDF só com imagens (como uma digitalização), uma página por texto."""
    import fitz
    doc = fitz.open()
    for i, text in enumerate(texts):
        img = render(text, condition, seed + i)
        # cola a imagem no topo de uma folha A4 a 300 DPI SEM esticar (esticar deixava o texto ilegível)
        canvas = __import__("PIL.Image", fromlist=["Image"]).new("L", (2480, 3508), 255)
        canvas.paste(img.crop((0, 0, min(img.size[0], 2480), min(img.size[1], 3508))), (0, 0))
        buf = io.BytesIO()
        canvas.save(buf, "JPEG", quality=80)
        page = doc.new_page(width=595, height=842)
        page.insert_image(page.rect, stream=buf.getvalue())
    out = doc.tobytes()
    doc.close()
    return out


def hostile_files():
    import fitz
    good = raster_pdf(["Documento de teste\nCPF 000"], "limpa")
    files = {"truncado.pdf": good[: len(good) // 3], "falso.pdf": b"%PDF-1.7\n" + os.urandom(4096)}
    d = fitz.open()
    d.new_page().insert_text((72, 72), "conteudo protegido")
    files["senha.pdf"] = d.tobytes(encryption=fitz.PDF_ENCRYPT_AES_256, user_pw="segredo", owner_pw="dono")
    d.close()
    d = fitz.open()
    d.new_page(width=14400, height=14400).insert_text((72, 72), "pagina gigante")  # 200 x 200 polegadas
    files["gigante.pdf"] = d.tobytes()
    d.close()
    return files


class Client:
    def __init__(self, url, token=None):
        import requests
        self.s = requests.Session()
        self.url = url.rstrip("/")
        if token:
            self.s.headers["X-API-Token"] = token

    def upload(self, name, data):
        r = self.s.post(f"{self.url}/upload", files={"file": (name, data, "application/pdf")}, timeout=120)
        return r.status_code, (r.json() if r.headers.get("content-type", "").startswith("application/json") else {})

    def tasks(self):
        return self.s.get(f"{self.url}/tasks", timeout=60).json()

    def delete(self, tid):
        for _ in range(30):
            r = self.s.delete(f"{self.url}/task/{tid}", timeout=60)
            if r.status_code != 409:
                return r.status_code
            time.sleep(2)
        return 409


def _proc_stats():
    import psutil
    procs = [p for p in psutil.process_iter(["name", "memory_info"]) if (p.info["name"] or "").lower().startswith("python")]
    return len(procs), sum(p.info["memory_info"].rss for p in procs if p.info["memory_info"]) / 1e9, \
        psutil.virtual_memory().used / 1e9


def wait(client, ids, timeout, log):
    """Espera as tarefas terminarem; devolve {id: tarefa} e picos de processos/memória."""
    t0, peak_procs, peak_rss, peak_used = time.time(), 0, 0.0, 0.0
    while True:
        n, rss, used = _proc_stats()
        peak_procs, peak_rss, peak_used = max(peak_procs, n), max(peak_rss, rss), max(peak_used, used)
        all_tasks = client.tasks()
        current = {i: all_tasks.get(i, {}) for i in ids}
        if all(t.get("completed") or t.get("error") for t in current.values()):
            break
        if time.time() - t0 > timeout:
            log(f"[!] tempo esgotado ({timeout}s): {sum(1 for t in current.values() if not (t.get('completed') or t.get('error')))} presas")
            break
        time.sleep(3)
    return current, {"segundos": round(time.time() - t0), "pico_processos_python": peak_procs,
                     "pico_rss_python_gb": round(peak_rss, 1), "pico_ram_maquina_gb": round(peak_used, 1)}


def check(task, expected_cpfs):
    """Invariantes de falha fechada para uma tarefa terminada."""
    problems = []
    status = task.get("status", "")
    if not (task.get("completed") or task.get("error")):
        problems.append("não terminou")
    elif not task.get("error") and status not in FINAL_OK:
        problems.append(f"estado final inesperado: {status}")
    found = {p["id"]: p.get("quantidade", 0) for p in task.get("pii_found") or []}
    if status == "Concluído" and expected_cpfs and found.get("cpf", 0) < expected_cpfs:
        problems.append(f"CONCLUÍDO com CPF a menos ({found.get('cpf', 0)}/{expected_cpfs})")
    return problems


def scenario_docs(name, n, pages):
    docs = pii_corpus.generate(max(n * 2, 12), 77)
    if name == "simultaneos":
        out = []
        for i in range(n):
            pair = docs[2 * i: 2 * i + 2]
            out.append((f"stress_simultaneo_{i}.pdf", raster_pdf([d.text for d in pair], "padrao", i * 10),
                        sum(1 for d in pair for t, _ in d.gabarito if t == "cpf")))
        return out
    if name == "grande":
        big = (docs * (pages // len(docs) + 1))[:pages]
        return [("stress_grande.pdf", raster_pdf([d.text for d in big], "padrao", 500),
                 len({v for d in big for t, v in d.gabarito if t == "cpf"}))]
    if name == "pessima":
        sel = docs[:4]
        return [("stress_pessima.pdf", raster_pdf([d.text for d in sel], "pessima", 900),
                 sum(1 for d in sel for t, _ in d.gabarito if t == "cpf"))]
    return [(fname, data, 0) for fname, data in hostile_files().items()]


def run(url, scenarios, n, pages, timeout, token=None, log=print):
    client = Client(url, token)
    report = {}
    for sc in scenarios:
        files = scenario_docs(sc, n, pages)
        log(f"== {sc}: {len(files)} arquivo(s)")
        ids, rejected, expected = [], {}, {}
        for fname, data, n_cpf in files:  # todos de uma vez: o app inicia cada um ao receber
            code, body = client.upload(fname, data)
            if code == 200 and body.get("task_id"):
                ids.append(body["task_id"])
                expected[body["task_id"]] = (fname, n_cpf)
            else:
                rejected[fname] = code
        final, stats = wait(client, ids, timeout, log) if ids else ({}, {})
        rows = []
        for tid, task in final.items():
            fname, n_cpf = expected[tid]
            rows.append({"arquivo": fname, "estado": task.get("status"), "erro": bool(task.get("error")),
                         "cpfs_esperados": n_cpf,
                         "cpfs_achados": next((p.get("quantidade") for p in task.get("pii_found") or [] if p["id"] == "cpf"), 0),
                         "alertas": len(task.get("alerts") or []), "problemas": check(task, n_cpf)})
        report[sc] = {"recusados_no_upload": rejected, "tarefas": rows, **stats}
        log(json.dumps(report[sc], ensure_ascii=False, indent=1))
        for tid in ids:
            client.delete(tid)
    return report


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--url", default="http://127.0.0.1:8001")
    ap.add_argument("--scenarios", default="simultaneos,grande,pessima,hostis")
    ap.add_argument("--n", type=int, default=8, help="uploads simultâneos")
    ap.add_argument("--pages", type=int, default=40, help="páginas do documento grande")
    ap.add_argument("--timeout", type=int, default=3600)
    ap.add_argument("--out")
    args = ap.parse_args(argv)
    report = run(args.url, [s for s in args.scenarios.split(",") if s], args.n, args.pages, args.timeout,
                 token=os.getenv("API_TOKEN") or None)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
    bad = [p for sc in report.values() for t in sc["tarefas"] for p in t["problemas"]]
    print(f"\nProblemas de invariante: {len(bad)}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())

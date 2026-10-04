# SPDX-License-Identifier: AGPL-3.0-or-later
"""CLI de main.py (--input/--output) e portabilidade (sem caminhos fixos)."""
import os
import re
import runpy
import sys

import pytest

import main
from sentry_testkit import make_text_pdf


class FakeApp:
    created = []
    review_for = set()
    fail_for = set()

    def __init__(self, pdf_path, output_dir=None, final_dir=None):
        self.pdf = pdf_path
        FakeApp.created.append((os.path.basename(pdf_path), output_dir, final_dir))

    def run(self):
        if os.path.basename(self.pdf) in FakeApp.fail_for:
            raise RuntimeError("falhou")

    def final_state(self):
        review = os.path.basename(self.pdf) in FakeApp.review_for
        return {"status": "Requer revisão" if review else "Concluído", "needs_review": review,
                "alerts": ["Pág 1: revisar"] if review else []}


@pytest.fixture()
def fake_app(monkeypatch):
    FakeApp.created, FakeApp.review_for, FakeApp.fail_for = [], set(), set()
    monkeypatch.setattr(main, "SentryApp", FakeApp)
    return FakeApp


def test_collect_pdfs_file_folder_and_missing(tmp_path):
    a = make_text_pdf(tmp_path / "b.pdf")
    make_text_pdf(tmp_path / "a.pdf")
    (tmp_path / "x.txt").write_text("nao e pdf")
    assert main.collect_pdfs(a) == [a]
    assert [os.path.basename(p) for p in main.collect_pdfs(str(tmp_path))] == ["a.pdf", "b.pdf"]
    assert main.collect_pdfs(str(tmp_path / "nada")) == []


def test_cli_processes_folder_and_maps_output_dirs(tmp_path, fake_app, capsys):
    make_text_pdf(tmp_path / "in" / "a.pdf")
    make_text_pdf(tmp_path / "in" / "b.pdf")
    out = tmp_path / "saida"
    assert main.cli(["--input", str(tmp_path / "in"), "--output", str(out)]) == 0
    assert fake_app.created == [("a.pdf", str(out / "work"), str(out)), ("b.pdf", str(out / "work"), str(out))]
    assert "[1/2] PROCESSANDO: a.pdf" in capsys.readouterr().out


def test_cli_without_output_uses_defaults(tmp_path, fake_app):
    pdf = make_text_pdf(tmp_path / "a.pdf")
    assert main.cli(["-i", pdf]) == 0
    assert fake_app.created == [("a.pdf", None, None)]


def test_cli_exit_codes(tmp_path, fake_app, capsys):
    make_text_pdf(tmp_path / "ok.pdf")
    pdf_review = make_text_pdf(tmp_path / "rev.pdf")
    pdf_fail = make_text_pdf(tmp_path / "bad.pdf")
    assert main.cli(["-i", str(tmp_path / "vazio")]) == 1
    assert "Nenhum PDF" in capsys.readouterr().err
    fake_app.review_for = {"rev.pdf"}
    assert main.cli(["-i", pdf_review]) == 3
    assert "REQUER REVISÃO" in capsys.readouterr().out
    fake_app.fail_for = {"bad.pdf"}
    assert main.cli(["-i", pdf_fail]) == 1
    assert main.cli(["-i", str(tmp_path)]) == 1   # erro em um arquivo domina o codigo de saida


def test_cli_requires_input_argument(capsys):
    with pytest.raises(SystemExit) as e:
        main.cli([])
    assert e.value.code == 2


def test_cli_end_to_end_on_text_pdf_without_models(tmp_path, monkeypatch):
    """CLI real (sem fakes de pipeline) num PDF com texto nativo, sem Tesseract/YOLO/IA: falha fechada."""
    make_text_pdf(tmp_path / "in" / "doc.pdf", text="sem dados")
    monkeypatch.setenv("BASE_DPI", "40")
    monkeypatch.setenv("VERIFY_OCR", "0")
    monkeypatch.setenv("TESSERACT_PATH", str(tmp_path / "nao-existe"))
    monkeypatch.setenv("YOLO_MODEL_PATH", str(tmp_path / "sem_modelo.pt"))
    monkeypatch.setattr(main.OCREngine, "get_grounding_map", lambda self, p, psm=3: ("", []))
    monkeypatch.setattr(main.AddressRedactor, "run_discovery",
                        lambda self, paths: self.failed_pages.update({1: "IA indisponivel"}))
    code = main.cli(["--input", str(tmp_path / "in"), "--output", str(tmp_path / "out")])
    assert code == 3   # IA falhou -> requer revisao (nunca 'Concluido' silencioso)
    assert (tmp_path / "out" / "doc_TARJADO_FINAL.pdf").exists()
    assert (tmp_path / "out" / "work" / "doc" / "process_log.log").exists()


def test_main_module_entrypoint_exits_with_cli_code(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["main.py", "--input", str(tmp_path / "nada")])
    with pytest.raises(SystemExit) as e:
        runpy.run_path(main.__file__, run_name="__main__")
    assert e.value.code == 1


def test_no_hardcoded_user_paths_in_source():
    """Portabilidade: nenhum caminho absoluto de maquina/usuario nos modulos (usa APP_*/env/relativos)."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    files = [os.path.join(root, "main.py"), os.path.join(root, "app_service.py"), os.path.join(root, "gatekeeper.py")]
    for dirpath, _, names in os.walk(os.path.join(root, "utils")):
        files += [os.path.join(dirpath, n) for n in names if n.endswith(".py")]
    pattern = re.compile(r"[A-Za-z]:\\\\?(?:TARJADOR|Users)|/home/|/Users/", re.IGNORECASE)
    for path in files:
        text = open(path, encoding="utf-8").read()
        assert not pattern.search(text), f"caminho fixo em {os.path.basename(path)}"

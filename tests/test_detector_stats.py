# SPDX-License-Identifier: AGPL-3.0-or-later
"""Retorno do revisor por detector: só contagens, ligado à tarefa, e nunca reduz proteção sozinho."""
import json

from utils.decisions import detector_stats
from utils.decisions.learning import LearningStore


def red(page, x, label=None, source="AI_Engine", width=1000):
    return {"page": page, "coords": [x, 100, x + 80, 120], "label": label, "source": source, "image_width": width}


def test_compare_counts_kept_removed_added():
    suggested = [red(1, 10, "CPF"), red(1, 200, "Telefone"), red(2, 10, "Telefone"), red(2, 300)]
    final = [red(1, 12, "CPF"), red(2, 10, "Telefone"), red(2, 500, None, "Manual")]
    counts = detector_stats.compare(suggested, final)
    assert counts["CPF"] == {"mantidas": 1, "removidas": 0, "adicionadas": 0}
    assert counts["Telefone"] == {"mantidas": 1, "removidas": 1, "adicionadas": 0}
    assert counts[detector_stats.NO_LABEL] == {"mantidas": 0, "removidas": 1, "adicionadas": 0}
    assert counts[detector_stats.MANUAL] == {"mantidas": 0, "removidas": 0, "adicionadas": 1}


def test_compare_rescales_editor_boxes_to_the_ai_image_width():
    suggested = [red(1, 100, "CPF", width=2000)]
    final = [{"page": 1, "coords": [50, 50, 90, 60], "label": "CPF", "image_width": 1000}]  # metade da escala
    assert detector_stats.compare(suggested, final)["CPF"]["mantidas"] == 1


def _task_dir(tmp_path, name="relatorio_abc"):
    out = tmp_path / "output" / name
    out.mkdir(parents=True)
    (out / "redactions_metadata.json").write_text(json.dumps([red(1, 10, "CPF"), red(1, 200, "Telefone")]),
                                                  encoding="utf-8")
    return out


def test_capture_is_opt_in_and_stores_only_counts(tmp_path, monkeypatch):
    out, root = _task_dir(tmp_path), tmp_path / "learning"
    monkeypatch.delenv("LEARNING_ENABLED", raising=False)
    assert detector_stats.capture(str(out), [red(1, 10, "CPF")], root=str(root)) == {}
    assert not (root / detector_stats.STATS_FILE).exists()

    monkeypatch.setenv("LEARNING_ENABLED", "1")
    detector_stats.capture(str(out), [red(1, 10, "CPF")], root=str(root))
    rows = [json.loads(line) for line in (root / detector_stats.STATS_FILE).read_text(encoding="utf-8").splitlines()]
    assert rows[0]["task"] == "relatorio_abc"
    assert set(rows[0]) == {"task", "at", "counts"}       # nada de texto, nada de coordenadas
    assert rows[0]["counts"]["Telefone"]["removidas"] == 1


def test_capture_never_breaks_finalization(tmp_path, monkeypatch):
    monkeypatch.setenv("LEARNING_ENABLED", "1")
    out = _task_dir(tmp_path)
    (out / "redactions_metadata.json").write_text("{quebrado", encoding="utf-8")
    assert detector_stats.capture(str(out), [red(1, 10)], root=str(tmp_path / "l")) == {}


def test_deleting_the_task_deletes_its_counts_and_purge_removes_the_file(tmp_path, monkeypatch):
    monkeypatch.setenv("LEARNING_ENABLED", "1")
    root = tmp_path / "learning"
    store = LearningStore(str(root))
    detector_stats.capture(str(_task_dir(tmp_path, "a")), [], root=str(root))
    detector_stats.capture(str(_task_dir(tmp_path, "b")), [], root=str(root))
    assert store.remove_task("a") == 1
    assert detector_stats.summary(str(root))["tarefas"] == 1
    store.purge()
    assert not (root / detector_stats.STATS_FILE).exists()


def test_summary_suggests_but_only_with_enough_data(tmp_path, monkeypatch):
    monkeypatch.setenv("LEARNING_ENABLED", "1")
    root = tmp_path / "learning"
    out = _task_dir(tmp_path)
    detector_stats.capture(str(out), [red(1, 10, "CPF")], root=str(root))     # telefone removido 1 vez
    tel = detector_stats.summary(str(root))["detectores"]["Telefone"]
    assert tel["precisao_observada"] == 0.0
    assert any("poucos dados" in s for s in tel["sugestoes"])                  # 1 caso não basta para sugerir
    for _ in range(25):
        detector_stats.capture(str(out), [red(1, 10, "CPF"), red(1, 600, "Telefone", "Manual")], root=str(root))
    tel = detector_stats.summary(str(root))["detectores"]["Telefone"]
    assert any("apaga muitas" in s for s in tel["sugestoes"])
    assert any("acrescenta muitas" in s for s in tel["sugestoes"])


def test_cli_detectores(tmp_path, capsys):
    from utils.decisions.cli import main
    assert main(["detectores", "--dir", str(tmp_path / "vazio")]) == 0
    assert json.loads(capsys.readouterr().out) == {"tarefas": 0, "detectores": {}}

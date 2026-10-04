# SPDX-License-Identifier: AGPL-3.0-or-later
"""scripts/check_versions.py: versão igual em pyproject, CITATION e CHANGELOG (e na tag da Release)."""
import importlib.util
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_spec = importlib.util.spec_from_file_location("check_versions", os.path.join(ROOT, "scripts", "check_versions.py"))
cv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cv)

PY = '[project]\nname = "x"\nversion = "1.2.3"\n'
CIT = "cff-version: 1.2.0\nversion: 1.2.3\n"
LOG = "# Changelog\n\n## [Não publicado]\n\n## [1.2.3] - 2026-10-04\n\n## [1.2.2]\n"


def test_consistent_versions_pass():
    assert cv.check(PY, CIT, LOG) == []
    assert cv.check(PY, CIT, LOG, tag="v1.2.3") == []


def test_divergences_are_reported():
    assert any("CITATION" in e for e in cv.check(PY, CIT.replace("1.2.3", "1.2.2"), LOG))
    assert any("CHANGELOG" in e for e in cv.check(PY, CIT, LOG.replace("## [1.2.3] - 2026-10-04\n\n", "")))
    assert any("tag" in e for e in cv.check(PY, CIT, LOG, tag="v1.2.4"))
    assert cv.check("[project]\n", CIT, LOG) == ["pyproject.toml: campo version não encontrado"]


def test_repository_versions_are_consistent():
    assert cv.main([]) == 0

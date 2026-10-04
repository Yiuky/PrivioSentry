#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Confere se a versão é a mesma em pyproject.toml, CITATION.cff e no CHANGELOG.md.

Uso:
  python scripts/check_versions.py                 # pyproject == CITATION; CHANGELOG tem a seção da versão
  python scripts/check_versions.py --tag v5.1.0    # também confere a tag (usado no workflow de Release)

Código de saída 1 se algo divergir.
"""
from __future__ import annotations

import argparse
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEMVER = r"\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?"


def _read(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as f:
        return f.read()


def pyproject_version(text):
    m = re.search(r'^version\s*=\s*"(%s)"' % SEMVER, text, re.M)
    return m.group(1) if m else None


def citation_version(text):
    m = re.search(r"^version:\s*['\"]?(%s)['\"]?\s*$" % SEMVER, text, re.M)
    return m.group(1) if m else None


def changelog_versions(text):
    """Versões com seção própria no CHANGELOG, na ordem em que aparecem (a mais nova primeiro)."""
    return re.findall(r"^## \[(%s)\]" % SEMVER, text, re.M)


def check(pyproject, citation, changelog, tag=None):
    errors = []
    version = pyproject_version(pyproject)
    if not version:
        return ["pyproject.toml: campo version não encontrado"]
    cit = citation_version(citation)
    if cit != version:
        errors.append("CITATION.cff: version %s != pyproject.toml %s" % (cit, version))
    versions = changelog_versions(changelog)
    if not versions:
        errors.append("CHANGELOG.md: nenhuma seção '## [X.Y.Z]'")
    elif versions[0] != version:
        errors.append("CHANGELOG.md: a seção mais nova é %s, esperado %s" % (versions[0], version))
    if tag is not None and tag.lstrip("v") != version:
        errors.append("tag %s não corresponde à versão %s" % (tag, version))
    return errors


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--tag", help="tag git a conferir (ex.: v5.1.0)")
    args = ap.parse_args(argv)
    errors = check(_read("pyproject.toml"), _read("CITATION.cff"), _read("CHANGELOG.md"), args.tag)
    if errors:
        for e in errors:
            print("ERRO: " + e)
        return 1
    print("Versão consistente: %s" % pyproject_version(_read("pyproject.toml")))
    return 0


if __name__ == "__main__":
    sys.exit(main())

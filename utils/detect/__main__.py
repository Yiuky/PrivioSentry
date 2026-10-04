# SPDX-License-Identifier: AGPL-3.0-or-later
"""python -m utils.detect --markdown   escreve docs/catalogo-pii.md a partir do catálogo
python -m utils.detect --json       imprime catálogo e perfis em JSON (o mesmo da API /policy/*)"""
import argparse
import json
import os
import sys

from . import catalog, profiles

DOC_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                        "docs", "catalogo-pii.md")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m utils.detect")
    ap.add_argument("--markdown", action="store_true", help=f"regenera {DOC_PATH}")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    if args.markdown:
        with open(DOC_PATH, "w", encoding="utf-8", newline="\n") as f:
            f.write(catalog.to_markdown() + "\n")
        print(f"escrito: {DOC_PATH}")
    if args.json or not args.markdown:
        print(json.dumps({"catalogo": [t.to_dict() for t in catalog.CATALOG], "perfis": profiles.describe_all()},
                         ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

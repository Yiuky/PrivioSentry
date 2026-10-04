# SPDX-License-Identifier: AGPL-3.0-or-later
"""Linha de comando do automelhoramento.

    python -m utils.decisions status     perfil ativo, histórico e quantidade de exemplos
    python -m utils.decisions train      treina um candidato; vira ativo só se passar no portão
    python -m utils.decisions rollback   volta ao perfil aprovado anterior
    python -m utils.decisions purge      apaga exemplos, cache e perfis desta máquina

O treino precisa do Laya instalado (pip install -e ".[laya]"). Código de saída: 0 ok, 2 reprovado.
"""
import argparse
import json
import sys

from .learning import GATE, LearningStore, train


def _print(obj):
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m utils.decisions", description=__doc__.splitlines()[0])
    ap.add_argument("command", choices=["status", "train", "rollback", "purge"])
    ap.add_argument("--dir", help="pasta do aprendizado (padrão: PRIVIO_LEARNING_DIR ou ./learning)")
    ap.add_argument("--synthetic", type=int, default=240, help="exemplos sintéticos no treino (padrão 240)")
    ap.add_argument("--yes", action="store_true", help="confirma o purge sem perguntar")
    args = ap.parse_args(argv)
    store = LearningStore(args.dir)

    if args.command == "status":
        examples = store.examples()
        _print({"dir": store.root, "manifest": store.manifest(), "gate": GATE,
                "examples": {"total": len(examples), "review": sum(e.get("source") == "review" for e in examples)}})
        return 0
    if args.command == "rollback":
        _print({"active": store.rollback()})
        return 0
    if args.command == "purge":
        if not args.yes:
            print("Isto apaga todos os exemplos e perfis desta máquina. Rode de novo com --yes para confirmar.")
            return 1
        store.purge()
        print("Aprendizado apagado.")
        return 0

    from .engine import LayaEngine
    engine = LayaEngine()
    report = train(store, engine.features, model=engine.model_id, n_synthetic=args.synthetic)
    _print(report)
    return 0 if report["approved"] else 2


if __name__ == "__main__":
    sys.exit(main())

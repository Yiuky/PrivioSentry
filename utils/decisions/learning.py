# SPDX-License-Identifier: AGPL-3.0-or-later
"""Automelhoramento: exemplos rotulados -> treino -> portão de qualidade -> perfil versionado.

Ciclo (comandos em utils/decisions/cli.py):

  1. coleta   exemplos sintéticos (seed) + correções do revisor (feedback.py, só com LEARNING_ENABLED=1)
  2. treino   o Laya fica congelado; treina-se uma regressão logística sobre as respostas dele às
              perguntas de questions.py, e escolhem-se os limiares de decisão numa parte separada
  3. portão   o candidato é medido no conjunto FIXO de avaliação (synthetic.holdout). Só vira o
              perfil ativo se atingir os mínimos e não piorar o perfil ativo
  4. versões  cada perfil é salvo (v1, v2...); `rollback` volta ao anterior

Privacidade: os exemplos ficam só nesta máquina, em PRIVIO_LEARNING_DIR (padrão ./learning, fora do
git), com o texto já minimizado (questions.normalize_state). `purge` apaga tudo.
"""
import hashlib
import json
import math
import os
import random
import tempfile
from datetime import datetime
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from .engine import Profile, logit
from .policy import Thresholds
from .questions import FEATURE_IDS, QUESTIONS_VERSION, normalize_state
from . import synthetic

# Portão de qualidade. Ajuste aqui, em um só lugar. Os mínimos valem para o conjunto REALISTA
# (synthetic.REALISTIC, escrito à mão e fora do treino); o conjunto gerado (holdout) só confirma o básico.
GATE = {
    "min_auc": 0.85,                 # separa residencial de não residencial (realista)
    "min_precision_personal": 0.85,  # quando afirma "residencial", acerta (realista; custo do erro: tarja a mais)
    "min_npv": 0.85,                 # quando afirma "não residencial", acerta (realista; senão suprimiria revisões)
    "min_auc_holdout": 0.90,         # sanidade no conjunto gerado
    "max_auc_drop": 0.01,            # não pode piorar o perfil ativo (AUC realista)
}
REVIEW_WEIGHT = 3.0  # uma correção real do revisor vale mais que um exemplo sintético

FeatureFn = Callable[[Sequence[str]], List[List[float]]]

# Pasta padrão: dentro do projeto (não da pasta de onde o programa foi aberto), coberta pelo .gitignore.
PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _now():
    return datetime.now().isoformat(timespec="seconds")


def _atomic_write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def _key(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:20]


# ------------------------------------------------------------------------------------------- store
class LearningStore:
    """Pasta local com examples.jsonl, cache de características, perfis versionados e manifest.json."""

    def __init__(self, root=None):
        self.root = os.path.abspath(root or os.getenv("PRIVIO_LEARNING_DIR") or os.path.join(PROJECT_DIR, "learning"))
        self.examples_path = os.path.join(self.root, "examples.jsonl")
        self.cache_path = os.path.join(self.root, "features_cache.json")
        self.profiles_dir = os.path.join(self.root, "profiles")
        self.manifest_path = os.path.join(self.root, "manifest.json")

    # exemplos ---------------------------------------------------------------------------------
    def add_examples(self, rows: Sequence[Dict]) -> int:
        """rows: {"text", "label" (0/1), "source", "task"?}. O texto é minimizado antes de gravar.

        "task" liga o exemplo à tarefa de origem: quando a tarefa é apagada (ou expira pela retenção),
        os exemplos dela também são apagados (remove_task)."""
        os.makedirs(self.root, exist_ok=True)
        n = 0
        with open(self.examples_path, "a", encoding="utf-8") as f:
            for r in rows:
                text = normalize_state(r.get("text"))
                if not text or r.get("label") not in (0, 1):
                    continue
                row = {"text": text, "label": int(r["label"]), "source": r.get("source", "import"), "at": _now()}
                if r.get("task"):
                    row["task"] = str(r["task"])
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
                n += 1
        return n

    def examples(self) -> List[Dict]:
        """Exemplos únicos por texto; o rótulo mais recente vence (o revisor pode mudar de ideia)."""
        if not os.path.exists(self.examples_path):
            return []
        latest = {}
        with open(self.examples_path, encoding="utf-8") as f:
            for line in f:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                latest[row["text"]] = row
        return list(latest.values())

    def remove_task(self, task) -> int:
        """Apaga os exemplos vindos de uma tarefa (direito de eliminação). Devolve quantos removeu."""
        if not task or not os.path.exists(self.examples_path):
            return 0
        kept, removed = [], 0
        with open(self.examples_path, encoding="utf-8") as f:
            for line in f:
                try:
                    if json.loads(line).get("task") == str(task):
                        removed += 1
                        continue
                except ValueError:
                    pass
                kept.append(line)
        if removed:
            fd, tmp = tempfile.mkstemp(dir=self.root, suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.writelines(kept)
            os.replace(tmp, self.examples_path)
        return removed

    # perfis -------------------------------------------------------------------------------------
    def manifest(self) -> Dict:
        try:
            with open(self.manifest_path, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return {"active": None, "history": []}

    def _profile_path(self, version):
        return os.path.join(self.profiles_dir, f"{version}.json")

    def load_profile(self, version) -> Optional[Profile]:
        try:
            with open(self._profile_path(version), encoding="utf-8") as f:
                return Profile.from_dict(json.load(f))
        except (OSError, ValueError, TypeError):
            return None

    def active_profile(self, model="") -> Optional[Profile]:
        """Perfil ativo, se for desta versão de perguntas e deste modelo. Senão None (zero-shot)."""
        version = self.manifest().get("active")
        profile = self.load_profile(version) if version else None
        if profile is None or profile.questions_version != QUESTIONS_VERSION:
            return None
        if model and profile.model and profile.model != model:
            return None
        return profile

    def save_profile(self, profile: Profile, activate: bool) -> str:
        manifest = self.manifest()
        profile.version = f"v{len(manifest['history']) + 1}"
        _atomic_write(self._profile_path(profile.version), profile.to_dict())
        manifest["history"].append({"version": profile.version, "at": _now(), "approved": profile.approved,
                                    "auc": profile.metrics.get("auc")})
        if activate:
            manifest["active"] = profile.version
        _atomic_write(self.manifest_path, manifest)
        return profile.version

    def rollback(self) -> Optional[str]:
        """Ativa o perfil aprovado anterior ao ativo (ou nenhum, voltando ao zero-shot)."""
        manifest = self.manifest()
        approved = [h["version"] for h in manifest["history"] if h.get("approved")]
        active = manifest.get("active")
        previous = None
        if active in approved:
            idx = approved.index(active)
            previous = approved[idx - 1] if idx > 0 else None
        manifest["active"] = previous
        _atomic_write(self.manifest_path, manifest)
        return previous

    def purge(self):
        """
        Apaga exemplos, cache e perfis (direito de eliminação / fim do uso). Só remove o que o próprio
        aprendizado cria: se PRIVIO_LEARNING_DIR apontar por engano para uma pasta com outros arquivos,
        eles ficam intactos (e a pasta também).
        """
        for path in (self.examples_path, self.cache_path, self.manifest_path):
            if os.path.isfile(path):
                os.remove(path)
        if os.path.isdir(self.root):  # temporários de gravações interrompidas
            for name in os.listdir(self.root):
                if name.endswith(".tmp"):
                    os.remove(os.path.join(self.root, name))
        if os.path.isdir(self.profiles_dir):
            for name in os.listdir(self.profiles_dir):
                if name.startswith("v") and name.endswith(".json"):
                    os.remove(os.path.join(self.profiles_dir, name))
            if not os.listdir(self.profiles_dir):
                os.rmdir(self.profiles_dir)
        if os.path.isdir(self.root) and not os.listdir(self.root):
            os.rmdir(self.root)

    # cache de características (o modelo é lento perto do treino) ----------------------------------
    def cached_features(self, texts: Sequence[str], feature_fn: FeatureFn, model: str) -> List[List[float]]:
        try:
            with open(self.cache_path, encoding="utf-8") as f:
                cache = json.load(f)
        except (OSError, ValueError):
            cache = {}
        tag = f"{model}|q{QUESTIONS_VERSION}|"
        missing = sorted({t for t in texts if tag + _key(t) not in cache})
        if missing:
            for text, feats in zip(missing, feature_fn(missing)):
                cache[tag + _key(text)] = feats
            _atomic_write(self.cache_path, cache)
        return [cache[tag + _key(t)] for t in texts]


# ------------------------------------------------------------------------------------- treino
def fit_logistic(X: List[List[float]], y: List[int], w: List[float], l2=1.0, iterations=50):
    """
    Regressão logística ponderada, com regularização L2, pelo método de Newton (IRLS): converge em poucas
    iterações e não depende de taxa de aprendizado. As características são padronizadas para o treino e a
    padronização é embutida nos pesos devolvidos, então o perfil continua sendo só (pesos, viés).
    """
    import numpy as np  # já vem com as dependências do projeto
    X_ = np.asarray(X, dtype=float)
    y_ = np.asarray(y, dtype=float)
    sw = np.asarray(w, dtype=float)
    sw = sw * (len(sw) / sw.sum())
    mu, sd = X_.mean(axis=0), X_.std(axis=0) + 1e-6
    Z = np.c_[(X_ - mu) / sd, np.ones(len(X_))]
    beta = np.zeros(Z.shape[1])
    reg = l2 * np.eye(Z.shape[1])
    reg[-1, -1] = 0.0  # não regulariza o viés
    for _ in range(iterations):
        p = 1.0 / (1.0 + np.exp(-np.clip(Z @ beta, -30, 30)))
        grad = Z.T @ (sw * (p - y_)) + reg @ beta
        hess = Z.T @ (Z * (sw * p * (1 - p))[:, None]) + reg
        step = np.linalg.solve(hess, grad)
        beta -= step
        if np.abs(step).max() < 1e-8:
            break
    weights = beta[:-1] / sd
    bias = beta[-1] - float(np.sum(beta[:-1] * mu / sd))
    return [float(v) for v in weights], float(bias)


def auc(scores: Sequence[float], labels: Sequence[int]) -> float:
    pos = [s for s, l in zip(scores, labels) if l == 1]
    neg = [s for s, l in zip(scores, labels) if l == 0]
    if not pos or not neg:
        return 0.0
    wins = sum(1.0 if p > n else 0.5 if p == n else 0.0 for p in pos for n in neg)
    return wins / (len(pos) * len(neg))


def choose_thresholds(scores, labels, min_precision=0.95, min_npv=0.97) -> Thresholds:
    """Menor corte "residencial" com precisão >= min_precision; maior corte "não" com NPV >= min_npv."""
    pairs = sorted(zip(scores, labels))
    personal = 0.99
    for t in sorted(set(scores)):
        claimed = [l for s, l in pairs if s >= t]
        if claimed and sum(claimed) / len(claimed) >= min_precision:
            personal = t
            break
    not_personal = 0.01
    for t in sorted(set(scores), reverse=True):
        claimed = [l for s, l in pairs if s <= t]
        if claimed and (len(claimed) - sum(claimed)) / len(claimed) >= min_npv and t < personal:
            not_personal = t
            break
    # Arredonda a favor da faixa: o corte "residencial" para baixo e o "não" para cima, para que o valor
    # gravado no perfil ainda inclua a pontuação que o definiu.
    return Thresholds(personal=math.floor(personal * 1e4) / 1e4, not_personal=math.ceil(not_personal * 1e4) / 1e4)


def evaluate(profile: Profile, X, y) -> Dict:
    scores = [profile.probability(x) for x in X]
    t = profile.thresholds
    said_yes = [l for s, l in zip(scores, y) if s >= t.personal]
    said_no = [l for s, l in zip(scores, y) if s <= t.not_personal]
    return {
        "n": len(y),
        "auc": round(auc(scores, y), 4),
        "precision_personal": round(sum(said_yes) / len(said_yes), 4) if said_yes else 0.0,
        "npv": round((len(said_no) - sum(said_no)) / len(said_no), 4) if said_no else 0.0,
        "coverage": round((len(said_yes) + len(said_no)) / len(y), 4) if y else 0.0,
        "uncertain_rate": round(1 - (len(said_yes) + len(said_no)) / len(y), 4) if y else 0.0,
    }


def gate(metrics: Dict, active: Optional[Profile], holdout_metrics: Optional[Dict] = None) -> List[str]:
    """Motivos de reprovação (lista vazia = aprovado). metrics = conjunto realista."""
    reasons = []
    if metrics["auc"] < GATE["min_auc"]:
        reasons.append(f"AUC realista {metrics['auc']} < {GATE['min_auc']}")
    if metrics["precision_personal"] < GATE["min_precision_personal"]:
        reasons.append(f"precisão 'residencial' {metrics['precision_personal']} < {GATE['min_precision_personal']}")
    if metrics["npv"] < GATE["min_npv"]:
        reasons.append(f"NPV {metrics['npv']} < {GATE['min_npv']}")
    if holdout_metrics is not None and holdout_metrics["auc"] < GATE["min_auc_holdout"]:
        reasons.append(f"AUC no conjunto gerado {holdout_metrics['auc']} < {GATE['min_auc_holdout']}")
    if active is not None and active.approved:
        prev = active.metrics.get("auc", 0.0)
        if metrics["auc"] < prev - GATE["max_auc_drop"]:
            reasons.append(f"AUC realista {metrics['auc']} pior que o perfil ativo ({prev})")
    return reasons


def train(store: LearningStore, feature_fn: FeatureFn, model: str, n_synthetic=240, seed=0) -> Dict:
    """Treina um candidato, avalia no conjunto fixo, aplica o portão e salva. Devolve um relatório."""
    rows: List[Tuple[str, int, float]] = [(normalize_state(t), l, 1.0) for t, l in synthetic.generate(n_synthetic)]
    for ex in store.examples():
        rows.append((ex["text"], ex["label"], REVIEW_WEIGHT if ex.get("source") == "review" else 1.0))
    rng = random.Random(seed)
    rng.shuffle(rows)
    cut = max(1, int(len(rows) * 0.75))
    fit_rows, tune_rows = rows[:cut], rows[cut:]

    X_fit = store.cached_features([r[0] for r in fit_rows], feature_fn, model)
    weights, bias = fit_logistic(X_fit, [r[1] for r in fit_rows], [r[2] for r in fit_rows])
    candidate = Profile(weights=[round(v, 5) for v in weights], bias=round(bias, 5), model=model,
                        questions_version=QUESTIONS_VERSION)
    X_tune = store.cached_features([r[0] for r in tune_rows], feature_fn, model)
    candidate.thresholds = choose_thresholds([candidate.probability(x) for x in X_tune], [r[1] for r in tune_rows])

    def measure(rows_):
        X_ = store.cached_features([normalize_state(t) for t, _ in rows_], feature_fn, model)
        y_ = [l for _, l in rows_]
        return evaluate(candidate, X_, y_), evaluate(Profile(model=model), X_, y_)

    metrics, zero_shot = measure(synthetic.realistic())
    holdout_metrics, _ = measure(synthetic.holdout())
    active = store.active_profile(model=model)
    reasons = gate(metrics, active, holdout_metrics)
    candidate.approved = not reasons
    candidate.metrics = {**metrics, "zero_shot_auc": zero_shot["auc"], "holdout": holdout_metrics,
                         "trained_on": {"synthetic": n_synthetic, "examples": len(rows) - n_synthetic},
                         "rejected_because": reasons}
    version = store.save_profile(candidate, activate=candidate.approved)
    return {"version": version, "approved": candidate.approved, "reasons": reasons, "metrics": candidate.metrics,
            "thresholds": candidate.to_dict()["thresholds"], "features": FEATURE_IDS,
            "active": store.manifest().get("active")}


__all__ = ["LearningStore", "train", "evaluate", "gate", "choose_thresholds", "fit_logistic", "auc", "GATE", "logit"]

# SPDX-License-Identifier: AGPL-3.0-or-later
"""Motores de decisão.

    FeatureEngine  interface mínima: features(textos) -> lista de vetores (um valor por pergunta)
    LayaEngine     implementação com o Laya (pip install -e .[laya]); carrega o modelo só no 1º uso
    DecisionService  motor + perfil aprendido -> probabilidade calibrada de "endereço residencial"

Configuração (variáveis de ambiente, documentadas em docs/configuration.md):
    DECISION_ENGINE   off (padrão) | laya
    DECISION_MODE     shadow (padrão) | assist   -- ver utils/decisions/policy.py
    LAYA_MODEL        id no Hugging Face ou pasta local (padrão: convaiinnovations/laya-multilingual)
    LAYA_DEVICE       cpu (padrão) | cuda
    LAYA_REVISION     commit fixo do modelo; "reviewed" usa os commits revisados pelo próprio Laya
"""
import logging
import math
import os
from dataclasses import dataclass, field
from typing import List, Optional, Sequence

from .policy import Thresholds
from .questions import ADDRESS_QUESTIONS, FEATURE_IDS, PRIMARY_QUESTION, QUESTIONS_VERSION, normalize_state

logger = logging.getLogger("decisions")

DEFAULT_LAYA_MODEL = "convaiinnovations/laya-multilingual"
_EPS = 1e-4


def logit(p):
    p = min(max(float(p), _EPS), 1 - _EPS)
    return math.log(p / (1 - p))


def sigmoid(z):
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    e = math.exp(z)
    return e / (1.0 + e)


class LayaEngine:
    """Responde as perguntas de questions.py com o Laya, tudo local. Devolve logits por pergunta."""

    name = "laya"

    def __init__(self, model_id=None, device=None):
        self.model_id = model_id or os.getenv("LAYA_MODEL") or DEFAULT_LAYA_MODEL
        self.device = device or os.getenv("LAYA_DEVICE") or "cpu"
        self._agent = None

    def _load(self):
        if self._agent is None:
            try:
                # Redes com inspeção TLS (proxy corporativo): usa o repositório de certificados do sistema.
                import truststore
                truststore.inject_into_ssl()
            except ImportError:
                pass
            import laya  # dependência opcional: pip install -e ".[laya]"
            logger.info(f"[decisions] carregando {self.model_id} em {self.device}...")
            self._agent = laya.load(self.model_id, device=self.device)
        return self._agent

    def features(self, texts: Sequence[str]) -> List[List[float]]:
        if not texts:
            return []
        agent = self._load()
        results = agent.predict_batch([normalize_state(t) for t in texts], ADDRESS_QUESTIONS)
        return [[logit(r["answers"][qid]["noul"]) for qid in FEATURE_IDS] for r in results]


@dataclass
class Profile:
    """Cabeça treinada (regressão logística sobre as características) + limiares. Ver learning.py."""

    version: str = "zero-shot"
    weights: List[float] = field(default_factory=lambda: [1.0] + [0.0] * (len(FEATURE_IDS) - 1))
    bias: float = 0.0
    thresholds: Thresholds = Thresholds()
    approved: bool = False  # só perfis aprovados pelo portão de qualidade valem no modo assist
    questions_version: int = QUESTIONS_VERSION
    model: str = ""
    metrics: dict = field(default_factory=dict)

    def probability(self, feats: Sequence[float]) -> float:
        return sigmoid(sum(w * x for w, x in zip(self.weights, feats)) + self.bias)

    def to_dict(self):
        d = dict(self.__dict__)
        d["thresholds"] = {"personal": self.thresholds.personal, "not_personal": self.thresholds.not_personal}
        return d

    @classmethod
    def from_dict(cls, d):
        d = dict(d)
        t = d.pop("thresholds", {}) or {}
        known = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        return cls(thresholds=Thresholds(**t), **known)


@dataclass
class Decision:
    p_personal: Optional[float]
    features: List[float]
    profile_version: str
    engine: str


class DecisionService:
    """O que o pipeline usa: motor + perfil ativo + modo."""

    def __init__(self, engine, profile: Optional[Profile] = None, mode="shadow"):
        self.engine = engine
        self.profile = profile or Profile()
        requested = (mode or "shadow").lower()
        if requested == "assist" and not self.profile.approved:
            logger.warning("[decisions] DECISION_MODE=assist sem perfil aprovado: seguindo em modo sombra.")
            requested = "shadow"
        self.mode = requested if requested in ("shadow", "assist") else "shadow"

    @property
    def thresholds(self):
        return self.profile.thresholds

    def decide_many(self, texts: Sequence[str]) -> List[Decision]:
        """Nunca levanta exceção: falha do motor vira p_personal=None (a política trata)."""
        try:
            feats = self.engine.features(list(texts))
        except Exception as e:
            logger.error(f"[decisions] motor de decisão falhou: {e}")
            return [Decision(None, [], self.profile.version, self.engine.name) for _ in texts]
        return [Decision(self.profile.probability(f), f, self.profile.version, self.engine.name) for f in feats]


_SERVICE = None
_LOADED = False


def get_engine() -> Optional[DecisionService]:
    """Serviço configurado pelo ambiente, criado uma vez por processo. None = decisor desligado."""
    global _SERVICE, _LOADED
    if _LOADED:
        return _SERVICE
    _LOADED = True
    kind = (os.getenv("DECISION_ENGINE") or "off").strip().lower()
    if kind in ("", "off", "0", "none"):
        return None
    if kind != "laya":
        logger.error(f"[decisions] DECISION_ENGINE desconhecido: {kind!r}; decisor desligado.")
        return None
    from .learning import LearningStore
    engine = LayaEngine()
    profile = LearningStore().active_profile(model=engine.model_id)
    _SERVICE = DecisionService(engine, profile, os.getenv("DECISION_MODE", "shadow"))
    logger.info(f"[decisions] Laya ativo em modo {_SERVICE.mode} (perfil {_SERVICE.profile.version}).")
    return _SERVICE


def reset_engine():
    """Para testes e para recarregar depois de um treino."""
    global _SERVICE, _LOADED
    _SERVICE, _LOADED = None, False


__all__ = ["DecisionService", "Decision", "LayaEngine", "Profile", "get_engine", "reset_engine",
           "PRIMARY_QUESTION", "logit", "sigmoid"]

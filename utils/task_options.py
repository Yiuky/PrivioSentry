# SPDX-License-Identifier: AGPL-3.0-or-later
"""Opções escolhidas na interface para CADA documento: perfil de política, nomes e "documento de baixa qualidade".

O servidor valida tudo (a interface só ajuda): perfil desconhecido, nomes sem o detector instalado ou nomes num perfil
que não procura nomes são recusados com mensagem clara. Sem opções (cliente antigo), valem os padrões do .env.
Cada tarefa roda num PROCESSO próprio, que aplica as opções só para si (apply_to_environment): os outros documentos
da fila não são afetados.

    perfil           POLICY_PROFILE
    nomes            NER_ENGINE=gliner (exige pip install -e ".[nomes]")
    baixa_qualidade  segundo olhar (SECOND_LOOK=1) + leitura extra de OCR (OCR_EXTRA_ENGINE=rapidocr, se instalada)
"""
import importlib.util
import os

from utils import ocr_extra, second_look
from utils.detect import ner, profiles

NAME_TYPES = ("nome_pessoa", "filiacao")


class OptionsError(ValueError):
    pass


def _installed(package):
    return importlib.util.find_spec(package) is not None


def profile_asks_names(profile_id):
    return any(t in profiles.PROFILES[profile_id]["acoes"] for t in NAME_TYPES)


def defaults():
    """O que vale hoje pelo .env (o que um envio sem opções recebe)."""
    return {"perfil": profiles.active_profile_id(),
            "nomes": ner.enabled() and _installed("gliner"),
            "baixa_qualidade": second_look.enabled() or ocr_extra.enabled()}


def catalog():
    """Para a interface (GET /options): perfis, padrões, disponibilidade e o motivo de cada indisponibilidade."""
    names_ok = _installed("gliner")
    extra_ok = _installed("rapidocr")
    return {
        "perfis": [{"id": pid, "curto": p.get("curto") or p["nome"], "nome": p["nome"], "descricao": p["descricao"],
                    "pede_nomes": profile_asks_names(pid)}
                   for pid, p in profiles.PROFILES.items()],
        "padrao": defaults(),
        "disponivel": {"nomes": names_ok, "leitura_extra": extra_ok, "segundo_olhar": True},
        "motivos": {
            "nomes": "" if names_ok else "Detector de nomes não instalado (pip install -e \".[nomes]\").",
            "leitura_extra": "" if extra_ok else "Leitura extra de OCR não instalada (pip install -e \".[ocr-extra]\"); "
                                                 "a baixa qualidade usa só o segundo olhar.",
        },
    }


def _flag(value):
    if value is None or str(value).strip() == "":
        return None
    v = str(value).strip().lower()
    if v in ("1", "true", "sim", "on", "yes"):
        return True
    if v in ("0", "false", "nao", "não", "off", "no"):
        return False
    raise OptionsError(f"Valor inválido: {value!r} (use sim/não)")


def resolve(perfil=None, nomes=None, baixa_qualidade=None):
    """Valida e completa as opções de um envio. Levanta OptionsError (vira HTTP 400)."""
    base = defaults()
    profile_id = (perfil or "").strip().lower() or base["perfil"]
    if profile_id not in profiles.PROFILES:
        raise OptionsError(f"Perfil desconhecido: {profile_id!r}")
    want_names = _flag(nomes)
    if want_names is None:
        want_names = base["nomes"] and profile_asks_names(profile_id)
    if want_names and not _installed("gliner"):
        raise OptionsError("Procurar nomes exige o detector de nomes instalado (pip install -e \".[nomes]\").")
    if want_names and not profile_asks_names(profile_id):
        raise OptionsError(f"O perfil '{profiles.PROFILES[profile_id]['nome']}' não procura nomes: "
                           "escolha um perfil LGPD, GDPR ou saúde.")
    low = _flag(baixa_qualidade)
    if low is None:
        low = base["baixa_qualidade"]
    return {"perfil": profile_id, "nomes": bool(want_names), "baixa_qualidade": bool(low),
            "segundo_olhar": bool(low), "leitura_extra": bool(low) and _installed("rapidocr")}


def apply_to_environment(options, environ=None):
    """No processo da tarefa: transforma as opções nas variáveis que o pipeline lê. Sem opções, não mexe em nada."""
    if not options:
        return {}
    env = os.environ if environ is None else environ
    changes = {"POLICY_PROFILE": options["perfil"],
               "NER_ENGINE": "gliner" if options.get("nomes") else "",
               "SECOND_LOOK": "1" if options.get("segundo_olhar") else "0",
               "OCR_EXTRA_ENGINE": "rapidocr" if options.get("leitura_extra") else ""}
    env.update(changes)
    return changes

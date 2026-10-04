# SPDX-License-Identifier: AGPL-3.0-or-later
"""Regra que combina a decisão do modelo com a classificação do LLM.

Invariante de segurança: o decisor só pode ACRESCENTAR proteção ou pedir revisão. Ele nunca tira a
tarja de um endereço que o LLM marcou como pessoal. Assim, um decisor ruim custa no máximo tarjas a
mais e revisões extras -- nunca um dado pessoal exposto.

Modos (variável DECISION_MODE):
    shadow  o decisor só observa e registra (para aprender); nada muda no resultado. É o padrão.
    assist  o decisor participa, mas só com um perfil aprovado pelo portão de qualidade.
"""
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Thresholds:
    """Faixas de probabilidade de "endereço residencial" (aprendidas no treino)."""

    personal: float = 0.90   # p >= personal  -> o decisor afirma que é pessoal
    not_personal: float = 0.10  # p <= not_personal -> o decisor afirma que não é pessoal
    # entre os dois: incerto


def combine_address_decision(llm_is_personal: bool, p_personal: Optional[float], mode: str,
                             thresholds: Thresholds = Thresholds()):
    """
    Devolve (is_personal, motivo_de_revisao_ou_None).

    p_personal: probabilidade calibrada do modelo, ou None se o decisor não respondeu.
    """
    if mode != "assist":
        return llm_is_personal, None
    if p_personal is None:
        # Modo assist pedido, mas o decisor falhou: segue o LLM e pede revisão (falha fechado).
        return llm_is_personal, "decisor local indisponível"
    if llm_is_personal:
        return True, None  # nunca reduz proteção
    if p_personal >= thresholds.personal:
        return True, f"decisor local indica endereço residencial (p={p_personal:.2f}); tarjado"
    if p_personal > thresholds.not_personal:
        return False, f"decisor local incerto sobre o tipo do endereço (p={p_personal:.2f})"
    return False, None

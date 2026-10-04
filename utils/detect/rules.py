# SPDX-License-Identifier: AGPL-3.0-or-later
"""Detectores por regra dos tipos de PII de formato conhecido (catalog.py).

Cada regra trabalha sobre o MAPA DE PALAVRAS do OCR (ou do texto digital do PDF) e devolve comandos de tarja no
mesmo formato da busca de CPF: {id_da_palavra: {índices de caracteres}}. Assim, revisão, editor, tarja nativa e
regiões a revisar valem para qualquer tipo.

Para evitar falso positivo, cada regra exige pelo menos um destes: dígito verificador, formato distintivo
(ex.: telefone com parênteses/hífen) ou palavra de contexto perto do valor (ex.: "RG", "agência", "nascido").
A palavra de contexto em si nunca é tarjada; só o valor.
"""
import re
import unicodedata
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Pattern, Set, Tuple

from . import validators as v

Commands = Dict[int, Set[int]]


@dataclass(frozen=True)
class Rule:
    type_id: str
    value: Pattern                      # grupo nomeado "v" = trecho a tarjar
    context: Optional[Pattern] = None   # procurado no texto (sem acento, minúsculo) logo ANTES do valor
    context_required: bool = False
    window: int = 40                    # quantos caracteres antes do valor olhar para achar o contexto
    accept: Optional[Callable[[str, bool], bool]] = None  # (valor, tem_contexto) -> aceita?
    # Se isto aparecer ENTRE a palavra de contexto e o valor, o contexto não vale (ex.: outra data ou outro
    # rótulo no meio: "Nascimento: 01/02/1980 Emissão: 05/06/2010" não faz da emissão uma data de nascimento)
    stop: Optional[Pattern] = None


def _norm(text):
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return text.lower()


def _digits_ok(n_min, n_max):
    return lambda value, _ctx: n_min <= len(v.only_digits(value)) <= n_max


def _phone_ok(value, has_ctx):
    d = v.only_digits(value)
    if d.startswith("55") and len(d) in (12, 13):
        d = d[2:]
    if d.startswith("0") and len(d) in (11, 12):  # DDD com zero de operadora: (065)
        d = d[1:]
    if len(set(d)) == 1:
        return False
    if len(d) in (8, 9):  # sem DDD: só com palavra de contexto ("Telefone: 3321-1234")
        return has_ctx and (len(d) == 8 or d[0] == "9")
    if len(d) not in (10, 11) or not 11 <= int(d[:2]) <= 99:
        return False
    if len(d) == 11 and d[2] != "9":  # celular com 9 dígitos começa com 9
        return False
    formatted = bool(re.search(r"[()\-+]", value))
    return formatted or has_ctx


def _card_ok(value, has_ctx):
    grouped = bool(re.fullmatch(r"\d{4}([\s\-.]\d{4}){2}[\s\-.]\d{1,7}", value.strip()))
    return v.is_valid_luhn(value) and (grouped or has_ctx)


def _cns_ok(value, has_ctx):
    grouped = bool(re.fullmatch(r"\d{3}\s\d{4}\s\d{4}\s\d{4}", value.strip()))
    return v.is_valid_cns(value) and (grouped or has_ctx)


def _plate_ok(value, has_ctx):
    # Só o padrão Mercosul (ABC1D23) é distintivo o bastante sozinho; o antigo (ABC-1234) confunde com
    # normas e códigos ("ISO-9001", "NBR-1406") e exige palavra de contexto
    compact = re.sub(r"[\s\-]", "", value)
    return bool(re.fullmatch(r"[A-Z]{3}\d[A-Z]\d{2}", compact)) or has_ctx


_CPF_FORMATTED = re.compile(r"\d{3}\.\d{3}\.\d{3}-\d{2}")


def _rg_ok(value, has_ctx):
    # Um CPF logo depois de "RG ... ," não é RG: a busca de CPF já o trata (evita contar duas vezes)
    if _CPF_FORMATTED.fullmatch(value.strip()) or v.is_valid_cpf(v.only_digits(value)):
        return False
    return 5 <= len(v.only_digits(value)) <= 14


_I = re.IGNORECASE
RULES: List[Rule] = [
    Rule("rg", re.compile(r"(?P<v>\b\d[\d.\-]{3,13}[\dxX]\b)"),
         re.compile(r"\b(rg|r\.\s?g\.|identidade|registro geral)\b"), context_required=True, window=30,
         accept=_rg_ok, stop=re.compile(r"\bcpf\b|\d{3}\.\d{3}\.\d{3}")),
    Rule("cnh", re.compile(r"(?P<v>\b\d{9,11}\b)"),
         re.compile(r"\b(cnh|habilitacao)\b"), context_required=True, window=40),
    Rule("titulo_eleitor", re.compile(r"(?P<v>\b\d{4}\s?\d{4}\s?\d{4}\b)"),
         re.compile(r"titulo\s+(de\s+)?eleitor|titulo\s+eleitoral|\beleitor\b"), context_required=True, window=40,
         accept=lambda value, _c: v.is_valid_titulo_eleitor(value)),
    Rule("pis_nis", re.compile(r"(?P<v>\b\d{3}\.?\s?\d{5}\.?\s?\d{2}-?\s?\d\b)"),
         re.compile(r"\b(pis|pasep|nis|nit)\b"), context_required=True, window=30,
         accept=lambda value, _c: v.is_valid_pis(value)),
    Rule("cns", re.compile(r"(?P<v>\b[12789]\d{2}\s?\d{4}\s?\d{4}\s?\d{4}\b)"),
         re.compile(r"\bcns\b|cartao\s+(do\s+)?sus|cartao\s+nacional\s+de\s+saude"), window=40, accept=_cns_ok),
    Rule("passaporte", re.compile(r"(?P<v>\b[A-Z]{2}\s?\d{6,7}\b)"),
         re.compile(r"passaporte"), context_required=True, window=30),
    Rule("ctps", re.compile(r"(?P<v>\b\d{5,8}(?:\s*(?:/|serie|série)\s*\d{3,5}(?:-[A-Z]{2})?)?\b)", _I),
         re.compile(r"\bctps\b|carteira\s+de\s+trabalho"), context_required=True, window=30),
    Rule("telefone", re.compile(r"(?<![\d(])(?P<v>(?:\+\s?55\s?)?(?:\(?\s?0?\d{2}\s?\)?\s?)?9?\s?\d{4}\s?[\-.]?\s?\d{4})(?!\d)"),
         re.compile(r"\b(tel|telefone|fone|celular|cel|whatsapp|contato)\b"), window=25, accept=_phone_ok),
    Rule("email", re.compile(r"(?P<v>[A-Za-z0-9._%+\-]+\s?@\s?[A-Za-z0-9.\-]+\.[A-Za-z]{2,})")),
    Rule("ip", re.compile(r"(?P<v>(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.]))"),
         accept=lambda value, _c: v.is_valid_ipv4(value)),
    Rule("cartao_pagamento", re.compile(r"(?P<v>\b(?:\d{4}[\s\-.]){3}\d{1,7}\b|\b\d{13,19}\b)"),
         re.compile(r"cartao|credito|debito|visa|master|elo\b|amex"), window=30, accept=_card_ok),
    Rule("conta_bancaria", re.compile(r"(?P<v>\b\d{3,12}(?:-[\dxX])?\b)"),
         re.compile(r"\b(agencia|ag\.?|conta|c/c|cc|conta\s+corrente|poupanca)\s*(n[o.º°]?\s*)?[:\-]?\s*$"),
         context_required=True, window=22, accept=_digits_ok(3, 13)),
    Rule("chave_pix", re.compile(r"(?P<v>\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b)")),
    Rule("data_nascimento",
         re.compile(r"(?P<v>\b\d{1,2}\s?[/.\-]\s?\d{1,2}\s?[/.\-]\s?\d{2,4}\b|\b\d{1,2}[ºo°]?\s+de\s+[a-zç]+\s+de\s+\d{4}\b)", _I),
         re.compile(r"nascid|nascimento|\bnasc\b|\bd\.?\s?n\.?\b"), context_required=True, window=40,
         stop=re.compile(r"\d{1,2}\s?[/.\-]\s?\d{1,2}\s?[/.\-]\s?\d{2,4}|emiss|expedi|validade|vencimento|"
                         r"admiss|\bdata\b(?!\s+de\s+nasc)")),
    Rule("placa_veiculo", re.compile(r"(?P<v>\b[A-Z]{3}[\s\-]?\d[A-Z0-9]\d{2}\b)"),
         re.compile(r"\bplaca\b|veiculo|renavam|automovel"), window=30, accept=_plate_ok),
]
RULES_BY_TYPE = {r.type_id: r for r in RULES}


def build_text(grounding) -> Tuple[str, List[Optional[Tuple[int, int]]]]:
    """Junta as palavras do mapa com espaços e guarda, para cada caractere, (id da palavra, índice) ou None."""
    parts, char_map = [], []
    for wid, word in enumerate(grounding or []):
        text = str(word.get("text", ""))
        if not text:
            continue
        if parts:
            parts.append(" ")
            char_map.append(None)
        parts.append(text)
        char_map.extend((wid, i) for i in range(len(text)))
    return "".join(parts), char_map


def find_in_grounding(grounding, type_ids) -> Dict[str, Tuple[Commands, Set[str]]]:
    """
    Procura os tipos pedidos no mapa de palavras.
    Devolve {tipo: (comandos de tarja, valores distintos normalizados)} só para os tipos encontrados.
    """
    text, char_map = build_text(grounding)
    if not text:
        return {}
    norm_text = _norm(text)  # mesmo comprimento para texto latino comum; usado só para o contexto
    results = {}
    for type_id in type_ids:
        rule = RULES_BY_TYPE.get(type_id)
        if rule is None:
            continue
        commands: Commands = {}
        values: Set[str] = set()
        for m in rule.value.finditer(text):
            value = m.group("v")
            start, end = m.span("v")
            has_ctx = False
            if rule.context is not None:
                window = norm_text[max(0, start - rule.window):start] if len(norm_text) == len(text) else \
                    _norm(text[max(0, start - rule.window):start])
                matches = list(rule.context.finditer(window))
                has_ctx = bool(matches)
                if has_ctx and rule.stop is not None and rule.stop.search(window[matches[-1].end():]):
                    has_ctx = False  # outro valor/rótulo entre o contexto e este valor
            if rule.context_required and not has_ctx:
                continue
            if rule.accept is not None and not rule.accept(value, has_ctx):
                continue
            for pos in range(start, end):
                ref = char_map[pos]
                if ref is not None and not text[pos].isspace():
                    commands.setdefault(ref[0], set()).add(ref[1])
            values.add(re.sub(r"\s", "", value).lower())
        if commands:
            results[type_id] = (commands, values)
    return results

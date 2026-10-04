# SPDX-License-Identifier: AGPL-3.0-or-later
"""Validadores de identificadores com dígito verificador PÚBLICO e estável.

Regra do projeto: só entra aqui algoritmo oficial e bem estabelecido. Documentos sem algoritmo nacional
confiável (RG, CNH, passaporte, CTPS) são detectados por formato + palavra de contexto (rules.py), nunca por
um cálculo "aproximado" que poderia descartar um número verdadeiro.
"""
import ipaddress

from utils.validators import is_valid_cnpj, is_valid_cpf  # noqa: F401  (reexportados para quem usa este módulo)


def only_digits(value):
    return "".join(ch for ch in str(value) if ch.isdigit())


def is_valid_pis(value):
    """PIS/PASEP/NIS/NIT: 11 dígitos, pesos 3,2,9,8,7,6,5,4,3,2 e módulo 11."""
    d = only_digits(value)
    if len(d) != 11 or len(set(d)) == 1:
        return False
    total = sum(int(a) * w for a, w in zip(d[:10], (3, 2, 9, 8, 7, 6, 5, 4, 3, 2)))
    dv = 11 - total % 11
    return (0 if dv >= 10 else dv) == int(d[10])


def is_valid_cns(value):
    """Cartão Nacional de Saúde (CNS): 15 dígitos começando com 1, 2, 7, 8 ou 9; soma ponderada (15..1) múltipla de 11."""
    d = only_digits(value)
    if len(d) != 15 or d[0] not in "12789" or len(set(d)) == 1:
        return False
    return sum(int(a) * w for a, w in zip(d, range(15, 0, -1))) % 11 == 0


def is_valid_titulo_eleitor(value):
    """Título de eleitor: 12 dígitos = 8 sequenciais + UF (01..28) + 2 verificadores (regra especial para SP/MG)."""
    d = only_digits(value)
    if len(d) != 12 or len(set(d)) == 1:
        return False
    seq, uf, dv = d[:8], d[8:10], d[10:]
    if not 1 <= int(uf) <= 28:
        return False
    sp_mg = uf in ("01", "02")
    dv1 = sum(int(a) * w for a, w in zip(seq, range(2, 10))) % 11
    dv1 = 1 if (dv1 == 0 and sp_mg) else (0 if dv1 == 10 else dv1)
    dv2 = (int(uf[0]) * 7 + int(uf[1]) * 8 + dv1 * 9) % 11
    dv2 = 1 if (dv2 == 0 and sp_mg) else (0 if dv2 == 10 else dv2)
    return dv == f"{dv1}{dv2}"


def is_valid_luhn(value, min_len=13, max_len=19):
    """Cartão de pagamento: 13 a 19 dígitos, algoritmo de Luhn."""
    d = only_digits(value)
    if not min_len <= len(d) <= max_len or len(set(d)) == 1:
        return False
    total = 0
    for i, ch in enumerate(reversed(d)):
        n = int(ch)
        if i % 2 == 1:
            n = n * 2 - 9 if n > 4 else n * 2
        total += n
    return total % 10 == 0


def is_valid_ipv4(value):
    try:
        ip = ipaddress.IPv4Address(str(value).strip())
    except ValueError:
        return False
    return not (ip.is_unspecified or ip.is_loopback)

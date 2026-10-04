# SPDX-License-Identifier: AGPL-3.0-or-later
"""Mascaramento de CPF para logs e artefatos de diagnóstico (LGPD).

Regra do projeto: nenhum CPF completo pode ser gravado em log ou em artefato de diagnóstico.
O CPF só existe em memória (para tarjar) e dentro do documento original.
"""
import logging
import re
import traceback

# CPF formatado (000.000.000-00), com separadores parciais/espaços ou 11 dígitos corridos.
# O lookbehind/lookahead evita mascarar pedaço de um número maior (ex.: CNPJ de 14 dígitos).
CPF_PATTERN = re.compile(r"(?<!\d)(\d{3})[.\s]?(\d{3})[.\s]?(\d{3})[-.\s]?(\d{2})(?!\d)")


def _mask_match(match):
    return f"***.***.{match.group(3)}-{match.group(4)}"


def mask_cpf(value):
    """'529.982.247-25' ou '52998224725' -> '***.***.247-25'. Valor inválido vira '***.***.***-**'."""
    digits = "".join(ch for ch in str(value) if ch.isdigit())
    if len(digits) != 11:
        return "***.***.***-**"
    return f"***.***.{digits[6:9]}-{digits[9:]}"


def mask_text(text):
    """Substitui todo CPF encontrado no texto pela versão mascarada."""
    if not text:
        return text
    return CPF_PATTERN.sub(_mask_match, str(text))


class CpfMaskingFilter(logging.Filter):
    """Filtro de logging: mascara CPF na mensagem (já formatada) e no traceback."""

    def filter(self, record):
        try:
            message = record.getMessage()
        except Exception:
            message = str(record.msg)
        record.msg = mask_text(message)
        record.args = None
        if record.exc_info:
            record.exc_text = mask_text("".join(traceback.format_exception(*record.exc_info)))
            record.exc_info = None
        elif record.exc_text:
            record.exc_text = mask_text(record.exc_text)
        return True


def install_log_masking(logger=None):
    """Instala o filtro em TODOS os handlers do logger (padrão: root).

    Filtros de logger não se aplicam a registros propagados de outros loggers; os de handler, sim.
    """
    target = logger or logging.getLogger()
    flt = CpfMaskingFilter()
    for handler in target.handlers:
        if not any(isinstance(f, CpfMaskingFilter) for f in handler.filters):
            handler.addFilter(flt)
    return flt

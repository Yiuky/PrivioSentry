# SPDX-License-Identifier: AGPL-3.0-or-later
"""Mascaramento de CPF para logs e artefatos de diagnóstico (LGPD).

Regra do projeto: nenhum CPF completo pode ser gravado em log ou em artefato de diagnóstico.
O CPF só existe em memória (para tarjar) e dentro do documento original.
"""
import logging
import re
import traceback

# CPF formatado (000.000.000-00), com separadores variados (ponto, espaço, vírgula, hífen, barra, até 2 seguidos)
# ou 11 dígitos corridos. Nos logs, mascarar a mais é aceitável; deixar passar um CPF, não.
# O lookbehind/lookahead evita mascarar pedaço de um número maior (ex.: CNPJ de 14 dígitos).
_SEP = r"[\s.,\-/]{0,2}"
CPF_PATTERN = re.compile(rf"(?<!\d)(\d{{3}}){_SEP}(\d{{3}}){_SEP}(\d{{3}}){_SEP}(\d{{2}})(?!\d)")


def _mask_match(match):
    return f"***.***.{match.group(3)}-{match.group(4)}"


def mask_cpf(value):
    """'529.982.247-25' ou '52998224725' -> '***.***.247-25'. Valor inválido vira '***.***.***-**'."""
    digits = "".join(ch for ch in str(value) if ch.isdigit())
    if len(digits) != 11:
        return "***.***.***-**"
    return f"***.***.{digits[6:9]}-{digits[9:]}"


# Segredos em URLs (ex.: "?token=..."): nunca vão para o log por inteiro.
SECRET_QUERY_PATTERN = re.compile(r"((?:api_)?token=)[^&\s\"']+", re.IGNORECASE)


def mask_secrets(text):
    """'/tasks?token=abc' -> '/tasks?token=***'."""
    if not text:
        return text
    return SECRET_QUERY_PATTERN.sub(r"\1***", str(text))


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
        record.msg = mask_secrets(mask_text(message))
        record.args = None
        if record.exc_info:
            record.exc_text = mask_text("".join(traceback.format_exception(*record.exc_info)))
            record.exc_info = None
        elif record.exc_text:
            record.exc_text = mask_text(record.exc_text)
        return True


class ArgsMaskingFilter(logging.Filter):
    """Mascara CPF e segredos DENTRO dos argumentos do registro, preservando a estrutura.

    O formatador de acesso do uvicorn lê record.args como tupla (cliente, método, caminho, versão, status):
    achatar a mensagem (como faz o CpfMaskingFilter) quebraria a formatação de cada requisição.
    """

    @staticmethod
    def _clean(value):
        if isinstance(value, (int, float)) or value is None:
            return value  # números (ex.: status HTTP) ficam como estão: o formatador espera o tipo original
        return mask_secrets(mask_text(value if isinstance(value, str) else str(value)))

    def filter(self, record):
        if isinstance(record.msg, str):
            record.msg = self._clean(record.msg)
        if isinstance(record.args, tuple):
            record.args = tuple(self._clean(a) for a in record.args)
        elif isinstance(record.args, dict):
            record.args = {k: self._clean(v) for k, v in record.args.items()}
        # Traceback (ex.: nome de arquivo com CPF numa exceção) também é mascarado
        if record.exc_info:
            record.exc_text = mask_secrets(mask_text("".join(traceback.format_exception(*record.exc_info))))
            record.exc_info = None
        elif record.exc_text:
            record.exc_text = mask_secrets(mask_text(record.exc_text))
        return True


def install_access_log_masking():
    """Mascara CPF e segredos nos registros do uvicorn (acesso e erro), que têm handlers e formatadores próprios.

    Filtro de LOGGER: vale para tudo o que esses loggers registram, mesmo com handlers criados depois.
    """
    flt = ArgsMaskingFilter()
    for name in ("uvicorn.access", "uvicorn.error"):
        lg = logging.getLogger(name)
        for old in [f for f in lg.filters if isinstance(f, CpfMaskingFilter)]:
            lg.removeFilter(old)
        if not any(isinstance(f, ArgsMaskingFilter) for f in lg.filters):
            lg.addFilter(flt)
    return flt


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

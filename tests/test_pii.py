# SPDX-License-Identifier: AGPL-3.0-or-later
import io
import logging

from sentry_testkit import CPF_A, CPF_A_FMT, CPF_B_FMT
from utils.pii import CpfMaskingFilter, install_log_masking, mask_cpf, mask_text


def test_mask_cpf_from_formatted_and_plain():
    assert mask_cpf(CPF_A_FMT) == "***.***.247-25"
    assert mask_cpf(CPF_A) == "***.***.247-25"
    assert mask_cpf("123") == "***.***.***-**"
    assert mask_cpf("") == "***.***.***-**"


def test_mask_text_covers_formats():
    text = f"a {CPF_A_FMT} b {CPF_A} c 529.982 247-25 d 529 982 247 25"
    out = mask_text(text)
    assert CPF_A not in out and CPF_A_FMT not in out and "529" not in out
    assert out.count("***.***.247-25") == 4


def test_mask_text_ignores_cnpj_and_short_numbers():
    text = "CNPJ 11.444.777/0001-61 processo 7001840.2026 telefone 99999-1234"
    assert mask_text(text) == text


def test_mask_text_handles_empty_and_non_str():
    assert mask_text("") == ""
    assert mask_text(None) is None
    assert mask_text(123) == "123"


def _logger_with_buffer():
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger = logging.getLogger("test_pii_logger")
    logger.handlers.clear()
    logger.propagate = False
    logger.setLevel(logging.DEBUG)
    logger.addHandler(handler)
    return logger, handler, stream


def test_filter_masks_message_args_and_exceptions():
    logger, handler, stream = _logger_with_buffer()
    handler.addFilter(CpfMaskingFilter())
    logger.info("CPF %s encontrado", CPF_A_FMT)
    logger.info(f"bruto {CPF_A}")
    try:
        raise ValueError(f"falha com {CPF_B_FMT}")
    except ValueError:
        logger.exception("erro")
    out = stream.getvalue()
    assert CPF_A_FMT not in out and CPF_A not in out and CPF_B_FMT not in out
    assert "***.***.247-25" in out and "***.***.777-35" in out
    assert "Traceback" in out  # traceback preservado, so mascarado


def test_filter_masks_preformatted_exc_text():
    flt = CpfMaskingFilter()
    record = logging.LogRecord("x", logging.ERROR, __file__, 1, "msg", None, None)
    record.exc_text = f"Traceback ... {CPF_A_FMT}"
    assert flt.filter(record)
    assert CPF_A_FMT not in record.exc_text


def test_filter_survives_bad_format_args():
    flt = CpfMaskingFilter()
    record = logging.LogRecord("x", logging.INFO, __file__, 1, "valor %d", ("nao-numero",), None)
    assert flt.filter(record)
    assert record.msg == "valor %d"


def test_install_log_masking_is_idempotent_and_covers_propagated_records():
    root = logging.getLogger()
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    root.addHandler(handler)
    try:
        install_log_masking()
        install_log_masking()
        assert sum(isinstance(f, CpfMaskingFilter) for f in handler.filters) == 1
        logging.getLogger("qualquer.modulo").warning("achei %s", CPF_A_FMT)
        assert CPF_A_FMT not in stream.getvalue()
    finally:
        root.removeHandler(handler)

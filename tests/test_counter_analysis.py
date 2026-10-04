# SPDX-License-Identifier: AGPL-3.0-or-later
"""Contra-análise: tenta QUEBRAR os detectores e as garantias do pipeline com casos adversos.

Falsos positivos em texto administrativo comum, entradas aleatórias e gigantes (tempo limitado, sem regex
explosivo), acentos/caracteres especiais (mapeamento de caracteres), propriedades gerais (só o valor é
tarjado; regiões dentro da página) e todos os perfis rodando o pipeline.
"""
import random
import string
import time

import pytest

from main import SentryApp
from sentry_testkit import CPF_A, CPF_A_FMT, make_text_pdf, word
from utils.detect import catalog, ner, profiles, rules

ALL_RULE_TYPES = list(rules.RULES_BY_TYPE)


def grounding(*texts):
    return [word(i, t, 100 * i) for i, t in enumerate(texts)]


def words(text):
    return grounding(*text.split())


# --- 1. falsos positivos: frases comuns em documentos oficiais que NÃO devem virar PII ----------------------
NOT_PII = [
    "Lei nº 13.709/2018 (LGPD) e Decreto nº 10.046/2019",
    "Processo nº 0001234-56.2024.8.11.0041 em trâmite na comarca",
    "valor total de R$ 1.500,00 (mil e quinhentos reais) pago em 3 parcelas",
    "Empresa Exemplo Ltda, CNPJ 00.000.000/0001-91",
    "CEP 78000-000 Cuiabá - MT",
    "reunião às 14:30 do dia 05/03/2024 na sala 12",
    "certificação ISO 9001 e ISO 27001 vigentes",
    "fls. 12 a 15 do volume 2, protocolo 2024/000123",
    "assinado eletronicamente em 01/02/2024 às 10:15",
    "conforme a prestação de contas de 2024 aprovada em assembleia",
    "artigo 5º, incisos I e II, parágrafo único",
    "edital 001/2024, item 3.2.1",
]


@pytest.mark.parametrize("text", NOT_PII)
def test_common_administrative_text_is_not_pii(text):
    found = rules.find_in_grounding(words(text), ALL_RULE_TYPES)
    assert found == {}, {t: v for t, (_, v) in found.items()}


# --- 2. formatos reais que DEVEM ser achados -----------------------------------------------------------------
SHOULD_FIND = [
    ("telefone", "Telefone: (65) 3321-1234 (fixo)"),
    ("telefone", "celular +55 65 99999-1234"),
    ("telefone", "WhatsApp 65 99999-1234"),
    ("email", "e-mail: maria.exemplo@example.com"),
    ("rg", "portador do RG nº 1.234.567 SSP/MT"),
    ("data_nascimento", "nascida em 03 de março de 1985"),
    ("conta_bancaria", "Ag. 1234-5 C/C 98765-4"),
    ("placa_veiculo", "veículo de placa ABC-1234"),
]


@pytest.mark.parametrize("type_id, text", SHOULD_FIND)
def test_real_world_formats_are_found(type_id, text):
    assert type_id in rules.find_in_grounding(words(text), [type_id]), text


# --- 3. robustez: lixo aleatório e texto gigante não quebram nem travam -------------------------------------
def test_random_garbage_never_crashes():
    rng = random.Random(7)
    alphabet = string.ascii_letters + string.digits + " .,-/()@:+ºªçãéÇÃ\t" + "0123456789" * 3
    for _ in range(300):
        tokens = ["".join(rng.choice(alphabet) for _ in range(rng.randint(1, 15))) for _ in range(rng.randint(1, 40))]
        gmap = grounding(*[t for t in tokens if t.strip()] or ["x"])
        for type_id, (commands, _values) in rules.find_in_grounding(gmap, ALL_RULE_TYPES).items():
            for wid, chars in commands.items():
                assert 0 <= wid < len(gmap)
                assert all(0 <= c < len(gmap[wid]["text"]) for c in chars), (type_id, gmap[wid]["text"], chars)


@pytest.mark.parametrize("unit", ["1 ", "12.", "a-1 ", "(65) ", "9" * 30 + " ", "@a.b ", "RG 1 "])
def test_huge_page_runs_in_bounded_time(unit):
    gmap = words(unit * 6000)  # dezenas de milhares de caracteres: um regex com retrocesso explosivo travaria
    started = time.time()
    rules.find_in_grounding(gmap, ALL_RULE_TYPES)
    assert time.time() - started < 10


# --- 4. acentos e caracteres especiais: a tarja cai nos caracteres certos ------------------------------------
@pytest.mark.parametrize("prefix", ["Telefône", "Telefone", "Teléfono:", "Tel.", "Ｔel", "ﬁcha tel"])
def test_unicode_context_keeps_character_mapping(prefix):
    gmap = grounding(*prefix.split(), "(65)", "99999-1234")
    res = rules.find_in_grounding(gmap, ["telefone"])
    assert "telefone" in res
    commands, _ = res["telefone"]
    value_ids = {len(prefix.split()), len(prefix.split()) + 1}
    assert set(commands) == value_ids                                 # só as palavras do valor


def test_context_words_are_never_redacted():
    cases = [("rg", "RG 1.234.567"), ("cnh", "CNH 98765432199"), ("passaporte", "passaporte FT123456"),
             ("data_nascimento", "nascido em 01/02/1980"), ("conta_bancaria", "conta 12345-6")]
    for type_id, text in cases:
        gmap = words(text)
        commands, _ = rules.find_in_grounding(gmap, [type_id])[type_id]
        assert 0 not in commands, (type_id, text)


# --- 5. CPF: os novos detectores não substituem nem atrapalham a busca de CPF -------------------------------
def test_cpf_is_still_found_by_cpf_detector_with_any_profile(tmp_path, monkeypatch):
    monkeypatch.setenv("BASE_DPI", "40")
    for pid in profiles.PROFILES:
        app = SentryApp(make_text_pdf(tmp_path / f"{pid}.pdf"))
        app.run_phase_0()
        app.grounding_maps = [grounding("CPF:", CPF_A_FMT, "Tel", "(65)", "98888-7777")]  # telefone que NÃO é CPF válido
        app.grounding_maps_sparse = [[]]
        app.grounding_maps_native = [[]]
        app.policy_profile = pid
        app.run_phase_2()
        app.run_policy_phase()
        assert app.cpf_redactions[1], pid
        assert app.known_cpfs == [CPF_A] and app.pii_summary["cpf"] == 1, pid
        assert all(0 <= v <= 1 for m in app.review_marks for v in m["box"]), pid
        app.session.close()


def test_phone_that_happens_to_pass_cpf_check_is_treated_as_cpf_safe_side(tmp_path, monkeypatch):
    """Limitação conhecida (docs/limitations.md): um telefone cujos 11 dígitos passam por acaso no DV de CPF é
    tarjado também como CPF. O erro fica do lado seguro (tarja a mais); afrouxar a regra de CPF arriscaria perder
    CPF verdadeiro. Se este teste mudar, a decisão precisa ser revista conscientemente."""
    from utils.ocr_engine import OCREngine
    from utils.validators import is_valid_cpf
    # O número é gerado aqui (nenhum valor que passe no DV de CPF fica escrito no código: auditoria I-01)
    phone = next(f"6599999{n:04d}" for n in range(10000) if is_valid_cpf(f"6599999{n:04d}"))
    gmap = grounding("Tel", "(65)", f"{phone[2:7]}-{phone[7:]}")
    _, found = OCREngine(tesseract_path=None).find_cpfs_in_grounding(gmap)
    assert found == {phone}


def test_policy_phase_tolerates_missing_extra_maps(tmp_path, monkeypatch):
    monkeypatch.setenv("BASE_DPI", "40")
    app = SentryApp(make_text_pdf(tmp_path / "d.pdf", n_pages=2))
    app.run_phase_0()
    app.grounding_maps = [grounding("Tel", "(65)", "99999-1234"), grounding("nada")]
    app.grounding_maps_sparse = []        # listas mais curtas que as páginas: não pode quebrar
    app.grounding_maps_native = []
    app.policy_profile = "lgpd_publicacao"
    app.run_policy_phase()
    assert app.pii_summary == {"telefone": 1}
    app.session.close()


# --- 6. catálogo × perfis × detectores: nada fica pela metade ----------------------------------------------
def test_every_profile_action_is_valid_and_runnable_types_have_rules():
    for pid in profiles.PROFILES:
        for type_id, action in profiles.runnable_actions(pid).items():
            assert action in (profiles.TARJAR, profiles.ALERTAR)
            special = ("cpf", "endereco_residencial") + ner.TYPES   # fases próprias e detector de nomes
            assert type_id in rules.RULES_BY_TYPE or type_id in special, (pid, type_id)


def test_sensitive_types_are_never_silently_redacted():
    # Dados sensíveis dependem de contexto: nos perfis, só ALERTAR (revisão humana), nunca tarja automática
    sensitive = {t.id for t in catalog.CATALOG if t.nivel == catalog.SENSIVEL}
    for pid, p in profiles.PROFILES.items():
        for type_id, action in p["acoes"].items():
            if type_id in sensitive:
                assert action == profiles.ALERTAR, (pid, type_id)


# --- 7. concorrência: falha e exceção ficam na página que as causou ----------------------------------------
def test_thread_failure_counters_are_isolated():
    import threading
    from utils.ocr_engine import OCREngine
    engine = OCREngine(tesseract_path=None)
    seen = {}
    barrier = threading.Barrier(2)

    def worker(name, fail):
        barrier.wait()
        if fail:
            engine._record_failure()
        barrier.wait()  # as duas threads leem depois que a falha aconteceu
        seen[name] = engine.thread_failures()

    threads = [threading.Thread(target=worker, args=("falha", True)), threading.Thread(target=worker, args=("ok", False))]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert seen == {"falha": 1, "ok": 0} and engine.failure_count == 1


def test_exception_in_one_page_does_not_hide_the_others():
    from utils.ocr_engine import OCREngine
    from utils.verifier import _ocr_images

    class Boom(OCREngine):
        def get_grounding_map(self, img_path, psm=3):
            if img_path == "b":
                raise RuntimeError("tesseract morreu")
            return "", [word(0, CPF_A_FMT, 0)]

    out = _ocr_images(Boom(tesseract_path=None), {1: "a", 2: "b", 3: "c"}, "6", workers=3)
    assert out[1][1] is None and out[3][1] is None
    assert isinstance(out[2][1], RuntimeError) and out[2][0] is None   # página 2 vira "não verificada"


# --- 8. regressões da revisão independente (2026-10-04) ------------------------------------------------------
def _types(text, *type_ids):
    return set(rules.find_in_grounding(words(text), list(type_ids or ALL_RULE_TYPES)))


def test_r5_phone_is_not_the_tail_of_a_longer_number():
    assert "telefone" not in _types("tel 12345678901234", "telefone")


@pytest.mark.parametrize("text", ["Telefone: 3321-1234", "Fone 99999-1234", "Tel.: (065) 3321-1234"])
def test_r6_phone_without_ddd_or_with_operator_zero(text):
    assert "telefone" in _types(text, "telefone")


def test_r6_operator_zero_ddd_is_fully_covered():
    gmap = words("Tel.: (065) 3321-1234")
    commands, _ = rules.find_in_grounding(gmap, ["telefone"])["telefone"]
    assert commands[1] == set(range(len("(065)")))                # "(065)" inteiro, não só "65)"


def test_r6_ordinal_birth_date():
    assert "data_nascimento" in _types("Data de nascimento 1º de março de 1980", "data_nascimento")


def test_r6_unlabelled_8_digit_number_is_not_a_phone():
    assert "telefone" not in _types("protocolo 3321-1234", "telefone")


def test_r7_cpf_after_rg_label_is_not_counted_as_rg():
    gmap = words(f"RG nº 1234567 SSP/MT, CPF {CPF_A_FMT}")
    commands, values = rules.find_in_grounding(gmap, ["rg"])["rg"]
    assert values == {"1234567"}


def test_r7_issue_date_is_not_birth_date():
    commands, values = rules.find_in_grounding(words("Nascimento: 01/02/1980 Emissão: 05/06/2010"),
                                               ["data_nascimento"])["data_nascimento"]
    assert values == {"01/02/1980"}


@pytest.mark.parametrize("text", ["norma ISO-9001", "NBR-1406 da ABNT", "código ABC-1234"])
def test_r7_old_plate_format_needs_context(text):
    assert "placa_veiculo" not in _types(text, "placa_veiculo")


def test_r7_old_plate_with_context_and_mercosul_alone():
    assert "placa_veiculo" in _types("placa ABC-1234", "placa_veiculo")
    assert "placa_veiculo" in _types("ABC1D23", "placa_veiculo")


def test_r2_traceback_and_object_args_are_masked():
    import logging
    from utils.pii import ArgsMaskingFilter
    try:
        raise FileNotFoundError(f"Requerimento {CPF_A_FMT}.pdf")
    except FileNotFoundError:
        import sys
        record = logging.LogRecord("uvicorn.error", logging.ERROR, __file__, 1, "erro %s %d",
                                   (RuntimeError(f"cpf {CPF_A_FMT}"), 500), sys.exc_info())
    ArgsMaskingFilter().filter(record)
    full = record.getMessage() + (record.exc_text or "")
    assert CPF_A_FMT not in full and "500" in record.getMessage() and "FileNotFoundError" in record.exc_text


@pytest.mark.parametrize("raw, expected", [("", 300), ("40", 40), ("10", 300), ("3000", 300), ("abc", 300), ("600", 600)])
def test_r11_single_dpi_parser(monkeypatch, raw, expected):
    from utils.session import render_dpi
    monkeypatch.setenv("BASE_DPI", raw)
    assert render_dpi() == expected


def test_r1_native_text_boxes_follow_page_rotation(tmp_path):
    """A caixa do texto digital precisa cair sobre o texto DESENHADO na imagem, mesmo com /Rotate."""
    import fitz
    from PIL import Image
    from utils.verifier import _words_to_grounding, page_words
    pdf = str(tmp_path / "girada.pdf")
    with fitz.open() as doc:
        page = doc.new_page(width=600, height=800)
        page.insert_text((50, 100), f"CPF {CPF_A_FMT}", fontsize=14)
        page.set_rotation(90)
        doc.save(pdf)
    with fitz.open(pdf) as doc:
        page = doc[0]
        pix = page.get_pixmap(alpha=False)  # 72 DPI: 1 ponto = 1 pixel
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples).convert("L")
        grounding = _words_to_grounding(page_words(page))
    cpf_word = next(w for w in grounding if CPF_A_FMT in w["text"])
    b = cpf_word["box"]
    crop = img.crop((int(b["x"]), int(b["y"]), int(b["x"] + b["w"]) + 1, int(b["y"] + b["h"]) + 1))
    assert crop.getextrema()[0] < 128, "a caixa precisa cobrir pixels escuros do texto, não área em branco"


def test_r8_one_review_region_per_occurrence(tmp_path, monkeypatch):
    monkeypatch.setenv("BASE_DPI", "72")
    app = SentryApp(make_text_pdf(tmp_path / "d.pdf"))
    app.run_phase_0()
    # duas ocorrências distantes (topo e rodapé) + duas palavras vizinhas da mesma ocorrência
    boxes = [[50, 50, 40, 12], [95, 50, 60, 12], [50, 780, 40, 12]]
    regions = app._relative_boxes(1, boxes)
    assert len(regions) == 2
    top, bottom = sorted(regions, key=lambda r: r[1])
    assert top[3] < 0.2 and bottom[1] > 0.8                       # nenhuma região cobre a página inteira
    app.session.close()


def test_r9_finalize_keeps_processing_summary_and_labels(tmp_path, monkeypatch):
    monkeypatch.setenv("BASE_DPI", "40")
    app = SentryApp(make_text_pdf(tmp_path / "d.pdf"))
    app.run_phase_0()
    app.manual_mode = True
    app.pii_summary = {"telefone": 1}
    state = app.final_state()
    for key in ("pii_summary", "pii_found", "policy_profile", "timings"):
        assert key not in state, key                               # não sobrescreve o que o processamento gravou
    app._load_metadata_safely([{"page": 1, "type": "pii", "coords": [1, 1, 30, 10], "label": "Telefone"}])
    app.run_phase_5()
    import json
    import os
    meta = json.load(open(os.path.join(app.session.output_dir, "redactions_metadata.json"), encoding="utf-8"))
    assert [m["label"] for m in meta] == ["Telefone"]              # antes virava "Endereço residencial"
    app.session.close()


def test_r13_verifier_works_in_chunks_and_reports_progress(tmp_path):
    import fitz
    from PIL import Image
    from utils.ocr_engine import OCREngine
    from utils.verifier import verify_pdf
    img = tmp_path / "p.png"
    Image.new("RGB", (60, 80), "white").save(img)
    pdf = str(tmp_path / "longo.pdf")
    with fitz.open() as doc:
        for _ in range(23):
            doc.new_page().insert_image(fitz.Rect(0, 0, 595, 842), filename=str(img))
        doc.save(pdf)
    seen_files, progress = [], []

    class CountingOCR(OCREngine):
        def get_grounding_map(self, img_path, psm=3):
            import os as _os
            seen_files.append(len(_os.listdir(_os.path.dirname(img_path))))
            return "", []

    leftovers, unverified = verify_pdf(pdf, ocr_engine=CountingOCR(tesseract_path=None), dpi=36, workers=2,
                                       progress=lambda done, total: progress.append(done))
    assert leftovers == {} and unverified == []
    assert max(seen_files) <= 4                                    # nunca mais que um lote em disco
    assert progress == [10, 20, 23]                                # progresso avança durante o OCR


# --- 9. documento real (condomínio): valores em reais não viram CPF; CPF com vírgula continua CPF ---------
def _cpfs(*texts):
    from utils.ocr_engine import OCREngine
    return OCREngine(tesseract_path=None).find_cpfs_in_grounding(grounding(*texts))[1]


def test_money_values_never_assemble_into_a_cpf():
    from utils.validators import is_valid_cpf
    # Procura um valor em reais + número vizinho cujos 11 dígitos passariam no DV de CPF (gerado, não escrito)
    combo = next((a, b) for a in range(1000, 10000) for b in range(100, 1000)
                 if is_valid_cpf(f"{a}00{b}{b % 100:02d}"[:11]))
    a, b = combo
    money = f"{str(a)[0]}.{str(a)[1:]},00"                         # ex.: "1.500,00"
    tail = f"{b}{b % 100:02d}"[:5]
    assert _cpfs("pago", money, tail) == set()
    assert _cpfs("R$", f"{a},00", tail) == set()


def test_cpf_read_with_comma_instead_of_hyphen_is_still_a_cpf():
    assert _cpfs("CPF", CPF_A_FMT.replace("-", ",")) == {CPF_A}


def test_ocr_noise_words_do_not_complete_a_cpf(monkeypatch):
    # Mesmo formato do falso positivo do documento real: dígitos soltos de ruído ("a1b", "x5y") completando
    # 11 dígitos com números curtos vizinhos. O número é gerado aqui (nada que passe no DV fica no código).
    from utils import ocr_engine
    from utils.validators import is_valid_cpf
    six = next(f"{n:06d}" for n in range(100000, 1000000) if is_valid_cpf(f"1{n:06d}5123"))
    words_ = ["a1b", f"{six}]", "x5y", "123]"]
    monkeypatch.setattr(ocr_engine, "_looks_like_ocr_noise", lambda text: False)
    assert _cpfs(*words_) == {f"1{six}5123"}                        # sem o filtro: falso CPF
    monkeypatch.undo()
    assert _cpfs(*words_) == set()                                  # com o filtro: nenhum


@pytest.mark.parametrize("text, expected", [("l1i3o7]x", True), ("a5b", True), ("Ol2x", True), ("123456]", False),
                                            ("529.982.247-25", False), ("CPF:", False), ("S29.982.247-25", False),
                                            ("nº", False), ("3A", False)])
def test_noise_word_classifier(text, expected):
    from utils.ocr_engine import _looks_like_ocr_noise
    assert _looks_like_ocr_noise(text) is expected


# --- 10. corpus: pedaço do Cartão SUS (CNS, 15 dígitos) não vira CPF; CPF escrito ao lado continua CPF -------
def _cns_with_cpf_prefix():
    """CNS válido cujos 11 primeiros dígitos também passam no DV de CPF (gerado aqui, nada fica no código)."""
    from utils.detect.validators import is_valid_cns
    from utils.validators import is_valid_cpf
    rng = random.Random(15)
    while True:
        d = "1" + "".join(str(rng.randint(0, 9)) for _ in range(14))
        if is_valid_cns(d) and is_valid_cpf(d[:11]):
            return d


def test_cns_fragment_is_not_a_cpf():
    cns = _cns_with_cpf_prefix()
    assert _cpfs("Cartão", "SUS:", cns[:3], cns[3:7], cns[7:11], cns[11:]) == set()
    assert _cpfs("CNS", cns) == set()


def test_cpf_written_whole_next_to_digits_is_kept_even_if_they_form_a_cns():
    # Fail-closed: uma palavra de exatamente 11 dígitos é forma de CPF e nunca é excluída como "parte de CNS"
    cns = _cns_with_cpf_prefix()
    assert _cpfs("CPF", cns[:11], cns[11:]) == {cns[:11]}


# --- 11. OCR real (medido no corpus): "@" lido como "(D"/"(W"; nome partido; "0" da placa lido como "O" -------
def _found(text, type_id):
    return rules.find_in_grounding(words(text), [type_id]).get(type_id, ({}, set()))[1]


@pytest.mark.parametrize("text, expected", [
    ("E-mail: maria.84(Dexample.com.", {"maria.84@example.com"}),
    ("contato joao.1 (Wexample.com", {"joao.1@example.com"}),
    ("E-mail: beatriz.7 1(Dexample.com", {"beatriz.71@example.com"}),   # nome partido pelo OCR
    ("e-mail maria.84Dexample.com.", {"maria.84dexample.com"}),          # "@" virou letra: vale com "e-mail"
    ("maria@example.com", {"maria@example.com"}),
])
def test_email_survives_ocr_misreads(text, expected):
    assert _found(text, "email") == expected


@pytest.mark.parametrize("text", ["maria.84Dexample.com sem rótulo", "acesse www.portal.gov.br", "conforme (Decreto nº 1",
                                  "o arquivo relatorio.com foi", "site: exemplo.com.br"])
def test_email_ocr_tolerance_does_not_invent_emails(text):
    assert _found(text, "email") == set()


@pytest.mark.parametrize("text, expected", [
    ("Veículo placa ZRDOD17", {"zrd0d17"}),       # "0" lido como "O": só com contexto
    ("placa ABCO234", {"abc0234"}),
    ("ABC1I23", {"abc1i23"}),                      # Mercosul: "I" na 5ª posição é letra legítima
    ("ZRDOD17 sem contexto", set()),
    ("norma ISO-9001", set()),
])
def test_plate_survives_ocr_letter_for_digit(text, expected):
    assert _found(text, "placa_veiculo") == expected

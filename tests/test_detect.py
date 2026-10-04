# SPDX-License-Identifier: AGPL-3.0-or-later
"""SENTRY Detect: catálogo, perfis, validadores e detectores por regra (números de teste GERADOS aqui)."""
import os
import random

import pytest

from sentry_testkit import word
from utils.detect import catalog, profiles, rules
from utils.detect import validators as v

RNG = random.Random(2026)


# --- geradores de números válidos (só para teste) ------------------------------------------------------
def make_pis():
    base = [RNG.randint(0, 9) for _ in range(10)]
    dv = 11 - sum(a * w for a, w in zip(base, (3, 2, 9, 8, 7, 6, 5, 4, 3, 2))) % 11
    return "".join(map(str, base)) + str(0 if dv >= 10 else dv)


def make_cns():
    while True:
        d = [1] + [RNG.randint(0, 9) for _ in range(14)]
        if sum(a * w for a, w in zip(d, range(15, 0, -1))) % 11 == 0:
            return "".join(map(str, d))


def make_titulo(uf="11"):
    seq = [RNG.randint(0, 9) for _ in range(8)]
    dv1 = sum(a * w for a, w in zip(seq, range(2, 10))) % 11
    dv1 = 0 if dv1 == 10 else dv1
    dv2 = (int(uf[0]) * 7 + int(uf[1]) * 8 + dv1 * 9) % 11
    dv2 = 0 if dv2 == 10 else dv2
    return "".join(map(str, seq)) + uf + f"{dv1}{dv2}"


def make_card():
    # Dígito de Luhn calculado AQUI, de forma independente do validador (dobra da direita para a esquerda)
    d = [4] + [RNG.randint(0, 9) for _ in range(14)]
    total = 0
    for i, n in enumerate(reversed(d)):
        if i % 2 == 0:  # posições que serão dobradas quando o dígito verificador entrar à direita
            n = n * 2 - 9 if n * 2 > 9 else n * 2
        total += n
    return "".join(map(str, d)) + str((10 - total % 10) % 10)


def mutate(number):
    last = (int(number[-1]) + 1) % 10
    return number[:-1] + str(last)


# --- catálogo e perfis ------------------------------------------------------------------------------------
def test_catalog_is_consistent():
    ids = [t.id for t in catalog.CATALOG]
    assert len(ids) == len(set(ids))
    for t in catalog.CATALOG:
        assert t.nivel in catalog.LEVELS and t.estado in (catalog.ATIVO, catalog.OPCIONAL, catalog.PLANEJADO)
        assert t.lgpd and t.gdpr and t.nist and t.hipaa and t.iso29100
        if t.nivel == catalog.SENSIVEL:
            assert "art. 5º, II" in t.lgpd or "art. 4º" in t.lgpd
            assert "art. 9" in t.gdpr or "art. 10" in t.gdpr


def test_every_active_rule_type_has_a_detector_and_vice_versa():
    with_own_phase = {"cpf", "endereco_residencial"}
    active = set(catalog.active_ids()) - with_own_phase
    assert active == set(rules.RULES_BY_TYPE)


def test_profiles_reference_only_catalog_types_and_always_protect_cpf():
    for pid, p in profiles.PROFILES.items():
        assert set(p["acoes"]) <= set(catalog.BY_ID), pid
        assert p["acoes"].get("cpf") == profiles.TARJAR, pid
        assert set(p["acoes"].values()) <= {profiles.TARJAR, profiles.ALERTAR}


def test_default_profile_keeps_original_behavior(monkeypatch):
    monkeypatch.delenv("POLICY_PROFILE", raising=False)
    assert profiles.active_profile_id() == "cpf_endereco"
    assert profiles.runnable_actions() == {"cpf": "tarjar", "endereco_residencial": "tarjar"}
    monkeypatch.setenv("POLICY_PROFILE", "inexistente")
    assert profiles.active_profile_id() == "cpf_endereco"


def test_planned_and_disabled_optional_types_are_not_run_but_stay_in_profile(monkeypatch):
    monkeypatch.setenv("POLICY_PROFILE", "lgpd_publicacao")
    monkeypatch.delenv("NER_ENGINE", raising=False)
    run = profiles.runnable_actions()
    assert "nome_pessoa" not in run and "foto_rosto" not in run and "telefone" in run
    acoes = profiles.describe_all()["lgpd_publicacao"]["acoes"]
    assert acoes["nome_pessoa"] == {"acao": "tarjar", "estado": "opcional", "rodando": False}
    assert acoes["foto_rosto"]["estado"] == "planejado" and acoes["telefone"]["rodando"]


def test_generated_catalog_doc_is_in_sync():
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs", "catalogo-pii.md")
    assert open(path, encoding="utf-8").read().strip() == catalog.to_markdown().strip(), \
        "rode: python -m utils.detect --markdown"


# --- validadores ------------------------------------------------------------------------------------------
@pytest.mark.parametrize("make, check", [(make_pis, v.is_valid_pis), (make_cns, v.is_valid_cns),
                                         (make_titulo, v.is_valid_titulo_eleitor), (make_card, v.is_valid_luhn)])
def test_validators_accept_generated_and_reject_mutated(make, check):
    for _ in range(20):
        n = make()
        assert check(n), n
        assert not check(mutate(n)), mutate(n)


# Vetores fixos, conferidos à mão (não dependem dos geradores acima)
def test_fixed_vectors_checked_by_hand():
    # PIS 1203456789-?: 1*3+2*2+0*9+3*8+4*7+5*6+6*5+7*4+8*3+9*2 = 189; 189 % 11 = 2; 11 - 2 = 9
    assert v.is_valid_pis("12034567899") and not v.is_valid_pis("12034567898")
    # CNS 100000000000007: 1*15 + 7*1 = 22, múltiplo de 11
    assert v.is_valid_cns("100000000000007") and not v.is_valid_cns("100000000000008")
    # Título SP (UF 01): sequência 10000001 -> 1*2 + 1*9 = 11, resto 0 -> regra SP/MG: dv1 = 1;
    # dv2 = (0*7 + 1*8 + 1*9) % 11 = 6  ->  100000010116. Pela regra geral seria dv1 = 0 (inválido aqui).
    assert v.is_valid_titulo_eleitor("100000010116")
    assert not v.is_valid_titulo_eleitor("100000010105")
    # Números de teste públicos das bandeiras (Luhn válido)
    assert v.is_valid_luhn("4111111111111111") and v.is_valid_luhn("5555555555554444")
    assert not v.is_valid_luhn("4111111111111112")


def test_validators_reject_degenerate_numbers():
    assert not v.is_valid_pis("00000000000")
    assert not v.is_valid_cns("000000000000000")
    assert not v.is_valid_titulo_eleitor("123456782901")      # UF 29 não existe
    assert not v.is_valid_luhn("1111111111111111")
    assert v.is_valid_ipv4("200.17.10.4") and not v.is_valid_ipv4("999.1.1.1") and not v.is_valid_ipv4("127.0.0.1")


# --- detectores ----------------------------------------------------------------------------------------------
def grounding(*texts):
    return [word(i, t, 100 * i) for i, t in enumerate(texts)]


def found(gmap, type_id):
    res = rules.find_in_grounding(gmap, [type_id])
    return res.get(type_id)


def redacted_words(gmap, type_id):
    res = found(gmap, type_id)
    return sorted(res[0]) if res else []


def test_context_word_is_never_redacted_only_the_value():
    pis = make_pis()
    gmap = grounding("PIS:", pis[:3] + "." + pis[3:8] + "." + pis[8:10] + "-" + pis[10])
    assert redacted_words(gmap, "pis_nis") == [1]


@pytest.mark.parametrize("type_id, texts, expected_words", [
    ("rg", ("RG", "12.345.678-9", "SSP/MT"), [1]),
    ("rg", ("protocolo", "12.345.678-9"), []),                       # sem contexto: não é RG
    ("cnh", ("CNH", "nº", "98765432199"), [2]),      # número inventado e que NÃO é CPF válido
    ("passaporte", ("Passaporte", "FT123456"), [1]),
    ("ctps", ("CTPS", "1234567", "série", "0012"), [1, 2, 3]),
    ("telefone", ("Tel.:", "(65)", "99999-1234"), [1, 2]),
    ("telefone", ("protocolo", "6599991234"), []),                   # sem formato nem contexto
    ("email", ("contato:", "fulano.teste@example.org"), [1]),
    ("chave_pix", ("chave", "123e4567-e89b-42d3-a456-426614174000"), [1]),
    ("data_nascimento", ("nascido", "em", "01/02/1980"), [2]),
    ("data_nascimento", ("assinado", "em", "01/02/1980"), []),       # data qualquer não é nascimento
    ("placa_veiculo", ("veículo", "placa", "ABC1D23"), [2]),
    ("placa_veiculo", ("norma", "ISO", "9001"), []),
    ("conta_bancaria", ("agência", "1234", "conta", "56789-0"), [1, 3]),
    ("conta_bancaria", ("prestação", "de", "contas", "2024"), []),
    ("ip", ("acesso", "do", "IP", "200.17.10.4"), [3]),
])
def test_rules(type_id, texts, expected_words):
    assert redacted_words(grounding(*texts), type_id) == expected_words


def test_checksum_rules_with_generated_numbers():
    cns = make_cns()
    spaced = f"{cns[:3]} {cns[3:7]} {cns[7:11]} {cns[11:]}"
    assert redacted_words(grounding("Cartão", "SUS", *spaced.split()), "cns") == [2, 3, 4, 5]
    assert redacted_words(grounding("Cartão", "SUS", mutate(cns)), "cns") == []
    titulo = make_titulo()
    assert redacted_words(grounding("Título", "de", "eleitor", titulo), "titulo_eleitor") == [3]
    card = make_card()
    grouped = [card[i:i + 4] for i in range(0, 16, 4)]
    assert redacted_words(grounding("cartão", *grouped), "cartao_pagamento") == [1, 2, 3, 4]
    assert redacted_words(grounding("cartão", mutate(card)), "cartao_pagamento") == []


def test_value_split_across_words_maps_to_char_indices():
    gmap = grounding("Tel", "(65)", "99999-1234", "fim")
    commands, values = found(gmap, "telefone")
    assert commands[1] == set(range(4)) and commands[2] == set(range(10))
    assert values == {"(65)99999-1234"}


# --- integração com o pipeline e com a API -----------------------------------------------------------------
@pytest.fixture()
def app(tmp_path, monkeypatch):
    from main import SentryApp
    from sentry_testkit import make_text_pdf
    monkeypatch.setenv("BASE_DPI", "40")
    a = SentryApp(make_text_pdf(tmp_path / "doc.pdf"))
    a.run_phase_0()
    a.grounding_maps = [grounding("Tel.:", "(65)", "99999-1234", "placa", "ABC1D23")]
    a.grounding_maps_sparse = [[]]
    a.grounding_maps_native = [[]]
    yield a
    a.session.close()


def test_policy_phase_redacts_and_labels_by_profile(app, monkeypatch):
    monkeypatch.setenv("POLICY_PROFILE", "lgpd_publicacao")
    app.policy_profile = "lgpd_publicacao"
    app.run_policy_phase()
    assert len(app.global_redactions[1]) == 2                     # telefone (2 palavras) tarjado
    assert set(app.box_labels[1].values()) == {"Telefone"}
    assert app.pii_summary == {"telefone": 1, "placa_veiculo": 1}
    assert app.needs_review and any(m["reason"].startswith("Placa de veículo") for m in app.review_marks)  # alertar


def test_default_profile_runs_no_extra_types(app):
    app.run_policy_phase()
    assert not app.global_redactions[1] and app.pii_summary == {}


def test_address_follows_profile(app):
    box = {"x": 1, "y": 2, "w": 3, "h": 4}
    app.address_redactions[1].append(box)
    app.global_redactions[1].append(box)
    app.address_redactor.results = {1: [{"text": "Rua A, casa 1", "type": "pessoal"}, {"text": "Av B", "type": "profissional"}]}
    app.policy_profile = "lgpd_interno"                           # endereço: alertar
    app._apply_address_policy()
    assert box not in app.global_redactions[1] and app.needs_review
    assert app.pii_summary["endereco_residencial"] == 1


def test_labels_reach_the_editor_metadata(app, monkeypatch):
    import json
    import os as _os
    app.policy_profile = "lgpd_publicacao"
    app.run_policy_phase()
    app.run_phase_5()
    meta = json.load(open(_os.path.join(app.session.output_dir, "redactions_metadata.json"), encoding="utf-8"))
    assert {m.get("label") for m in meta} == {"Telefone"}


def test_policy_api_is_read_only_and_has_no_personal_data(monkeypatch):
    import importlib
    from fastapi.testclient import TestClient
    import app_service
    importlib.reload(app_service)
    c = TestClient(app_service.app)
    cat = c.get("/policy/catalog").json()
    assert {t["id"] for t in cat["tipos"]} == set(catalog.BY_ID)
    prof = c.get("/policy/profiles").json()
    assert prof["ativo"] == "cpf_endereco" and "lgpd_publicacao" in prof["perfis"]
    assert c.post("/policy/catalog").status_code == 405

# SPDX-License-Identifier: AGPL-3.0-or-later
"""Modelos de documento: reconhecer e tarjar sem IA, inspecionar depois, gerar rascunho com/sem IA.

Tudo com PDFs FICTÍCIOS gerados aqui (I-01) e sem Ollama/rede (I-08). Contra testes de tarja a menos (I-03):
valor que continua, dois rótulos na mesma linha, rótulo colado, endereço fora dos campos, modelos parecidos."""
import os

import fitz
import pytest

from sentry_testkit import CPF_A_FMT, CPF_B_FMT
from utils.doc_templates import draft, engine, schema
from utils.verifier import _words_to_grounding, page_words

TITLE = "SECRETARIA FICTICIA DE TESTES AMBIENTAIS"
SUB = "LICENCA DE EXEMPLO PARA TESTES AUTOMATIZADOS"
LINES = [
    (60, TITLE, 13), (60, SUB, 12), (60, "Coordenadoria de Modelos e Documentos", 11),
    (60, f"PROPRIETARIO: Maria Silvana Teste       CPF/CNPJ: {CPF_A_FMT}", 10),
    (60, "Fone: (65) 99999-0000", 10),
    (60, "ENDERECO: Travessa das Amostras, 45, Bairro", 10),
    (60, "Imaginario, Cidade Amostral - UF", 10),
    (60, f"RESPONSAVEL TECNICO: Joao Ficticio de Teste CPF:{CPF_B_FMT}", 10),
    (60, "Nome do empreendimento: Fazenda Modelo", 10),
    (60, "Reside na Rua das Flores Ficticias, 10, Bairro Teste.", 10),
]


def make_pdf(path, lines=LINES, pages=1):
    doc = fitz.open()
    for _ in range(pages):
        p = doc.new_page(width=595, height=842)
        y = 70
        for x, text, size in lines:
            p.insert_text((x, y), text, fontsize=size)
            y += 26
    doc.save(str(path))
    doc.close()
    return str(path)


def words_of(path):
    with fitz.open(path) as doc:
        return [_words_to_grounding(page_words(p)) for p in doc]


def text_of(words, ids):
    return " ".join(str(words[i]["text"]) for i in sorted(ids, key=lambda k: (words[k]["box"]["y"], words[k]["box"]["x"])))


def template(**over):
    t = {"id": "licenca-teste", "nome": "Licença de teste", "status": "rascunho",
         "reconhecimento": {"ancoras": [TITLE, SUB, "Coordenadoria de Modelos e Documentos"], "minimo": 0.8},
         "campos": [{"rotulo": "PROPRIETARIO", "tipo": "nome_pessoa"}, {"rotulo": "CPF/CNPJ", "tipo": "cpf"},
                    {"rotulo": "ENDERECO", "tipo": "endereco_residencial", "linhas": 2},
                    {"rotulo": "Fone", "tipo": "telefone"},
                    {"rotulo": "RESPONSAVEL TECNICO", "tipo": "nome_pessoa"},
                    {"rotulo": "CPF", "tipo": "cpf", "obrigatorio": False}]}
    t.update(over)
    return schema.validate(t)


@pytest.fixture()
def pdf(tmp_path):
    return make_pdf(tmp_path / "licenca.pdf")


# ------------------------------------------------------------------ esquema e pasta
def test_schema_is_strict(tmp_path):
    for bad in ({"id": "../x"}, {"id": "ok", "reconhecimento": {"ancoras": []}},
                {"id": "ok", "reconhecimento": {"ancoras": ["a b"]}, "campos": []},
                {"id": "ok", "reconhecimento": {"ancoras": ["a b"], "minimo": 0.1}, "campos": [{"rotulo": "x"}]},
                {"id": "ok", "reconhecimento": {"ancoras": ["a b"]}, "campos": [{"rotulo": "x", "direcao": "cima"}]}):
        with pytest.raises(schema.TemplateError):
            schema.validate(bad)


def test_save_import_and_edit_go_back_to_draft_only_explicit_approval(monkeypatch, tmp_path):
    monkeypatch.setenv("PRIVIO_DOC_TEMPLATES_DIR", str(tmp_path / "m"))
    saved = schema.save(dict(template(), status="aprovado"))           # importar "aprovado" não aprova
    assert saved["status"] == "rascunho" and saved["versao"] == 1
    approved = schema.save(saved, approve=True)
    assert approved["status"] == "aprovado" and approved["aprovado_em"]
    same = schema.save(approved)                                        # salvar sem mudar: continua aprovado
    assert same["status"] == "aprovado" and same["versao"] == 1
    edited = schema.save(dict(approved, campos=approved["campos"][:2]))
    assert edited["status"] == "rascunho" and edited["versao"] == 2
    assert [t["id"] for t in schema.load_all()[0]] == ["licenca-teste"]
    assert schema.delete("licenca-teste") and schema.get("licenca-teste") is None


def test_template_folder_is_ignored_by_git_and_docker():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for name in (".gitignore", ".dockerignore"):
        with open(os.path.join(root, name), encoding="utf-8") as fh:
            assert "modelos_documento/" in fh.read().split(), name


# ------------------------------------------------------------------ reconhecimento
def test_recognizes_by_fixed_phrases(pdf):
    found = engine.match([template()], words_of(pdf))
    assert found["modelo"]["id"] == "licenca-teste" and found["pontuacao"] == 1.0


def test_other_document_is_not_recognized(tmp_path):
    other = make_pdf(tmp_path / "o.pdf", [(60, "OFICIO QUALQUER DE OUTRO ORGAO", 12), (60, "Texto livre.", 10)])
    assert engine.match([template()], words_of(other))["modelo"] is None


def test_two_similar_templates_apply_neither(pdf):
    twin = template(id="licenca-gemea")
    found = engine.match([template(), twin], words_of(pdf))
    assert found["modelo"] is None and set(found["ambiguos"]) == {"licenca-teste", "licenca-gemea"}


def test_page_count_limits(pdf):
    t = template(reconhecimento={"ancoras": [TITLE, SUB], "minimo": 1, "paginas_min": 2, "paginas_max": 3})
    assert engine.match([t], words_of(pdf))["modelo"] is None


# ------------------------------------------------------------------ campos (tarja a menos = I-03)
def test_fields_take_the_value_and_stop_at_the_next_label(pdf):
    words = words_of(pdf)[0]
    result, missing = engine.apply(template(), [words])
    ids = set(result[1]["comandos"])
    text = text_of(words, ids)
    assert "Maria Silvana Teste" in text and CPF_A_FMT in text and "(65) 99999-0000" in text
    assert "Travessa das Amostras, 45, Bairro" in text and "Imaginario, Cidade Amostral - UF" in text  # 2 linhas
    assert "Joao Ficticio de Teste" in text
    assert "CPF/CNPJ:" not in text and "PROPRIETARIO:" not in text                 # o rótulo fica visível
    assert "Fazenda" not in text and "empreendimento" not in text                   # "Nome do ...:" não é "Nome:"
    assert missing == []


def test_value_glued_to_its_label_is_cut_after_the_colon(pdf):
    words = words_of(pdf)[0]
    result, _ = engine.apply(template(), [words])
    glued = next(i for i, w in enumerate(words) if w["text"].startswith("CPF:") and CPF_B_FMT in w["text"])
    assert result[1]["comandos"][glued] == set(range(len("CPF:"), len(words[glued]["text"])))


def test_word_limit_cut_is_reported_for_review(pdf):
    t = template(campos=[{"rotulo": "ENDERECO", "tipo": "endereco_residencial", "max_palavras": 2}])
    _, found = engine.extract(words_of(pdf)[0], t["campos"][0], [])
    assert found and found[0]["truncado"] is True


def test_label_below_layout(tmp_path):
    path = make_pdf(tmp_path / "b.pdf", [(60, TITLE, 12), (60, "INTERESSADO", 10), (60, "Maria Silvana Teste", 10)])
    field = schema.validate({"id": "x1", "reconhecimento": {"ancoras": ["a b"]},
                             "campos": [{"rotulo": "INTERESSADO", "direcao": "abaixo"}]})["campos"][0]
    words = words_of(path)[0]
    commands, found = engine.extract(words, field)
    assert text_of(words, commands) == "Maria Silvana Teste" and found


def test_missing_required_label_is_reported(pdf):
    t = template(campos=[{"rotulo": "INEXISTENTE", "tipo": "outro"}])
    _, missing = engine.apply(t, words_of(pdf))
    assert missing == [(0, "INEXISTENTE")]


# ------------------------------------------------------------------ inspeção por regras
def test_label_inspection_flags_values_without_redaction(pdf):
    words = words_of(pdf)[0]
    fone = [i for i, w in enumerate(words) if w["text"] in ("(65)", "99999-0000")]
    flagged = engine.inspect_labels(words, covered=set())
    assert any(label == "Fone" and set(fone) <= set(ids) for label, ids in flagged)
    assert not any(label == "Fone" for label, _ in engine.inspect_labels(words, covered=set(fone)))   # contra teste


def test_masked_text_hides_redacted_words(pdf):
    words = words_of(pdf)[0]
    result, _ = engine.apply(template(), [words])
    text = engine.masked_text(words, set(result[1]["comandos"]))
    assert "Maria" not in text and CPF_A_FMT not in text and "█████" in text and "PROPRIETARIO:" in text


# ------------------------------------------------------------------ rascunho a partir de documento revisado
def reviewed_boxes(words, wanted):
    """Caixas de tarja do 'revisor' sobre as palavras que contêm algum dos trechos pedidos."""
    return [dict(w["box"]) for w in words if any(t in w["text"] for t in wanted)]


def test_draft_from_reviewed_document(pdf):
    words = words_of(pdf)
    boxes = reviewed_boxes(words[0], ["Maria", "Silvana", "Teste", "529.982", "Travessa", "das", "Amostras,", "45,",
                                      "Imaginario,", "Cidade", "Amostral", "-", "UF"])
    labels = {1: ["Nome de pessoa"] * len(boxes)}
    t, report = draft.build(words, {1: boxes}, labels)
    by_label = {engine.norm(f["rotulo"]): f for f in t["campos"]}
    assert "proprietario" in by_label and "cpf cnpj" in by_label and "endereco" in by_label
    assert by_label["endereco"]["linhas"] == 2
    anchors = t["reconhecimento"]["ancoras"]
    assert TITLE in anchors and SUB in anchors
    assert not any("Maria" in a or "Silvana" in a for a in anchors)        # nome tarjado nunca vira âncora
    assert t["status"] == "rascunho" and report["campos"] == len(t["campos"])
    assert engine.match([schema.validate(t)], words)["modelo"] is not None    # o rascunho reconhece o próprio doc


class FakeAI:
    def __init__(self, answer):
        self.answer, self.prompts = answer, []

    def analyze_text(self, prompt, vision_model=False, **kw):
        self.prompts.append(prompt)
        return self.answer, {}


def test_ai_suggestions_are_kept_only_if_they_exist_in_the_text(pdf):
    words = words_of(pdf)
    boxes = reviewed_boxes(words[0], ["Maria", "Silvana", "Teste", "529.982"])
    t, _ = draft.build(words, {1: boxes})
    ai = FakeAI({"nome": "Licença fictícia", "ancoras": ["Coordenadoria de Modelos e Documentos", "FRASE INVENTADA"],
                 "rotulos": [{"rotulo": "Fone", "tipo": "telefone"}, {"rotulo": "Campo Inventado", "tipo": "cpf"}]})
    t, note = draft.ai_suggest(t, words, {1: boxes}, client=ai)
    assert "FRASE INVENTADA" not in t["reconhecimento"]["ancoras"]
    labels = [f["rotulo"] for f in t["campos"]]
    assert "Fone" in labels and "Campo Inventado" not in labels
    assert next(f for f in t["campos"] if f["rotulo"] == "Fone")["sugerido_ia"] is True
    sent = ai.prompts[0]
    assert "Maria" not in sent and "529" not in sent and "65" not in sent    # só texto mascarado sai para a IA
    assert t["nome"] == "Licença fictícia" and schema.validate(t)


def test_ai_failure_keeps_the_rule_based_draft(pdf):
    words = words_of(pdf)
    t, _ = draft.build(words, {1: reviewed_boxes(words[0], ["Maria"])})
    before = [f["rotulo"] for f in t["campos"]]
    t, note = draft.ai_suggest(t, words, {}, client=FakeAI({"error": "fora do ar"}))
    assert [f["rotulo"] for f in t["campos"]] == before and "IA" in note


# ------------------------------------------------------------------ regressões da varredura de bugs
def grid(rows):
    """Palavras com caixas sintéticas: [(y, "texto da linha")] (sem PDF; valores fictícios)."""
    out = []
    for y, line in rows:
        x = 50
        for t in line.split():
            out.append({"text": t, "box": {"x": x, "y": y, "w": 12 * len(t), "h": 20}})
            x += 12 * len(t) + 10
    return out


FICHA = {"id": "ficha", "reconhecimento": {"ancoras": ["FICHA CADASTRAL FICTICIA"]},
         "campos": [{"rotulo": "Nome"}, {"rotulo": "Endereço", "tipo": "endereco_residencial"},
                    {"rotulo": "Cidade", "obrigatorio": False}]}


def test_required_label_with_empty_value_is_missing():
    """'Endereço:' achado mas o valor caiu na linha de baixo (linhas=1): não pode contar como achado (I-13)."""
    page = grid([(10, "FICHA CADASTRAL FICTICIA"), (60, "Nome: FULANO DE TAL"), (110, "Endereço:"),
                 (140, "Rua das Acácias Fictícias 77")])
    result, missing = engine.apply(schema.validate(FICHA), [page])
    assert (0, "Endereço") in missing
    assert result[1]["campos"]["Endereço"] == [{"palavras": 0, "truncado": False}]   # ocorrência continua registrada


def test_empty_occurrence_on_a_listed_page_is_missing_for_that_page():
    t = schema.validate(dict(FICHA, campos=[{"rotulo": "Nome", "paginas": [1, 2]}]))
    pages = [grid([(60, "Nome: FULANO DE TAL")]), grid([(60, "Nome:"), (90, "FULANO DE TAL")])]
    _, missing = engine.apply(t, pages)
    assert missing == [(2, "Nome")]


def test_required_field_on_a_page_beyond_the_document_is_missing():
    t = schema.validate(dict(FICHA, campos=[{"rotulo": "Nome"}, {"rotulo": "Endereço", "paginas": [2]}]))
    _, missing = engine.apply(t, [grid([(60, "Nome: FULANO DE TAL"), (110, "Endereço: Rua Ficticia 9")])])
    assert missing == [(0, "Endereço")]
    t = schema.validate(dict(FICHA, campos=[{"rotulo": "Endereço", "paginas": [2, 3]}]))
    assert engine.apply(t, [grid([(60, "Nome: FULANO DE TAL")])])[1] == [(0, "Endereço")]   # sem repetição


def test_other_label_word_without_colon_does_not_cut_the_value():
    page = grid([(10, "FICHA CADASTRAL FICTICIA"), (60, "Nome: FULANO DE TAL"),
                 (110, "Endereço: Avenida Cidade Jardim Ficticia 400 Cidade: Exemplopolis")])
    result, missing = engine.apply(schema.validate(FICHA), [page])
    endereco = {page[i]["text"] for i in engine.extract(page, schema.validate(FICHA)["campos"][1],
                                                         [f["rotulo"] for f in FICHA["campos"]])[0]}
    assert endereco == {"Avenida", "Cidade", "Jardim", "Ficticia", "400"}            # para no rótulo "Cidade:"
    assert "Exemplopolis" in {page[i]["text"] for i in result[1]["comandos"]} and missing == []


def test_inspection_labels_without_colon_inside_the_value_are_not_stop_words():
    ws = grid([(10, "Endereço: Rua das Acácias Ficticias 77")])
    flagged = {label: [ws[i]["text"] for i in ids] for label, ids in engine.inspect_labels(ws, set())}
    assert flagged["Endereço"] == ["Rua", "das", "Acácias", "Ficticias", "77"]
    ws = grid([(10, "Proprietário: FULANO Pai Ficticio DE TAL Fone: 0000")])
    flagged = {label: [ws[i]["text"] for i in ids] for label, ids in engine.inspect_labels(ws, set())}
    assert flagged["Proprietário"] == ["FULANO", "Pai", "Ficticio", "DE", "TAL"]       # para em "Fone:"
    ws = grid([(10, "Proprietário: FULANO Pai : TAL")])                                # "Pai :" separado é rótulo
    flagged = {label: [ws[i]["text"] for i in ids] for label, ids in engine.inspect_labels(ws, set())}
    assert flagged["Proprietário"] == ["FULANO"]


def test_two_passing_templates_apply_neither_even_with_different_scores():
    """Genérico (1 âncora do órgão, 100%) x específico (5 de 6): os dois passam no mínimo -> nenhum (I-13)."""
    gen = schema.validate({"id": "generico", "reconhecimento": {"ancoras": ["ORGAO FICTICIO ESTADUAL"]},
                           "campos": [{"rotulo": "Nome"}]})
    spec = schema.validate({"id": "especifico", "reconhecimento": {"ancoras": [
        "ORGAO FICTICIO ESTADUAL", "LICENCA FICTICIA", "CONDICIONANTES GERAIS", "VALIDADE DA LICENCA",
        "ATIVIDADE LICENCIADA", "TEXTO QUE MUDOU"]}, "campos": [{"rotulo": "Nome"}]})
    doc = grid([(10, "ORGAO FICTICIO ESTADUAL"), (40, "LICENCA FICTICIA"), (70, "CONDICIONANTES GERAIS"),
                (100, "VALIDADE DA LICENCA"), (130, "ATIVIDADE LICENCIADA")])
    found = engine.match([gen, spec], [doc])
    assert found["modelo"] is None and set(found["ambiguos"]) == {"generico", "especifico"}
    assert engine.match([spec], [doc])["modelo"]["id"] == "especifico"               # contra teste: sozinho aplica


@pytest.mark.parametrize("tid", ["con", "prn", "aux", "nul", "com1", "com9", "lpt1", "lpt9", "CON", "Nul"])
def test_windows_reserved_names_are_not_template_ids(tid):
    with pytest.raises(schema.TemplateError):
        schema.validate({"id": tid, "reconhecimento": {"ancoras": ["A B"]}, "campos": [{"rotulo": "x"}]})
    with pytest.raises(schema.TemplateError):
        schema._path(tid.lower())
    assert schema.slug(tid) == "modelo"
    assert not schema.ID_RE.match("modelo\n")
    assert schema.ID_RE.match("console") and schema.ID_RE.match("com10") and schema.ID_RE.match("nul-1")  # contra


@pytest.mark.parametrize("name", ["ANA", "MARIA", "MARIANA"])
def test_glued_label_and_redacted_value_never_reach_the_ai_unmasked(name):
    """'PROPRIETARIO:ANA' numa palavra só, tarja só sobre 'ANA' (centro da palavra fora da tarja)."""
    words = grid([(10, "LICENCA FICTICIA DE TESTE"), (60, f"PROPRIETARIO:{name} Fone: 0000")])
    gi = next(i for i, w in enumerate(words) if w["text"] == f"PROPRIETARIO:{name}")
    box = {"x": words[gi]["box"]["x"] + 12 * len("PROPRIETARIO:") - 2, "y": 58, "w": 12 * len(name) + 4, "h": 24}
    assert gi not in engine.covered_ids(words, [box])                                # o centro não está na tarja
    text = draft.masked_document([words], {1: [box]})
    assert name not in text and "Fone:" in text and "LICENCA" in text                 # vizinhos continuam visíveis

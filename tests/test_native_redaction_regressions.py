"""Regressões da tarja nativa (finalização pelo editor): página girada, campo de formulário e caixa do revisor
invertida ou inválida. Dados fictícios; sem Tesseract (VERIFY_OCR=0)."""
import fitz
import pytest
from PIL import Image

from main import SentryApp
from utils.verifier import _words_to_grounding, page_words

EMAIL = "fulano.teste@example.com"


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("BASE_DPI", "72")
    monkeypatch.setenv("VERIFY_OCR", "0")


def _pdf(tmp_path, rotation=0, widget=False):
    path = str(tmp_path / f"doc_{rotation}.pdf")
    with fitz.open() as d:
        p = d.new_page(width=600, height=800)
        p.insert_text((50, 100), f"E-mail {EMAIL}", fontsize=14)
        if widget:
            w = fitz.Widget()
            w.field_name, w.field_type = "email", fitz.PDF_WIDGET_TYPE_TEXT
            w.rect, w.field_value = fitz.Rect(50, 200, 300, 225), EMAIL
            p.add_widget(w)
        p.set_rotation(rotation)
        d.save(path)
    return path


def _finalize(tmp_path, pdf, manual):
    app = SentryApp(pdf, output_dir=str(tmp_path / "out"), final_dir=str(tmp_path / "fin"))
    out = app.run(manual_redactions=manual, native_mode=True)
    state = app.final_state()
    app.session.close()
    return out, state


def _email_box(pdf):
    """Caixa do e-mail no espaço da imagem renderizada (o que o editor mostra e devolve)."""
    with fitz.open(pdf) as d:
        b = next(w for w in _words_to_grounding(page_words(d[0])) if EMAIL in w["text"])["box"]
    return [b["x"] - 3, b["y"] - 3, b["x"] + b["w"] + 3, b["y"] + b["h"] + 3]


def _dark_ratio(pdf, box):
    with fitz.open(pdf) as d:
        pix = d[0].get_pixmap(alpha=False)
    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples).convert("L").crop(tuple(int(v) for v in box))
    data = img.tobytes()
    return sum(v < 60 for v in data) / len(data)


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_native_redaction_lands_on_the_box_in_rotated_pages(tmp_path, rotation):
    pdf = _pdf(tmp_path, rotation)
    box = _email_box(pdf)
    with fitz.open(pdf) as d:
        width = d[0].rect.width                                           # largura da página como é exibida
    out, _ = _finalize(tmp_path, pdf, [{"page": 1, "type": "pii", "label": "E-mail", "coords": box,
                                         "image_width": width}])
    with fitz.open(out) as d:
        assert EMAIL not in d[0].get_text()
    assert _dark_ratio(out, box) > 0.9                                    # a tarja está onde o revisor desenhou


@pytest.mark.parametrize("rotation", [0, 90])
def test_form_fields_under_the_box_leave_no_trace_in_the_file(tmp_path, rotation):
    values = ["fulano.teste@example.com", "Rua Ficticia 10", "outro valor ficticio"]
    pdf = str(tmp_path / f"form_{rotation}.pdf")
    with fitz.open() as d:
        p = d.new_page(width=600, height=800)
        for i, v in enumerate(values):
            w = fitz.Widget()
            w.field_name, w.field_type = f"campo{i}", fitz.PDF_WIDGET_TYPE_TEXT
            w.rect, w.field_value = fitz.Rect(50, 200 + 30 * i, 300, 225 + 30 * i), v
            p.add_widget(w)
        p.set_rotation(rotation)
        d.save(pdf)
    with fitz.open(pdf) as d:                                             # a caixa como o editor a vê (girada)
        box = fitz.Rect(48, 198, 302, 290) * d[0].rotation_matrix
        width = d[0].rect.width
    box.normalize()
    out, _ = _finalize(tmp_path, pdf, [{"page": 1, "type": "pii", "coords": list(box), "image_width": width}])
    with fitz.open(out) as d:
        assert list(d[0].widgets()) == []
        blob = b"".join((d.xref_object(x) or "").encode("latin-1", "ignore") + (d.xref_stream(x) or b"")
                        for x in range(1, d.xref_length()))
    assert [v for v in values if v.encode() in blob] == []                # nem no formulário (AcroForm)


def test_inverted_box_from_the_editor_still_redacts(tmp_path):
    pdf = _pdf(tmp_path)
    x0, y0, x1, y1 = _email_box(pdf)
    out, _ = _finalize(tmp_path, pdf, [{"page": 1, "type": "pii", "coords": [x1, y1, x0, y0], "image_width": 600}])
    with fitz.open(out) as d:
        assert EMAIL not in d[0].get_text()


@pytest.mark.parametrize("coords", [["a", "b", "c", "d"], [10, 10, 10, 50], None, [1, 2, 3]])
def test_box_that_cannot_be_applied_never_ends_concluido(tmp_path, coords):
    pdf = _pdf(tmp_path)
    good = _email_box(pdf)
    _, state = _finalize(tmp_path, pdf, [{"page": 1, "type": "pii", "coords": good, "image_width": 600},
                                         {"page": 1, "type": "pii", "coords": coords, "image_width": 600}])
    assert state["needs_review"] and any("não pôde ser aplicada" in a for a in state["alerts"])

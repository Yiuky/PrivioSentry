# SPDX-License-Identifier: AGPL-3.0-or-later
"""UI: etiquetas das tarjas no editor (relatado com print). Uma etiqueta por TRECHO (as palavras de um endereço e as
caixas quase iguais das várias leituras de OCR não repetem a etiqueta), CPF com a etiqueta "CPF" (não "possível
assinatura"), e a linha de botões da barra lateral não corta texto com fonte maior."""
import pytest
from playwright.sync_api import expect

from ui_support import box

pytestmark = pytest.mark.ui


def labelled(page_no, coords, label, type_="pii", source="AI_Engine"):
    b = box(page_no, coords, source=source, type_=type_)
    b["label"] = label
    return b


def tags(page):
    """[(rótulo, etiqueta visível?)] na ordem desenhada."""
    return page.evaluate("""() => [...document.querySelectorAll('#layer-1 .redaction-box')].map(b => [
        b.dataset.label || '', getComputedStyle(b, '::before').display !== 'none' && !!b.dataset.label])""")


def visible_tags(page, label):
    return sum(1 for lab, vis in tags(page) if lab == label and vis)


def test_address_words_on_one_line_show_a_single_tag(page, live_app, open_task):
    words = [labelled(1, (100 + i * 70, 300, 160 + i * 70, 325), "Endereço residencial") for i in range(5)]
    tid = live_app.seed_task("end.pdf", redactions=words)
    open_task(tid)
    assert visible_tags(page, "Endereço residencial") == 1
    # a descrição continua em cada caixa (leitor de tela e dica)
    labels = page.eval_on_selector_all("#layer-1 .redaction-box", "els => els.map(e => e.getAttribute('aria-label'))")
    assert len(labels) == 5 and all("Endereço residencial" in a for a in labels)


def test_almost_identical_boxes_from_several_ocr_readings_show_one_tag(page, live_app, open_task):
    dup = [labelled(1, (200, 200, 400, 230), "CPF", type_="signature"),
           labelled(1, (203, 198, 402, 231), "CPF", type_="signature"),
           labelled(1, (199, 201, 399, 229), "CPF", type_="signature")]
    tid = live_app.seed_task("dup.pdf", redactions=dup)
    open_task(tid)
    assert visible_tags(page, "CPF") == 1


def test_cpf_boxes_are_labelled_cpf_not_possible_signature(page, live_app, open_task):
    tid = live_app.seed_task("cpf.pdf", redactions=[
        labelled(1, (100, 100, 300, 130), "CPF", type_="signature"),
        box(1, (100, 400, 300, 470), source="YOLO_Vision", type_="signature")])
    open_task(tid)
    cpf = page.locator("#layer-1 .redaction-box").nth(0)
    expect(cpf).to_have_attribute("data-label", "CPF")
    expect(cpf).not_to_have_class("type-signature")
    sig = page.locator("#layer-1 .redaction-box.type-signature")
    expect(sig).to_have_count(1)                                       # a assinatura de verdade continua
    assert "ASSINATURA" in sig.get_attribute("data-label")


# ------------------------------------------------------------------ contratestes
def test_separate_addresses_keep_their_own_tags(page, live_app, open_task):
    tid = live_app.seed_task("dois.pdf", redactions=[
        labelled(1, (100, 300, 160, 325), "Endereço residencial"), labelled(1, (170, 300, 230, 325), "Endereço residencial"),
        labelled(1, (100, 500, 160, 525), "Endereço residencial"),       # outra linha: outro trecho
        labelled(1, (520, 300, 580, 325), "Endereço residencial")])      # mesma linha, mas longe
    open_task(tid)
    assert visible_tags(page, "Endereço residencial") == 3


def test_different_types_side_by_side_keep_both_tags(page, live_app, open_task):
    tid = live_app.seed_task("tipos.pdf", redactions=[
        labelled(1, (100, 300, 200, 325), "E-mail"), labelled(1, (210, 300, 310, 325), "Telefone")])
    open_task(tid)
    assert visible_tags(page, "E-mail") == 1 and visible_tags(page, "Telefone") == 1


def test_action_buttons_never_clip_text_with_a_wider_font(page, open_app):
    # No navegador do usuário a fonte saiu mais larga e "Processar todos" aparecia cortado
    open_app()
    page.add_style_tag(content=".sidebar-actions .tool-btn { font-size: 15px !important; }")
    widths = page.evaluate("""() => [...document.querySelectorAll('.sidebar-actions .tool-btn')]
                               .map(b => [b.innerText, b.scrollWidth, b.clientWidth])""")
    assert all(sw <= cw + 1 for _t, sw, cw in widths), widths
    for label in ("Processar todos", "Excluir todos", "Documentação"):
        expect(page.get_by_role("button", name=label)).to_be_visible()


def test_one_tag_per_line_even_when_word_heights_differ(page, live_app, open_task):
    # Print relatado: palavras da mesma linha com alturas diferentes por 1-3 px embaralhavam a ordem e cada uma ou
    # duas palavras ganhavam etiqueta; e "em" não tarjado no meio partia o trecho
    ys = [302, 299, 304, 300, 303, 298]
    words = [labelled(1, (80 + i * 75, ys[i], 140 + i * 75, ys[i] + 25), "Endereço residencial") for i in range(6)]
    words.append(labelled(1, (80 + 6 * 75 + 40, 301, 80 + 6 * 75 + 120, 326), "Endereço residencial"))  # depois de "em"
    tid = live_app.seed_task("alturas.pdf", redactions=list(reversed(words)))   # ordem embaralhada de propósito
    open_task(tid)
    assert visible_tags(page, "Endereço residencial") == 1
    # a etiqueta fica na primeira palavra (a mais à esquerda)
    first = page.evaluate("""() => { const b = [...document.querySelectorAll('#layer-1 .redaction-box')]
        .find(e => getComputedStyle(e, '::before').display !== 'none'); return parseFloat(b.style.left); }""")
    lefts = page.evaluate("() => [...document.querySelectorAll('#layer-1 .redaction-box')].map(e => parseFloat(e.style.left))")
    assert first == min(lefts)


def test_tag_stays_inside_its_box_and_never_covers_the_line_above(page, live_app, open_task):
    # Print relatado: a etiqueta desenhada ACIMA da caixa da linha de baixo parecia uma tarja "CPF" sobre outra palavra
    tid = live_app.seed_task("dentro.pdf", redactions=[labelled(1, (300, 300, 520, 330), "CPF", type_="signature")])
    open_task(tid)
    inside = page.evaluate("""() => { const b = document.querySelector('#layer-1 .redaction-box');
        const st = getComputedStyle(b, '::before'); return parseFloat(st.top) >= 0; }""")
    assert inside


def test_tag_of_a_short_first_word_is_not_hidden_by_the_next_box(page, live_app, open_task):
    words = [labelled(1, (100, 300, 140, 325), "Endereço residencial"), labelled(1, (150, 300, 260, 325), "Endereço residencial")]
    tid = live_app.seed_task("curta.pdf", redactions=words)
    open_task(tid)
    z = page.evaluate("""() => [...document.querySelectorAll('#layer-1 .redaction-box')]
        .map(b => [b.classList.contains('no-tag'), parseInt(getComputedStyle(b).zIndex) || 0])""")
    tagged = [zi for no_tag, zi in z if not no_tag]
    others = [zi for no_tag, zi in z if no_tag]
    assert tagged and all(t > o for t in tagged for o in others)

# SPDX-License-Identifier: AGPL-3.0-or-later
"""Rotas do gerenciador de modelos de documento (/doc-templates/*), como um APIRouter separado.

O app_service injeta o que é dele (achar a tarefa, a pasta, as tarjas revisadas, o guarda da Administração): o
pacote não importa o app e pode virar um serviço próprio. Todas as rotas exigem a Administração ligada: um modelo
muda o que é tarjado.

Nada daqui devolve texto do documento: o teste devolve pontuação, rótulos e contagens; o rascunho devolve o modelo
(rótulos e frases fixas que o administrador vai revisar).
"""
import glob
import json
import os

from fastapi import APIRouter, Body, HTTPException

from utils import doc_templates
from utils.doc_templates import draft, engine, schema


def _page_size(task_dir, base, page, redactions):
    for r in redactions:
        if r.get("page") == page and r.get("image_width") and r.get("image_height"):
            return float(r["image_width"]), float(r["image_height"])
    png = os.path.join(task_dir, "00_original_images", f"{base}_page_{page}.png")
    if os.path.exists(png):
        from PIL import Image
        with Image.open(png) as im:
            return float(im.size[0]), float(im.size[1])
    return None


def task_pages(task_dir, base, input_path, redactions):
    """Palavras de cada página na escala das tarjas: texto digital do PDF de entrada (quando tem) ou o OCR salvo.
    Levanta HTTPException 409 se não houver nenhuma das duas fontes (PDF apagado e OCR removido pelo purge)."""
    from utils.verifier import _words_to_grounding, page_words
    pages = []
    native_doc = None
    if input_path and os.path.exists(input_path):
        import fitz
        native_doc = fitz.open(input_path)
    try:
        n = len(native_doc) if native_doc is not None else len(glob.glob(os.path.join(task_dir, "01_ocr_results",
                                                                                         "page_*.json")))
        for page in range(1, n + 1):
            words = []
            size = _page_size(task_dir, base, page, redactions)
            if native_doc is not None:
                p = native_doc[page - 1]
                scale = (size[0] / p.rect.width) if size else float(os.getenv("BASE_DPI", "300")) / 72.0
                words = _words_to_grounding(page_words(p))
                for w in words:
                    b = w["box"]
                    w["box"] = {"x": b["x"] * scale, "y": b["y"] * scale, "w": b["w"] * scale, "h": b["h"] * scale}
            if len(words) < 5:  # página digitalizada: o OCR salvo
                path = os.path.join(task_dir, "01_ocr_results", f"page_{page}.json")
                try:
                    with open(path, encoding="utf-8") as fh:
                        words = [w for w in json.load(fh) if isinstance(w, dict) and "box" in w] or words
                except (OSError, ValueError):
                    pass
            pages.append(words)
    finally:
        if native_doc is not None:
            native_doc.close()
    if not any(pages):
        raise HTTPException(status_code=409, detail="Sem texto deste documento: o PDF de entrada e o OCR não existem "
                                                    "mais (apagados ou purge). Processe o documento de novo.")
    return pages


def boxes_by_page(redactions):
    boxes, labels = {}, {}
    for r in redactions:
        try:
            x0, y0, x1, y1 = (float(v) for v in r["coords"])
            page = int(r["page"])
        except (KeyError, TypeError, ValueError):
            continue
        boxes.setdefault(page, []).append({"x": min(x0, x1), "y": min(y0, y1), "w": abs(x1 - x0), "h": abs(y1 - y0)})
        labels.setdefault(page, []).append(r.get("label") or ("Assinatura" if r.get("type") == "signature" else ""))
    return boxes, labels


def make_router(deps):
    """deps: require_admin(), task_source(task_id) -> (pasta da tarefa, nome base, PDF de entrada, tarjas,
    revisadas: o revisor salvou no editor)."""
    router = APIRouter(prefix="/doc-templates", tags=["modelos de documento"])

    def guard():
        deps["require_admin"]()

    @router.get("")
    def list_templates():
        guard()
        items, errors = schema.load_all()
        return {"modelos": items, "erros": errors, "ligado": doc_templates.enabled(),
                "inspecao": doc_templates.inspection_mode()}

    @router.post("/rascunho")
    def make_draft(payload: dict = Body(...)):
        """{"task_id", "ia": bool, "nome"}: rascunho a partir do documento revisado (não é salvo)."""
        guard()
        task_dir, base, input_path, redactions, reviewed = deps["task_source"](str(payload.get("task_id") or ""))
        if not reviewed or not redactions:
            # sugestões da IA não revisadas não ensinam modelo: só as tarjas que o revisor confirmou e salvou
            raise HTTPException(status_code=409, detail="O documento não tem tarjas revisadas: revise e clique em "
                                                        "Salvar no editor antes.")
        pages = task_pages(task_dir, base, input_path, redactions)
        boxes, labels = boxes_by_page(redactions)
        result, report = draft.build(pages, boxes, labels, name=payload.get("nome") or None)
        if payload.get("ia"):
            result, report["ia"] = draft.ai_suggest(result, pages, boxes)
        result["id"] = schema.free_id(result["id"])  # salvar o rascunho nunca substitui um modelo existente
        if not result["reconhecimento"]["ancoras"] or not result["campos"]:
            report["aviso"] = ("Faltam âncoras ou campos: complete à mão (documento em texto corrido ou "
                               "digitalizado costuma não ter rótulos).")
        return {"modelo": result, "relatorio": report}

    @router.post("/testar")
    def test_template(payload: dict = Body(...)):
        """{"task_id", "modelo": {...}} ou {"task_id", "id"}: o modelo reconhece o documento? Só contagens."""
        guard()
        data = payload.get("modelo") or schema.get(str(payload.get("id") or ""))
        if data is None:
            raise HTTPException(status_code=404, detail="Modelo não encontrado")
        try:
            template = schema.validate(data)
        except schema.TemplateError as e:
            raise HTTPException(status_code=400, detail=str(e))
        task_dir, base, input_path, redactions, _ = deps["task_source"](str(payload.get("task_id") or ""))
        pages = task_pages(task_dir, base, input_path, redactions)
        others = [t for t in schema.load_all()[0] if t["id"] != template["id"]]
        found = engine.match([template] + others, pages)
        mine = engine.match([template], pages)
        result, missing = engine.apply(template, pages)
        fields = {}
        for page, slot in result.items():
            for label, occ in slot["campos"].items():
                f = fields.setdefault(label, {"ocorrencias": 0, "palavras": 0, "truncado": False})
                f["ocorrencias"] += len(occ)
                f["palavras"] += sum(o["palavras"] for o in occ)
                f["truncado"] = f["truncado"] or any(o["truncado"] for o in occ)
        return {"reconhecido": mine["modelo"] is not None, "pontuacao": mine["pontuacao"],
                "ancoras_encontradas": mine["ancoras_encontradas"],
                "conflito_com": [i for i in found["ambiguos"] if i != template["id"]],
                "outro_modelo_vence": (found["modelo"] or {}).get("id") not in (None, template["id"]),
                "campos": fields, "faltando": list(dict.fromkeys(label for _, label in missing)), "paginas": len(pages)}

    @router.get("/{tid}")
    def get_template(tid: str):
        guard()
        try:
            item = schema.get(tid)
        except schema.TemplateError as e:
            raise HTTPException(status_code=400, detail=str(e))
        if item is None:
            raise HTTPException(status_code=404, detail="Modelo não encontrado")
        return item

    @router.post("")
    def save_template(payload: dict = Body(...)):
        """Cria ou atualiza. Sempre volta a rascunho se o conteúdo mudou (importar também)."""
        guard()
        try:
            return schema.save(payload)
        except schema.TemplateError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @router.post("/{tid}/aprovar")
    def approve_template(tid: str):
        """Aprovação explícita: só modelo aprovado com 'dispensa_ia' pode dispensar a IA de visão."""
        guard()
        try:
            if not schema.ID_RE.match(tid):
                raise schema.TemplateError("id inválido")
            return schema.save({"id": tid}, approve=True)
        except schema.TemplateError as e:
            raise HTTPException(status_code=404 if "não existe" in str(e) else 400, detail=str(e))

    @router.delete("/{tid}")
    def delete_template(tid: str):
        guard()
        try:
            if not schema.delete(tid):
                raise HTTPException(status_code=404, detail="Modelo não encontrado")
        except schema.TemplateError as e:
            raise HTTPException(status_code=400, detail=str(e))
        return {"status": "apagado", "id": tid}

    return router

# SPDX-License-Identifier: AGPL-3.0-or-later
"""Gerenciador de modelos de documento (/doc-templates/*): rascunho a partir de documento revisado, teste,
aprovação explícita, guarda da Administração. PDFs fictícios (I-01), sem IA de verdade (I-08)."""
import importlib
import json
import os

import pytest

pytest.importorskip("fastapi")

from test_doc_templates import CPF_A_FMT, TITLE, make_pdf, words_of  # noqa: E402


@pytest.fixture()
def svc(monkeypatch):
    import app_service
    importlib.reload(app_service)
    monkeypatch.setattr(app_service, "start_worker", lambda tid, **kw: None)
    from fastapi.testclient import TestClient
    return TestClient(app_service.app), app_service


def reviewed_task(c, mod, tmp_path, wanted=("Maria", "Silvana", "Teste", "529.982")):
    pdf = make_pdf(tmp_path / "licenca.pdf")
    with open(pdf, "rb") as fh:
        tid = c.post("/upload", files={"file": ("licenca.pdf", fh.read())}).json()["task_id"]
    words = words_of(mod.tasks[tid]["input_path"])[0]
    reds = [{"page": 1, "type": "pii", "label": "Nome de pessoa", "image_width": 595, "image_height": 842,
             "coords": [w["box"]["x"], w["box"]["y"], w["box"]["x"] + w["box"]["w"], w["box"]["y"] + w["box"]["h"]]}
            for w in words if any(t in w["text"] for t in wanted)]
    out = os.path.join(mod.OUTPUT_DIR, mod.task_base(mod.tasks[tid]))
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "manual_redactions.json"), "w", encoding="utf-8") as fh:
        json.dump(reds, fh)
    mod.tasks[tid].update(completed=True)
    return tid


def test_draft_test_save_approve_cycle(svc, tmp_path):
    c, mod = svc
    tid = reviewed_task(c, mod, tmp_path)
    r = c.post("/doc-templates/rascunho", json={"task_id": tid})
    assert r.status_code == 200, r.text
    body = r.json()
    draft = body["modelo"]
    assert draft["status"] == "rascunho" and TITLE in draft["reconhecimento"]["ancoras"]
    assert {f["rotulo"] for f in draft["campos"]} >= {"PROPRIETARIO", "CPF/CNPJ"}
    assert "Maria" not in json.dumps(draft) and CPF_A_FMT not in json.dumps(draft)   # valores não entram no modelo

    test = c.post("/doc-templates/testar", json={"task_id": tid, "modelo": draft}).json()
    assert test["reconhecido"] is True and test["campos"]["PROPRIETARIO"]["palavras"] >= 3
    assert "Maria" not in json.dumps(test)                                            # teste devolve só contagens

    saved = c.post("/doc-templates", json=draft).json()
    assert saved["status"] == "rascunho" and saved["versao"] == 1
    assert [m["id"] for m in c.get("/doc-templates").json()["modelos"]] == [saved["id"]]
    approved = c.post(f"/doc-templates/{saved['id']}/aprovar").json()
    assert approved["status"] == "aprovado"
    edited = c.post("/doc-templates", json=dict(approved, nome="Outro nome")).json()
    assert edited["status"] == "rascunho" and edited["versao"] == 2                  # editar desfaz a aprovação
    assert c.delete(f"/doc-templates/{saved['id']}").json()["status"] == "apagado"
    assert c.get(f"/doc-templates/{saved['id']}").status_code == 404


def test_imported_approved_template_becomes_draft(svc):
    c, _ = svc
    t = {"id": "importado", "status": "aprovado", "dispensa_ia": True,
         "reconhecimento": {"ancoras": ["FRASE FIXA UM", "FRASE FIXA DOIS"]}, "campos": [{"rotulo": "CPF"}]}
    assert c.post("/doc-templates", json=t).json()["status"] == "rascunho"


def test_draft_with_ai_uses_masked_text(svc, tmp_path, monkeypatch):
    c, mod = svc
    tid = reviewed_task(c, mod, tmp_path)
    sent = []

    def fake(self, prompt, system_prompt=None, only=None, vision_model=False):
        sent.append((prompt, vision_model))
        return {"nome": "Licença fictícia", "ancoras": [], "rotulos": [{"rotulo": "Fone", "tipo": "telefone"}]}, {}
    from utils import ai_client
    monkeypatch.setattr(ai_client.AIClient, "analyze_text", fake)
    body = c.post("/doc-templates/rascunho", json={"task_id": tid, "ia": True}).json()
    assert "Fone" in [f["rotulo"] for f in body["modelo"]["campos"]] and "IA sugeriu" in body["relatorio"]["ia"]
    prompt, vision = sent[0]
    assert vision is True and "Maria" not in prompt and "529" not in prompt


def test_draft_needs_review_and_a_text_source(svc, tmp_path):
    c, mod = svc
    tid = reviewed_task(c, mod, tmp_path, wanted=())
    assert c.post("/doc-templates/rascunho", json={"task_id": tid}).status_code == 409   # sem tarjas revisadas
    tid = reviewed_task(c, mod, tmp_path)
    os.remove(mod.tasks[tid]["input_path"])
    r = c.post("/doc-templates/rascunho", json={"task_id": tid})
    assert r.status_code == 409 and "OCR" in r.json()["detail"]
    assert c.post("/doc-templates/rascunho", json={"task_id": "nao-e-uuid"}).status_code == 404


def test_invalid_template_and_ids(svc):
    c, _ = svc
    assert c.post("/doc-templates", json={"id": "../../x"}).status_code == 400
    assert c.get("/doc-templates/..%2Fx").status_code in (400, 404)
    assert c.post("/doc-templates/nao-existe/aprovar").status_code == 404


def test_template_manager_requires_admin(svc, monkeypatch):
    c, _ = svc
    monkeypatch.setenv("ADMIN_ENABLED", "0")
    assert c.get("/doc-templates").status_code == 404
    assert c.post("/doc-templates", json={}).status_code == 404


def test_template_writes_from_another_site_are_refused(svc):
    c, _ = svc
    t = {"id": "x-site", "reconhecimento": {"ancoras": ["A B"]}, "campos": [{"rotulo": "CPF"}]}
    assert c.post("/doc-templates", json=t, headers={"Origin": "https://atacante.example"}).status_code == 403


def test_healthz_answers_the_kubernetes_probe_host(svc):
    c, _ = svc
    assert c.get("/healthz", headers={"Host": "10.1.2.3:8001"}).status_code == 200
    assert c.get("/api/info", headers={"Host": "10.1.2.3:8001"}).status_code == 421   # o resto continua protegido


def test_draft_refuses_unreviewed_ai_suggestions(svc, tmp_path):
    c, mod = svc
    tid = reviewed_task(c, mod, tmp_path)
    out = os.path.join(mod.OUTPUT_DIR, mod.task_base(mod.tasks[tid]))
    os.replace(os.path.join(out, "manual_redactions.json"), os.path.join(out, "redactions_metadata.json"))
    r = c.post("/doc-templates/rascunho", json={"task_id": tid})
    assert r.status_code == 409 and "Salvar" in r.json()["detail"]


def test_draft_never_takes_the_id_of_an_existing_template(svc, tmp_path):
    """Rascunho com o mesmo nome de um modelo aprovado: id novo; salvar não troca o aprovado."""
    c, mod = svc
    tid = reviewed_task(c, mod, tmp_path)
    first = c.post("/doc-templates/rascunho", json={"task_id": tid, "nome": "Licenca ficticia"}).json()["modelo"]
    saved = c.post("/doc-templates", json=first).json()
    assert c.post(f"/doc-templates/{saved['id']}/aprovar").json()["status"] == "aprovado"
    again = c.post("/doc-templates/rascunho", json={"task_id": tid, "nome": "Licenca ficticia"}).json()["modelo"]
    assert again["id"] == f"{saved['id']}-2"
    c.post("/doc-templates", json=again)
    assert c.get(f"/doc-templates/{saved['id']}").json()["status"] == "aprovado"
    assert c.post("/doc-templates/rascunho", json={"task_id": tid, "nome": "Licenca ficticia"}).json()["modelo"]["id"] \
        == f"{saved['id']}-3"

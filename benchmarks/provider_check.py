# SPDX-License-Identifier: AGPL-3.0-or-later
"""Verificação de um provedor de IA ANTES de usá-lo com documentos reais (procedimento: docs/procedimento-ia-externa.md).

Roda o caminho de verdade do projeto (cliente de IA, trava de saída, descoberta de endereços, agente com
ferramentas, inspeção de modelo de documento, rascunho de modelo com IA) contra o provedor configurado, usando SÓ
DADOS FICTÍCIOS gerados aqui. Não aceita PDF de entrada de propósito.

    python -m benchmarks.provider_check --preset gemini --key-env GEMINI_API_KEY --model gemini-flash-lite-latest
    python -m benchmarks.provider_check            # usa a configuração atual (.env + Administração)

Saída: uma linha por verificação (OK / FALHOU / PULADA) e um relatório JSON em output/ (sem chave, sem texto de
resposta). Código de saída 0 = tudo OK (ou pulado com motivo), 1 = alguma falha.
"""
import argparse
import json
import os
import sys
import tempfile
import time
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

PRESETS = {
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai",
    "openai": "https://api.openai.com/v1",
    "anthropic": "https://api.anthropic.com/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "mistral": "https://api.mistral.ai/v1",
    "ollama": "http://localhost:11434",
    "lmstudio": "http://localhost:1234/v1",
}
CPF = "529.982.247-25"           # fictícios (scripts/audit_public_tree.py, ALLOWED_CPFS)
CPF2 = "111.444.777-35"
ADDRESS = "Travessa dos Testes, 45, Bairro Imaginario, Cidade Ficticia - UF"
FORM_LINES = [
    "SECRETARIA FICTICIA DE TESTES AMBIENTAIS",
    "LICENCA DE EXEMPLO PARA TESTES AUTOMATIZADOS",
    f"PROPRIETARIO: Maria Silvana Teste       CPF/CNPJ: {CPF}",
    "Fone: (65) 99999-0000",
    f"ENDERECO: {ADDRESS}",
    "Nome do empreendimento: Fazenda Modelo",
]


def configure(preset=None, key_env=None, model=None):
    """Aplica no ambiente DESTE processo (não grava nada). Devolve a descrição sem a chave."""
    if preset:
        os.environ["AI_PROVIDER"] = "ollama" if preset == "ollama" else "openai"
        os.environ["AI_BASE_URL"] = PRESETS[preset]
    if key_env:
        os.environ["AI_API_KEY"] = os.environ.get(key_env, "")
    if model:
        os.environ["AI_VISION_MODEL"] = model
        os.environ["AI_TEXT_MODEL"] = model
        os.environ["SECOND_LOOK_MODEL"] = model
    os.environ.setdefault("PRIVIO_RUNTIME_DIR", tempfile.mkdtemp(prefix="privio_check_"))  # disjuntor isolado
    for k in ("AI_SECONDARY_PROVIDER", "SECOND_LOOK_BASE_URL", "SECOND_LOOK_API_KEY"):  # chave de outro provedor
        os.environ.pop(k, None)
    from utils.ai_client import configured_backends
    return configured_backends()[0].describe()


def _result(name, status, detail="", **numbers):
    return {"verificacao": name, "status": status, "detalhe": str(detail)[:200], **numbers}


def check_egress_block():
    """Destino externo sem liberação: a chamada nem sai."""
    from utils import egress
    from utils.ai_client import AIClient, configured_backends
    url = configured_backends()[0].base_url
    if not egress.is_external(url):
        return _result("trava_de_saida", "PULADA", "servidor local: nada a bloquear")
    before = os.environ.pop("AI_ALLOW_EXTERNAL", None)
    try:
        egress._sent.clear()
        response, _ = AIClient().analyze_text('Responda {"ok": true}', vision_model=True)
        blocked = isinstance(response, dict) and response.get("egress_blocked") and egress.sent() == []
        return _result("trava_de_saida", "OK" if blocked else "FALHOU",
                       "bloqueada antes de sair" if blocked else "a chamada não foi bloqueada")
    finally:
        if before is not None:
            os.environ["AI_ALLOW_EXTERNAL"] = before


def check_connection():
    from utils.ai_client import configured_backends
    t0 = time.time()
    ok, why = configured_backends()[0].probe(vision=True, timeout=20)
    return _result("conexao_e_chave", "OK" if ok else "FALHOU", why, segundos=round(time.time() - t0, 2))


def check_chat_json():
    from utils.ai_client import AIClient
    t0 = time.time()
    response, metrics = AIClient().analyze_text('Responda exatamente com o JSON {"ok": true}', vision_model=True)
    ok = isinstance(response, dict) and response.get("ok") is True
    return _result("chat_json", "OK" if ok else "FALHOU", "" if ok else (response or {}).get("error", "fora do formato"),
                   segundos=round(time.time() - t0, 2), tokens_entrada=(metrics or {}).get("input_tokens", 0),
                   tokens_saida=(metrics or {}).get("output_tokens", 0))


def _form_pdf(folder):
    import fitz
    path = os.path.join(folder, "formulario_ficticio.pdf")
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    for i, line in enumerate(FORM_LINES):
        page.insert_text((60, 70 + 26 * i), line, fontsize=11)
    doc.save(path)
    doc.close()
    return path


def check_vision_addresses(folder):
    """O pedido de endereços do pipeline (utils/address_redactor.py), com imagem e texto da página fictícia."""
    import logging

    import fitz

    from utils.address_redactor import AddressRedactor
    from utils.session import Session
    pdf = _form_pdf(folder)
    png = os.path.join(folder, "pagina_1.png")
    with fitz.open(pdf) as doc:
        doc[0].get_pixmap(dpi=110).save(png)
        text = doc[0].get_text()
    session = Session(pdf, output_dir=os.path.join(folder, "trabalho"))
    try:
        redactor = AddressRedactor(session, logging.getLogger("provider_check"))
        t0 = time.time()
        redactor.run_discovery([png], page_texts=[" ".join(text.split())])
        secs = round(time.time() - t0, 2)
    finally:
        session.close()
    if 1 in redactor.failed_pages:
        return _result("visao_enderecos", "FALHOU", redactor.failed_pages[1], segundos=secs)
    found = redactor.results.get(1, [])
    personal = [a for a in found if a.get("type") == "pessoal" and "travessa" in a.get("text", "").lower()]
    return _result("visao_enderecos", "OK" if personal else "FALHOU",
                   "endereço residencial fictício achado e classificado" if personal else
                   f"{len(found)} endereço(s), nenhum pessoal com o endereço fictício", segundos=secs,
                   enderecos=len(found))


def check_agent_tools():
    """Agente com ferramentas (segundo olhar): acha o CPF fictício no texto."""
    from utils import second_look
    text = f"Requerente: Joao Ficticio de Teste\nCPF: {CPF2}\nTelefone: (65) 98888-0000\nAssunto: pedido de licenca"
    t0 = time.time()
    items, info = second_look.run_agent(text, ["cpf", "telefone"])
    secs = round(time.time() - t0, 2)
    if items is None:
        return _result("agente_ferramentas", "FALHOU", info.get("erro"), segundos=secs)
    digits = {"".join(c for c in v if c.isdigit()) for _, v in items}
    ok = CPF2.replace(".", "").replace("-", "") in digits
    return _result("agente_ferramentas", "OK" if ok else "FALHOU", "" if ok else "CPF fictício não apontado",
                   segundos=secs, passos=info.get("passos"), achados=len(items))


def check_template_inspection(repeats=5):
    """Inspeção de modelo: o agente lê o texto já tarjado (█) e aponta o endereço que ficou de fora.

    Repete: a resposta do modelo varia (medido com o Gemini Flash-Lite: errou 1 de 7). Com "dispensar a IA de
    visão", um erro aqui é um endereço sem tarja; por isso só passa com acerto em TODAS as repetições."""
    from utils import second_look
    text = ("SECRETARIA FICTICIA DE TESTES AMBIENTAIS\nPROPRIETARIO: █████ █████ █████   CPF/CNPJ: █████\n"
            f"Observacao: o proprietario reside na {ADDRESS}.")
    hits, invented, failures, secs = 0, 0, [], 0.0
    for i in range(repeats):
        t0 = time.time()
        items, info = second_look.run_agent(text, ["cpf", "endereco_residencial"])
        secs += time.time() - t0
        if items is None:
            failures.append(info.get("erro"))
            continue
        hits += any(second_look.type_id_for(t) == "endereco_residencial" and "Travessa" in v for t, v in items)
        invented += any("█" in v for _, v in items)
    ok = hits == repeats and not invented
    # chamada recusada (ex.: limite de uso) não é erro do modelo: fica "não medida", mas também não aprova
    detail = (f"acertou {hits}/{repeats - len(failures)}"
              + (f"; {len(failures)} não medida(s) por falha de chamada (rode de novo)" if failures else "")
              + ("; apontou trecho já tarjado" if invented else "")
              + ("" if ok else " — não use 'dispensar a IA de visão' com este modelo"))
    return _result("inspecao_modelo", "OK" if ok else "FALHOU", detail, segundos=round(secs, 2),
                   acertos=hits, repeticoes=repeats)


def check_template_draft(folder):
    """Rascunho de modelo com ajuda da IA: só texto mascarado sai; sugestões conferidas no texto."""
    from utils.doc_templates import draft, schema
    from utils.verifier import _words_to_grounding, page_words
    import fitz
    pdf = _form_pdf(folder)
    with fitz.open(pdf) as doc:
        pages = [_words_to_grounding(page_words(p)) for p in doc]
    boxes = [dict(w["box"]) for w in pages[0] if any(t in w["text"] for t in ("Maria", "Silvana", "Teste", "529.982"))]
    base, _ = draft.build(pages, {1: boxes})
    n_fields = len(base["campos"])
    t0 = time.time()
    result, note = draft.ai_suggest(base, pages, {1: boxes})
    secs = round(time.time() - t0, 2)
    ok = note.startswith("IA sugeriu")
    try:
        schema.validate(result)
    except schema.TemplateError as e:
        ok, note = False, f"rascunho inválido: {e}"
    return _result("rascunho_modelo_ia", "OK" if ok else "FALHOU", note, segundos=secs,
                   campos_antes=n_fields, campos_depois=len(result["campos"]))


def check_full_pipeline():
    from benchmarks.env import get_ocr_config
    if not get_ocr_config():
        return _result("pipeline_completo", "PULADA", "Tesseract não encontrado (TESSERACT_PATH)")
    return _result("pipeline_completo", "PULADA", "rode o exemplo: python main.py --input examples/sample_input.pdf")


def run(preset=None, key_env=None, model=None, out_dir=None, repeats=5, per_minute=10):
    described = configure(preset, key_env, model)
    if described["externo"]:  # ritmo abaixo do limite por minuto dos planos gratuitos (medido no Gemini: 15)
        os.environ.setdefault("AI_REQUESTS_PER_MINUTE", str(per_minute))
    os.environ["AI_ALLOW_EXTERNAL"] = os.environ.get("AI_ALLOW_EXTERNAL") or "1"  # só neste processo e para fictícios
    folder = tempfile.mkdtemp(prefix="privio_check_dados_")
    results = [check_egress_block()]
    os.environ["AI_ALLOW_EXTERNAL"] = "1"
    for fn in (check_connection, check_chat_json, lambda: check_vision_addresses(folder), check_agent_tools,
               lambda: check_template_inspection(repeats), lambda: check_template_draft(folder), check_full_pipeline):
        try:
            results.append(fn())
        except Exception as e:  # uma verificação quebrada não esconde as outras
            results.append(_result(getattr(fn, "__name__", "verificacao"), "FALHOU", f"{type(e).__name__}: {e}"))
    from utils import egress, ratelimit
    report = {"quando": datetime.now().isoformat(timespec="seconds"), "servidor": described,
              "pedidos_por_minuto": ratelimit.per_minute(described["endereco"]) or "sem limite",
              "limite_de_uso_esgotado": ratelimit.hit(),  # 429 que não passou com a espera pedida pelo provedor
              "destinos_externos_usados": egress.sent(), "resultados": results,
              "aprovado": all(r["status"] != "FALHOU" for r in results)}
    out_dir = out_dir or os.path.join(ROOT, "output")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"provider_check_{datetime.now():%Y%m%d_%H%M%S}.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, ensure_ascii=False)
    report["arquivo"] = path
    return report


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--preset", choices=sorted(PRESETS), help="endereço do provedor (senão, a configuração atual)")
    ap.add_argument("--key-env", help="NOME da variável de ambiente com a chave (a chave nunca vai na linha de comando)")
    ap.add_argument("--model", help="modelo (precisa aceitar imagens e ferramentas)")
    ap.add_argument("--out", help="pasta do relatório (padrão: output/, fora do git)")
    ap.add_argument("--repeticoes", type=int, default=5, help="repetições da inspeção (padrão 5; todas precisam acertar)")
    ap.add_argument("--por-minuto", type=float, default=10, help="ritmo dos pedidos a um provedor externo "
                    "(padrão 10; o plano gratuito do Gemini aceita 15 por minuto)")
    args = ap.parse_args(argv)
    from dotenv import load_dotenv
    load_dotenv()
    from utils import settings
    settings.apply()
    report = run(args.preset, args.key_env, args.model, args.out, max(1, args.repeticoes), args.por_minuto)
    s = report["servidor"]
    print(f"Servidor: {s['endereco']} · modelo {s['modelo_visao']} · externo={s['externo']} · com_chave={s['com_chave']}")
    for r in report["resultados"]:
        extra = ", ".join(f"{k}={v}" for k, v in r.items() if k not in ("verificacao", "status", "detalhe"))
        print(f"  [{r['status']:7}] {r['verificacao']:<22} {r['detalhe']}{' (' + extra + ')' if extra else ''}")
    print(f"Resultado: {'APROVADO' if report['aprovado'] else 'REPROVADO'} · relatório: {report['arquivo']}")
    return 0 if report["aprovado"] else 1


if __name__ == "__main__":
    sys.exit(main())

# SPDX-License-Identifier: AGPL-3.0-or-later
"""Segundo olhar: um agente local curto revê as páginas em dúvida e só pode ACRESCENTAR proteção.

    SECOND_LOOK=1                     liga (desligado por padrão)
    SECOND_LOOK_SCOPE=revisao         só páginas que já iam para revisão (padrão) | todas
    SECOND_LOOK_MODEL=gemma4:e4b      modelo (medido: o melhor custo/benefício; docs/benchmarks.md)
    SECOND_LOOK_BASE_URL              API no padrão da OpenAI (padrão: o servidor de IA principal; Ollama -> {url}/v1)
    SECOND_LOOK_API_KEY / SECOND_LOOK_TIMEOUT (120) / SECOND_LOOK_MAX_TURNS (6)

Como funciona (o "harness" medido no benchmark, mas pela API, sem aplicativo): o modelo recebe instruções curtas e
duas ferramentas, `ler_pagina` (linhas numeradas do texto da página) e `buscar` (linhas que contêm um termo), e devolve
os dados pessoais em JSON, copiados do texto. Regras que não dependem do modelo:
    * só os tipos que o perfil de política pede;
    * cada valor devolvido precisa ser LOCALIZADO nas palavras do OCR; o que não for localizado é descartado
      (o modelo pode inventar: medido, um Qwen 9B inventou um valor) e contado no log;
    * só acrescenta: tarja (perfil "tarjar") ou região a revisar (perfil "alertar"); nunca remove nada;
    * falha do agente (servidor fora, sem resposta válida) manda a página para revisão.
"""
import json
import logging
import os
import re
import unicodedata

import time

import requests

from utils import egress, ratelimit

logger = logging.getLogger("second_look")

# tipo do catálogo -> como o modelo deve chamá-lo (e apelidos que ele costuma usar)
TYPE_NAMES = {
    "cpf": ["cpf"], "rg": ["rg", "identidade", "carteira de identidade"], "cnh": ["cnh", "habilitação"],
    "cns": ["cns", "cartão sus", "cartao sus"], "pis_nis": ["pis", "nis", "pis/nis", "pis_nis"],
    "telefone": ["telefone", "celular", "fone"], "email": ["email", "e-mail"],
    "data_nascimento": ["data de nascimento", "data_nascimento", "nascimento"],
    "placa_veiculo": ["placa", "placa de veículo", "placa_veiculo"],
    "nome_pessoa": ["nome", "nome de pessoa", "nome_pessoa", "pessoa"], "filiacao": ["filiação", "filiacao", "mãe", "pai"],
    # só na inspeção dos modelos de documento (o segundo olhar comum deixa endereço para a fase de visão)
    "endereco_residencial": ["endereço", "endereco", "endereço residencial", "endereco_residencial", "residência"],
}
LABEL = {"cpf": "CPF", "rg": "RG", "cnh": "CNH", "cns": "CNS (cartão SUS)", "pis_nis": "PIS/NIS",
         "telefone": "telefone", "email": "e-mail", "data_nascimento": "data de nascimento",
         "placa_veiculo": "placa de veículo", "nome_pessoa": "nome de pessoa", "filiacao": "filiação (nome da mãe/pai)",
         "endereco_residencial": "endereço residencial de pessoa"}

SYSTEM = ("Você revisa páginas de documentos lidas por OCR. Use a ferramenta ler_pagina para ler a página (e buscar, se "
          "precisar). Copie os valores EXATAMENTE como aparecem no texto. Não invente. Responda só com o JSON pedido.")

TOOLS = [
    {"type": "function", "function": {
        "name": "ler_pagina", "description": "Devolve as linhas numeradas do texto da página (OCR).",
        "parameters": {"type": "object", "properties": {
            "inicio": {"type": "integer", "description": "primeira linha (1 = início)"},
            "fim": {"type": "integer", "description": "última linha"}}}}},
    {"type": "function", "function": {
        "name": "buscar", "description": "Devolve as linhas da página que contêm o termo (sem diferenciar acentos/maiúsculas).",
        "parameters": {"type": "object", "properties": {"termo": {"type": "string"}}, "required": ["termo"]}}},
]


def enabled():
    return os.getenv("SECOND_LOOK", "0").strip().lower() in ("1", "true", "sim")


def scope():
    return "todas" if os.getenv("SECOND_LOOK_SCOPE", "revisao").strip().lower() == "todas" else "revisao"


def _strip(text):
    return unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode("ascii").lower()


def _endpoint():
    base = os.getenv("SECOND_LOOK_BASE_URL")
    if not base:
        provider = (os.getenv("AI_PROVIDER") or "ollama").strip().lower()
        root = os.getenv("AI_BASE_URL") or (os.getenv("OLLAMA_API_URL", "http://localhost:11434")
                                            if provider == "ollama" else "http://localhost:1234/v1")
        base = root.rstrip("/") + ("/v1" if provider == "ollama" and not root.rstrip("/").endswith("/v1") else "")
    return base.rstrip("/") + "/chat/completions"


def model():
    """SECOND_LOOK_MODEL; sem ele, o modelo da IA principal (mesmo servidor), e só então o padrão antigo."""
    if os.getenv("SECOND_LOOK_MODEL"):
        return os.getenv("SECOND_LOOK_MODEL")
    if not os.getenv("SECOND_LOOK_BASE_URL"):
        main = os.getenv("AI_VISION_MODEL") or os.getenv("OLLAMA_VISION_MODEL")
        if main:
            return main
    return "gemma4:e4b"


def _task(types):
    # Medido com um provedor na nuvem (benchmarks/provider_check.py): mostrar só "cpf" como exemplo de tipo fazia o
    # modelo devolver o nome por extenso ou nada para endereço no texto corrido; com os identificadores, o texto
    # corrido pedido e o "█ já protegido", acertou em todas as repetições.
    names = "; ".join(f"{t} ({LABEL[t]})" for t in types if t in LABEL)
    return ("Leia a página com a ferramenta ler_pagina e liste TODOS os dados pessoais destes tipos: " + names + ". "
            "Procure também no texto corrido, não só em campos com rótulo. Trechos com █ já estão protegidos: "
            "ignore-os. Copie cada valor EXATAMENTE como aparece no texto. Não invente. Responda APENAS com JSON "
            'no formato {"achados": [{"tipo": "<um dos tipos acima>", "texto": "..."}]}; sem achados: {"achados": []}')


def _retry_wait(response):
    """Segundos pedidos pelo provedor num 429 (cabeçalho Retry-After ou "retryDelay": "33s" do Gemini), até 60."""
    return ratelimit.parse(response)[0]


def _int(value, default):
    try:
        return int(value or default)
    except (TypeError, ValueError):
        return default


def _run_tool(name, args, lines):
    if not isinstance(args, dict):  # argumentos fora do formato: a ferramenta responde vazio, o agente segue
        args = {}
    if name == "ler_pagina":
        start = max(1, _int(args.get("inicio"), 1))
        end = min(len(lines), _int(args.get("fim"), len(lines)))
        return "\n".join(f"{i}: {lines[i - 1]}" for i in range(start, end + 1)) or "(página vazia)"
    if name == "buscar":
        term = _strip(args.get("termo") or "")
        hits = [f"{i}: {line}" for i, line in enumerate(lines, 1) if term and term in _strip(line)]
        return "\n".join(hits) or "(nada encontrado)"
    return f"ferramenta desconhecida: {name}"


def run_agent(page_text, types, post=None):
    """Ciclo curto de agente. Devolve (itens [(tipo, texto)] ou None, info {passos, tokens, erro})."""
    post = post or requests.post
    lines = page_text.splitlines() or [page_text]
    model_name = model()
    # sem servidor próprio, o segundo olhar usa o servidor principal e a chave dele
    key = os.getenv("SECOND_LOOK_API_KEY") or ("" if os.getenv("SECOND_LOOK_BASE_URL") else os.getenv("AI_API_KEY", ""))
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    timeout = float(os.getenv("SECOND_LOOK_TIMEOUT", "120") or 120)
    max_turns = int(os.getenv("SECOND_LOOK_MAX_TURNS", "6") or 6)
    messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": _task(types)}]
    info = {"passos": 0, "tokens": 0, "erro": None}
    if ratelimit.should_pend():  # o documento vai ficar pendente e ser refeito: não gasta mais pedidos
        info["erro"] = "limite de uso do provedor de IA: documento pendente"
        return None, info
    try:  # o texto da página só sai da rede local com AI_ALLOW_EXTERNAL=1 (utils/egress.py)
        external = egress.check(_endpoint(), "Segundo olhar: servidor")
    except egress.ExternalBlocked as e:
        info["erro"] = str(e)
        return None, info
    if external:
        egress.record(_endpoint())
    for _ in range(max_turns):
        info["passos"] += 1
        try:
            payload = {"model": model_name, "messages": messages, "tools": TOOLS, "temperature": 0, "stream": False}
            ratelimit.pace(_endpoint())
            r = post(_endpoint(), headers=headers, timeout=timeout, json=payload, allow_redirects=False)
            for _ in range(2):  # limite por minuto: espera o que o provedor pede e tenta de novo
                wait, long = ratelimit.parse(r) if r.status_code == 429 else (0, True)
                if long:  # sem 429, ou cota esgotada (esperar aqui não adianta)
                    break
                time.sleep(wait)
                r = post(_endpoint(), headers=headers, timeout=timeout, json=payload, allow_redirects=False)
            if r.status_code == 429:
                ratelimit.note()
                raise RuntimeError("HTTP 429: limite de uso do provedor de IA")
            egress.refuse_redirect(r)
            if r.status_code >= 400:
                raise RuntimeError(f"HTTP {r.status_code}: {str(r.text)[:120]}")
            data = r.json()
        except Exception as e:
            info["erro"] = f"{type(e).__name__}: {str(e)[:160]}"
            return None, info
        try:  # corpo fora do formato (lista, número...) = falha desta página, nunca do documento inteiro
            info["tokens"] += _int((data.get("usage") or {}).get("prompt_tokens"), 0)
            msg = ((data.get("choices") or [{}])[0].get("message")) or {}
            calls = [c for c in (msg.get("tool_calls") or []) if isinstance(c, dict)]
        except (AttributeError, IndexError, TypeError):
            info["erro"] = "resposta do servidor fora do formato"
            return None, info
        if calls:
            messages.append({"role": "assistant", "content": msg.get("content") or "", "tool_calls": calls})
            for call in calls:
                fn = call.get("function") or {}
                try:
                    args = json.loads(fn.get("arguments") or "{}") if isinstance(fn.get("arguments"), str) \
                        else (fn.get("arguments") or {})
                except ValueError:
                    args = {}
                messages.append({"role": "tool", "tool_call_id": call.get("id", ""), "name": fn.get("name", ""),
                                 "content": _run_tool(fn.get("name", ""), args, lines)})
            continue
        content = str(msg.get("content") or "")
        match = re.search(r"\{.*\}", content, re.DOTALL)
        try:
            parsed = json.loads(match.group()) if match else None
        except ValueError:
            parsed = None
        if not isinstance(parsed, dict) or not isinstance(parsed.get("achados"), list):
            info["erro"] = "resposta sem o JSON pedido"
            return None, info
        return [(str(i.get("tipo", "")), str(i.get("texto", ""))) for i in parsed["achados"] if isinstance(i, dict)], info
    info["erro"] = f"sem resposta final em {max_turns} passos"
    return None, info


def type_id_for(label):
    key = _strip(label).strip()
    for type_id, names in TYPE_NAMES.items():
        # o modelo costuma devolver o nome que o pedido mostrou ("endereço residencial de pessoa"): vale também
        if key == type_id or key in (_strip(n) for n in names) or key == _strip(LABEL.get(type_id, "")):
            return type_id
    return None


_NAME_TOKEN = re.compile(r"^[A-Za-zÀ-ÿ][a-zà-ÿ'\-]+$|^[A-ZÀ-Þ][A-ZÀ-Þ'\-]+$")


NUMERIC_TYPES = ("cpf", "rg", "cnh", "cns", "pis_nis", "telefone")
_SERVICE_PHONE = re.compile(r"^(?:0?(?:800|300|500|900)|400[0-9]|300[0-9])")
_PLATE_CONTEXT = re.compile(r"placa|ve[ií]culo|renavam", re.IGNORECASE)


def core_value(type_id, value):
    """Tipos numéricos: só o trecho do primeiro ao último dígito ("12345678 SSP/MT" -> "12345678"): o órgão emissor
    e rótulos colados não são o dado (medido nos documentos reais: o agente incluía "SSP/MT" no RG)."""
    if type_id not in NUMERIC_TYPES:
        return value
    m = re.search(r"\d.*\d", value)
    return m.group() if m else value


def plausible(type_id, value, context=""):
    """
    O valor tem cara do tipo? As mesmas exigências das regras do pipeline (dígito verificador, formato). Medido no
    benchmark: sem isto, o agente acrescentava lixo de OCR ("CPF" de 12 dígitos, placa "BR4.47", nome "EEE ERR").
    Recusar aqui só deixa de ACRESCENTAR: a proteção do pipeline não muda.
    """
    from utils.detect import rules
    from utils.detect import validators as v
    from utils.validators import is_valid_cpf
    digits = re.sub(r"\D", "", value)
    if type_id == "cpf":
        return len(digits) == 11 and is_valid_cpf(digits)
    if type_id == "cns":
        return v.is_valid_cns(digits)
    if type_id == "pis_nis":
        return v.is_valid_pis(digits)
    if type_id == "telefone":
        # 0800/0300/4004...: número de serviço de empresa, não de pessoa (medido nos documentos reais)
        return rules._phone_ok(value, True) and not _SERVICE_PHONE.match(digits)
    if type_id == "email":
        return bool(rules.RULES_BY_TYPE["email"].value.search(value.strip()))
    if type_id == "data_nascimento":
        return bool(re.search(r"\d{1,2}\s?[/.\-]\s?\d{1,2}\s?[/.\-]\s?\d{2,4}|\d{1,2}º?\s+de\s+\w+\s+de\s+\d{4}", value))
    if type_id == "placa_veiculo":
        compact = rules._plate_canon(re.sub(r"[\s\-]", "", value.upper()))
        if not re.fullmatch(r"[A-Z]{3}\d[A-Z0-9]\d{2}", compact):
            return False
        # Mercosul (ABC1D23) vale sozinho; o formato antigo (ABC1234) exige "placa"/"veículo" perto, como nas regras
        return compact[4].isalpha() or bool(_PLATE_CONTEXT.search(context))
    if type_id in ("nome_pessoa", "filiacao"):
        tokens = [t for t in re.split(r"[\s,;]+", value.strip()) if t]
        big = [t for t in tokens if len(t) >= 3]
        if len(big) < 2 or not all(_NAME_TOKEN.match(t) for t in tokens if len(t) >= 3):
            return False
        # lixo de OCR: palavra sem vogal ou com a mesma letra repetida 3 vezes ("EEE", "SSFRUP")
        return all(re.search(r"[aeiouáéíóúâêôãõ]", t.lower()) and not re.search(r"(.)\1\1", t.lower()) for t in big)
    if type_id in ("rg", "cnh"):
        return 5 <= len(digits) <= 14
    if type_id == "endereco_residencial":  # ao menos 3 partes ("Rua X, 10"): uma palavra solta não é endereço
        return len([t for t in re.split(r"[\s,;]+", value.strip()) if t]) >= 3
    return True


def _norm_chars(text):
    return [(i, c) for i, c in enumerate(_strip(text)) if c.isalnum()]


def locate(value, grounding):
    """{id da palavra: {índices dos caracteres}} onde o valor aparece (comparando só letras e dígitos, em sequência
    de palavras consecutivas). Vazio se o valor não existe na página: é a defesa contra valores inventados."""
    target = "".join(c for _i, c in _norm_chars(value))
    if len(target) < 4:
        return {}
    stream = []  # (caractere, id da palavra, índice no texto da palavra)
    for wid, w in enumerate(grounding):
        for idx, ch in _norm_chars(w.get("text", "")):
            stream.append((ch, wid, idx))
    flat = "".join(c for c, _w, _i in stream)
    commands = {}
    pos = flat.find(target)
    while pos >= 0:  # TODAS as ocorrências: o mesmo nome/telefone pode aparecer mais de uma vez na página
        for ch, wid, idx in stream[pos:pos + len(target)]:
            commands.setdefault(wid, set()).add(idx)
        pos = flat.find(target, pos + len(target))
    # cobre a palavra inteira de nomes/e-mails (pontuação no meio), mas só as palavras tocadas
    return commands

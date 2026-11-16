# SPDX-License-Identifier: AGPL-3.0-or-later
"""Configuração pela tela Admin, guardada num arquivo local e aplicada como variáveis de ambiente.

O pipeline continua lendo só variáveis de ambiente; este módulo apenas as escreve. Ordem de valor: o que foi salvo
no Admin > .env/ambiente > padrão do código. "Restaurar padrão" (valor null) volta ao .env/ambiente.

O arquivo (PRIVIO_SETTINGS_FILE, padrão ./privio_settings.json) pode conter chaves de API: está no .gitignore e
no .dockerignore, é gravado de forma atômica e as chaves NUNCA voltam pela API (só "definida: sim/não").

Cada tarefa roda num processo novo que herda o ambiente do serviço; no Windows o processo reimporta o app_service,
que reaplica este arquivo. Itens com restart=True são lidos uma vez na subida do serviço.

Fora daqui de propósito: API_TOKEN, APP_HOST, APP_PORT, ALLOWED_HOSTS, ADMIN_ENABLED e pastas (só no .env: quem
mexe nelas pela web pode se trancar fora ou expor o serviço).
"""
import json
import math
import os
import tempfile
from datetime import datetime
from urllib.parse import urlsplit

from utils import egress

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROFILES = ("cpf_endereco", "lgpd_publicacao", "lgpd_interno", "gdpr", "saude_hipaa")


def _f(key, group, label, kind="text", help="", choices=None, restart=False, minimum=None, maximum=None,
       placeholder="", labels=None, section="", advanced=False):
    return {"key": key, "group": group, "label": label, "kind": kind, "help": help, "choices": list(choices or []),
            "restart": restart, "min": minimum, "max": maximum, "placeholder": placeholder,
            "labels": dict(labels or {}), "section": section, "advanced": advanced}


GROUPS = [
    {"id": "ia", "titulo": "IA principal", "descricao": "O servidor que lê as páginas (endereços e auditoria de "
                                                        "assinaturas). Nesta máquina por padrão; um provedor na "
                                                        "nuvem só recebe conteúdo com a liberação abaixo."},
    {"id": "ia_reserva", "titulo": "IA reserva", "descricao": "Opcional. Assume quando a principal falha; com a "
                                                              "verificação cruzada, também confere cada página."},
    {"id": "deteccao", "titulo": "Detecção e política", "descricao": "O que procurar por padrão. Cada envio ainda "
                                                                     "pode escolher o perfil na barra lateral do "
                                                                     "editor."},
    {"id": "ocr", "titulo": "OCR e verificação", "descricao": "Leitura das páginas (Tesseract) e conferência do PDF "
                                                              "final."},
    {"id": "operacao", "titulo": "Operação", "descricao": "Fila, tamanho dos arquivos e por quanto tempo eles ficam "
                                                          "guardados."},
]

PROVIDER_LABELS = {"ollama": "Ollama", "openai": "Padrão OpenAI (LM Studio, vLLM, servidor da organização, nuvem)"}
FIELDS = [
    _f("AI_PROVIDER", "ia", "Tipo de servidor", "choice", "Os atalhos acima preenchem este campo e o endereço.",
       ["ollama", "openai"], labels=PROVIDER_LABELS, section="Servidor"),
    _f("AI_BASE_URL", "ia", "Endereço", "url", "Ex.: http://localhost:11434 (Ollama) ou https://api.openai.com/v1",
       section="Servidor"),
    _f("AI_API_KEY", "ia", "Chave de API", "secret", "Só para provedores que pedem chave. Guardada só nesta máquina; "
       "nunca é mostrada de volta.", section="Servidor"),
    _f("AI_VISION_MODEL", "ia", "Modelo", "text", "Precisa aceitar imagens. \"Listar modelos\" mostra os que o "
       "servidor oferece.", section="Servidor"),
    _f("AI_VISION_TIMEOUT", "ia", "Tempo limite por página (s)", "number", "Aumente se o servidor for lento e as "
       "páginas estiverem indo para revisão por tempo esgotado.", minimum=10, maximum=3600, section="Servidor",
       advanced=True),
    _f("AI_ALLOW_EXTERNAL", "ia", "Permitir IA fora desta rede", "bool", "Ligado, imagens das páginas e o texto lido "
       "delas são enviados ao provedor configurado. Desligado, a chamada é bloqueada antes de sair e a página vai "
       "para revisão.", section="Envio para fora desta rede"),
    _f("AI_REQUESTS_PER_MINUTE", "ia", "Pedidos por minuto", "number", "Vazio = automático (12 num provedor "
       "externo, sem limite nesta rede); 0 = sem limite. Vale para todos os documentos juntos. Fique abaixo do "
       "limite do seu plano: fica mais lento, mas sem recusas.", minimum=0, maximum=10000,
       section="Limite de uso do provedor"),
    _f("AI_LIMIT_ACTION", "ia", "Quando a cota do provedor acabar", "choice", "Pendente: o documento fica sem PDF "
       "e é processado de novo sozinho mais tarde (as páginas são enviadas outra vez).", ["revisao", "pendente"],
       labels={"revisao": "Mandar as páginas para revisão", "pendente": "Deixar pendente e tentar de novo"},
       section="Limite de uso do provedor"),
    _f("AI_LIMIT_RETRY_MINUTES", "ia", "Pendente: tentar de novo a cada (min)", "number", "Depois de 24 tentativas, "
       "o documento segue para revisão.", minimum=1, maximum=1440, section="Limite de uso do provedor",
       advanced=True),
    _f("AI_SECONDARY_PROVIDER", "ia_reserva", "Tipo de servidor", "choice", "", ["", "ollama", "openai"],
       labels=dict(PROVIDER_LABELS, **{"": "Sem reserva"}), section="Servidor reserva"),
    _f("AI_SECONDARY_BASE_URL", "ia_reserva", "Endereço", "url", "", placeholder="http://localhost:1234/v1",
       section="Servidor reserva"),
    _f("AI_SECONDARY_API_KEY", "ia_reserva", "Chave de API", "secret", "Guardada só nesta máquina.",
       section="Servidor reserva"),
    _f("AI_SECONDARY_VISION_MODEL", "ia_reserva", "Modelo", "text", "", section="Servidor reserva"),
    _f("AI_CROSS_CHECK", "ia_reserva", "Verificação cruzada", "bool", "A reserva também lê cada página e os achados "
       "se somam (nunca reduz a proteção). Dobra o tempo de IA.", section="Servidor reserva"),
    _f("POLICY_PROFILE", "deteccao", "Perfil padrão", "choice", "O que é tarjado e o que só gera alerta "
       "(docs/catalogo-pii.md).", PROFILES, section="O que procurar"),
    _f("NER_ENGINE", "deteccao", "Detector de nomes", "choice", "Precisa do pacote opcional: pip install -e "
       "\".[nomes]\".", ["", "gliner"], labels={"": "Desligado", "gliner": "GLiNER (local)"},
       section="O que procurar"),
    _f("OCR_EXTRA_ENGINE", "deteccao", "Leitura extra de OCR", "choice", "Uma terceira leitura somada às duas do "
       "Tesseract. Precisa de pip install -e \".[ocr-extra]\".", ["", "rapidocr"],
       labels={"": "Desligada", "rapidocr": "RapidOCR (local)"}, section="O que procurar"),
    _f("SECOND_LOOK", "deteccao", "Segundo olhar", "bool", "Um agente revê as páginas em dúvida e só acrescenta "
       "tarjas. Usa o servidor da IA principal, salvo endereço próprio.", section="Segundo olhar"),
    _f("SECOND_LOOK_MODEL", "deteccao", "Modelo do segundo olhar", "text", "Precisa aceitar ferramentas (tools).",
       section="Segundo olhar"),
    _f("SECOND_LOOK_BASE_URL", "deteccao", "Endereço próprio", "url", "Vazio = o da IA principal.",
       section="Segundo olhar", advanced=True),
    _f("SECOND_LOOK_API_KEY", "deteccao", "Chave própria", "secret", "Vazio = a da IA principal.",
       section="Segundo olhar", advanced=True),
    _f("DOC_TEMPLATES", "deteccao", "Usar modelos de documento", "bool", "Reconhece documentos de layout conhecido "
       "e tarja os campos sem IA (seção Modelos de documento).", section="Modelos de documento"),
    _f("DOC_TEMPLATE_INSPECTION", "deteccao", "Inspeção depois do modelo", "choice", "Agente: lê o texto já "
       "tarjado e aponta o que ficou de fora (poucos tokens). Só regras: zero token, mas a página sem IA de visão "
       "vai para revisão.", ["agente", "regras"], labels={"agente": "Agente", "regras": "Só regras"},
       section="Modelos de documento"),
    _f("TESSERACT_PATH", "ocr", "Executável do Tesseract", "text", "Vazio = o que estiver no PATH.",
       section="Leitura"),
    _f("TESSERACT_LANG", "ocr", "Idioma do OCR", "text", "Ex.: por, por+eng.", section="Leitura", advanced=True),
    _f("BASE_DPI", "ocr", "DPI de leitura", "number", "300 é o medido como melhor; acima disso a leitura de CPF "
       "piora (docs/benchmarks.md).", minimum=72, maximum=1200, section="Leitura", advanced=True),
    _f("VERIFY_OCR", "ocr", "Reler o PDF final com OCR", "bool", "Recomendado. Desligado, toda página com imagem "
       "fica sem verificação e vai para revisão.", section="Verificação do PDF final"),
    _f("VERIFY_DPI", "ocr", "DPI da verificação", "number", "", minimum=72, maximum=1200,
       section="Verificação do PDF final", advanced=True),
    _f("MAX_PARALLEL_TASKS", "operacao", "Documentos ao mesmo tempo", "number", "Os demais esperam na fila.",
       restart=True, minimum=1, maximum=32, section="Fila e arquivos"),
    _f("MAX_UPLOAD_MB", "operacao", "Tamanho máximo do PDF (MB)", "number", "", restart=True, minimum=1,
       maximum=10000, section="Fila e arquivos"),
    _f("RETENTION_DAYS", "operacao", "Apagar documentos após (dias)", "number", "0 = nunca. As pastas de cada "
       "documento guardam imagens e texto das páginas: apague o que não precisa mais.", restart=True, minimum=0,
       maximum=3650, section="Retenção"),
]
BY_KEY = {f["key"]: f for f in FIELDS}
DECIMAL_KEYS = {"AI_VISION_TIMEOUT", "AI_REQUESTS_PER_MINUTE", "AI_LIMIT_RETRY_MINUTES", "RETENTION_DAYS"}
# Endereço -> chave dele. Trocar o servidor (outro host) apaga a chave salva e desliga a liberação de IA externa,
# salvo se o mesmo pedido as reenviar: a chave de um provedor nunca segue para outro, e destino novo pede nova
# confirmação.
URL_KEYS = {"AI_BASE_URL": "AI_API_KEY", "AI_SECONDARY_BASE_URL": "AI_SECONDARY_API_KEY",
            "SECOND_LOOK_BASE_URL": "SECOND_LOOK_API_KEY"}
_applied = {}   # chave -> valor que ESTE módulo escreveu no ambiente
_original = {}  # chave -> valor do .env/ambiente antes do Admin (None = não existia)
_startup = {}   # itens lidos só na subida: valor no momento em que o serviço subiu


class SettingsError(ValueError):
    pass


def path():
    return os.getenv("PRIVIO_SETTINGS_FILE") or os.path.join(BASE_DIR, "privio_settings.json")


def load():
    try:
        with open(path(), encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {"values": {}}
    if not isinstance(data, dict) or not isinstance(data.get("values"), dict):
        return {"values": {}}
    data["values"] = {k: str(v) for k, v in data["values"].items() if k in BY_KEY and v is not None}
    return data


def _write(data):
    target = path()
    folder = os.path.dirname(os.path.abspath(target))
    os.makedirs(folder, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=folder, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
    os.replace(tmp, target)
    try:
        os.chmod(target, 0o600)  # chaves de API: só o dono lê (no Windows vale a permissão da pasta)
    except OSError:
        pass


def apply(environ=None):
    """Escreve no ambiente os valores salvos; item que deixou de ter valor salvo volta ao original (.env/ambiente).
    Itens nunca salvos não são tocados."""
    env = os.environ if environ is None else environ
    saved = load()["values"]
    for key in list(_applied):
        if key not in saved:
            original = _original.pop(key, None)
            if original is None:
                env.pop(key, None)
            else:
                env[key] = original
            del _applied[key]
    for key, value in saved.items():
        if key not in _applied:
            _original[key] = env.get(key)
        env[key] = value
        _applied[key] = value


def mark_startup():
    """Chamado na subida do serviço: lembra os itens que só valem depois de reiniciar."""
    _startup.update({f["key"]: os.environ.get(f["key"]) for f in FIELDS if f["restart"]})


def _validate(field, value):
    value = str(value).strip()
    kind = field["kind"]
    if kind == "bool":
        if value.lower() in ("1", "true", "sim", "on", "yes"):
            return "1"
        if value.lower() in ("0", "false", "nao", "não", "off", "no", ""):
            return "0"
        raise SettingsError(f"{field['label']}: use sim/não")
    if kind == "choice":
        if value not in field["choices"]:
            raise SettingsError(f"{field['label']}: valor fora da lista")
        return value
    if kind == "number":
        try:
            number = float(value)
        except ValueError:
            raise SettingsError(f"{field['label']}: número inválido")
        if not math.isfinite(number):
            raise SettingsError(f"{field['label']}: número inválido")
        # os itens lidos com int() (DPI, fila, tamanho) não aceitam fração: "2.5" impedia o serviço de subir
        if field["key"] not in DECIMAL_KEYS and number != int(number):
            raise SettingsError(f"{field['label']}: use um número inteiro")
        if (field["min"] is not None and number < field["min"]) or (field["max"] is not None and number > field["max"]):
            raise SettingsError(f"{field['label']}: entre {field['min']} e {field['max']}")
        return str(int(number)) if number == int(number) else str(number)
    if kind == "url" and value:
        parts = urlsplit(value)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise SettingsError(f"{field['label']}: use um endereço http:// ou https://")
        # usuário/senha na URL, barra invertida ou espaço: o destino real pode não ser o que parece (trava de saída)
        if "@" in parts.netloc or any(c in value for c in "\\ \t") or egress.host_of(value) != parts.hostname.lower():
            raise SettingsError(f"{field['label']}: endereço inválido (sem usuário/senha, espaços ou \\)")
        return value.rstrip("/")
    if any(c in value for c in "\r\n\0"):
        raise SettingsError(f"{field['label']}: caractere inválido")
    return value


def _host(url):
    return egress.host_of(url)


def save(changes):
    """changes: {CHAVE: valor | None}. None = voltar ao .env/padrão. Chave secreta vazia = manter a atual.
    Valida tudo antes de gravar (nada é salvo se algum valor for inválido) e aplica no ambiente."""
    if not isinstance(changes, dict):
        raise SettingsError("Formato inválido")
    data = load()
    values = dict(data["values"])
    host_changed = False
    for url_key, secret_key in URL_KEYS.items():
        if url_key in changes and _host(changes[url_key]) != _host(os.environ.get(url_key)):
            host_changed = True
            if not str(changes.get(secret_key) or "").strip():
                values[secret_key] = ""  # vazio (não None): também esconde uma chave vinda do .env
    # Sem endereço próprio, o segundo olhar usa o servidor principal: a chave dele também não segue para outro host
    second_look_follows = not str(changes.get("SECOND_LOOK_BASE_URL", os.environ.get("SECOND_LOOK_BASE_URL")) or "")
    if ("AI_BASE_URL" in changes and second_look_follows
            and _host(changes["AI_BASE_URL"]) != _host(os.environ.get("AI_BASE_URL"))
            and not str(changes.get("SECOND_LOOK_API_KEY") or "").strip()):
        values["SECOND_LOOK_API_KEY"] = ""
    if host_changed and "AI_ALLOW_EXTERNAL" not in changes:
        values["AI_ALLOW_EXTERNAL"] = "0"
    for key, value in changes.items():
        field = BY_KEY.get(key)
        if field is None:
            raise SettingsError(f"Item desconhecido ou não configurável pela web: {key}")
        if value is None:
            values.pop(key, None)
            continue
        if field["kind"] == "secret" and str(value).strip() == "":
            continue
        values[key] = _validate(field, value)
    data["values"] = values
    if values.get("AI_ALLOW_EXTERNAL") == "1" and data.get("externo_liberado_em") is None:
        data["externo_liberado_em"] = datetime.now().isoformat(timespec="seconds")
    elif values.get("AI_ALLOW_EXTERNAL") != "1":
        data.pop("externo_liberado_em", None)
    data["atualizado_em"] = datetime.now().isoformat(timespec="seconds")
    _write(data)
    apply()
    return data


def _num(value):
    value = float(value)
    return str(int(value)) if value == int(value) else str(value)


def effective(extra=None):
    """Valor EM USO de cada item, lido pelas mesmas funções que o pipeline usa (não uma cópia dos padrões).
    Itens lidos só na subida do serviço vêm em `extra` (o app_service sabe o valor com que subiu)."""
    import shutil

    from utils import ai_client, doc_templates, ocr_extra, ratelimit, second_look, session, verifier
    from utils.detect import ner, profiles
    out = {}
    main_ai = ai_client._backend_from_env("AI_", "principal")
    reserve = ai_client._backend_from_env("AI_SECONDARY_", "reserva")
    out["AI_PROVIDER"] = "openai" if isinstance(main_ai, ai_client.OpenAICompatBackend) else "ollama"
    out["AI_BASE_URL"] = egress.safe_url(main_ai.base_url)
    out["AI_VISION_MODEL"] = main_ai.vision_model or ""
    out["AI_VISION_TIMEOUT"] = _num(main_ai.timeout(True))
    out["AI_ALLOW_EXTERNAL"] = "1" if egress.external_allowed() else "0"
    out["AI_REQUESTS_PER_MINUTE"] = _num(ratelimit.per_minute(main_ai.base_url))
    out["AI_LIMIT_ACTION"] = ("pendente" if (os.getenv("AI_LIMIT_ACTION") or "revisao").strip().lower() == "pendente"
                              else "revisao")
    out["AI_LIMIT_RETRY_MINUTES"] = _num(ratelimit.retry_minutes())
    if reserve is None:
        out.update(AI_SECONDARY_PROVIDER="", AI_SECONDARY_BASE_URL="", AI_SECONDARY_VISION_MODEL="")
    else:
        out["AI_SECONDARY_PROVIDER"] = "openai" if isinstance(reserve, ai_client.OpenAICompatBackend) else "ollama"
        out["AI_SECONDARY_BASE_URL"] = egress.safe_url(reserve.base_url)
        out["AI_SECONDARY_VISION_MODEL"] = reserve.vision_model or ""
    out["AI_CROSS_CHECK"] = "1" if os.getenv("AI_CROSS_CHECK", "0").strip().lower() in ("1", "true", "sim") else "0"
    out["POLICY_PROFILE"] = profiles.active_profile_id()
    out["NER_ENGINE"] = "gliner" if ner.enabled() else ""
    out["OCR_EXTRA_ENGINE"] = "rapidocr" if ocr_extra.enabled() else ""
    out["SECOND_LOOK"] = "1" if second_look.enabled() else "0"
    out["SECOND_LOOK_MODEL"] = second_look.model()
    out["SECOND_LOOK_BASE_URL"] = egress.safe_url(second_look._endpoint().rsplit("/chat/completions", 1)[0])
    out["DOC_TEMPLATES"] = "1" if doc_templates.enabled() else "0"
    out["DOC_TEMPLATE_INSPECTION"] = doc_templates.inspection_mode()
    out["TESSERACT_PATH"] = os.getenv("TESSERACT_PATH") or shutil.which("tesseract") or ""
    out["TESSERACT_LANG"] = os.getenv("TESSERACT_LANG", "por")
    out["BASE_DPI"] = str(session.render_dpi())
    out["VERIFY_OCR"] = "1" if os.getenv("VERIFY_OCR", "1") == "1" else "0"
    out["VERIFY_DPI"] = str(verifier.verify_dpi())
    out.update(extra or {})
    return out


def describe(extra_effective=None):
    """Itens para a tela Admin. Chaves secretas: só se estão definidas, nunca o valor. `efetivo` = valor em uso."""
    from utils.detect.profiles import PROFILES as PROFILE_INFO
    saved = load()
    in_use = effective(extra_effective)
    out = []
    for f in FIELDS:
        key = f["key"]
        current = os.environ.get(key)
        if key in saved["values"]:
            origin = "admin"
        elif current not in (None, ""):  # "CHAVE=" vazio no .env vale como não definido
            origin = "env"
        else:
            origin = "padrao"
        item = dict(f, origem=origin, definido=bool(current))
        item["valor"] = None if f["kind"] == "secret" else (current or "")
        item["pendente_reinicio"] = bool(f["restart"]) and key in _startup and _startup[key] != current
        item["efetivo"] = None if f["kind"] == "secret" else in_use.get(key, "")
        if key == "POLICY_PROFILE":
            item["labels"] = {pid: PROFILE_INFO[pid]["nome"] for pid in f["choices"] if pid in PROFILE_INFO}
        out.append(item)
    return {"grupos": GROUPS, "campos": out, "arquivo": os.path.basename(path()),
            "atualizado_em": saved.get("atualizado_em"), "externo_liberado_em": saved.get("externo_liberado_em")}

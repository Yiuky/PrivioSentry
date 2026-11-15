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
import os
import tempfile
from datetime import datetime
from urllib.parse import urlsplit

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROFILES = ("cpf_endereco", "lgpd_publicacao", "lgpd_interno", "gdpr", "saude_hipaa")


def _f(key, group, label, kind="text", help="", choices=None, restart=False, minimum=None, maximum=None,
       placeholder=""):
    return {"key": key, "group": group, "label": label, "kind": kind, "help": help, "choices": list(choices or []),
            "restart": restart, "min": minimum, "max": maximum, "placeholder": placeholder}


GROUPS = [
    {"id": "ia", "titulo": "IA principal", "descricao": "Servidor que lê as páginas (endereços e auditoria de "
                                                        "assinaturas). Local por padrão; provedor na nuvem só com a "
                                                        "liberação abaixo."},
    {"id": "ia_reserva", "titulo": "IA reserva", "descricao": "Assume quando a principal falha; com a verificação "
                                                              "cruzada, também confere cada página."},
    {"id": "deteccao", "titulo": "Detecção e política", "descricao": "O que procurar por padrão (cada envio ainda "
                                                                     "pode escolher na barra lateral)."},
    {"id": "ocr", "titulo": "OCR e verificação", "descricao": "Leitura das páginas (Tesseract) e conferência do PDF "
                                                              "final."},
    {"id": "operacao", "titulo": "Operação", "descricao": "Fila, limites e retenção dos arquivos."},
]

FIELDS = [
    _f("AI_PROVIDER", "ia", "Tipo de API", "choice", "ollama = API do Ollama; openai = padrão OpenAI (LM Studio, "
       "vLLM, servidor da organização e provedores na nuvem)", ["ollama", "openai"]),
    _f("AI_BASE_URL", "ia", "Endereço da API", "url", "Ex.: http://localhost:11434 (Ollama) ou "
       "https://api.openai.com/v1", placeholder="http://localhost:11434"),
    _f("AI_API_KEY", "ia", "Chave de API", "secret", "Guardada só nesta máquina; nunca é mostrada de volta."),
    _f("AI_VISION_MODEL", "ia", "Modelo (visão)", "text", "Precisa aceitar imagens.", placeholder="gemma4:e4b"),
    _f("AI_VISION_TIMEOUT", "ia", "Tempo limite por página (s)", "number", "", minimum=10, maximum=3600),
    _f("AI_ALLOW_EXTERNAL", "ia", "Permitir IA fora desta rede", "bool", "Com isso ligado, imagens das páginas e "
       "o texto lido delas são enviados ao provedor configurado. Sem isso, a chamada é bloqueada e a página vai "
       "para revisão."),
    _f("AI_REQUESTS_PER_MINUTE", "ia", "Pedidos por minuto (ritmo)", "number", "Padrão (restaurar padrão) = automático: 12 por minuto "
       "num provedor externo, sem limite nesta rede. 0 = sem limite. Conta todos os documentos em processamento "
       "juntos, por servidor. Ponha abaixo do limite do seu plano: mais lento, mas sem recusas.", minimum=0,
       maximum=10000),
    _f("AI_LIMIT_ACTION", "ia", "Se o provedor recusar por limite de uso", "choice", "revisao = as páginas sem "
       "IA vão para revisão. pendente = o documento fica pendente, sem PDF, e é refeito sozinho depois (as "
       "páginas são enviadas de novo).", ["revisao", "pendente"]),
    _f("AI_LIMIT_RETRY_MINUTES", "ia", "Pendente: tentar de novo a cada (min)", "number", "Depois de 24 "
       "retomadas (AI_LIMIT_MAX_RETRIES), o documento segue para revisão.", minimum=1, maximum=1440),
    _f("AI_SECONDARY_PROVIDER", "ia_reserva", "Tipo de API", "choice", "Vazio = sem reserva.", ["", "ollama",
                                                                                                "openai"]),
    _f("AI_SECONDARY_BASE_URL", "ia_reserva", "Endereço da API", "url", "", placeholder="http://localhost:1234/v1"),
    _f("AI_SECONDARY_API_KEY", "ia_reserva", "Chave de API", "secret", "Guardada só nesta máquina."),
    _f("AI_SECONDARY_VISION_MODEL", "ia_reserva", "Modelo (visão)", "text", ""),
    _f("AI_CROSS_CHECK", "ia_reserva", "Verificação cruzada", "bool", "A reserva também lê cada página; os achados "
       "se somam (nunca reduz a proteção). Dobra o tempo de IA."),
    _f("POLICY_PROFILE", "deteccao", "Perfil padrão", "choice", "Catálogo em docs/catalogo-pii.md.", PROFILES),
    _f("NER_ENGINE", "deteccao", "Detector de nomes", "choice", "gliner exige pip install -e \".[nomes]\".",
       ["", "gliner"]),
    _f("OCR_EXTRA_ENGINE", "deteccao", "Leitura extra de OCR", "choice", "rapidocr exige pip install -e "
       "\".[ocr-extra]\".", ["", "rapidocr"]),
    _f("SECOND_LOOK", "deteccao", "Segundo olhar (IA)", "bool", "Um agente revê as páginas em dúvida e só "
       "acrescenta tarjas. Usa o servidor principal, salvo endereço próprio."),
    _f("SECOND_LOOK_MODEL", "deteccao", "Modelo do segundo olhar", "text", "Precisa aceitar ferramentas (tools).",
       placeholder="gemma4:e4b"),
    _f("SECOND_LOOK_BASE_URL", "deteccao", "Endereço próprio do segundo olhar", "url", "Vazio = o da IA principal."),
    _f("SECOND_LOOK_API_KEY", "deteccao", "Chave do segundo olhar", "secret", "Vazio = a da IA principal."),
    _f("DOC_TEMPLATES", "deteccao", "Modelos de documento", "bool", "Reconhece documentos de layout conhecido e "
       "tarja os campos do modelo sem IA (Administração > Modelos de documento)."),
    _f("DOC_TEMPLATE_INSPECTION", "deteccao", "Inspeção depois do modelo", "choice", "agente = um agente lê o texto "
       "já tarjado e aponta o que ficou de fora (gasta poucos tokens, só texto); regras = zero token, mas página "
       "sem IA de visão vai sempre para revisão.", ["agente", "regras"]),
    _f("TESSERACT_PATH", "ocr", "Executável do Tesseract", "text", "Vazio = o do PATH."),
    _f("TESSERACT_LANG", "ocr", "Idioma do OCR", "text", "Ex.: por, por+eng.", placeholder="por"),
    _f("BASE_DPI", "ocr", "DPI de leitura", "number", "300 é o medido como melhor; acima disso a revocação de CPF "
       "cai (docs/benchmarks.md).", minimum=72, maximum=1200),
    _f("VERIFY_OCR", "ocr", "OCR na verificação final", "bool", "Recomendado. Desligado, páginas só com imagem não "
       "são verificadas."),
    _f("VERIFY_DPI", "ocr", "DPI da verificação", "number", "", minimum=72, maximum=1200),
    _f("MAX_PARALLEL_TASKS", "operacao", "Documentos ao mesmo tempo", "number", "", restart=True, minimum=1,
       maximum=32),
    _f("MAX_UPLOAD_MB", "operacao", "Tamanho máximo do PDF (MB)", "number", "", restart=True, minimum=1,
       maximum=10000),
    _f("RETENTION_DAYS", "operacao", "Apagar tarefas após (dias)", "number", "0 = nunca. Aplicado na subida do "
       "serviço.", restart=True, minimum=0, maximum=3650),
]
BY_KEY = {f["key"]: f for f in FIELDS}
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
        if (field["min"] is not None and number < field["min"]) or (field["max"] is not None and number > field["max"]):
            raise SettingsError(f"{field['label']}: entre {field['min']} e {field['max']}")
        return str(int(number)) if number == int(number) else str(number)
    if kind == "url" and value:
        parts = urlsplit(value)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise SettingsError(f"{field['label']}: use um endereço http:// ou https://")
        return value.rstrip("/")
    if any(c in value for c in "\r\n\0"):
        raise SettingsError(f"{field['label']}: caractere inválido")
    return value


def _host(url):
    try:
        return (urlsplit(str(url or "")).hostname or "").lower()
    except ValueError:
        return ""


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


def describe():
    """Itens para a tela Admin. Chaves secretas: só se estão definidas, nunca o valor."""
    saved = load()
    out = []
    for f in FIELDS:
        key = f["key"]
        current = os.environ.get(key)
        if key in saved["values"]:
            origin = "admin"
        elif current is not None:
            origin = "env"
        else:
            origin = "padrao"
        item = dict(f, origem=origin, definido=bool(current))
        item["valor"] = None if f["kind"] == "secret" else (current or "")
        item["pendente_reinicio"] = bool(f["restart"]) and key in _startup and _startup[key] != current
        out.append(item)
    return {"grupos": GROUPS, "campos": out, "arquivo": os.path.basename(path()),
            "atualizado_em": saved.get("atualizado_em"), "externo_liberado_em": saved.get("externo_liberado_em")}

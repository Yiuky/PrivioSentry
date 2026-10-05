# SPDX-License-Identifier: AGPL-3.0-or-later
"""Cliente de IA LOCAL com qualquer servidor: Ollama ou compatível com a API da OpenAI (LM Studio, vLLM, llama.cpp,
LocalAI, servidor de IA da organização), com IA reserva, disjuntor e verificação cruzada.

Configuração (docs/configuration.md):
    AI_PROVIDER            ollama (padrão) | openai        tipo do servidor principal
    AI_BASE_URL            endereço (padrão: OLLAMA_API_URL ou http://localhost:11434; openai: http://localhost:1234/v1)
    AI_API_KEY             chave, se o servidor exigir (nunca vai para log nem para a API /health/ai)
    AI_TEXT_MODEL / AI_VISION_MODEL    modelos (padrão: OLLAMA_MODEL / OLLAMA_VISION_MODEL)
    AI_TEXT_TIMEOUT / AI_VISION_TIMEOUT   tempo limite por chamada (padrão: OLLAMA_*_TIMEOUT, 300 / 600 s)
    AI_SECONDARY_*         o mesmo para a IA RESERVA (opcional): PROVIDER, BASE_URL, API_KEY, TEXT_MODEL, VISION_MODEL,
                           TEXT_TIMEOUT, VISION_TIMEOUT (cada servidor com o próprio tempo limite)
    AI_BREAKER_FAILURES    falhas seguidas que "desligam" um servidor (padrão 3)
    AI_BREAKER_COOLDOWN    segundos desligado antes de testar de novo (padrão 120)
    AI_RESET_EVERY         a cada N chamadas, pede ao servidor para descarregar o modelo (0 = nunca; só Ollama)
    AI_CROSS_CHECK=1       a reserva também analisa cada página e os resultados se somam (utils/address_redactor.py)

Disjuntor: cada tentativa que falha (sem conexão, tempo esgotado, erro 5xx, resposta sem JSON) conta; com
AI_BREAKER_FAILURES falhas seguidas o servidor fica desligado por AI_BREAKER_COOLDOWN segundos (as chamadas nem
tentam: vão para a reserva ou devolvem erro na hora, e o pipeline manda a página para revisão). Depois do intervalo,
UMA chamada de teste decide se ele volta. O estado fica num arquivo compartilhado pelas tarefas (cada tarefa é um
processo): uma tarefa nova já sabe que o servidor caiu. Ao desligar um Ollama, o modelo é descarregado (recupera de
estados degenerados e de memória presa).
"""
import base64
import hashlib
import json
import os
import re
import tempfile
import threading
import time
from io import BytesIO

import requests
from PIL import Image

# Trava global: um modelo local por vez (o app troca por um multiprocessing.Lock compartilhado entre tarefas)
ollama_lock = threading.Lock()

SYSTEM_TEXT = "Você é um assistente especialista em análise de documentos brasileiros."
SYSTEM_VISION = "Você é um especialista em análise visual de documentos. Extraia informações em JSON puro, sem explicações."


def _env_float(name, default):
    """Timeout em segundos lido do ambiente (aceita decimais); inválido -> padrão."""
    try:
        value = float(os.getenv(name, default))
        return value if value > 0 else float(default)
    except (TypeError, ValueError):
        return float(default)


def _env_int(name, default):
    try:
        return max(0, int(os.getenv(name, default)))
    except (TypeError, ValueError):
        return default


def _raise_for_server_error(response):
    """Erro 5xx do servidor (ex.: Ollama sem VRAM) deve disparar o retry/fallback, não virar 'resposta'."""
    if response.status_code >= 500:
        raise RuntimeError(f"HTTP {response.status_code} do servidor de IA")


def clean_json_response(text):
    """Remove blocos de markdown e extrai o primeiro objeto JSON válido encontrado."""
    text = str(text or "").strip()
    text = re.sub(r'```json\s*|\s*```', '', text).strip()
    try:
        return json.loads(text)
    except Exception:
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except Exception as e:
                return {"error": f"JSON malformado: {e}", "raw_fragment": match.group(), "full_raw": text}
        return {"error": "Nenhum JSON encontrado na resposta", "full_raw": text}


# ------------------------------------------------------------------------------------------- disjuntor
class Breaker:
    """Disjuntor por servidor, com estado num arquivo compartilhado entre processos (gravação atômica)."""

    def __init__(self, path=None):
        self.path = path or os.path.join(os.getenv("PRIVIO_RUNTIME_DIR") or tempfile.gettempdir(),
                                         "privio_ai_health.json")
        self._lock = threading.Lock()

    @staticmethod
    def failures_to_open():
        return max(1, _env_int("AI_BREAKER_FAILURES", 3))

    @staticmethod
    def cooldown():
        return _env_float("AI_BREAKER_COOLDOWN", 120)

    def _read(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _write(self, data):
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=os.path.dirname(self.path), suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f)
            os.replace(tmp, self.path)
        except OSError:
            pass  # sem disco para o estado: o disjuntor só não é compartilhado

    def state(self, key):
        return self._read().get(key, {})

    def allow(self, key):
        """False enquanto desligado. Depois do intervalo, libera UMA tentativa (meio-aberto)."""
        st = self.state(key)
        until = float(st.get("open_until") or 0)
        return not until or time.time() >= until

    def half_open(self, key):
        """Intervalo terminou mas o servidor ainda não provou que voltou."""
        until = float(self.state(key).get("open_until") or 0)
        return bool(until) and time.time() >= until

    def success(self, key):
        with self._lock:
            data = self._read()
            if key in data and (data[key].get("failures") or data[key].get("open_until")):
                data[key].update(failures=0, open_until=0)
                self._write(data)

    def failure(self, key, error):
        """Conta a falha. Devolve True se esta falha DESLIGOU o servidor agora."""
        with self._lock:
            data = self._read()
            st = data.setdefault(key, {"failures": 0, "open_until": 0, "times_opened": 0})
            st["failures"] = int(st.get("failures") or 0) + 1
            st["last_error"] = str(error)[:200]
            st["last_failure_at"] = time.time()
            opened = False
            if st["failures"] >= self.failures_to_open():
                st["open_until"] = time.time() + self.cooldown()
                st["times_opened"] = int(st.get("times_opened") or 0) + 1
                st["failures"] = 0
                opened = True
            self._write(data)
            return opened

    def snapshot(self):
        now = time.time()
        return {k: {"desligado": bool(v.get("open_until") and now < float(v["open_until"])),
                    "volta_em_s": max(0, round(float(v.get("open_until") or 0) - now)),
                    "falhas_seguidas": v.get("failures", 0), "vezes_desligado": v.get("times_opened", 0),
                    "ultimo_erro": v.get("last_error", "")} for k, v in self._read().items()}


# ------------------------------------------------------------------------------------------- servidores
class Backend:
    kind = "?"

    def __init__(self, base_url, text_model, vision_model, api_key="", role="principal", prefix="AI_"):
        self.prefix = prefix
        self.base_url = (base_url or "").rstrip("/")
        self.model = text_model
        self.vision_model = vision_model
        self.api_key = api_key or ""
        self.role = role
        self.calls = 0

    def timeout(self, vision):
        """Tempo limite DESTE servidor (a reserva pode ser mais lenta: outro modelo, carga sob demanda)."""
        kind = "VISION" if vision else "TEXT"
        legacy = _env_float(f"OLLAMA_{kind}_TIMEOUT", 600 if vision else 300)
        general = _env_float(f"AI_{kind}_TIMEOUT", legacy)
        return _env_float(f"{self.prefix}{kind}_TIMEOUT", general) if self.prefix != "AI_" else general

    def key(self, vision):
        return f"{self.kind}|{self.base_url}|{self.vision_model if vision else self.model}"

    def describe(self):
        """Sem a chave."""
        return {"papel": self.role, "tipo": self.kind, "endereco": self.base_url, "modelo_texto": self.model,
                "modelo_visao": self.vision_model, "com_chave": bool(self.api_key)}

    def reset(self):
        """Pede ao servidor, pela API, para descarregar o modelo (quando suportado). Nunca levanta exceção."""

    def probe(self, vision=True, timeout=10):
        """Teste de saúde pela API (lista de modelos): (ok, motivo). Também acusa modelo que não existe no servidor."""
        return False, "não implementado"


class OllamaBackend(Backend):
    kind = "ollama"

    @property
    def url(self):
        return self.base_url + "/api/chat"

    def chat(self, system, prompt, image_b64, timeout, vision):
        user = {"role": "user", "content": prompt}
        if image_b64:
            user["images"] = [image_b64]
        options = {"num_ctx": int(os.getenv("AI_CONTEXT_WINDOW", "32768")), "num_predict": 2048, "temperature": 0.1}
        if vision:
            options["top_p"] = 0.9
        payload = {"model": self.vision_model if vision else self.model,
                   "messages": [{"role": "system", "content": system}, user],
                   "stream": False, "think": False, "options": options}
        response = requests.post(self.url, json=payload, timeout=timeout)
        _raise_for_server_error(response)
        raw_text = response.text
        data = clean_json_response(raw_text)
        duration_ms = round(data.get("total_duration", 0) / 1000000, 2)
        metrics = {"input_tokens": data.get("prompt_eval_count", 0), "output_tokens": data.get("eval_count", 0),
                   "total_duration_ms": duration_ms, "total_duration_sec": round(duration_ms / 1000, 2),
                   "total_duration_min": round(duration_ms / 60000, 2),
                   "total_duration_hr": round(duration_ms / 3600000, 2), "backend": self.role}
        if "message" in data:
            return data["message"].get("content", ""), metrics, raw_text, True
        return data, metrics, raw_text, False

    def reset(self):
        for model in {self.model, self.vision_model}:
            try:
                requests.post(self.base_url + "/api/generate", json={"model": model, "keep_alive": 0}, timeout=15)
            except Exception:
                pass

    def probe(self, vision=True, timeout=10):
        try:
            r = requests.get(self.base_url + "/api/tags", timeout=timeout)
            if r.status_code != 200:
                return False, f"HTTP {r.status_code}"
            names = {m.get("name") for m in (r.json().get("models") or []) if isinstance(m, dict)}
        except Exception as e:
            return False, f"{type(e).__name__}: {str(e)[:120]}"
        model = self.vision_model if vision else self.model
        if names and model not in names and f"{model}:latest" not in names:
            return False, f"modelo '{model}' não existe no servidor"
        return True, "ok"


class OpenAICompatBackend(Backend):
    """POST {base}/chat/completions no formato da OpenAI (LM Studio, vLLM, llama.cpp, servidores corporativos)."""
    kind = "openai"

    def chat(self, system, prompt, image_b64, timeout, vision):
        content = [{"type": "text", "text": prompt}]
        if image_b64:
            content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}})
        payload = {"model": self.vision_model if vision else self.model, "stream": False, "temperature": 0.1,
                   "max_tokens": int(os.getenv("AI_MAX_TOKENS", "4096")),
                   "messages": [{"role": "system", "content": system},
                                {"role": "user", "content": content if image_b64 else prompt}]}
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        t0 = time.time()
        response = requests.post(self.base_url + "/chat/completions", json=payload, headers=headers, timeout=timeout)
        _raise_for_server_error(response)
        if response.status_code in (401, 403):
            raise RuntimeError(f"HTTP {response.status_code}: servidor de IA recusou a chave (AI_API_KEY)")
        raw_text = response.text
        data = clean_json_response(raw_text)
        usage = data.get("usage") or {} if isinstance(data, dict) else {}
        sec = round(time.time() - t0, 2)
        metrics = {"input_tokens": usage.get("prompt_tokens", 0), "output_tokens": usage.get("completion_tokens", 0),
                   "total_duration_ms": round(sec * 1000, 2), "total_duration_sec": sec,
                   "total_duration_min": round(sec / 60, 2), "total_duration_hr": round(sec / 3600, 2),
                   "backend": self.role}
        choices = data.get("choices") if isinstance(data, dict) else None
        if choices:
            return (choices[0].get("message") or {}).get("content") or "", metrics, raw_text, True
        return data, metrics, raw_text, False

    def _headers(self):
        return {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}

    def probe(self, vision=True, timeout=10):
        """GET {base}/models: padrão da API da OpenAI, presente em LM Studio, vLLM, llama.cpp e afins."""
        try:
            r = requests.get(self.base_url + "/models", headers=self._headers(), timeout=timeout)
            if r.status_code in (401, 403):
                return False, f"HTTP {r.status_code}: chave recusada"
            if r.status_code != 200:
                return False, f"HTTP {r.status_code}"
            ids = {m.get("id") for m in (r.json().get("data") or []) if isinstance(m, dict)}
        except Exception as e:
            return False, f"{type(e).__name__}: {str(e)[:120]}"
        model = self.vision_model if vision else self.model
        if ids and model not in ids:
            return False, f"modelo '{model}' não existe no servidor"
        return True, "ok"

    def reset(self):
        """Descarrega pela API REST do LM Studio (/api/v1/models/unload), quando existir; outros servidores: nada."""
        root = re.sub(r"/v1/?$", "", self.base_url)
        try:
            r = requests.get(root + "/api/v1/models", headers=self._headers(), timeout=10)
            if r.status_code != 200:
                return
            for m in r.json().get("models") or []:
                if m.get("key") in (self.model, self.vision_model):
                    for inst in m.get("loaded_instances") or []:
                        requests.post(root + "/api/v1/models/unload", headers=self._headers(),
                                      json={"instance_id": inst.get("id")}, timeout=30)
        except Exception:
            pass


def _backend_from_env(prefix, role):
    provider = (os.getenv(f"{prefix}PROVIDER") or ("ollama" if role == "principal" else "")).strip().lower()
    if not provider:
        return None
    if provider in ("openai", "lmstudio", "lm_studio", "vllm", "llamacpp", "openai_compat"):
        cls, default_url = OpenAICompatBackend, "http://localhost:1234/v1"
    else:
        cls, default_url = OllamaBackend, os.getenv("OLLAMA_API_URL", "http://localhost:11434")
    url = os.getenv(f"{prefix}BASE_URL") or default_url
    text = os.getenv(f"{prefix}TEXT_MODEL") or (os.getenv("OLLAMA_MODEL", "llama3") if role == "principal" else "")
    vision = os.getenv(f"{prefix}VISION_MODEL") or (os.getenv("OLLAMA_VISION_MODEL", "gemma4:e4b")
                                                     if role == "principal" else "")
    text, vision = text or vision, vision or text
    return cls(url, text, vision, os.getenv(f"{prefix}API_KEY", ""), role, prefix)


def configured_backends():
    backends = [_backend_from_env("AI_", "principal")]
    secondary = _backend_from_env("AI_SECONDARY_", "reserva")
    if secondary is not None:
        backends.append(secondary)
    return backends


# ------------------------------------------------------------------------------------------- cliente
class AIClient:
    def __init__(self, backends=None, breaker=None):
        self.backends = backends or configured_backends()
        self.breaker = breaker or Breaker()
        primary = self.backends[0]
        # compatibilidade (logs e testes antigos)
        self.url = getattr(primary, "url", primary.base_url)
        self.model = primary.model
        self.vision_model = primary.vision_model

    _clean_json_response = staticmethod(clean_json_response)

    @property
    def has_secondary(self):
        return len(self.backends) > 1

    def health(self, live=False):
        """Servidores (sem chave), estado do disjuntor e, com live=True, o teste de saúde de cada um pela API."""
        out = {"servidores": [b.describe() for b in self.backends], "disjuntor": self.breaker.snapshot()}
        if live:
            for desc, b in zip(out["servidores"], self.backends):
                ok, why = b.probe(vision=True, timeout=5)
                desc["no_ar"], desc["teste"] = ok, why
        return out

    def _maybe_reset(self, backend):
        every = _env_int("AI_RESET_EVERY", 0)
        backend.calls += 1
        if every and backend.calls % every == 0:
            backend.reset()

    def _run(self, backend, vision, attempt_fn, fail_message):
        """Até 3 tentativas num servidor, respeitando o disjuntor. Devolve (resultado, img_bytes, métricas)."""
        key = backend.key(vision)
        last_error = None
        if self.breaker.half_open(key):
            ok, why = backend.probe(vision)
            if not ok:
                self.breaker.failure(key, f"teste de saúde: {why}")
                return {"error": f"IA '{backend.role}' continua fora do ar ({why})", "breaker_open": True}, None, {}
        for attempt in range(3):
            if not self.breaker.allow(key):
                st = self.breaker.state(key)
                return {"error": f"IA '{backend.role}' desligada pelo disjuntor (falhas seguidas: "
                                 f"{st.get('last_error', '')[:120]})", "breaker_open": True}, None, {}
            try:
                with ollama_lock:
                    out = attempt_fn(backend, attempt)
                self.breaker.success(key)
                self._maybe_reset(backend)
                return out
            except Exception as e:
                last_error = str(e)
                if self.breaker.failure(key, e):
                    backend.reset()
                time.sleep(2 + attempt)
        return {"error": f"{fail_message}: {last_error}", "_backend_failed": backend.role}, None, {}

    def _call(self, vision, attempt_fn, fail_message, only=None):
        """Principal; se falhar (ou estiver desligada), a reserva. only="reserva" consulta só a reserva."""
        backends = [b for b in self.backends if only is None or b.role == only]
        result = ({"error": "nenhuma IA configurada"}, None, {})
        for i, backend in enumerate(backends):
            result = self._run(backend, vision, attempt_fn, fail_message)
            response = result[0]
            if not (isinstance(response, dict) and "error" in response):
                if i > 0 and isinstance(response, dict):
                    response.setdefault("_backend", backend.role)  # o pipeline registra que a reserva respondeu
                return result
            if isinstance(response, dict) and response.get("model_output_invalid") and i + 1 < len(backends):
                continue  # resposta da principal sem formato: a reserva confere (vigia)
        return result

    def analyze_text(self, prompt, system_prompt=SYSTEM_TEXT, only=None):
        def attempt(backend, _n):
            content, metrics, raw, is_chat = backend.chat(system_prompt, prompt, None, backend.timeout(False),
                                                          vision=False)
            if not is_chat:
                if not isinstance(content, dict) or "error" in content:
                    raise RuntimeError(f"resposta inesperada do servidor: {str(raw)[:120]}")
                return content, metrics
            parsed = clean_json_response(content)
            if isinstance(parsed, dict) and "error" in parsed:
                parsed["model_output_invalid"] = True
            return parsed, metrics

        result = self._call(False, lambda b, n: attempt(b, n), "Falha após 3 tentativas", only)
        if len(result) == 3 and result[1] is None and isinstance(result[0], dict) and "error" in result[0]:
            return result[0], result[2]
        return result

    def analyze_image(self, image_path, prompt, only=None):
        """
        Mesma imagem (reduzida a cada falha, 512 px por vez: falta de memória no servidor) para a principal e,
        se ela falhar, para a reserva.
        """
        base_max_size = int(os.getenv("AI_IMAGE_RESOLUTION", "2048"))

        def attempt(backend, n):
            max_size = max(512, base_max_size - (n * 512))
            with Image.open(image_path) as img:
                img.thumbnail((max_size, max_size))
                buffered = BytesIO()
                img.convert("RGB").save(buffered, format="JPEG", quality=90 - (n * 10))
                img_bytes = buffered.getvalue()
            content, metrics, raw, is_chat = backend.chat(SYSTEM_VISION, prompt,
                                                          base64.b64encode(img_bytes).decode("utf-8"),
                                                          backend.timeout(True), True)
            if not is_chat:
                raise RuntimeError(f"resposta inesperada do servidor: {str(raw)[:120]}")
            if not content:
                return {"error": "A IA retornou uma mensagem vazia", "raw_response": raw[:500],
                        "model_output_invalid": True}, img_bytes, metrics
            parsed = clean_json_response(content)
            if isinstance(parsed, dict) and "error" in parsed:
                parsed["model_output_invalid"] = True
            return parsed, img_bytes, metrics

        return self._call(True, attempt, "Falha crítica na API em 3 tentativas", only)


def backend_fingerprint():
    """Identifica a configuração de IA sem expor chaves (para auditoria nos logs)."""
    desc = json.dumps([b.describe() for b in configured_backends()], sort_keys=True)
    return hashlib.sha256(desc.encode()).hexdigest()[:12]


# Nome antigo (o projeto começou só com Ollama)
OllamaClient = AIClient

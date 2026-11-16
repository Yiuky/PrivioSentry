"""
Limite de uso do provedor de IA (HTTP 429): o que esperar, o que não adianta esperar e o ritmo dos pedidos.

Dois casos:
- curto: o provedor diz quanto esperar (cabeçalho Retry-After ou "retryDelay" do Gemini) e cabe em 60 s.
  Quem chamou espera e tenta de novo.
  Sem indicação nenhuma, espera 5 s.
- longo: cota diária ("PerDay"), conta sem crédito ("insufficient_quota"), espera acima de 60 s, ou um limite
  curto que continuou depois das novas tentativas. Não adianta esperar na hora.

No caso longo, a página vai para revisão (padrão) ou, com AI_LIMIT_ACTION=pendente, o documento inteiro fica
pendente e o serviço o reprocessa depois (app_service.py). O processamento pendente para antes de gerar PDF.
Pendente só vale no processo de um documento do serviço (allow_pending): a linha de comando e as chamadas do
próprio serviço (rascunho de modelo, teste da Administração) sempre se comportam como "revisao".
"""
import json
import os
import re
import tempfile
import threading
import time

from utils import egress

MAX_WAIT = 60.0
EXTERNAL_DEFAULT = 12  # pedidos por minuto num provedor externo sem valor configurado (abaixo dos 15 do Gemini grátis)
_hit = []          # limites longos vistos NESTE processo (um processo por documento)
# Trava da reserva de vez. No serviço, o worker troca pela trava entre processos RATE_LOCK (app_service.py),
# separada da trava da IA: reservar a vez não espera uma chamada longa de outro documento terminar.
lock = threading.Lock()
_slots = {}  # host -> próxima vez livre vista por ESTE processo (vale mesmo sem o arquivo compartilhado)
_pending = [False]  # este processo pode deixar o documento pendente? (só o worker de uma tarefa do serviço)


class RateLimited(RuntimeError):
    def __init__(self, wait, long):
        super().__init__("HTTP 429: limite de uso do provedor de IA" + (" (cota esgotada)" if long else ""))
        self.wait, self.long = wait, long


def parse(response):
    """(segundos a esperar, longo) de uma resposta 429."""
    text = str(getattr(response, "text", "") or "")
    try:
        hint = float(response.headers.get("retry-after") or 0)
    except (TypeError, ValueError, AttributeError):
        hint = 0.0
    if not hint:
        match = re.search(r'"retryDelay"\s*:\s*"(\d+(?:\.\d+)?)s"', text)
        hint = float(match.group(1)) if match else 0.0
    long = bool(re.search(r"PerDay|insufficient_quota", text)) or hint > MAX_WAIT
    return min(MAX_WAIT, max(1.0, hint or 5.0)), long


def note():
    """Registra um limite longo: é o que faz o documento ficar pendente (se o administrador ligou)."""
    _hit.append(time.time())


def hit():
    return bool(_hit)


def clear():
    """Novo documento: o limite visto no anterior não vale para este."""
    del _hit[:]


def allow_pending(on=True):
    _pending[0] = bool(on)


def pending_mode():
    return _pending[0] and (os.getenv("AI_LIMIT_ACTION") or "revisao").strip().lower() == "pendente"


def should_pend():
    """True: este documento já bateu no limite e vai ser reprocessado depois; não vale gastar mais pedidos."""
    return hit() and pending_mode()


def retry_minutes():
    try:
        return max(1.0, float(os.getenv("AI_LIMIT_RETRY_MINUTES") or 60))
    except ValueError:
        return 60.0


def max_resumes():
    try:
        return max(0, int(os.getenv("AI_LIMIT_MAX_RETRIES") or 24))
    except ValueError:
        return 24


def per_minute(url):
    """Pedidos por minuto para este servidor. Vazio = automático: externo 12, nesta rede sem limite. 0 = sem limite."""
    raw = (os.getenv("AI_REQUESTS_PER_MINUTE") or "").strip()
    if not raw:
        return float(EXTERNAL_DEFAULT) if egress.is_external(url) else 0.0
    try:
        return max(0.0, float(raw))
    except ValueError:
        return float(EXTERNAL_DEFAULT)  # valor inválido: fica no lado seguro


def _state_path():
    return os.path.join(os.getenv("PRIVIO_RUNTIME_DIR") or tempfile.gettempdir(), "privio_ai_pace.json")


def _read():
    try:
        with open(_state_path(), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write(data):
    path = _state_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f)
        for attempt in range(5):  # no Windows, outro processo lendo o arquivo faz o replace falhar por instantes
            try:
                os.replace(tmp, path)
                break
            except PermissionError:
                time.sleep(0.01 * (attempt + 1))
        else:
            os.remove(tmp)
    except OSError:
        pass  # sem disco para o estado: o limite continua neste processo (_slots), só deixa de ser compartilhado


def pace(url, sleep=time.sleep, clock=time.time):
    """Espera a vez antes de um pedido ao servidor `url`: no máximo per_minute(url) pedidos por minuto, somando
    TODOS os documentos em processamento (estado num arquivo compartilhado, como o disjuntor). Devolve a espera."""
    rate = per_minute(url)
    if rate <= 0:
        return 0.0
    interval = 60.0 / rate
    host = egress.host_of(url) or str(url)
    # shortcut: chamadas do próprio serviço (rascunho de modelo) usam uma trava local; colidir com um worker no
    # mesmo instante só gasta uma vaga a mais. Se pesar, passar o AI_LOCK também ao processo principal.
    # prazo na trava: se o dono morreu segurando, segue só com o limite deste processo (_slots)
    got = lock.acquire(timeout=60)
    try:
        now = clock()
        data = _read()
        slot = max(float(data.get(host) or 0), _slots.get(host, 0.0))
        if slot - now > 3600:  # relógio mudou ou estado velho: recomeça
            slot = 0.0
        slot = max(now, slot)
        data[host] = _slots[host] = slot + interval
        _write(data)  # gravação atômica; sem a trava (dono morto), no máximo duas reservas na mesma vaga
    finally:
        if got:
            lock.release()
    wait = slot - now
    if wait > 0:
        sleep(wait)
    return wait

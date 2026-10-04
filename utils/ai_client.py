# SPDX-License-Identifier: AGPL-3.0-or-later
import os
import requests
import json
import base64
import re
import threading
from PIL import Image
from io import BytesIO

# Criação de uma Trava de Execução (Lock) Global
# Isso organiza chamadas SIMULTÂNEAS de FastApi (Múltiplos Documentos de uma Batelada)
# Forçando-os a formar uma fila ao chamar o LLM local, impedindo timeout e OOM.
ollama_lock = threading.Lock()


def _env_float(name, default):
    """Timeout em segundos lido do ambiente (aceita decimais); inválido -> padrão."""
    try:
        value = float(os.getenv(name, default))
        return value if value > 0 else float(default)
    except (TypeError, ValueError):
        return float(default)


def _raise_for_server_error(response):
    """Erro 5xx do servidor (ex.: Ollama sem VRAM) deve disparar o retry/fallback, não virar 'resposta'."""
    if response.status_code >= 500:
        raise RuntimeError(f"HTTP {response.status_code} do servidor de IA")

class OllamaClient:
    def __init__(self):
        # Usamos o endpoint de CHAT que é o padrão recomendado para modelos de visão e pensamento
        self.url = os.getenv("OLLAMA_API_URL", "http://localhost:11434").rstrip('/') + "/api/chat"
        self.model = os.getenv("OLLAMA_MODEL", "llama3")
        self.vision_model = os.getenv("OLLAMA_VISION_MODEL", "gemma4:e4b")

    def _clean_json_response(self, text):
        """Remove blocos de markdown e extrai o primeiro objeto JSON válido encontrado."""
        text = text.strip()
        
        # Remove tags de marcação markdown se existirem
        text = re.sub(r'```json\s*|\s*```', '', text).strip()
        
        try:
            return json.loads(text)
        except Exception:
            # Tenta extrair qualquer coisa que pareça um JSON { ... }
            match = re.search(r'\{.*\}', text, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group())
                except Exception as e:
                    return {"error": f"JSON malformado: {e}", "raw_fragment": match.group(), "full_raw": text}
            
            return {"error": "Nenhum JSON encontrado na resposta", "full_raw": text}

    def analyze_text(self, prompt, system_prompt="Você é um assistente especialista em análise de documentos brasileiros."):
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ],
            "stream": False,
            "think": False,
            "options": {
                "num_ctx": int(os.getenv("AI_CONTEXT_WINDOW", "32768")),
                "num_predict": 2048,
                "temperature": 0.1
            }
        }
        
        last_error = None
        for attempt in range(3):
            try:
                # BLOQUEIO HOMOGÊNEO: Apenas uma requisição usa a IA por vez.
                with ollama_lock:
                    timeout_val = _env_float("OLLAMA_TEXT_TIMEOUT", 300)
                    response = requests.post(self.url, json=payload, timeout=timeout_val)
                _raise_for_server_error(response)

                raw_text = response.text
                data = self._clean_json_response(raw_text)
                
                duration_ms = round(data.get("total_duration", 0) / 1000000, 2)
                duration_sec = round(duration_ms / 1000, 2)
                duration_min = round(duration_sec / 60, 2)
                
                metrics = {
                    "input_tokens": data.get("prompt_eval_count", 0),
                    "output_tokens": data.get("eval_count", 0),
                    "total_duration_ms": duration_ms,
                    "total_duration_sec": duration_sec,
                    "total_duration_min": duration_min,
                    "total_duration_hr": round(duration_min / 60, 2)
                }
    
                if "message" in data:
                    return self._clean_json_response(data["message"].get("content", "")), metrics
                return data, metrics
            except Exception as e:
                last_error = str(e)
                import time; time.sleep(2)
                continue
                
        return {"error": f"Falha após 3 tentativas: {last_error}"}, {}

    def analyze_image(self, image_path, prompt):
        """
        Utiliza o endpoint de CHAT com Budgets e Contexto dinâmicos.
        Implementa Retry-Fallback com drástica redução de VRAM a cada falha.
        """
        base_max_size = int(os.getenv("AI_IMAGE_RESOLUTION", "2048"))
        ctx_window = int(os.getenv("AI_CONTEXT_WINDOW", "32768"))
        
        last_error = None
        for attempt in range(3):
            # Reduz agressivamente a resolução em 512px por falha
            max_size = max(512, base_max_size - (attempt * 512))
            
            with Image.open(image_path) as img:
                img.thumbnail((max_size, max_size))
                buffered = BytesIO()
                img.save(buffered, format="JPEG", quality=90 - (attempt * 10))
                img_bytes = buffered.getvalue()
                img_str = base64.b64encode(img_bytes).decode('utf-8')
    
            payload = {
                "model": self.vision_model,
                "messages": [
                    {
                        "role": "system",
                        "content": "Você é um especialista em análise visual de documentos. Extraia informações em JSON puro, sem explicações."
                    },
                    {
                        "role": "user",
                        "content": prompt,
                        "images": [img_str]
                    }
                ],
                "stream": False,
                "think": False,
                "options": {
                    "num_ctx": ctx_window,
                    "num_predict": 2048,
                    "temperature": 0.1,
                    "top_p": 0.9
                }
            }
            
            try:
                # BLOQUEIO HOMOGÊNEO
                with ollama_lock:
                    timeout_val = _env_float("OLLAMA_VISION_TIMEOUT", 600)
                    response = requests.post(self.url, json=payload, timeout=timeout_val)
                _raise_for_server_error(response)

                raw_text = response.text
                data = self._clean_json_response(raw_text)
                
                duration_ms = round(data.get("total_duration", 0) / 1000000, 2)
                duration_sec = round(duration_ms / 1000, 2)
                duration_min = round(duration_sec / 60, 2)
                
                metrics = {
                    "input_tokens": data.get("prompt_eval_count", 0),
                    "output_tokens": data.get("eval_count", 0),
                    "total_duration_ms": duration_ms,
                    "total_duration_sec": duration_sec,
                    "total_duration_min": duration_min,
                    "total_duration_hr": round(duration_min / 60, 2)
                }
    
                message_content = ""
                if "message" in data:
                    message_content = data["message"].get("content", "")
                
                if not message_content:
                    return {"error": "A IA retornou uma mensagem vazia", "raw_response": raw_text}, img_bytes, metrics
                    
                return self._clean_json_response(message_content), img_bytes, metrics
            
            except Exception as e:
                last_error = str(e)
                import time; time.sleep(3)
                continue
                
        return {"error": f"Falha crítica na API em 3 tentativas: {last_error}"}, None, {}

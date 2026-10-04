# SPDX-License-Identifier: AGPL-3.0-or-later
import os
import sys
import requests
import base64
import time
from PIL import Image
from io import BytesIO

# Configuracoes da API do Ollama
OLLAMA_URL = "http://localhost:11434/api/chat"
IMAGE_PATH = sys.argv[1] if len(sys.argv) > 1 else None  # usage: python scripts/test_vision_models.py path/to/image.jpg
MODELS = ["hf.co/unsloth/Qwen3.5-9B-GGUF:Q6_K"]

PROMPT = """
OBJETIVO: Agir como um perito em análise de documentos e extrair TODOS os endereços da imagem.

INSTRUÇÕES CRÍTICAS:
1. Junte os componentes do mesmo endereço (ex: Rua, Número, Casa/Lote, Bairro, CEP, Cidade, UF) em um único endereço completo, estruturado e contínuo. Não retorne fragmentos separados.
2. Classifique rigorosamente:
   - "pessoal": Qualquer endereço de residência civil, domicílio de pessoa física ou do contratante quando este for pessoa física (ex: endereços residenciais contendo Casa, Apto, Bloco, condomínios ou setores residenciais como SMPW).
   - "profissional": Sede de empresas, escritórios ou órgãos de serviço.
   - "secundário": Local de obra, canteiro, fazenda de posse ou empreendimento.

FORMATO DE SAÍDA (APENAS JSON):
{
  "addresses": [
    {"text": "Endereço completo 1", "type": "categoria"},
    {"text": "Endereço completo 2", "type": "categoria"}
  ]
}
"""

def get_image_base64(path, max_resolution):
    with Image.open(path) as img:
        img.thumbnail((max_resolution, max_resolution))
        buffered = BytesIO()
        img.save(buffered, format="JPEG", quality=90)
        img_bytes = buffered.getvalue()
        return base64.b64encode(img_bytes).decode('utf-8')

def test_model_scenarios(model_name, image_base64, resolution):
    scenarios = [
        {"name": "Scenario A (think: False)", "payload_extra": {"think": False}, "options": {"num_ctx": 35000, "temperature": 0.1}},
        {"name": "Scenario B (think: True, num_predict: 8192)", "payload_extra": {}, "options": {"num_ctx": 35000, "temperature": 0.1, "num_predict": 8192}}
    ]
    
    for scenario in scenarios:
        print("\n==================================================")
        print(f"TESTANDO MODELO: {model_name} (Resolucao: {resolution}px) - {scenario['name']}")
        print("==================================================")
        
        payload = {
            "model": model_name,
            "messages": [
                {
                    "role": "system",
                    "content": "Você é um especialista em análise visual de documentos. Extraia informações em JSON puro, sem explicações."
                },
                {
                    "role": "user",
                    "content": PROMPT,
                    "images": [image_base64]
                }
            ],
            "stream": False,
            "format": "json",
            "options": scenario["options"],
            **scenario["payload_extra"]
        }
        
        start_time = time.time()
        try:
            response = requests.post(OLLAMA_URL, json=payload, timeout=180)
            duration = time.time() - start_time
            print(f"Status Code: {response.status_code}")
            print(f"Tempo de Resposta: {duration:.2f}s")
            
            if response.status_code == 200:
                try:
                    data = response.json()
                    message_content = data.get("message", {}).get("content", "")
                    print("\n--- Resposta da IA ---")
                    print(message_content)
                    print("----------------------")
                except Exception as parse_err:
                    print(f"Erro ao processar JSON de retorno: {parse_err}")
                    print(f"Resposta bruta: {response.text}")
            else:
                print(f"Erro retornado pelo Ollama: {response.text}")
                
        except Exception as e:
            print(f"Falha/Timeout na requisicao: {e}")

def main():
    if not IMAGE_PATH or not os.path.exists(IMAGE_PATH):
        print("ERRO: Imagem de teste nao encontrada no caminho especificado:")
        print(f"  {IMAGE_PATH}")
        return
        
    # Testar apenas resolucao 1024px para fins de velocidade e precisao comprovadas
    res = 1024
    print(f"\n[+] Codificando imagem com resolucao maxima de {res}px...")
    try:
        image_base64 = get_image_base64(IMAGE_PATH, res)
        print(f"Tamanho base64: {len(image_base64)} caracteres.")
    except Exception as img_err:
        print(f"Erro ao processar imagem para {res}px: {img_err}")
        return
        
    for model in MODELS:
        test_model_scenarios(model, image_base64, res)


if __name__ == "__main__":
    main()

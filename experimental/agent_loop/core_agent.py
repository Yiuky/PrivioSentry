# SPDX-License-Identifier: AGPL-3.0-or-later
import os
import json
import base64
import requests
from io import BytesIO
from PIL import Image
from agent_loop.agent_tools import AgentTools
from agent_loop.grid_system import SpatialGrid

# Configuração Padrão do Ollama Local
OLLAMA_URL = "http://localhost:11434/api/chat"
VISION_MODEL = os.getenv("OLLAMA_VISION_MODEL", "gemma4:e4b") # Modelo multimodal com boa percepção

SYSTEM_PROMPT = """Você é um Agente Analista especializado na LGPD (Lei Brasileira).
Sua missão é identificar e TARJAR informações sensíveis como CPFs (Sequencia de 11 números, comumente sendo xxx.xxx.xxx-xx), e Endereços PESSOAIS.

ATENÇÃO: APENAS Endereços Pessoais (residências de pessoas físicas) devem ser tarjados. 
Endereços Profissionais, Sedes de Empresas, Prefeituras, Órgãos Públicos ou Fazendas/Empreendimentos puramente comerciais NÃO devem ser tarjados.
ATENÇÃO: NOMES DE PESSOAS NÃO DEVEM SER TARJADOS (Regra de Negócio: Nomes são necessários para identificação do processo). 

ATENÇÃO: Caso identifique qualquer CPFs ou Endereço parcial, ou se a leitura do OCR for duvidosa/borrada em uma dessas áreas sensíveis, você deve ser AGRESSIVO: tarje o BLOCO INTEIRO (a palavra completa ou o conjunto de bboxes) para garantir 100% de obscuridade.

Para verificar se é um CPF, você pode usar a ferramenta de validar_cpf, que recebe uma string e retorna True se for um CPF válido, e False caso contrário.
Se o CPF já tiver sido tarjado, tarje novamente. O importante é que todos os CPFs estejam tarjados na imagem final.
Você guiará ferramentas usando JSON ESTRITO.

Para se guiar pela imagem gigante, as imagens que eu lhe envio contêm uma GRADE de coordenadas (A1, A2, B1, etc.).

Ações permitidas:
1. "zoom": (Input: ID do quadrante, ex: "B2") -> Eu lhe enviarei um recorte HD de perto daquele setor.
2. "read": (Input: ID do quadrante, ex: "C1") -> Farei OCR e devolverei as palavras com seus Bounding Boxes espaciais [x, y, w, h] exatos da folha.
3. "read_line": (Input: Array com Quadrante e Y, ex: ["B2", 1540]) -> Lê a linha inteira APENAS dentro daquela célula (A1, B2...) para você entender o contexto sem ver outras colunas.
4. "validar_cpf": (Input: A string suspeita a ser checada, ex: "123.456.789-00") -> Eu rodo a matriz federal e te aviso se é Verdadeiro (para ser tarjado) ou Falso (falso positivo inútil).
5. "tarjar": (Input: A array exata do Bounding Box recebida no read, ex: [260, 300, 150, 15]) -> Aplica cirurgicamente a tarja preta.
6. "finish": (Input: "none") -> Quando não houver mais nada para procurar na tela inteira.

ATENÇÃO: NUNCA tente tarjar um "Quadrante Inteiro" (Exemplo: "B2" no tarjar falhará o sistema).
Para esconder um dado sensível, você OBRIGATORIAMENTE precisa usar "read" num quadrante, aguardar eu devolver o JSON contendo os bboxes exatos de cada palavra, e SÓ ENTÃO usar a ação "tarjar" passando a array de números correspondente ao que você quer esconder.

Sua primeira ação sempre deve ser analisar a tela inteira, se não der pra ler, dê zoom. Ou então interaja lendo as células.

Estrutura OBRIGATÓRIA (sempre retorne neste formato):
{
  "thought": "raciocínio sobre o que devo fazer agora",
  "action": "zoom",
  "action_input": "A1"
}

NUNCA responda nada além do JSON absoluto.
"""

class ReActAgent:
    def __init__(self, base_image_path):
        self.grid = SpatialGrid(cols=4, rows=6)
        self.tools = AgentTools(base_image_path)
        self.image_path = base_image_path
        self.log_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "agent_brain_log.txt")
        self.output_img = os.path.join(os.path.dirname(os.path.abspath(__file__)), "final_result_by_agent.jpg")
        
        # Inicia zera o log
        with open(self.log_file, "w", encoding="utf-8") as f:
            f.write(f"--- INIT AGENT LOOP PARA {base_image_path} ---\n")
            
        self.grid_image_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "grid_view.jpg")
        self.grid.render_grid_on_image(self.image_path, self.grid_image_path)
        
        self.messages = [
            {"role": "system", "content": SYSTEM_PROMPT}
        ]

    def _log_to_file(self, content):
        with open(self.log_file, "a", encoding="utf-8") as f:
            f.write(content + "\n")

    def _img_to_base64(self, path):
        with Image.open(path) as img:
            img.thumbnail((2048, 2048)) 
            buffered = BytesIO()
            img.save(buffered, format="JPEG", quality=80)
            return base64.b64encode(buffered.getvalue()).decode('utf-8')

    def step(self):
        print("\n[*] Agente Pensando...")
        payload = {
            "model": VISION_MODEL,
            "messages": self.messages,
            "stream": False,
            "format": "json",
            "options": {"temperature": 0.1, "num_ctx": 40000}
        }
        
        try:
            r = requests.post(OLLAMA_URL, json=payload, timeout=300)
            data = r.json()
            reply = data.get("message", {}).get("content", "")
            return reply
        except Exception as e:
            print(f"Erro na IA: {e}")
            return '{"thought": "Erro de conexão API. Abortando loop.", "action": "finish", "action_input": "none"}'

    def run_loop(self, max_steps=12, discovery_context=None):
        # 1. Se houver redações prévias, aplica elas fisicamente na memória
        if discovery_context and "boxes" in discovery_context:
            self.tools.apply_initial_redactions(discovery_context["boxes"])
        
        # 2. Cria uma imagem temporária JÁ TARJADA para ser a base do Agente
        temp_base_redacted = os.path.join(os.path.dirname(os.path.abspath(__file__)), "temp_base_redacted.jpg")
        self.tools.render_final_output(temp_base_redacted)
        
        # 3. Gera a imagem da grade em cima da imagem que JÁ ESTÁ TARJADA
        self.grid.render_grid_on_image(temp_base_redacted, self.grid_image_path)
            
        initial_image_b64 = self._img_to_base64(self.grid_image_path)
        
        # 3. Mapeia regiões YOLO para Quadrantes específicos para facilitar a vida da IA
        yolo_list = discovery_context.get("yolo_regions", []) if discovery_context else []
        yolo_map_str = "Nenhuma área YOLO detectada."
        if yolo_list:
            yolo_quadrants = set()
            for rect in yolo_list:
                # Centro do rect: x + w/2, y + h/2
                cx, cy = rect[0] + rect[2]/2, rect[1] + rect[3]/2
                for label, box in self.grid.cells.items():
                    if (box["x"] <= cx <= box["x"]+box["w"]) and (box["y"] <= cy <= box["y"]+box["h"]):
                        yolo_quadrants.add(label)
            yolo_map_str = ", ".join(sorted(list(yolo_quadrants)))

        pii_list = discovery_context.get("pii_list", []) if discovery_context else []
        addr_list = discovery_context.get("address_list", []) if discovery_context else []
        
        pii_str = ", ".join(pii_list) if pii_list else "Nenhum CPF óbvio."
        addr_str = ", ".join(addr_list) if addr_list else "Nenhum Endereço óbvio."
        
        # 4. Inicia rastreador de progresso
        self.visited_quadrants = set()
        self.all_quadrants = sorted(list(self.grid.cells.keys()))
        
        first_msg = f"""Aqui está o documento atual. 
O motor de Heurística já analisou a folha e já tarjou os seguintes dados:
- CPFs: {pii_str}
- Endereços: {addr_str}
- Quadrantes com Assinaturas/Carimbos (YOLO): {yolo_map_str}

SUA MISSÃO - VARREDURA SISTEMÁTICA TOTAL:
1. Você OBRIGATORIAMENTE deve percorrer TODA a grade de coordenadas ({", ".join(self.all_quadrants)}).
2. Dê prioridade absoluta aos quadrantes YOLO: {yolo_map_str}.
3. Se verificar qualquer dado sensível parcial ou ilegível em áreas críticas, tarje o BLOCO INTEIRO por segurança.
4. Você NÃO pode chamar "finish" antes de ler ou dar zoom em cada um dos {len(self.all_quadrants)} setores.
5. ATENÇÃO: Nomes de pessoas NÃO devem ser tarjados.

Inicie agora por A1."""
        
        self.messages.append({
            "role": "user",
            "content": first_msg,
            "images": [initial_image_b64]
        })
        self._log_to_file(f"[USER] {first_msg}")
        
        step_count = 0
        while step_count < max_steps:
            step_count += 1
            print(f"\n" + "="*50)
            print(f" AUDIT STEP {step_count}/{max_steps}")
            print("="*50)
            
            reply_text = self.step()
            print(f"---> LLM Answer: {reply_text.strip()}")
            self._log_to_file(f"[AGENTE]\n{reply_text.strip()}\n")
            
            self.messages.append({"role": "assistant", "content": reply_text})
            
            try:
                command = json.loads(reply_text)
            except json.JSONDecodeError:
                err = "Erro: Você deve responder em formato JSON estrito."
                self.messages.append({"role": "user", "content": err})
                self._log_to_file(f"[SYSTEM] {err}")
                continue
                
            action = command.get("action")
            action_input = command.get("action_input", "")
            
            if action == "finish":
                pending = [q for q in self.all_quadrants if q not in self.visited_quadrants]
                if pending:
                    err = f"Erro: Você tentou finalizar a página sem auditar os quadrantes: {', '.join(pending)}. Continue a varredura até completar todos."
                    print(f"[!] Agente tentou fugir! Bloqueando finish. Pendentes: {pending}")
                    self.messages.append({"role": "user", "content": err})
                    continue

                print(f"[+] O Agente declarou que a auditoria da página terminou.")
                self._log_to_file("\n[SYSTEM] FIM DO PROCESSAMENTO DE PÁGINA (Action: finish).")
                self.tools.render_final_output(self.output_img)
                print(f"[!] Documento tarjado salvo em: {self.output_img}")
                print(f"[!] Histórico de pensamentos salvo em: {self.log_file}")
                break
                
            if action == "zoom":
                box = self.grid.get_coords(action_input)
                if not box:
                    self.messages.append({"role": "user", "content": f"Erro: Quadrante inválido."})
                    continue
                print(f"[*] ZOOM em {action_input}")
                self.visited_quadrants.add(action_input.upper())
                zoom_file = self.tools.execute_zoom(box, os.path.join(os.path.dirname(os.path.abspath(__file__)), f"zoom_{action_input}.jpg"))
                img_b64 = self._img_to_base64(zoom_file)
                
                pending = [q for q in self.all_quadrants if q not in self.visited_quadrants]
                msg = f"Aqui está o corte focado de {action_input}. Auditados: {len(self.visited_quadrants)}/24. Pendentes: {', '.join(pending)}"
                
                self.messages.append({"role": "user", "content": msg, "images": [img_b64]})
                self._log_to_file(f"[SYSTEM] Ferramenta Zoom executada em {action_input}.")
                
            elif action == "read":
                box = self.grid.get_coords(action_input)
                if not box:
                    self.messages.append({"role": "user", "content": f"Erro: Quadrante inválido."})
                    continue
                print(f"[*] LENDO OCR de {action_input}")
                self.visited_quadrants.add(action_input.upper())
                text = self.tools.execute_read(box)
                print(f"---> OCR Result: {text}")
                
                # Devolvemos o texto E o Grid atualizado para a IA manter consciência espacial total
                img_b64 = self._img_to_base64(self.grid_image_path)
                pending = [q for q in self.all_quadrants if q not in self.visited_quadrants]
                msg = f"O setor {action_input} retornou OCR. Auditados: {len(self.visited_quadrants)}/24. Pendentes: {', '.join(pending)}\n\n{text}"
                
                self.messages.append({
                    "role": "user", 
                    "content": msg,
                    "images": [img_b64]
                })
                self._log_to_file(f"[SYSTEM] Leitura OCR executada em {action_input} com atualização de imagem.")
                
            elif action == "validar_cpf":
                print(f"[*] VALIDANDO CPF FÍSICO: {action_input}")
                res = self.tools.execute_validar_cpf(action_input)
                self.messages.append({
                    "role": "user",
                    "content": f"O sistema rodou o verificador sobre '{action_input}': {res}"
                })
                self._log_to_file(f"[SYSTEM] Ferramenta validar_cpf: {action_input} -> {res}")
                
            elif action == "read_line":
                try:
                    # Suporta ["A1", 1000] ou apenas o número 1000
                    quadrante = None
                    y_val = None
                    
                    if isinstance(action_input, list) and len(action_input) == 2:
                        quadrante = action_input[0]
                        y_val = int(action_input[1])
                    else:
                        y_val = int(action_input)
                    
                    x_min, x_max = 0, None
                    if quadrante:
                        box = self.grid.get_coords(quadrante)
                        if box:
                            x_min = box["x"]
                            x_max = box["x"] + box["w"]
                    
                    print(f"[*] LENDO LINHA LOCALIZADA (Y={y_val}, Q={quadrante})")
                    res = self.tools.execute_read_line(y_val, x_min=x_min, x_max=x_max)
                    print(f"---> Line Content: {res}")
                    self.messages.append({"role": "user", "content": res})
                    self._log_to_file(f"[SYSTEM] {res}")
                except Exception as e:
                    err = f"Erro: action_input para read_line deve ser um número ou ['A1', Y]. Detalhe: {e}"
                    self.messages.append({"role": "user", "content": err})
                
            elif action == "tarjar":
                # Resiliência Antialucinação: Converte quase qualquer formato (string, lista dupla, etc) em Bboxes reais
                bboxes_to_process = []
                
                def extract_bboxes(raw_input):
                    import re
                    # Se for lista pura [x,y,w,h]
                    if isinstance(raw_input, list) and len(raw_input) == 4 and all(isinstance(v, (int, float)) for v in raw_input):
                        return [raw_input]
                    # Se for lista de listas [[x,y,w,h], ...]
                    if isinstance(raw_input, list) and len(raw_input) > 0 and isinstance(raw_input[0], list):
                        return [b for b in raw_input if isinstance(b, list) and len(b) == 4]
                    # Se for string "[1,2,3,4]" ou "[1,2,3,4], [5,6,7,8]"
                    if isinstance(raw_input, str):
                        found = re.findall(r'\[\s*(\d+(?:\.\d+)?)\s*,\s*(\d+(?:\.\d+)?)\s*,\s*(\d+(?:\.\d+)?)\s*,\s*(\d+(?:\.\d+)?)\s*\]', raw_input)
                        return [[float(v) for v in box] for box in found]
                    return []

                bboxes_to_process = extract_bboxes(action_input)

                if not bboxes_to_process:
                    err = "Erro matemático: action_input da tarja inválido. Deve ser um array [x, y, w, h]. Recebi: " + str(action_input)
                    self.messages.append({"role": "user", "content": err})
                    self._log_to_file(f"[SYSTEM] {err}")
                    continue
                # 1. Aplica as tarjas logicas
                for bbox in bboxes_to_process:
                    print(f"[*] TARJANDO bloco físico {bbox}!")
                    self.tools.execute_tarjar(bbox)
                
                # 2. RENDERIZAÇÃO DE FEEDBACK: Gera a nova imagem com as tarjas físicas aplicadas
                temp_base_redacted = os.path.join(os.path.dirname(os.path.abspath(__file__)), "temp_base_redacted.jpg")
                self.tools.render_final_output(temp_base_redacted)
                
                # 3. ATUALIZA A GRADE: Desenha a grade sobre a folha recém-tarjada
                self.grid.render_grid_on_image(temp_base_redacted, self.grid_image_path)
                
                # 4. ENVIA PARA O AGENTE: Ele agora vê que o lugar ficou preto
                img_b64 = self._img_to_base64(self.grid_image_path)
                msg = f"Sucesso: {len(bboxes_to_process)} blocos foram tarjados. Aqui está o documento atualizado para continuar sua varredura."
                
                self.messages.append({"role": "user", "content": msg, "images": [img_b64]})
                self._log_to_file(f"[SYSTEM] Tarjas aplicadas e imagem de grid atualizada enviada.")
            else:
                self.messages.append({"role": "user", "content": "Erro: Action ignorada ou desconhecida."})
                
        # Garante exportação mesmo que estoure o limite de turnos sem pedir 'finish'
        if step_count >= max_steps:
            print(f"\n[!] Teto de Operações Atingido ({max_steps} turnos). Forçando renderização Final.")
            self._log_to_file("\n[SYSTEM] FIM FORÇADO: TIMEOUT DE TURNOS.")
            self.tools.render_final_output(self.output_img)
            print(f"[!] Documento tarjado salvo emergencialmente em: {self.output_img}")
            print(f"[!] Histórico de pensamentos fechado em: {self.log_file}")

# SPDX-License-Identifier: AGPL-3.0-or-later
import os
from PIL import Image, ImageDraw
import pytesseract
import re

pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

class AgentTools:
    def __init__(self, base_image_path):
        self.base_image_path = base_image_path
        self.redactions = [] # Registra todas as tarjas feitas

    def apply_initial_redactions(self, boxes):
        """Aplica tarjas vindas do motor de heurística antes do agente começar."""
        if not boxes: return
        print(f"[*] Aplicando {len(boxes)} tarjas iniciais do motor de Heurística...")
        self.redactions.extend(boxes)

    def execute_zoom(self, box, output_filename="current_zoom.jpg", overlap=300):
        """Recorta um pedaço expandido (com sobreposição) para evitar morte de contexto nas bordas do grid."""
        try:
            with Image.open(self.base_image_path) as img:
                w_max, h_max = img.size
                x1 = max(0, box["x"] - overlap)
                y1 = max(0, box["y"] - overlap)
                x2 = min(w_max, box["x"] + box["w"] + overlap)
                y2 = min(h_max, box["y"] + box["h"] + overlap)
                
                crop = img.crop((x1, y1, x2, y2))
                crop.save(output_filename, "JPEG", quality=90)
                return output_filename
        except Exception as e:
            print(f"Failed to zoom: {e}")
            return None

    def execute_read(self, box, overlap=300):
        """Faz OCR numa versão expandida do bloco para salvar palavras cortadas no limite da coordenada."""
        try:
            with Image.open(self.base_image_path) as img:
                w_max, h_max = img.size
                x1 = max(0, box["x"] - overlap)
                y1 = max(0, box["y"] - overlap)
                x2 = min(w_max, box["x"] + box["w"] + overlap)
                y2 = min(h_max, box["y"] + box["h"] + overlap)

                crop = img.crop((x1, y1, x2, y2))
                data = pytesseract.image_to_data(crop, lang="por+eng", config="--psm 3", output_type=pytesseract.Output.DICT)
                
                results = []
                for i in range(len(data['text'])):
                    text = data['text'][i].strip()
                    if text:
                        # Compensação Matemática: Transcreve as arrays com base no x1 expandido em vez do grid zero.
                        bx = data['left'][i] + x1
                        by = data['top'][i] + y1
                        bw = data['width'][i]
                        bh = data['height'][i]
                        results.append(f"'{text}' -> [{bx}, {by}, {bw}, {bh}]")
                if not results: return "Nenhum texto legível encontrado neste setor."
                return "Texto e Bounding Boxes (Área Expandida com Sobreposição em 300px):\n" + "\n".join(results)
        except Exception as e:
            return f"Error reading text: {e}"

    def execute_read_line(self, y_coord, height=80, x_min=0, x_max=None):
        """Faz um OCR horizontal restrito a um intervalo X ou à célula para entender o contexto de uma linha."""
        try:
            with Image.open(self.base_image_path) as img:
                w_img, h_img = img.size
                if x_max is None: x_max = w_img
                
                # Define uma faixa horizontal
                y1 = max(0, y_coord - (height // 2))
                y2 = min(h_img, y_coord + (height // 2))
                
                # Restringe ao X da célula se solicitado
                crop = img.crop((x_min, y1, x_max, y2))
                text = pytesseract.image_to_string(crop, lang="por+eng", config="--psm 7")
                
                if not text.strip():
                    return f"Linha (Y={y_coord}) no intervalo X[{x_min}-{x_max}] está vazia ou ilegível."
                return f"CONTEÚDO DA LINHA (Y={y_coord}, X={x_min}-{x_max}):\n{text.strip()}"
        except Exception as e:
            return f"Error reading line: {e}"

    def execute_validar_cpf(self, cpf_string):
        """Usa a constante matemática de soma ponderada para validar CPF federal."""
        numeros = re.sub(r'[^0-9]', '', str(cpf_string))
        if len(numeros) != 11:
            return f"Falso: '{cpf_string}' tem {len(numeros)} dígitos. CPFs reais têm 11."
        if numeros == numeros[0] * 11:
            return "Falso: Dígitos idênticos não formam CPF."
            
        def calc_digito(cpf_parc, peso_ini):
            soma = sum(int(d) * p for d, p in zip(cpf_parc, range(peso_ini, 1, -1)))
            resto = soma % 11
            return '0' if resto < 2 else str(11 - resto)
            
        d1 = calc_digito(numeros[:9], 10)
        d2 = calc_digito(numeros[:10], 11)
        
        if numeros[-2:] == d1 + d2:
            return "Verdadeiro: É um CPF matematicamente válido. (TARJE ESTE DADO)"
        return "Falso: Possui 11 dígitos, mas o dígito verificador matemático indica que NÃO é um CPF real (talvez seja um processo civil ou contrato)."

    def execute_tarjar(self, bbox_array):
        """Aplica uma tarja espacial numa coordenada cirúrgica."""
        try:
            xb, yb, wb, hb = bbox_array
            self.redactions.append({"x": xb, "y": yb, "w": wb, "h": hb})
            return f"TARJADO com Sucesso (Coordenada Pessoal cimentada em: {bbox_array})"
        except Exception as e:
            return f"Falha matemática ao iterar Box: {e}"

    def render_final_output(self, output_path="final_agent_result.jpg"):
        """Renderiza a imagem final aplicando todas as tarjas aprovadas."""
        try:
            with Image.open(self.base_image_path) as img:
                draw = ImageDraw.Draw(img)
                for r in self.redactions:
                    shape = [r["x"], r["y"], r["x"] + r["w"], r["y"] + r["h"]]
                    draw.rectangle(shape, fill="black", outline="black")
                img.save(output_path, "JPEG", quality=85)
                return output_path
        except Exception as e:
            print(f"Error rendering final: {e}")
            return None

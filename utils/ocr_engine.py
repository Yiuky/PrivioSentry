# SPDX-License-Identifier: AGPL-3.0-or-later
import re
import pytesseract
from PIL import Image
from utils.validators import is_valid_cpf, is_valid_cnpj

class OCREngine:
    def __init__(self, tesseract_path, lang="por+eng", logger=None):
        self.tesseract_path = tesseract_path
        self.lang = lang
        self.logger = logger
        if self.tesseract_path:
            pytesseract.pytesseract.tesseract_cmd = self.tesseract_path

    def _run_tesseract_with_fallback(self, img, method="data", psm=3):
        """Internal helper to execute Tesseract with 50% fallback resize on crash."""
        w_orig, h_orig = img.size
        custom_config = f'--psm {psm}'
        
        def attempt_scan(img_input, current_scale):
            if method == "data":
                data = pytesseract.image_to_data(img_input, lang=self.lang, config=custom_config, output_type=pytesseract.Output.DICT)
                if current_scale != 1.0:
                    for key in ['left', 'top', 'width', 'height']:
                        data[key] = [int(v / current_scale) for v in data[key]]
                return data
            else:
                text = pytesseract.image_to_string(img_input, lang=self.lang, config=custom_config).strip()
                return text

        # Attempt 1: 100% size
        try:
            return attempt_scan(img, 1.0)
        except Exception:
            if self.logger:
                self.logger.warning(f"[!] TESSERACT FALLBACK: Crash at full size ({w_orig}x{h_orig}). Retrying at 50%...")
            
            # Attempt 2: 50% size
            try:
                scale = 0.5
                img_safe = img.resize((int(w_orig * scale), int(h_orig * scale)), resample=Image.Resampling.LANCZOS)
                return attempt_scan(img_safe, scale)
            except Exception as e2:
                if self.logger:
                    self.logger.error(f"[!!] TESSERACT CRITICAL FAIL: {e2}")
                return {"text": []} if method == "data" else ""

    def image_to_data(self, img, psm=3):
        return self._run_tesseract_with_fallback(img, method="data", psm=psm)

    def image_to_string(self, img, psm=3):
        return self._run_tesseract_with_fallback(img, method="string", psm=psm)

    def get_full_ocr_data(self, img_path, psm=11):
        """Processes page in two halves (Top/Bottom) for maximum precision, using universal fallback."""
        img_orig = Image.open(img_path).convert("RGB")
        w, h = img_orig.size
        
        half_h = int(h * 0.55)
        top_half = img_orig.crop((0, 0, w, half_h))
        bottom_half = img_orig.crop((0, h - half_h, w, h))
        
        # Safe execution on both halves
        data_top = self.image_to_data(top_half, psm=psm)
        data_bottom = self.image_to_data(bottom_half, psm=psm)
        
        # Merge data_bottom into data_top with coordinate and hierarchy offset
        offset_y = h - half_h
        max_block = max(data_top.get('block_num', [0])) if data_top.get('block_num') else 0
        
        for i in range(len(data_bottom.get('text', []))):
            for key in data_top.keys():
                val = data_bottom[key][i]
                if key == 'top' and data_bottom['level'][i] >= 2:
                    val += offset_y
                if key == 'block_num':
                    val += max_block
                data_top[key].append(val)
                
        return data_top

    def extract_page_text(self, img_path, psm=11):
        """Standardizes on split-processing for character recognition too."""
        data = self.get_full_ocr_data(img_path, psm)
        # Use only valid text items (words)
        words = []
        for i, text in enumerate(data['text']):
            if data['level'][i] == 5: # Level 5 is Word
                if str(text).strip():
                    words.append(str(text))
        return " ".join(words)

    def get_grounding_map(self, img_path, psm=3):
        """
        Gera Markdown Indexado e um JSON estruturado de objetos (Words).
        Preserva parágrafos e quebras de linha.
        """
        data = self.get_full_ocr_data(img_path, psm)
        
        md_lines = []
        current_line_text = []
        clean_map = []
        
        last_block = -1
        last_line = -1
        
        for i in range(len(data['text'])):
            if data['level'][i] == 5: # Word
                text = str(data['text'][i]).strip()
                if text:
                    block_num = data['block_num'][i]
                    line_num = data['line_num'][i]
                    
                    # Gestão de Layout (Markdown)
                    if block_num != last_block and last_block != -1:
                        if current_line_text:
                            md_lines.append(" ".join(current_line_text))
                        md_lines.append("") # Parágrafo
                        current_line_text = []
                    elif line_num != last_line and last_line != -1:
                        if current_line_text:
                            md_lines.append(" ".join(current_line_text))
                        current_line_text = []
                    
                    idx = len(clean_map)
                    current_line_text.append(f"[{idx}] {text}")
                    
                    # JSON Estruturado e Arrumado
                    clean_map.append({
                        "id": idx,
                        "text": text,
                        "box": {
                            "x": data["left"][i],
                            "y": data["top"][i],
                            "w": data["width"][i],
                            "h": data["height"][i]
                        },
                        "conf": data["conf"][i]
                    })
                    
                    last_block = block_num
                    last_line = line_num
        
        # Adiciona a última linha pendente
        if current_line_text:
            md_lines.append(" ".join(current_line_text))
            
        return "\n".join(md_lines), clean_map

    def find_cpfs_in_grounding(self, grounding_map):
        """
        Identifica quais IDs e quais CARACTERES dentro desses IDs compõem um CPF.
        Aplica filtros de 'Jump-11' para evitar ecos de repetição e 
        heurística de exclusão para padrões de Data/Hora.
        """
        digit_to_source = [] # [(digito, word_id, char_idx), ...]
        
        # Expressões para identificar se a palavra original parece uma Data ou Hora
        date_pattern = re.compile(r'\d{2,4}[./-]\d{2}[./-]\d{2,4}')
        time_pattern = re.compile(r'\d{2}:\d{2}:\d{2}')
        
        excluded_ids = set()
        
        digits_only = ""
        last_box = None
        
        for word_id, item in enumerate(grounding_map):
            text = item["text"]
            box = item["box"]
            
            # Marcar IDs que parecem datas/horas para evitar colisões acidentais
            if date_pattern.search(text) or time_pattern.search(text):
                digits_only += "X"
                digit_to_source.append(("X", -1, -1))
                excluded_ids.add(word_id)
                continue
                
            word_digits = []
            for char_idx, char in enumerate(text):
                if char.isdigit():
                    word_digits.append((char, word_id, char_idx))
            
            if word_digits:
                # Checa a distância geométrica do último box numérico
                if last_box is not None:
                    y_diff = abs(box['y'] - last_box['y'])
                    # Evita divisões por zero ou valores negativos no gap X
                    x_dist = max(0, box['x'] - (last_box['x'] + last_box['w']))
                    
                    max_h = max(box['h'], last_box['h'])
                    
                    # Se estiver em outra linha (y_diff > 1.5x) ou muito distante (x_dist > 4x a altura da fonte)
                    if y_diff > max_h * 1.5 or x_dist > max_h * 4:
                        digits_only += "X"
                        digit_to_source.append(("X", -1, -1))
                
                for char, w_id, c_idx in word_digits:
                    digits_only += char
                    digit_to_source.append((char, w_id, c_idx))
                    
                last_box = box
        redaction_commands = {}
        found_cpfs = set()
        
        if len(digits_only) >= 11:
            # === PRE-FILTRO DE CNPJs ===
            # CNPJs (14 digs) não devem ser tarjados. Sub-sequências de 11 num CNPJ podem colidir com CPFs!
            if len(digits_only) >= 14:
                chars_list = list(digits_only)
                j = 0
                while j <= len(chars_list) - 14:
                    candidate_cnpj = "".join(chars_list[j:j+14])
                    if 'X' not in candidate_cnpj and is_valid_cnpj(candidate_cnpj):
                        for k in range(j, j+14): chars_list[k] = 'X'
                        j += 14 # Pula o CNPJ inteiro
                    else:
                        j += 1
                digits_only = "".join(chars_list)

            # === BUSCA DE CPFs ===
            i = 0
            while i <= len(digits_only) - 11:
                candidate = digits_only[i:i+11]
                
                # Se houver uma quebra geográfica na string candidata, pula pra depois dela
                x_pos = candidate.rfind('X')
                if x_pos != -1:
                    i += x_pos + 1
                    continue
                    
                if is_valid_cpf(candidate):
                    # Verifica se o 'núcleo' do CPF não vem de um campo de data/hora excluído
                    involved_ids = {digit_to_source[k][1] for k in range(i, i+11)}
                    
                    # Se todos os IDs envolvidos forem 'data/hora', ignoramos (colisão provável)
                    if involved_ids.issubset(excluded_ids):
                        i += 1
                        continue
                        
                    found_cpfs.add(candidate)
                    for k in range(i, i+11):
                        _, w_id, c_idx = digit_to_source[k]
                        if w_id not in redaction_commands:
                            redaction_commands[w_id] = set()
                        redaction_commands[w_id].add(c_idx)
                    
                    # PULO DO GATO: Se achou um CPF, pula 11 posições para evitar 'ecos'
                    i += 11
                else:
                    i += 1
                        
        return redaction_commands, found_cpfs

    def find_address_in_grounding(self, coordinate_map, address_text):
        """
        Localiza as caixas geométricas de um endereço, ignorando labels/cabeçalhos.
        """
        import re
        def normalize(t): return re.sub(r'[^\w\s]', '', t).lower().strip()
        
        # Lista de Labels que NÃO devem ser tarjados
        SKIP_LABELS = {
            "rua", "avenida", "av", "logradouro", "bairro", "cidade", "estado", "uf", 
            "numero", "nº", "num", "complemento", "compl", "cep", "endereço", "endereco",
            "país", "pais"
        }
        
        target = normalize(address_text)
        if not target: return []
        
        # Palavras-chave do endereço (mais de 2 letras e que NÃO sejam labels)
        keywords = []
        for word in target.split():
            norm_word = normalize(word)
            if len(norm_word) > 2 and norm_word not in SKIP_LABELS:
                keywords.append(norm_word)
        
        boxes = []
        # Se as palavras-chave principais (conteúdo) aparecerem no mapa, capturamos o box
        for item in coordinate_map:
            norm_word = normalize(item["text"])
            if norm_word and any(kw == norm_word for kw in keywords):
                boxes.append(item["box"])
        
        return boxes

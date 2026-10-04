# SPDX-License-Identifier: AGPL-3.0-or-later
import os
import json
from utils.ai_client import OllamaClient
from utils.lexicon import is_immune

class AddressRedactor:
    def __init__(self, session, logger):
        self.session = session
        self.logger = logger
        self.ai = OllamaClient()
        self.results = {}
        self.failed_pages = {}  # page_num -> motivo; páginas sem análise de endereço (revisão obrigatória)

    def run_discovery(self, image_paths):
        """
        Fase 1: Consulta a IA para identificar e classificar endereços nas imagens originais.
        """
        self.logger.info("--- ADDRESS REDACTOR: INICIANDO DESCOBERTA SEMÂNTICA ---")
        
        prompt = """
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

        for i, img_path in enumerate(image_paths):
            page_num = i + 1
            self.logger.info(f"[*] Analisando endereços na página {page_num} via AI ({self.ai.vision_model})...")
            
            # Consulta a visão da IA (agora retorna bytes e métricas)
            response, img_bytes, metrics = self.ai.analyze_image(img_path, prompt)
            
            # Salva interação completa para debug (Prompt, Resposta, Imagem e Métricas)
            prefix = f"page_{page_num}_address_discovery"
            self.session.save_ai_interaction(
                phase_key="Address_Redactor",
                prefix=prefix,
                prompt=prompt,
                response=response,
                metrics=metrics,
                img_bytes=img_bytes
            )

            if not isinstance(response, dict) or "error" in response:
                reason = response.get('error') if isinstance(response, dict) else "Resposta da IA em formato inesperado"
                self.logger.error(f"[!] Erro na IA para página {page_num}: {reason}")
                self.failed_pages[page_num] = str(reason)
                continue

            # Salva os resultados desta página
            self.results[page_num] = response.get("addresses", [])
            
            # Exporta o JSON de descoberta na pasta da sessão
            output_json = os.path.join(self.session.dirs["07_addresses_ia"], f"page_{page_num}_addresses.json")
            with open(output_json, "w", encoding='utf-8') as f:
                json.dump(response, f, indent=4, ensure_ascii=False)
                
            self.logger.info(f"[+] {len(self.results[page_num])} endereços encontrados na página {page_num}.")

        return self.results

    def refine_redaction_with_text_ai(self, page_num, indexed_text, discovered_addresses, coordinate_map=None):
        """
        Fase 2: Filtra e identifica quais IDs de palavras do mapa indexado pertencem a endereços pessoais.
        Utiliza um algoritmo de casamento de padrões determinístico e preciso em Python.
        """
        if not discovered_addresses:
            return []

        # Filtra apenas endereços pessoais
        pessoais = [a["text"] for a in discovered_addresses if a.get("type") == "pessoal"]
        if not pessoais:
            return []

        self.logger.info(f"[*] Refinando precisão da página {page_num} via Casamento de Padrões Programático...")

        # Se coordinate_map não foi fornecido, extrai os IDs e textos a partir de indexed_text
        if not coordinate_map:
            import re
            coordinate_map = []
            pattern = re.compile(r'\[(\d+)\]\s*([^\s\[]+)')
            for match in pattern.finditer(indexed_text):
                idx = int(match.group(1))
                word = match.group(2)
                coordinate_map.append({"id": idx, "text": word})

        import unicodedata
        import re

        def normalize_token(token):
            nfkd_form = unicodedata.normalize('NFKD', token)
            only_ascii = nfkd_form.encode('ASCII', 'ignore').decode('ASCII')
            return re.sub(r'[^A-Z0-9]', '', only_ascii.upper())

        # Strategy A: Tokens split by spaces and commas only (keeps hyphens, dots, slashes intact)
        strategy_a_tokens = set()
        # Strategy B: Tokens split by all punctuation (individual words)
        strategy_b_tokens = set()
        
        for addr in pessoais:
            # Strategy A
            for t in re.split(r'[\s,]+', addr):
                norm = normalize_token(t)
                if norm:
                    strategy_a_tokens.add(norm)
            # Strategy B
            for t in re.split(r'[\s,;\.\-\/]+', addr):
                norm = normalize_token(t)
                if norm:
                    strategy_b_tokens.add(norm)

        ids_to_redact = []
        
        for item in coordinate_map:
            word_text = item.get("text", "")
            w_id = item.get("id")
            
            # Check label safety filter: ending with colon
            if word_text.endswith(":"):
                continue
                
            # Check lexical protection
            if is_immune(word_text):
                continue
                
            # Normalize the word text
            norm_word = normalize_token(word_text)
            if not norm_word:
                continue
                
            matched = False
            # 1. Exact match in Strategy A tokens (e.g. A-1 matches A-1, 78.550-352 matches 78.550-352)
            if norm_word in strategy_a_tokens:
                matched = True
            # 2. Exact match in Strategy B tokens AND length is > 2 (to avoid matching short words like 1, 2, A, S)
            elif norm_word in strategy_b_tokens and len(norm_word) > 2:
                matched = True
            # 3. The OCR word is a compound word and contains one of the Strategy B tokens (length > 2) as substring
            elif any(t in norm_word for t in strategy_b_tokens if len(t) > 2):
                matched = True
                
            if matched:
                ids_to_redact.append(w_id)

        # Salva o debug da interação simulada para manter compatibilidade e auditoria
        dummy_prompt = f"AUDITORIA PROGRAMÁTICA DE ENDEREÇOS PESSOAIS\nEndereços Alvo: {pessoais}"
        self.session.save_ai_interaction(
            phase_key="Address_Audit_Programmatic",
            prefix=f"page_{page_num}_text_audit",
            prompt=dummy_prompt,
            response={"ids_to_redact": ids_to_redact},
            metrics={"total_duration_ms": 0}
        )

        return ids_to_redact

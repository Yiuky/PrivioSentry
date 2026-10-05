# SPDX-License-Identifier: AGPL-3.0-or-later
import os
import json
import re
import unicodedata
from utils.ai_client import OllamaClient
from utils.lexicon import is_immune

# Rótulos que o LLM costuma usar. Tudo é comparado sem acento, sem caixa e sem espaços nas pontas.
PERSONAL_TYPES = {"pessoal", "residencial", "residencia", "domicilio", "domiciliar", "particular", "moradia",
                  "personal", "residential", "home"}
NON_PERSONAL_TYPES = {"profissional", "comercial", "empresarial", "institucional", "trabalho", "secundario",
                      "obra", "empreendimento", "professional", "business", "secondary", "work"}


def _normalize_label(value):
    text = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode("ascii")
    return " ".join(text.lower().split())


def classify_address_type(value):
    """'pessoal', 'nao_pessoal' ou 'desconhecido' para o rótulo de tipo devolvido pelo LLM."""
    label = _normalize_label(value)
    if label in PERSONAL_TYPES:
        return "pessoal"
    if label in NON_PERSONAL_TYPES:
        return "nao_pessoal"
    return "desconhecido"

from utils.detect import config as _config

_STOP = _config.lexicon()["conectores_sem_acento"]  # utils/detect/data/lexico.json
_DATE_OR_TIME = re.compile(r"^\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4}[.,;]?$|^\d{1,2}[:h]\d{2}")
_OCR_LOOKALIKE = str.maketrans({"0": "O", "1": "I", "5": "S", "8": "B"})


def _norm_token(token):
    nfkd = unicodedata.normalize("NFKD", token)
    return re.sub(r"[^A-Z0-9]", "", nfkd.encode("ASCII", "ignore").decode("ASCII").upper())


def _address_units(address):
    """
    Uma UNIDADE por palavra do endereço: (forma inteira, pedaços). "78.550-352" -> ("78550352", {"78","550","352"}).
    Devolve (unidades, índices das significativas, abreviações). Conectores ("à", "de") e termos estruturais
    (Rua, Bairro, CEP...) ajudam a manter o trecho contínuo, mas não contam como prova de que é o endereço.
    """
    units, significant, abbreviations = [], set(), {}
    for chunk in re.split(r"[\s,;]+", address):
        if not chunk or _DATE_OR_TIME.match(chunk):
            continue  # o LLM às vezes cola uma data no "endereço": data nunca é parte de endereço
        whole = _norm_token(chunk)
        if not whole:
            continue
        pieces = {p for p in (_norm_token(x) for x in re.split(r"[.\-/]+", chunk)) if p}
        idx = len(units)
        units.append((whole, pieces | {whole}))
        if whole not in _STOP and not is_immune(chunk) and (len(whole) >= 2 or whole.isdigit()):
            significant.add(idx)
        if chunk.endswith(".") and len(whole) >= 2 and whole.isalpha():
            abbreviations[whole] = idx  # "Jd.", "Pres." -> casam com "Jardim", "Presidente"
    return units, significant, abbreviations


def _is_subsequence(short, long):
    it = iter(long)
    return all(ch in it for ch in short)


def _unit_for(word, units, abbreviations):
    """Índice da unidade do endereço que a palavra do OCR representa, ou None."""
    if not word:
        return None
    for i, (_whole, forms) in enumerate(units):
        if word in forms:
            return i
    if len(word) >= 5:
        fixed = word.translate(_OCR_LOOKALIKE)  # "FL0RES" -> "FLORES"
        for i, (whole, forms) in enumerate(units):
            if fixed in forms:
                return i
            if len(whole) == len(word) and whole.isalpha() and sum(a != b for a, b in zip(whole, word)) == 1:
                return i
    for abbr, i in abbreviations.items():
        if word[0] == abbr[0] and len(word) > len(abbr) and _is_subsequence(abbr, word):
            return i
    return None


def locate_address_spans(address, coordinate_map, min_coverage=None):
    """
    Trechos contínuos do OCR (listas de índices) que correspondem ao endereço.

    Um trecho começa numa palavra que representa uma unidade SIGNIFICATIVA do endereço, segue enquanto as palavras
    casarem (tolerando até 2 palavras desconhecidas no meio, típicas de erro de OCR, e palavras partidas
    "Flo" + "res") e é aceito se cobrir pelo menos metade das unidades significativas, com no mínimo 2 delas quando
    o endereço tem 2 ou mais. Dentro do trecho, rótulos ("Endereço:"), termos estruturais (Rua, Bairro...),
    conectores ("à", "de"), pontuação e datas nunca são tarjados.
    """
    units, significant, abbreviations = _address_units(address)
    if not significant:
        return []
    # Limiares em utils/detect/data/parametros.json ("endereco")
    if min_coverage is None:
        min_coverage = _config.param("endereco", "cobertura_minima")
    max_gap = _config.param("endereco", "folga_max_palavras")
    words = [_norm_token(str(w.get("text", ""))) for w in coordinate_map]
    need = min(int(_config.param("endereco", "partes_minimas")), len(significant))
    max_len = len(units) + int(_config.param("endereco", "comprimento_extra"))

    def step(j):
        """(unidade, quantas palavras consumiu) a partir de j, tentando também juntar j e j+1."""
        unit = _unit_for(words[j], units, abbreviations)
        if unit is not None:
            return unit, 1
        if j + 1 < len(words) and words[j] and words[j + 1]:
            unit = _unit_for(words[j] + words[j + 1], units, abbreviations)
            if unit is not None:
                return unit, 2
        return None, 1

    candidates = []
    for i in range(len(words)):
        first, used = step(i)
        if first is None or first not in significant:
            continue
        matched, last, gap, j = {first}, i + used - 1, 0, i + used
        hits, duplicates = used, 0
        while j < len(words) and j - i <= max_len:
            unit, used = step(j)
            if unit is not None:
                if unit in significant:
                    duplicates += unit in matched  # a mesma parte do endereço de novo: sinal de palavra solta vizinha
                    matched.add(unit)
                hits += used
                last, gap, j = j + used - 1, 0, j + used
                continue
            gap += 1
            if gap > max_gap:
                break
            j += 1
        if len(matched) >= need and len(matched) / len(significant) >= min_coverage:
            # Mais unidades casadas vence; depois, sem repetir unidade (não engole "10" solto antes de "Flores 10");
            # depois, mais palavras casadas (CEP partido "78.550-" + "352" inteiro); por fim, o trecho mais curto.
            candidates.append((len(matched), -duplicates, hits, -(last - i), i, last))
    spans, taken = [], set()
    for *_score, i, last in sorted(candidates, reverse=True):
        if any(k in taken for k in range(i, last + 1)):
            continue
        taken.update(range(i, last + 1))
        span = [k for k in range(i, last + 1)
                if words[k] and not str(coordinate_map[k].get("text", "")).endswith(":")
                and not is_immune(str(coordinate_map[k].get("text", "")))
                and not _DATE_OR_TIME.match(str(coordinate_map[k].get("text", "")))]
        if span:
            spans.append(span)
    return sorted(spans)


# Pedido da descoberta de endereços: COPIAR como está na página (o pedido antigo mandava "juntar os componentes num
# endereço completo e estruturado", e o modelo redigia endereços com partes que não estavam na página: não
# localizados = revisão, e às vezes tarja no lugar errado). Medido em benchmarks/address_eval.py.
DISCOVERY_PROMPT = """
OBJETIVO: listar TODOS os endereços que aparecem nesta página de documento.

REGRAS:
1. Copie cada endereço EXATAMENTE como está escrito na página: as mesmas palavras, abreviações, números e pontuação.
   Não complete, não corrija, não reorganize e não junte partes que estão em lugares diferentes da página.
2. Se o endereço continuar na linha seguinte, copie as partes em sequência, como um só endereço.
3. Não invente. Se não houver endereço, devolva a lista vazia.
4. Classifique cada endereço:
   - "pessoal": residência ou domicílio de pessoa física (residente, domiciliado, morador; Casa, Apto, Bloco,
     Quadra/Lote residencial).
   - "profissional": sede ou endereço de empresa, órgão público ou escritório.
   - "secundário": local de obra, canteiro, imóvel objeto do contrato, fazenda ou empreendimento.
5. Na dúvida entre "pessoal" e outro tipo, use "pessoal".

FORMATO DE SAÍDA (APENAS JSON):
{"addresses": [{"text": "endereço copiado da página", "type": "pessoal"}]}
"""

# Saída estruturada do Ollama ("format"): a resposta sempre vem no formato da lista
DISCOVERY_SCHEMA = {
    "type": "object",
    "properties": {"addresses": {"type": "array", "items": {
        "type": "object",
        "properties": {"text": {"type": "string"}, "type": {"type": "string",
                                                            "enum": ["pessoal", "profissional", "secundário"]}},
        "required": ["text", "type"]}}},
    "required": ["addresses"],
}


def with_ocr_text(prompt, ocr_text, limit=12000):
    """Acrescenta o texto lido pelo OCR para o modelo COPIAR dele (a imagem continua indo junto)."""
    text = " ".join(str(ocr_text or "").split())[:limit]
    if not text:
        return prompt
    return (prompt + "\nTEXTO DA PÁGINA LIDO PELO OCR (pode ter erros de leitura; copie os endereços a partir dele "
            "e use a imagem para conferir):\n<<<\n" + text + "\n>>>\n")


def cross_check_enabled(client):
    enabled = os.getenv("AI_CROSS_CHECK", "0").strip().lower() in ("1", "true", "sim")
    return enabled and getattr(client, "has_secondary", False)


def merge_cross_check(primary, secondary):
    """
    Soma as respostas da IA principal e da reserva. Endereço visto por uma só entra; tipos diferentes para o mesmo
    endereço viram "pessoal" (o mais protetor). Devolve (resposta, motivo de revisão ou "").
    """
    def ok(r):
        return isinstance(r, dict) and "error" not in r and isinstance(r.get("addresses"), list)
    if not ok(primary) and not ok(secondary):
        return primary, ""
    if not ok(secondary):
        return primary, "verificação cruzada: a IA reserva não respondeu"
    if not ok(primary):
        return secondary, "verificação cruzada: só a IA reserva respondeu"
    merged, notes = {}, set()
    for item in list(primary["addresses"]) + list(secondary["addresses"]):
        if not isinstance(item, dict) or not str(item.get("text") or "").strip():
            continue
        key = " ".join(_norm_token(t) for t in str(item["text"]).split())
        kind = classify_address_type(item.get("type"))
        if key in merged:
            if (merged[key][1] == "pessoal") != (kind == "pessoal"):
                notes.add("as duas IAs discordaram do tipo de um endereço (tratado como pessoal)")
                merged[key] = ({**merged[key][0], "type": "pessoal"}, "pessoal")
            continue
        merged[key] = (dict(item), kind)
    def keys(resp):
        return {" ".join(_norm_token(t) for t in str(i.get("text", "")).split())
                for i in resp["addresses"] if isinstance(i, dict)}
    # Só o que a VERIFICADORA viu e a principal não (é aí que ela acrescenta proteção). O contrário é normal quando a
    # verificadora é mais fraca e, medido nos documentos reais, mandava TODAS as páginas para revisão à toa.
    only_secondary = len(keys(secondary) - keys(primary))
    if only_secondary:
        notes.add(f"{only_secondary} endereço(s) apontado(s) só pela IA verificadora")
    return {**primary, "addresses": [v[0] for v in merged.values()]}, "; ".join(sorted(notes))


# Pedido original da descoberta de endereços (mantido para comparação em benchmarks/address_eval.py)
DISCOVERY_PROMPT_LEGACY = """
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


class AddressRedactor:
    def __init__(self, session, logger):
        self.session = session
        self.logger = logger
        self.ai = OllamaClient()
        self.results = {}
        self.failed_pages = {}  # page_num -> motivo; páginas sem análise de endereço (revisão obrigatória)
        self.review_notes = {}  # page_num -> motivo; análise feita, mas com classificação incerta (revisão)
        self.unlocated = {}     # page_num -> endereços pessoais que o LLM viu mas não foram achados no OCR

    def run_discovery(self, image_paths, page_texts=None):
        """
        Fase 1: Consulta a IA para identificar e classificar endereços nas imagens originais.
        page_texts: texto de cada página (texto digital do PDF ou OCR) para o modelo COPIAR os endereços dele.
        ADDRESS_PROMPT=legado volta ao pedido antigo (só imagem, "endereço completo e estruturado").
        """
        self.logger.info("--- ADDRESS REDACTOR: INICIANDO DESCOBERTA SEMÂNTICA ---")
        
        legacy = (os.getenv("ADDRESS_PROMPT") or "").strip().lower() == "legado"

        for i, img_path in enumerate(image_paths):
            page_num = i + 1
            if legacy:
                prompt = DISCOVERY_PROMPT_LEGACY
            else:
                text = page_texts[i] if page_texts and i < len(page_texts) else ""
                prompt = with_ocr_text(DISCOVERY_PROMPT, text)
            self.logger.info(f"[*] Analisando endereços na página {page_num} via AI ({self.ai.vision_model})...")
            
            # Consulta a visão da IA (agora retorna bytes e métricas)
            response, img_bytes, metrics = self.ai.analyze_image(img_path, prompt)
            if cross_check_enabled(self.ai) and not (isinstance(response, dict) and response.get("_backend")):
                # Verificação cruzada: a IA reserva também lê a página; as respostas se SOMAM (nunca reduz proteção)
                second, _, second_metrics = self.ai.analyze_image(img_path, prompt, only="reserva")
                self.session.save_ai_interaction(phase_key="Address_Redactor", prefix=f"page_{page_num}_crosscheck",
                                                 prompt=prompt, response=second, metrics=second_metrics, img_bytes=None)
                response, note = merge_cross_check(response, second)
                if note:
                    self.logger.warning(f"[!] Página {page_num}: {note}")
                    self.review_notes[page_num] = "; ".join(x for x in (self.review_notes.get(page_num), note) if x)
            
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

            addresses = response.get("addresses")
            if not isinstance(addresses, list):
                self.logger.error(f"[!] Resposta da IA sem a lista 'addresses' na página {page_num}.")
                self.failed_pages[page_num] = "Resposta da IA sem a lista de endereços"
                continue

            # Salva os resultados desta página, com o tipo normalizado
            self.results[page_num] = self._normalize_types(page_num, addresses)
            
            # Exporta o JSON de descoberta na pasta da sessão
            output_json = os.path.join(self.session.dirs["07_addresses_ia"], f"page_{page_num}_addresses.json")
            with open(output_json, "w", encoding='utf-8') as f:
                json.dump(response, f, indent=4, ensure_ascii=False)
                
            self.logger.info(f"[+] {len(self.results[page_num])} endereços encontrados na página {page_num}.")

        return self.results

    def _normalize_types(self, page_num, addresses):
        """
        Normaliza o tipo de cada endereço para que o filtro "pessoal" não dependa da grafia do LLM
        ("Pessoal", "residencial "...). Tipo desconhecido é tratado como pessoal (tarja conservadora) e a
        página vai para revisão. Itens fora do formato também mandam a página para revisão.
        """
        normalized, unknown, malformed = [], [], 0
        for item in addresses:
            if not isinstance(item, dict) or not str(item.get("text") or "").strip():
                malformed += 1
                continue
            item = dict(item)
            raw = item.get("type")
            kind = classify_address_type(raw)
            if kind == "desconhecido":
                unknown.append(str(raw))
                kind = "pessoal"
            item["type_original"] = raw
            item["type"] = "pessoal" if kind == "pessoal" else _normalize_label(raw)
            normalized.append(item)
        reasons = []
        if unknown:
            reasons.append(f"tipo de endereço não reconhecido ({', '.join(sorted(set(unknown)))[:80]}), tarjado como pessoal")
        if malformed:
            reasons.append(f"{malformed} item(ns) da IA fora do formato")
        if reasons:
            self.logger.warning(f"[!] Página {page_num}: {'; '.join(reasons)}.")
            self.review_notes[page_num] = "; ".join(reasons)
        return normalized

    def refine_redaction_with_text_ai(self, page_num, indexed_text, discovered_addresses, coordinate_map=None):
        """
        Localiza no OCR as palavras de cada endereço PESSOAL e devolve os IDs a tarjar (casamento determinístico).

        Localiza o endereço como um TRECHO contínuo do texto (ver locate_address_spans), e não como um "saco de
        palavras": palavras soltas iguais em outros pontos da página ("à", um número, o nome da cidade, uma data)
        não são tarjadas. Endereço pessoal que não for localizado fica em self.unlocated[page_num] para o pipeline
        mandar a página para revisão (falha fechado), em vez de espalhar tarjas.
        """
        self.unlocated[page_num] = []
        if not discovered_addresses:
            return []
        pessoais = [a["text"] for a in discovered_addresses if a.get("type") == "pessoal"]
        if not pessoais:
            return []

        self.logger.info(f"[*] Localizando {len(pessoais)} endereço(s) pessoal(is) na página {page_num} (trecho contínuo)...")

        # Se coordinate_map não foi fornecido, extrai os IDs e textos a partir de indexed_text
        if not coordinate_map:
            import re
            coordinate_map = []
            pattern = re.compile(r'\[(\d+)\]\s*([^\s\[]+)')
            for match in pattern.finditer(indexed_text):
                coordinate_map.append({"id": int(match.group(1)), "text": match.group(2)})

        ids_to_redact = []
        for addr in pessoais:
            if not _address_units(addr)[1]:
                continue  # só termos genéricos ("Rua", "Centro", "Apto"): nada identificável para tarjar ou revisar
            spans = locate_address_spans(addr, coordinate_map)
            if not spans and addr not in self.unlocated[page_num]:  # o LLM às vezes repete o mesmo endereço
                self.unlocated[page_num].append(addr)
            for span in spans:
                for idx in span:
                    w_id = coordinate_map[idx].get("id", idx)
                    if w_id not in ids_to_redact:
                        ids_to_redact.append(w_id)
        ids_to_redact.sort()

        # Salva o debug da interação simulada para manter compatibilidade e auditoria
        dummy_prompt = f"AUDITORIA PROGRAMÁTICA DE ENDEREÇOS PESSOAIS\nEndereços Alvo: {pessoais}"
        self.session.save_ai_interaction(
            phase_key="Address_Audit_Programmatic",
            prefix=f"page_{page_num}_text_audit",
            prompt=dummy_prompt,
            response={"ids_to_redact": ids_to_redact, "nao_localizados": len(self.unlocated[page_num])},
            metrics={"total_duration_ms": 0}
        )

        return ids_to_redact

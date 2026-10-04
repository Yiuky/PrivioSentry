# SPDX-License-Identifier: AGPL-3.0-or-later
"""Catálogo de tipos de dado pessoal (PII) e seu enquadramento em referências nacionais e internacionais.

É a "fonte da verdade" de SENTRY Detect: perfis de política (profiles.py), detectores (rules.py), relatório
por documento e a documentação (docs/catalogo-pii.md, gerada por `python -m utils.detect --markdown`).

Atenção à redação: o enquadramento indica a QUE categoria das referências o tipo corresponde. Detectar e
tarjar esses tipos APOIA práticas alinhadas a essas referências; não torna um documento "conforme".

Para acrescentar um tipo: inclua-o aqui (estado "planejado" se ainda não houver detector), acrescente-o aos
perfis que fizer sentido, escreva o detector em rules.py com testes e regenere a documentação.
"""
from dataclasses import asdict, dataclass

# Níveis
DIRETO = "identificador direto"      # identifica sozinho (documento, nome completo...)
PESSOAL = "dado pessoal"             # identifica ou contata a pessoa (telefone, e-mail, endereço...)
SENSIVEL = "dado pessoal sensível"   # LGPD art. 5º, II / GDPR art. 9 e 10
INDIRETO = "identificador indireto"  # identifica combinado com outros dados (placa, data de nascimento, IP...)

ATIVO = "ativo"
PLANEJADO = "planejado"

# Referências citadas (mantidas curtas; o texto legal completo está nas fontes oficiais)
REF_LGPD_I = "LGPD art. 5º, I (dado pessoal)"
REF_LGPD_II = "LGPD art. 5º, II (dado pessoal sensível)"
REF_GDPR_4 = "GDPR art. 4(1)"


@dataclass(frozen=True)
class PIIType:
    id: str
    nome: str
    nivel: str
    estado: str
    deteccao: str
    lgpd: str
    gdpr: str
    iso29100: str
    nist: str
    hipaa: str
    nota: str = ""

    def to_dict(self):
        return asdict(self)


def _t(id, nome, nivel, estado, deteccao, lgpd, gdpr, nist, hipaa, nota="", iso="PII"):
    return PIIType(id, nome, nivel, estado, deteccao, lgpd, gdpr, iso, nist, hipaa, nota)


CATALOG = [
    # --- documentos e números de identificação (Brasil) -------------------------------------------------
    _t("cpf", "CPF", DIRETO, ATIVO, "regra + dígito verificador (OCR, passada esparsa e texto digital)",
       REF_LGPD_I, REF_GDPR_4 + " e art. 87 (número de identificação nacional)", "identificador pessoal (ex.: SSN)",
       "outro número de identificação único"),
    _t("rg", "RG (carteira de identidade)", DIRETO, ATIVO, "formato + palavra de contexto (RG, identidade)",
       REF_LGPD_I, REF_GDPR_4 + " e art. 87", "identificador pessoal", "outro número de identificação único",
       "Sem algoritmo nacional de dígito verificador: exige contexto."),
    _t("cnh", "CNH (registro da habilitação)", DIRETO, ATIVO, "formato + palavra de contexto (CNH, habilitação)",
       REF_LGPD_I, REF_GDPR_4, "identificador pessoal (carteira de motorista)", "número de certificado/licença"),
    _t("titulo_eleitor", "Título de eleitor", DIRETO, ATIVO, "regra + dígito verificador + contexto",
       REF_LGPD_I, REF_GDPR_4, "identificador pessoal", "outro número de identificação único"),
    _t("pis_nis", "PIS/PASEP/NIS/NIT", DIRETO, ATIVO, "regra + dígito verificador + contexto",
       REF_LGPD_I, REF_GDPR_4, "identificador pessoal", "outro número de identificação único"),
    _t("cns", "Cartão Nacional de Saúde (CNS/SUS)", DIRETO, ATIVO, "regra + dígito verificador",
       REF_LGPD_I + "; associado a dado de saúde pode compor dado sensível", REF_GDPR_4,
       "identificador pessoal", "número de beneficiário de plano de saúde"),
    _t("passaporte", "Passaporte", DIRETO, ATIVO, "formato + palavra de contexto (passaporte)",
       REF_LGPD_I, REF_GDPR_4, "identificador pessoal (passaporte)", "número de certificado/licença"),
    _t("ctps", "Carteira de Trabalho (CTPS)", DIRETO, ATIVO, "formato + palavra de contexto (CTPS)",
       REF_LGPD_I, REF_GDPR_4, "identificador pessoal", "outro número de identificação único"),
    # --- contato e localização -----------------------------------------------------------------------
    _t("endereco_residencial", "Endereço residencial", PESSOAL, ATIVO, "LLM de visão + casamento com o OCR (+ decisor Laya)",
       REF_LGPD_I, REF_GDPR_4 + " (dado de localização)", "endereço", "subdivisão geográfica menor que o estado"),
    _t("telefone", "Telefone", PESSOAL, ATIVO, "formato brasileiro (DDD) ou palavra de contexto",
       REF_LGPD_I, REF_GDPR_4, "número de telefone", "número de telefone/fax",
       "Telefones institucionais também são marcados: o revisor decide."),
    _t("email", "E-mail", PESSOAL, ATIVO, "formato", REF_LGPD_I, REF_GDPR_4 + " (identificador online)",
       "endereço de e-mail", "endereço de e-mail", "E-mails institucionais também são marcados: o revisor decide."),
    _t("ip", "Endereço IP", INDIRETO, ATIVO, "formato IPv4 válido", REF_LGPD_I + " (quando vinculado a pessoa)",
       REF_GDPR_4 + " (identificador online)", "informação de ativo (IP)", "endereço IP"),
    _t("geolocalizacao", "Coordenadas geográficas", INDIRETO, PLANEJADO, "formato lat/long (planejado)",
       REF_LGPD_I, REF_GDPR_4 + " (dado de localização)", "informação vinculável", "subdivisão geográfica"),
    # --- financeiro ----------------------------------------------------------------------------------
    _t("cartao_pagamento", "Cartão de pagamento", DIRETO, ATIVO, "Luhn + formatação em grupos ou contexto",
       REF_LGPD_I, REF_GDPR_4, "conta financeira / cartão de crédito", "número de conta"),
    _t("conta_bancaria", "Agência e conta bancária", DIRETO, ATIVO, "palavra de contexto (agência, conta, c/c)",
       REF_LGPD_I, REF_GDPR_4, "conta financeira", "número de conta"),
    _t("chave_pix", "Chave Pix aleatória", DIRETO, ATIVO, "formato (UUID)", REF_LGPD_I, REF_GDPR_4,
       "conta financeira", "número de conta",
       "Chaves Pix de CPF, e-mail ou telefone já são cobertas pelos respectivos tipos."),
    # --- características e datas ---------------------------------------------------------------------
    _t("data_nascimento", "Data de nascimento", INDIRETO, ATIVO, "data + palavra de contexto (nascido, nascimento)",
       REF_LGPD_I, REF_GDPR_4, "informação vinculável (data de nascimento)", "datas relacionadas à pessoa (exceto ano)"),
    _t("placa_veiculo", "Placa de veículo", INDIRETO, ATIVO, "formato antigo ou Mercosul",
       REF_LGPD_I + " (quando vinculada a pessoa)", REF_GDPR_4, "bem de propriedade pessoal (registro de veículo)",
       "identificador de veículo (inclui placa)"),
    _t("nome_pessoa", "Nome de pessoa", DIRETO, PLANEJADO, "GLiNER (reconhecimento de nomes) — backlog B-73",
       REF_LGPD_I, REF_GDPR_4, "nome", "nomes",
       "Na LAI, nome de servidor no exercício da função costuma ser público: exceção decidida por perfil/Laya (B-74)."),
    _t("filiacao", "Filiação (nome da mãe/pai)", DIRETO, PLANEJADO, "GLiNER + contexto — backlog B-73",
       REF_LGPD_I, REF_GDPR_4, "nome / informação vinculável", "nomes (inclui parentes)"),
    _t("assinatura", "Assinatura", DIRETO, PLANEJADO, "detector YOLO (hoje só localiza para auditar CPFs próximos)",
       REF_LGPD_I, REF_GDPR_4, "característica pessoal", "—"),
    _t("foto_rosto", "Foto de rosto", DIRETO, PLANEJADO, "detecção de rosto (planejado)", REF_LGPD_I,
       REF_GDPR_4 + "; art. 9 se usado para identificação biométrica", "característica pessoal (foto)",
       "foto de rosto inteiro e imagens comparáveis"),
    # --- dados sensíveis (dependem de contexto: só alerta + revisão humana) ---------------------------
    _t("saude", "Dado de saúde (diagnóstico, CID, tratamento)", SENSIVEL, PLANEJADO,
       "LLM/Laya sobre o contexto, sempre com revisão humana", REF_LGPD_II, "GDPR art. 9 (dados de saúde)",
       "informação médica", "número de prontuário e informação de saúde associada", iso="PII sensível"),
    _t("biometrico_genetico", "Dado biométrico ou genético", SENSIVEL, PLANEJADO, "LLM/Laya + revisão",
       REF_LGPD_II, "GDPR art. 9", "característica pessoal (biometria)", "identificador biométrico", iso="PII sensível"),
    _t("religiao", "Convicção religiosa", SENSIVEL, PLANEJADO, "LLM/Laya + revisão", REF_LGPD_II, "GDPR art. 9",
       "informação vinculável", "—", iso="PII sensível"),
    _t("opiniao_politica", "Opinião política / filiação partidária", SENSIVEL, PLANEJADO, "LLM/Laya + revisão",
       REF_LGPD_II, "GDPR art. 9", "informação vinculável", "—", iso="PII sensível"),
    _t("filiacao_sindical", "Filiação a sindicato", SENSIVEL, PLANEJADO, "LLM/Laya + revisão", REF_LGPD_II,
       "GDPR art. 9", "informação vinculável", "—", iso="PII sensível"),
    _t("origem_etnica", "Origem racial ou étnica", SENSIVEL, PLANEJADO, "LLM/Laya + revisão", REF_LGPD_II,
       "GDPR art. 9", "informação vinculável", "—", iso="PII sensível"),
    _t("vida_sexual", "Vida sexual / orientação sexual", SENSIVEL, PLANEJADO, "LLM/Laya + revisão", REF_LGPD_II,
       "GDPR art. 9", "informação vinculável", "—", iso="PII sensível"),
    _t("antecedentes_criminais", "Condenações e infrações penais", SENSIVEL, PLANEJADO, "LLM/Laya + revisão",
       "LGPD: não listado no art. 5º, II; o tratamento para persecução penal fica fora da LGPD e segue lei específica "
       "(art. 4º, III)", "GDPR art. 10", "informação vinculável", "—",
       iso="PII sensível"),
]

BY_ID = {t.id: t for t in CATALOG}
LEVELS = (DIRETO, PESSOAL, SENSIVEL, INDIRETO)


def get(type_id):
    return BY_ID[type_id]


def active_ids():
    return [t.id for t in CATALOG if t.estado == ATIVO]


def to_markdown():
    """Tabela do catálogo para docs/catalogo-pii.md (gerada; não edite o .md à mão)."""
    lines = [
        "# Catálogo de dados pessoais (PII)",
        "",
        "> Gerado por `python -m utils.detect --markdown` a partir de `utils/detect/catalog.py`. Não edite à mão.",
        ">",
        "> O enquadramento indica a que categoria de cada referência o tipo corresponde. Detectar e tarjar esses",
        "> tipos **apoia** práticas alinhadas a essas referências; **não** torna um documento \"conforme\".",
        "> Itens *planejados* ainda não têm detector.",
        "",
    ]
    for level in LEVELS:
        items = [t for t in CATALOG if t.nivel == level]
        lines += [f"## {level[0].upper()}{level[1:]}", "",
                  "| Tipo | Estado | Detecção | LGPD | GDPR | ISO/IEC 29100 | NIST SP 800-122 | HIPAA Safe Harbor |",
                  "|---|---|---|---|---|---|---|---|"]
        for t in items:
            nota = f"<br>*{t.nota}*" if t.nota else ""
            lines.append(f"| **{t.nome}** (`{t.id}`){nota} | {t.estado} | {t.deteccao} | {t.lgpd} | {t.gdpr} | "
                         f"{t.iso29100} | {t.nist} | {t.hipaa} |")
        lines.append("")
    return "\n".join(lines)

# SPDX-License-Identifier: AGPL-3.0-or-later
"""Termos estruturais de endereço que NUNCA devem ser tarjados (fonte única)."""

IMMUNE_WORDS = {
    "RUA", "AVENIDA", "AV", "AV.", "PRAÇA", "PRACA", "PRAÇA/RUA", "TRAVESSA", "LOGRADOURO", "ALAMEDA", "RODOVIA", "BR", "MT", "KM",
    "BAIRRO", "COMPLEMENTO", "NÚMERO", "NUMERO", "N", "N°", "Nº", "S/N", "LOTE", "LOTEAMENTO", "QUADRA", "QD", "LT",
    "CIDADE", "MUNICÍPIO", "MUNICIPIO", "UF", "ESTADO", "PAÍS", "PAIS", "CEP", "COORDENADA", "COORDENADAS",
    "DATA", "INICIAL", "FINAL", "INÍCIO", "INICIO", "TÉRMINO", "TERMINO", "CÓDIGO", "CODIGO", "TIPO", "PREVISÃO",
    "PROPRIETÁRIO", "PROPRIETARIO", "CONTRATANTE", "CONTRATADO", "CONTRATO", "VALOR", "R$", "AÇÃO", "ACAO", "INSTITUCIONAL",
    "FINALIDADE", "AMBIENTAL", "CPF", "CNPJ", "CPF/CNPJ", "ASSINATURA", "BRASIL", "ZONA", "RURAL", "URBANA",
    "GLEBA", "FAZENDA", "SITIO", "SÍTIO", "CHACARA", "CHÁCARA", "ESTRADA", "VICINAL", "LINHA",
    "SETOR", "RESIDENCIAL", "CONDOMINIO", "CONDOMÍNIO", "EDIFICIO", "EDIFÍCIO", "BLOCO", "APTO", "APARTAMENTO",
    "SALA", "ANDAR", "ANEXO", "FUNDOS", "DADOS", "OBRA", "OBRA/SERVIÇO", "SERVIÇO", "SERVICO", "LOCAL",
    "LOCALIZAÇÃO", "LOCALIZACAO", "SITUADO", "CELEBRADO", "EM"
}

_SHORT_CONNECTORS = {"DE", "DO", "DA", "EM", "NO", "NA", "E", "A", "O", "AO", "AOS", "AS", "OS", "DOS", "DAS",
                     "NOS", "NAS", "UM", "UMA"}


def _strip_accents(text):
    import unicodedata
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")


def is_immune(word):
    """True se a palavra é um termo estrutural/conector que não deve ser tarjado."""
    w = word.strip(" \t\r\n.,;:/-()[]{}").upper()
    if not w:
        return True
    # Se contiver números, nunca é imune
    if any(char.isdigit() for char in w):
        return False
    if w in _SHORT_CONNECTORS or _strip_accents(w) in _SHORT_CONNECTORS:  # "À", "ÀS" também são conectores
        return True
    return w in IMMUNE_WORDS

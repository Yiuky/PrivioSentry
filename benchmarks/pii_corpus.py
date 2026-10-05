# SPDX-License-Identifier: AGPL-3.0-or-later
"""Corpus de avaliação FICTÍCIO para os detectores de PII (com resposta conhecida).

Gera documentos de tipos variados (ata de condomínio, contrato, ficha de cadastro, ofício, atendimento de saúde)
a partir de modelos, preenchidos com valores GERADOS (CPF, PIS, CNS, título com dígito verificador válido,
telefones, e-mails example.com...). Cada documento traz:
    gabarito  [(tipo, valor)]  o que DEVE ser achado
    iscas     [(tipo_da_isca, valor)]  o que NÃO deve ser achado (outras datas, valores em reais, processo,
              CNPJ, protocolo, endereço comercial...)

Nada aqui é dado real: nomes e ruas vêm de listas fictícias e os números são gerados na hora (nenhum número que
passe no dígito verificador fica escrito no código). Usado por benchmarks/pii_eval.py e pelo portão dos testes.
"""
import random
from dataclasses import dataclass, field
from typing import List, Tuple

NOMES = ["Maria Exemplo", "João Fictício", "Ana Teste", "Pedro Modelo", "Carla Amostra", "Lucas Simulado",
         "Beatriz Hipotética", "Rafael Ensaio", "Juliana Protótipo", "Marcos Rascunho"]
SOBRENOMES = ["da Silva Teste", "Souza Exemplo", "Pereira Fictício", "Lima Modelo", "Costa Amostra"]
RUAS = ["Rua das Acácias", "Rua Beija-Flor", "Avenida das Palmeiras", "Travessa do Sol", "Rua Ipê Roxo",
        "Alameda dos Pinheiros", "Rua São Benedito", "Rua Primavera"]
BAIRROS = ["Jardim Exemplo", "Vila Teste", "Bairro Fictício", "Residencial Aurora", "Centro"]
CIDADES = ["Cidade Fictícia - UF", "Município Exemplo - UF"]
EMPRESAS = ["Comércio Exemplo Ltda", "Construtora Fictícia S/A", "Clínica Modelo Ltda"]


def _dv_cpf(base):
    s = sum(int(d) * w for d, w in zip(base, range(len(base) + 1, 1, -1)))
    r = (s * 10) % 11
    return "0" if r == 10 else str(r)


def gen_cpf(rng):
    base = "".join(str(rng.randint(0, 9)) for _ in range(9))
    d1 = _dv_cpf(base)
    d2 = _dv_cpf(base + d1)
    n = base + d1 + d2
    return f"{n[:3]}.{n[3:6]}.{n[6:9]}-{n[9:]}"


def gen_cnpj(rng):
    base = [rng.randint(0, 9) for _ in range(8)] + [0, 0, 0, 1]
    for weights in ([5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2], [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]):
        r = sum(d * w for d, w in zip(base, weights)) % 11
        base.append(0 if r < 2 else 11 - r)
    n = "".join(map(str, base))
    return f"{n[:2]}.{n[2:5]}.{n[5:8]}/{n[8:12]}-{n[12:]}"


def gen_pis(rng):
    base = [rng.randint(0, 9) for _ in range(10)]
    dv = 11 - sum(d * w for d, w in zip(base, (3, 2, 9, 8, 7, 6, 5, 4, 3, 2))) % 11
    n = "".join(map(str, base)) + str(0 if dv >= 10 else dv)
    return f"{n[:3]}.{n[3:8]}.{n[8:10]}-{n[10]}"


def gen_cns(rng):
    while True:
        d = [rng.choice([1, 2])] + [rng.randint(0, 9) for _ in range(14)]
        if sum(a * w for a, w in zip(d, range(15, 0, -1))) % 11 == 0:
            n = "".join(map(str, d))
            return f"{n[:3]} {n[3:7]} {n[7:11]} {n[11:]}"


def gen_rg(rng):
    return f"{rng.randint(1, 9)}.{rng.randint(100, 999)}.{rng.randint(100, 999)}"


def gen_phone(rng):
    return rng.choice([f"(65) 9{rng.randint(1000, 9999)}-{rng.randint(1000, 9999)}",
                       f"(65) 3{rng.randint(100, 999)}-{rng.randint(1000, 9999)}"])


def gen_email(rng, nome):
    return nome.split()[0].lower().replace("ã", "a").replace("é", "e").replace("í", "i").replace("ó", "o") + \
        f".{rng.randint(1, 99)}@example.com"


def gen_date(rng, y0=1950, y1=2005):
    return f"{rng.randint(1, 28):02d}/{rng.randint(1, 12):02d}/{rng.randint(y0, y1)}"


def gen_plate(rng):
    letters = "".join(rng.choice("BCDFGHJKLMNPQRSTVWXZ") for _ in range(3))
    return f"{letters}{rng.randint(0, 9)}{rng.choice('BCDFGHJKLMNPQRSTVWXZ')}{rng.randint(10, 99)}"


def gen_process(rng):
    return f"{rng.randint(1000000, 9999999)}-{rng.randint(10, 99)}.20{rng.randint(10, 26)}.8.11.{rng.randint(1000, 9999)}"


@dataclass
class Doc:
    kind: str
    lines: List[str]
    gabarito: List[Tuple[str, str]] = field(default_factory=list)
    iscas: List[Tuple[str, str]] = field(default_factory=list)

    @property
    def text(self):
        return "\n".join(self.lines)


def _person(rng):
    return f"{rng.choice(NOMES)} {rng.choice(SOBRENOMES)}"


def _address(rng):
    return f"{rng.choice(RUAS)}, {rng.randint(1, 2999)}, {rng.choice(BAIRROS)}, {rng.choice(CIDADES)}"


def ata_condominio(rng):
    d = Doc("ata_condominio", [])
    reuniao = gen_date(rng, 2020, 2026)
    valor = f"R$ {rng.randint(1, 9)}.{rng.randint(100, 999)},00"
    d.lines += ["ATA DA ASSEMBLEIA GERAL ORDINÁRIA DO CONDOMÍNIO RESIDENCIAL EXEMPLO",
                f"Aos {reuniao}, às 19:30, reuniram-se os condôminos à {rng.choice(RUAS)}, {rng.randint(1, 999)}.",
                f"Aprovada a previsão orçamentária de {valor} conforme processo {gen_process(rng)}."]
    d.iscas += [("data_comum", reuniao), ("valor", valor)]
    for _ in range(rng.randint(2, 4)):
        nome, cpf, phone = _person(rng), gen_cpf(rng), gen_phone(rng)
        d.lines.append(f"Condômino {nome}, unidade {rng.randint(1, 20)}{rng.choice('AB')}, CPF {cpf}, telefone {phone}.")
        d.gabarito += [("cpf", cpf), ("telefone", phone)]
    return d


def contrato_locacao(rng):
    d = Doc("contrato_locacao", [])
    nome, cpf, rg, nasc = _person(rng), gen_cpf(rng), gen_rg(rng), gen_date(rng)
    email, assinatura = gen_email(rng, nome), gen_date(rng, 2024, 2026)
    cnpj = gen_cnpj(rng)
    d.lines += ["CONTRATO DE LOCAÇÃO RESIDENCIAL",
                f"LOCADORA: {rng.choice(EMPRESAS)}, CNPJ {cnpj}, com sede na Avenida Comercial, 1000, sala 10.",
                f"LOCATÁRIO: {nome}, portador do RG nº {rg} SSP/UF, CPF {cpf}, nascido em {nasc},",
                f"residente à {_address(rng)}, e-mail {email}.",
                f"Valor mensal: R$ 2.350,00. Assinado em {assinatura}."]
    d.gabarito += [("cpf", cpf), ("rg", rg), ("data_nascimento", nasc), ("email", email)]
    d.iscas += [("cnpj", cnpj), ("data_comum", assinatura), ("valor", "R$ 2.350,00")]
    return d


def ficha_cadastro(rng):
    d = Doc("ficha_cadastro", [])
    nome, cpf, pis, nasc, plate = _person(rng), gen_cpf(rng), gen_pis(rng), gen_date(rng), gen_plate(rng)
    phone, email = gen_phone(rng), gen_email(rng, nome)
    d.lines += ["FICHA DE CADASTRO",
                f"Nome: {nome}",
                f"CPF: {cpf}   PIS: {pis}",
                f"Data de nascimento: {nasc}",
                f"Celular: {phone}   E-mail: {email}",
                f"Veículo placa {plate}",
                f"Protocolo 2024/{rng.randint(100000, 999999)} emitido em {gen_date(rng, 2023, 2026)}"]
    d.gabarito += [("cpf", cpf), ("pis_nis", pis), ("data_nascimento", nasc), ("telefone", phone), ("email", email),
                   ("placa_veiculo", plate)]
    return d


def oficio_publico(rng):
    d = Doc("oficio_publico", [])
    proc, data = gen_process(rng), gen_date(rng, 2023, 2026)
    d.lines += ["OFÍCIO Nº 123/2024 — SECRETARIA MUNICIPAL DE EXEMPLO",
                f"Referente ao processo nº {proc}, de {data}, nos termos da Lei nº 13.709/2018.",
                "Atendimento ao público: (65) 3613-0000, de segunda a sexta, das 8:00 às 18:00.",
                f"Valor empenhado: R$ {rng.randint(10, 99)}.{rng.randint(100, 999)},{rng.randint(10, 99)}."]
    d.iscas += [("processo", proc), ("data_comum", data)]
    # Telefone institucional: o detector é por FORMATO e o acha (o catálogo documenta); decidir se é público
    # (LAI) é da revisão/decisor. Por isso entra no gabarito como telefone.
    d.gabarito += [("telefone", "(65) 3613-0000")]
    return d


def atendimento_saude(rng):
    d = Doc("atendimento_saude", [])
    nome, cns, cpf, nasc = _person(rng), gen_cns(rng), gen_cpf(rng), gen_date(rng)
    d.lines += ["FICHA DE ATENDIMENTO — UNIDADE DE SAÚDE EXEMPLO",
                f"Paciente: {nome}   Cartão SUS: {cns}",
                f"CPF {cpf}   D.N. {nasc}",
                f"Atendido em {gen_date(rng, 2024, 2026)} às 10:15."]
    d.gabarito += [("cns", cns), ("cpf", cpf), ("data_nascimento", nasc)]
    return d


def gen_nup(rng):
    """Número único de processo federal (5.6/4-2), sem dígito verificador real."""
    return f"{rng.randint(10000, 99999)}.{rng.randint(100000, 999999)}/20{rng.randint(10, 26)}-{rng.randint(10, 99)}"


def gen_coord(rng, hemi):
    return f"{rng.randint(1, 60)}°{rng.randint(0, 59):02d}'{rng.randint(0, 59):02d},{rng.randint(0, 9999):04d}\"{hemi}"


def parecer_tecnico(rng):
    """Formatos achados nos documentos testados (valores fictícios): CNPJ cortado por borda de tabela, número de
    processo federal, coordenadas em graus coladas e e-mail com o "@" lido como "(" + letra."""
    d = Doc("parecer_tecnico", [])
    nome, cpf, cnpj, nup = _person(rng), gen_cpf(rng), gen_cnpj(rng), gen_nup(rng)
    lat, lon = gen_coord(rng, "S"), gen_coord(rng, "W")
    local = nome.split()[0].lower().replace("ã", "a").replace("é", "e").replace("í", "i").replace("ó", "o")
    email = f"{local}.{rng.randint(1, 99)}@example.com"
    d.lines += ["PARECER TÉCNICO — ANÁLISE DE CADASTRO",
                f"Processo SUSEP nº {nup}, empresa CNPJ {cnpj[:-2]} | {cnpj[-2:]} Responsável",
                f"Interessado: {nome}, CPF {cpf}, e-mail: {email.replace('@', '(G')}",
                f"Coordenadas do imóvel: {lon} {lat}, conforme a analista responsável."]
    d.gabarito += [("cpf", cpf), ("email", email)]
    d.iscas += [("processo", nup), ("cnpj", cnpj), ("coordenada", lon), ("coordenada", lat)]
    return d


TEMPLATES = [ata_condominio, contrato_locacao, ficha_cadastro, oficio_publico, atendimento_saude, parecer_tecnico]


def generate(n=50, seed=2026):
    rng = random.Random(seed)
    return [TEMPLATES[i % len(TEMPLATES)](rng) for i in range(n)]


# ------------------------------------------------------------------------------------------- endereços
LOGRADOUROS = [("Rua", "R."), ("Avenida", "Av."), ("Travessa", "Tv."), ("Alameda", "Al.")]
NOMES_RUA = ["das Acácias", "Beija-Flor", "das Palmeiras", "do Sol", "Ipê Roxo", "dos Pinheiros", "São Benedito",
             "Primavera", "Coronel Exemplo", "Presidente Fictício"]
BAIRROS_ABREV = [("Jardim Exemplo", "Jd. Exemplo"), ("Vila Teste", "Vl. Teste"), ("Residencial Aurora", "Res. Aurora"),
                 ("Bairro Fictício", "Bairro Fictício"), ("Centro", "Centro")]


@dataclass
class AddressDoc:
    kind: str
    lines: List[str]
    enderecos: List[Tuple[str, str]] = field(default_factory=list)  # (texto exato como na página, tipo)

    @property
    def text(self):
        return "\n".join(self.lines)


def _address_text(rng, residencial):
    tipo, abrev = rng.choice(LOGRADOUROS)
    bairro, bairro_abrev = rng.choice(BAIRROS_ABREV)
    abbreviate = rng.random() < 0.4
    parts = [f"{abrev if abbreviate else tipo} {rng.choice(NOMES_RUA)}", f"nº {rng.randint(1, 2999)}"]
    if residencial:
        parts.append(rng.choice([f"Apto {rng.randint(101, 1204)}", f"Casa {rng.randint(1, 40)}",
                                 f"Bloco {rng.choice('ABCD')}, Apto {rng.randint(101, 804)}", f"Quadra {rng.randint(1, 30)}, Lote {rng.randint(1, 40)}"]))
    else:
        parts.append(rng.choice([f"Sala {rng.randint(1, 1500)}", "Galpão 2", "Térreo", f"Loja {rng.randint(1, 30)}"]))
    parts += [bairro_abrev if abbreviate else bairro, f"CEP {rng.randint(10, 99)}.{rng.randint(100, 999)}-{rng.randint(100, 999)}",
              rng.choice(CIDADES)]
    return ", ".join(parts)


def _wrap(text, width=70):
    """Quebra como numa página (o endereço pode ficar partido em duas linhas)."""
    out, line = [], ""
    for word in text.split():
        if line and len(line) + 1 + len(word) > width:
            out.append(line)
            line = word
        else:
            line = f"{line} {word}".strip()
    return out + ([line] if line else [])


def address_doc(rng, i):
    """Página fictícia com endereços pessoais, profissionais e secundários, e iscas (datas, "à", horários, valores)."""
    d = AddressDoc(["contrato", "requerimento", "ata"][i % 3], [])
    nome, empresa = _person(rng), rng.choice(EMPRESAS)
    pessoal, prof, sec = _address_text(rng, True), _address_text(rng, False), _address_text(rng, False)
    data = gen_date(rng, 2023, 2026)
    if d.kind == "contrato":
        body = (f"CONTRATO DE PRESTAÇÃO DE SERVIÇOS. CONTRATANTE: {nome}, residente e domiciliado na {pessoal}. "
                f"CONTRATADA: {empresa}, com sede na {prof}. Objeto: reforma do imóvel situado na {sec}, "
                f"com início em {data}, às 8:00, pelo valor de R$ {rng.randint(1, 9)}.{rng.randint(100, 999)},00.")
        d.enderecos += [(pessoal, "pessoal"), (prof, "profissional"), (sec, "secundario")]
    elif d.kind == "requerimento":
        body = (f"REQUERIMENTO. {nome}, portador do CPF {gen_cpf(rng)}, residente à {pessoal}, vem requerer à "
                f"Secretaria Municipal de Exemplo, situada na {prof}, licença para a obra localizada na {sec}. "
                f"Protocolado em {data} às 14:30.")
        d.enderecos += [(pessoal, "pessoal"), (prof, "profissional"), (sec, "secundario")]
    else:
        body = (f"ATA DA REUNIÃO realizada em {data}, às 19:00, na sede da {empresa}, {prof}. Compareceu o morador "
                f"{nome}, residente na {pessoal}, que relatou problemas no canteiro de obras da {sec}.")
        d.enderecos += [(prof, "profissional"), (pessoal, "pessoal"), (sec, "secundario")]
    d.lines = _wrap(body)
    return d


def generate_addresses(n=12, seed=2026):
    rng = random.Random(seed)
    return [address_doc(rng, i) for i in range(n)]

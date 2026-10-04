# SPDX-License-Identifier: AGPL-3.0-or-later
"""Endereços FICTÍCIOS rotulados (1 = residencial/pessoal, 0 = não pessoal).

Usados para o treino inicial e, com outra semente, como conjunto fixo de avaliação do portão de
qualidade. São gerados de forma determinística (nenhum arquivo de dados para manter). Atenção: dados
sintéticos medem só o básico; quem melhora o modelo de verdade são as correções do revisor
(utils/decisions/feedback.py). Nunca acrescente endereços reais aqui.
"""
import random

TRAIN_SEED = 1
HOLDOUT_SEED = 2026

# Conjunto REALISTA, escrito à mão (frases variadas, fora dos moldes do gerador abaixo). Nunca entra no
# treino: serve só ao portão de qualidade, porque o conjunto gerado é parecido demais com o de treino e
# superestima a qualidade (no 1º experimento: AUC 0,99 no gerado contra 0,91 aqui). Tudo fictício.
REALISTIC = [
 ("Rua das Acácias, 123, apto 45, Jardim Exemplo, Cidade Fictícia - UF", 1),
 ("residente e domiciliado à Rua Projetada B, nº 12, Bloco C, Apto 302, Residencial Primavera", 1),
 ("Endereço: Travessa Bem-Te-Vi, 40, casa 3, fundos, Vila Teste", 1),
 ("morador do Condomínio Recanto Verde, quadra 4, casa 17", 1),
 ("Av. das Palmeiras, 900, apartamento 1204, torre 2, Bairro Modelo", 1),
 ("com domicílio na Rua Sete de Setembro, 55, Centro, Município Exemplo", 1),
 ("Rua Alfa, s/n, casa amarela, próximo à praça, Vila Nova", 1),
 ("Residência: Alameda dos Ipês, 210, Jardim das Flores, CEP 00000-000", 1),
 ("Edifício Solar das Águas, apto 803, Rua do Lago, 77", 1),
 ("Rua São Benedito, 1500, casa 2, Bairro Boa Esperança, Cidade Fictícia", 1),
 ("Conjunto Habitacional Esperança, bloco 7, apto 22", 1),
 ("Chácara onde reside a requerente, Estrada do Barreiro, km 3", 1),
 ("Rua Ipê Roxo, 88, Residencial Bela Vista, Cidade Exemplo - UF", 1),
 ("Kitnet 4, Rua Doze, 300, Vila Operária", 1),
 ("Travessa Primavera, 19, sobrado, Jardim América", 1),
 ("Rua Beija-Flor, 702, Parque das Nações, Município Modelo - UF", 1),
 ("Av. Getúlio Exemplo, 1500, Sala 1203, Ed. Corporate Tower, Centro", 0),
 ("Prefeitura Municipal de Cidade Fictícia, Praça Central, s/n", 0),
 ("Sítio São José, Estrada da Lagoa, s/n, zona rural", 0),
 ("Empresa Fictícia Comércio Ltda, CNPJ 00.000.000/0000-00, estabelecida na Rua Alfa, 300, galpão 2", 0),
 ("Secretaria de Estado de Exemplo, Palácio Administrativo, bloco B, Centro Político", 0),
 ("Fazenda Santa Luzia, Rodovia BR-000, km 45, lado esquerdo", 0),
 ("Escritório de Advocacia Modelo, Rua do Comércio, 45, conjunto 801", 0),
 ("Hospital Regional Exemplo, Av. da Saúde, 1000", 0),
 ("Escola Estadual Fictícia, Rua da Educação, 12, Bairro Escolar", 0),
 ("Loja 15 do Shopping Exemplo, Av. Principal, 2000", 0),
 ("Canteiro de obras do Edifício Horizonte, Rua Nova, lote 8", 0),
 ("Tribunal de Justiça Fictício, Fórum da Comarca, Rua da Justiça, 1", 0),
 ("Cartório do 1º Ofício, Rua Direita, 33, sala 2", 0),
 ("Indústria Modelo S/A, Distrito Industrial, quadra 5, lote 10", 0),
 ("Posto de Saúde do Bairro Exemplo, Rua da Paz, 400", 0),
 ("Gleba Rio Claro, lote 23, assentamento Fictício", 0),
 ("Clínica Odontológica Sorriso, Av. Brasil, 750, sala 3", 0),
 ("Câmara Municipal de Município Modelo, Rua do Legislativo, 10", 0),
 ("Supermercado Exemplo, Rodovia dos Imigrantes, km 2", 0),
 ("Delegacia de Polícia Civil, Av. da Segurança, 90", 0),
]

_LOGRADOUROS = ["Rua", "Avenida", "Travessa", "Alameda", "Rua Projetada", "Estrada"]
_NOMES = ["das Acácias", "dos Ipês", "Fictícia", "Exemplo", "das Flores", "do Sol", "Beija-Flor", "dos Pinheiros",
          "Bem-Te-Vi", "Primavera", "das Palmeiras", "Boa Esperança", "São Benedito", "Santa Rita"]
_BAIRROS = ["Jardim Exemplo", "Bairro Fictício", "Vila Teste", "Residencial Aurora", "Jardim das Américas",
            "Centro", "Bosque da Saúde", "Parque Modelo"]
_CIDADES = ["Cidade Fictícia - UF", "Município Exemplo - UF", "Vila Modelo - UF"]

_RESID_COMPLEMENTOS = ["casa 0", "apto 000", "apartamento 000, bloco B", "Condomínio Residencial Bela Vista, casa 00",
                       "quadra 00, lote 00, casa", "Edifício Residencial Solar, apto 000", "fundos", "casa 0, sobrado"]
_RESID_PREFIXOS = ["", "residente na ", "domiciliado na ", "morador da ", "com residência na "]

_EMPRESAS = ["Comércio Exemplo Ltda", "Construtora Fictícia S/A", "Escritório Modelo Advocacia",
             "Clínica Exemplo", "Loja Teste ME", "Indústria Fictícia Ltda", "Contabilidade Modelo"]
_EMP_COMPLEMENTOS = ["sala 000", "Edifício Empresarial Alfa, sala 00", "loja 00", "galpão 0", "andar 00, conjunto 000"]
_ORGAOS = ["Secretaria de Estado de Exemplo", "Prefeitura Municipal de Cidade Fictícia", "Tribunal de Justiça Fictício",
           "Câmara Municipal Modelo", "Autarquia Estadual Exemplo", "Defensoria Pública Fictícia"]
_RURAIS = ["Fazenda Boa Vista", "Sítio Recanto Fictício", "Chácara Modelo", "Gleba Exemplo, lote 00",
           "Lote 00 do Loteamento Fictício", "Obra do Residencial Aurora (canteiro)", "Empreendimento Fictício, área 0"]
_RODOVIAS = ["Rodovia MT-000, km 00", "BR-000, km 000", "Estrada Vicinal 00, zona rural"]


def _street(rng):
    return f"{rng.choice(_LOGRADOUROS)} {rng.choice(_NOMES)}, {rng.randint(1, 3000)}"


def _city(rng):
    return f"{rng.choice(_BAIRROS)}, {rng.choice(_CIDADES)}, CEP 00000-000"


def _residential(rng):
    return f"{rng.choice(_RESID_PREFIXOS)}{_street(rng)}, {rng.choice(_RESID_COMPLEMENTOS)}, {_city(rng)}".strip()


def _non_personal(rng):
    kind = rng.randrange(4)
    if kind == 0:
        return f"{rng.choice(_EMPRESAS)}, {_street(rng)}, {rng.choice(_EMP_COMPLEMENTOS)}, {_city(rng)}"
    if kind == 1:
        return f"{rng.choice(_ORGAOS)}, {_street(rng)}, {_city(rng)}"
    if kind == 2:
        return f"{rng.choice(_RURAIS)}, {rng.choice(_RODOVIAS)}, {rng.choice(_CIDADES)}"
    return f"sede da {rng.choice(_EMPRESAS)}: {_street(rng)}, {rng.choice(_EMP_COMPLEMENTOS)}, {_city(rng)}"


def generate(n=200, seed=TRAIN_SEED):
    """Lista de (texto, rótulo) balanceada e embaralhada."""
    rng = random.Random(seed)
    rows = [(_residential(rng), 1) for _ in range(n // 2)] + [(_non_personal(rng), 0) for _ in range(n - n // 2)]
    rng.shuffle(rows)
    return rows


def holdout(n=160):
    """Conjunto fixo de avaliação (semente diferente da de treino)."""
    return generate(n, HOLDOUT_SEED)


def realistic():
    """Conjunto realista fixo (texto, rótulo), escrito à mão; só para avaliação."""
    return list(REALISTIC)

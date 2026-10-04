# Catálogo de dados pessoais (PII)

> Gerado por `python -m utils.detect --markdown` a partir de `utils/detect/catalog.py`. Não edite à mão.
>
> O enquadramento indica a que categoria de cada referência o tipo corresponde. Detectar e tarjar esses
> tipos **apoia** práticas alinhadas a essas referências; **não** torna um documento "conforme".
> Itens *planejados* ainda não têm detector.

## Identificador direto

| Tipo | Estado | Detecção | LGPD | GDPR | ISO/IEC 29100 | NIST SP 800-122 | HIPAA Safe Harbor |
|---|---|---|---|---|---|---|---|
| **CPF** (`cpf`) | ativo | regra + dígito verificador (OCR, passada esparsa e texto digital) | LGPD art. 5º, I (dado pessoal) | GDPR art. 4(1) e art. 87 (número de identificação nacional) | PII | identificador pessoal (ex.: SSN) | outro número de identificação único |
| **RG (carteira de identidade)** (`rg`)<br>*Sem algoritmo nacional de dígito verificador: exige contexto.* | ativo | formato + palavra de contexto (RG, identidade) | LGPD art. 5º, I (dado pessoal) | GDPR art. 4(1) e art. 87 | PII | identificador pessoal | outro número de identificação único |
| **CNH (registro da habilitação)** (`cnh`) | ativo | formato + palavra de contexto (CNH, habilitação) | LGPD art. 5º, I (dado pessoal) | GDPR art. 4(1) | PII | identificador pessoal (carteira de motorista) | número de certificado/licença |
| **Título de eleitor** (`titulo_eleitor`) | ativo | regra + dígito verificador + contexto | LGPD art. 5º, I (dado pessoal) | GDPR art. 4(1) | PII | identificador pessoal | outro número de identificação único |
| **PIS/PASEP/NIS/NIT** (`pis_nis`) | ativo | regra + dígito verificador + contexto | LGPD art. 5º, I (dado pessoal) | GDPR art. 4(1) | PII | identificador pessoal | outro número de identificação único |
| **Cartão Nacional de Saúde (CNS/SUS)** (`cns`) | ativo | regra + dígito verificador | LGPD art. 5º, I (dado pessoal); associado a dado de saúde pode compor dado sensível | GDPR art. 4(1) | PII | identificador pessoal | número de beneficiário de plano de saúde |
| **Passaporte** (`passaporte`) | ativo | formato + palavra de contexto (passaporte) | LGPD art. 5º, I (dado pessoal) | GDPR art. 4(1) | PII | identificador pessoal (passaporte) | número de certificado/licença |
| **Carteira de Trabalho (CTPS)** (`ctps`) | ativo | formato + palavra de contexto (CTPS) | LGPD art. 5º, I (dado pessoal) | GDPR art. 4(1) | PII | identificador pessoal | outro número de identificação único |
| **Cartão de pagamento** (`cartao_pagamento`) | ativo | Luhn + formatação em grupos ou contexto | LGPD art. 5º, I (dado pessoal) | GDPR art. 4(1) | PII | conta financeira / cartão de crédito | número de conta |
| **Agência e conta bancária** (`conta_bancaria`) | ativo | palavra de contexto (agência, conta, c/c) | LGPD art. 5º, I (dado pessoal) | GDPR art. 4(1) | PII | conta financeira | número de conta |
| **Chave Pix aleatória** (`chave_pix`)<br>*Chaves Pix de CPF, e-mail ou telefone já são cobertas pelos respectivos tipos.* | ativo | formato (UUID) | LGPD art. 5º, I (dado pessoal) | GDPR art. 4(1) | PII | conta financeira | número de conta |
| **Nome de pessoa** (`nome_pessoa`)<br>*Na LAI, nome de servidor no exercício da função costuma ser público: exceção decidida por perfil/Laya (B-74).* | opcional | GLiNER local (NER_ENGINE=gliner): confiança alta = tarja sugerida, média = revisão | LGPD art. 5º, I (dado pessoal) | GDPR art. 4(1) | PII | nome | nomes |
| **Filiação (nome da mãe/pai)** (`filiacao`) | opcional | GLiNER local + contexto (filho de, mãe, genitora...) | LGPD art. 5º, I (dado pessoal) | GDPR art. 4(1) | PII | nome / informação vinculável | nomes (inclui parentes) |
| **Assinatura** (`assinatura`) | planejado | detector YOLO (hoje só localiza para auditar CPFs próximos) | LGPD art. 5º, I (dado pessoal) | GDPR art. 4(1) | PII | característica pessoal | — |
| **Foto de rosto** (`foto_rosto`) | planejado | detecção de rosto (planejado) | LGPD art. 5º, I (dado pessoal) | GDPR art. 4(1); art. 9 se usado para identificação biométrica | PII | característica pessoal (foto) | foto de rosto inteiro e imagens comparáveis |

## Dado pessoal

| Tipo | Estado | Detecção | LGPD | GDPR | ISO/IEC 29100 | NIST SP 800-122 | HIPAA Safe Harbor |
|---|---|---|---|---|---|---|---|
| **Endereço residencial** (`endereco_residencial`) | ativo | LLM de visão + casamento com o OCR (+ decisor Laya) | LGPD art. 5º, I (dado pessoal) | GDPR art. 4(1) (dado de localização) | PII | endereço | subdivisão geográfica menor que o estado |
| **Telefone** (`telefone`)<br>*Telefones institucionais também são marcados: o revisor decide.* | ativo | formato brasileiro (DDD) ou palavra de contexto | LGPD art. 5º, I (dado pessoal) | GDPR art. 4(1) | PII | número de telefone | número de telefone/fax |
| **E-mail** (`email`)<br>*E-mails institucionais também são marcados: o revisor decide.* | ativo | formato | LGPD art. 5º, I (dado pessoal) | GDPR art. 4(1) (identificador online) | PII | endereço de e-mail | endereço de e-mail |

## Dado pessoal sensível

| Tipo | Estado | Detecção | LGPD | GDPR | ISO/IEC 29100 | NIST SP 800-122 | HIPAA Safe Harbor |
|---|---|---|---|---|---|---|---|
| **Dado de saúde (diagnóstico, CID, tratamento)** (`saude`) | planejado | LLM/Laya sobre o contexto, sempre com revisão humana | LGPD art. 5º, II (dado pessoal sensível) | GDPR art. 9 (dados de saúde) | PII sensível | informação médica | número de prontuário e informação de saúde associada |
| **Dado biométrico ou genético** (`biometrico_genetico`) | planejado | LLM/Laya + revisão | LGPD art. 5º, II (dado pessoal sensível) | GDPR art. 9 | PII sensível | característica pessoal (biometria) | identificador biométrico |
| **Convicção religiosa** (`religiao`) | planejado | LLM/Laya + revisão | LGPD art. 5º, II (dado pessoal sensível) | GDPR art. 9 | PII sensível | informação vinculável | — |
| **Opinião política / filiação partidária** (`opiniao_politica`) | planejado | LLM/Laya + revisão | LGPD art. 5º, II (dado pessoal sensível) | GDPR art. 9 | PII sensível | informação vinculável | — |
| **Filiação a sindicato** (`filiacao_sindical`) | planejado | LLM/Laya + revisão | LGPD art. 5º, II (dado pessoal sensível) | GDPR art. 9 | PII sensível | informação vinculável | — |
| **Origem racial ou étnica** (`origem_etnica`) | planejado | LLM/Laya + revisão | LGPD art. 5º, II (dado pessoal sensível) | GDPR art. 9 | PII sensível | informação vinculável | — |
| **Vida sexual / orientação sexual** (`vida_sexual`) | planejado | LLM/Laya + revisão | LGPD art. 5º, II (dado pessoal sensível) | GDPR art. 9 | PII sensível | informação vinculável | — |
| **Condenações e infrações penais** (`antecedentes_criminais`) | planejado | LLM/Laya + revisão | LGPD: não listado no art. 5º, II; o tratamento para persecução penal fica fora da LGPD e segue lei específica (art. 4º, III) | GDPR art. 10 | PII sensível | informação vinculável | — |

## Identificador indireto

| Tipo | Estado | Detecção | LGPD | GDPR | ISO/IEC 29100 | NIST SP 800-122 | HIPAA Safe Harbor |
|---|---|---|---|---|---|---|---|
| **Endereço IP** (`ip`) | ativo | formato IPv4 válido | LGPD art. 5º, I (dado pessoal) (quando vinculado a pessoa) | GDPR art. 4(1) (identificador online) | PII | informação de ativo (IP) | endereço IP |
| **Coordenadas geográficas** (`geolocalizacao`) | planejado | formato lat/long (planejado) | LGPD art. 5º, I (dado pessoal) | GDPR art. 4(1) (dado de localização) | PII | informação vinculável | subdivisão geográfica |
| **Data de nascimento** (`data_nascimento`) | ativo | data + palavra de contexto (nascido, nascimento) | LGPD art. 5º, I (dado pessoal) | GDPR art. 4(1) | PII | informação vinculável (data de nascimento) | datas relacionadas à pessoa (exceto ano) |
| **Placa de veículo** (`placa_veiculo`) | ativo | formato antigo ou Mercosul | LGPD art. 5º, I (dado pessoal) (quando vinculada a pessoa) | GDPR art. 4(1) | PII | bem de propriedade pessoal (registro de veículo) | identificador de veículo (inclui placa) |


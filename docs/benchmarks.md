# Benchmarks (somente dados sintéticos)

> **Leia isto primeiro.** Todos os números abaixo foram medidos em **digitalizações sintéticas, geradas** (tipografia limpa,
> ruído leve, rotação leve). Documentos reais (carimbos, manuscritos, fotografias de papel, digitalizações tortas ou de
> baixo contraste, tabelas, layouts com várias colunas) são mais difíceis, portanto **a revocação no mundo real é desconhecida e
> deve ser menor**. Trate estes resultados como uma linha de base de regressão e uma forma de comparar configurações,
> não como garantia de acurácia. A revisão humana de toda saída continua obrigatória.

## O que é medido

O benchmark (`benchmarks/`) gera PDFs A4 digitalizados (páginas somente raster, sem camada de texto) com ground truth:

* 3 CPFs válidos por página (formatados `000.000.000-00` ou 11 dígitos sem formatação), em fontes/tamanhos variados
  (Arial, Times, Courier, Verdana, Georgia, Calibri na máquina que o executou);
* iscas que **não** devem ser tarjadas: um CPF com dígito verificador errado, um CNPJ válido, uma data/horário, um número
  de processo e um número de telefone;
* texto de corpo preenchendo a página, desfoque gaussiano, ruído gaussiano (sigma 8 = "digitalização limpa", sigma 28 = "digitalização ruim"),
  manchas e uma rotação aleatória de +-1,2 grau. As páginas são JPEG de 300 DPI (q80) embutidas em um PDF A4.

Duas coisas são avaliadas por configuração `(render DPI, Tesseract psm)`:

1. **Detecção** (`OCREngine.get_grounding_map` + `find_cpfs_in_grounding` no PDF original renderizado no
   DPI indicado): revocação/precisão no nível de CPF (correspondência de valor) e *cobertura de caixas* (fração das caixas de CPF do ground truth cujo
   centro cai dentro de uma caixa de tarja produzida por `Session.get_redaction_boxes`; conservadora, porque o centro
   de um CPF dividido em várias palavras do OCR pode cair no espaço entre as caixas das palavras).
2. **Verificação** (`utils.verifier.verify_pdf` em um PDF *final* construído como o pipeline faz: 1240 px de largura,
   JPEG q75). Dois PDFs finais são construídos a partir das mesmas páginas: **com vazamento** (apenas o primeiro CPF de cada página é
   tarjado, então 2 CPFs/página vazam) e **limpo** (os três tarjados). Reportado: fração dos CPFs vazados que o
   verificador encontra e páginas limpas sinalizadas indevidamente.

Os tempos são segundos de relógio (wall-clock) por página (renderização + OCR), medidos com 4 processos worker em paralelo, cada Tesseract
em thread única, em uma máquina Windows 10 de 20 núcleos com Tesseract 5.4.1 (traineddata `por`). Trate-os como
relativos, não absolutos.

## Reproduzir

```bash
python -m benchmarks.run_benchmark --pages 10 --dpis 200 300 400 --psms 3 6 11 --workers 4 --seed 42 --noise 8 \
    --out benchmarks/results/synthetic_noise8.json
```

Requer o Tesseract (defina `TESSERACT_PATH`/`TESSDATA_PREFIX` se ele não estiver no PATH). O corpus é determinístico
para um dado `--seed`; o JSON completo (incluindo as linhas por página) das execuções reportadas aqui está em `benchmarks/results/`.

## Resultados, 10 páginas, 30 CPFs válidos, 20 CPFs vazados (seed 42)

### Digitalização limpa (ruído sigma 8) - `synthetic_noise8.json`

| DPI de renderização | psm | revocação de CPF | precisão | cobertura de caixas | s/página (detecção) |
|---:|---:|---:|---:|---:|---:|
| 200 | 3 / 6 / 11 | 100 % | 100 % | 100 % | 4,3 - 4,7 |
| 300 | 3 / 6 / 11 | 100 % | 100 % | 100 % | 7,2 - 7,6 |
| 400 | 3 / 6 / 11 | 96,7 % (29/30) | 100 % | 96,7 % | 10,9 - 11,2 |

Verificação (PDF final, 1240 px, JPEG q75): **20/20 CPFs vazados encontrados e 0/10 páginas limpas sinalizadas em todas as
combinações de DPI de verificação 200/300/400 e psm 3/6/11.** Tempo de 3,7 s/página a 200 DPI, 5,1 - 5,7 s/página a 300 - 400 DPI.

### Digitalização ruim (ruído sigma 28) - `synthetic_noise28.json`

| DPI de renderização | psm | revocação de CPF | precisão | cobertura de caixas | s/página (detecção) |
|---:|---:|---:|---:|---:|---:|
| 200 | 3 / 6 | 96,7 % | 100 % | 96,7 % | 4,3 - 4,4 |
| 200 | 11 | 96,7 % | 96,7 % (1 CPF falso) | 96,7 % | 4,3 |
| 300 | 3 / 6 / 11 | 100 % | 100 % | 100 % | 7,6 - 7,7 |
| 400 | 3 / 6 / 11 | 93,3 % (28/30) | 100 % | 93,3 % | 10,2 - 11,5 |

A verificação novamente encontrou **20/20 vazamentos com 0/10 páginas limpas sinalizadas** nas nove configurações (4,2 - 7,1 s/página).

### Sondagem em resolução mais alta - `synthetic_dpi600_probe.json` (4 páginas, 12 CPFs, psm 3, sigma 8)

| DPI de renderização | revocação de CPF | precisão | cobertura de caixas | s/página (detecção) | verificação a 600 DPI: revocação de vazamentos |
|---:|---:|---:|---:|---:|---:|
| 600 | 75 % (9/12) | 90 % (1 CPF falso) | 50 % | 21,4 | 87,5 % (7/8) |

## O que os números dizem (e o que não dizem)

* Neste corpus sintético, **300 DPI foi a melhor configuração de detecção**; 200 DPI foi quase tão bom e ~40 % mais rápido.
  A revocação **caiu a 400 e especialmente a 600 DPI**: o Tesseract fragmenta os dígitos em tokens pequenos em tamanhos
  de renderização grandes, o que torna mais difícil juntar as sequências de dígitos em um único CPF. O padrão antigo do projeto, `BASE_DPI=1000`, **não
  foi medido** (uma única página A4 leva minutos); com base nessas evidências, ele está fora da faixa em que as digitalizações sintéticas
  se comportam melhor. Isso pode ser diferente para digitalizações reais, então meça com seus próprios dados (permitidos) antes de alterar o padrão.
* `psm` 3, 6 e 11 deram a mesma revocação em texto sintético limpo; diferenças só apareceriam em layouts mais bagunçados.
  Os únicos CPFs falsos observados foram um com psm 11 a 200 DPI (digitalização ruim) e um com psm 3 a 600 DPI.
* O verificador pós-tarja foi perfeito aqui (nenhum vazamento perdido, nenhum alarme falso) mesmo a 200 DPI em um JPEG
  de 1240 px; isso é esperado para tipografia limpa e diz pouco sobre manuscritos, carimbos ou fotografias ruins.
  A sondagem com dpi=600 mostra que ele também não é imune à fragmentação do OCR (7/8).
* Não medido: manuscritos, assinaturas com CPFs escritos por perto, acurácia do YOLO, descoberta de endereços pelo LLM de visão,
  qualidade da correspondência de endereços (veja `tests/test_address_matching.py` para a caracterização de tarja excessiva/insuficiente),
  PDFs com camada de texto nativa (esses são verificados por extração exata de texto, não por OCR).
* Os tamanhos de amostra são pequenos (30 CPFs): um único erro move a revocação em 3,3 pontos. Use os arquivos JSON para o detalhe por página.

## Rodada de 2026-10-04: DPI de renderização (300 × 600 × 1000)

Motivação: o padrão `BASE_DPI=1000` deixava um documento real de 10 páginas em ~14 minutos (61% do tempo no OCR).

### Sintético (`--pages 8 --dpis 300 600 1000 --psms 3 11 --workers 6 --seed 7 --noise 12`, 24 CPFs)

| DPI | psm | revocação de CPF | precisão | cobertura de caixas | s/página |
|---:|---:|---:|---:|---:|---:|
| 300 | 3 | 100,0% | 100,0% | 100,0% | 7,1 |
| 300 | 11 | 100,0% | 100,0% | 100,0% | 8,0 |
| 600 | 3 | 62,5% | 88,2% | 33,3% | 22,5 |
| 600 | 11 | 58,3% | 93,3% | 25,0% | 22,0 |
| 1000 | 3 | 58,3% | 93,3% | 29,2% | 21,0 |
| 1000 | 11 | 62,5% | 100,0% | 33,3% | 19,5 |

Verificação (PDF final 1240 px): vazamentos encontrados 16/16 a 300 DPI, 14/16 a 600, 11 a 13/16 a 1000; nenhuma página
limpa sinalizada em nenhuma configuração.

### Documento real (10 páginas digitalizadas, só contagens; OCR duplo sequencial)

| DPI | renderização | OCR duplo | CPFs distintos |
|---:|---:|---:|---:|
| 300 | 16 s | 101 s | 6 |
| 400 | 28 s | 154 s | 6 |
| 600 | 45 s | 245 s | 5 |
| 1000 | 82 s | ~510 s | 5 |

A 300 DPI, os 5 CPFs achados a 1000 DPI foram todos encontrados. O sexto veio da passada esparsa, montado com 4 pedaços
de duas linhas, sem CPF inteiro numa palavra: provável falso positivo (vira tarja sugerida a mais, que o revisor remove).

**Decisão:** padrão `BASE_DPI=300`. Somado ao OCR das páginas em paralelo (`OCR_WORKERS`), o OCR deve ficar perto de
10× mais rápido. As duas passadas de OCR (padrão + esparsa) foram mantidas de propósito: cada leitura a mais pode achar
um CPF que a outra perdeu.

## Corpus fictício de PII: revocação e precisão por tipo

`benchmarks/pii_corpus.py` gera documentos **fictícios** de cinco modelos (ata de condomínio, contrato de locação, ficha
de cadastro, ofício público, ficha de atendimento de saúde) com resposta conhecida (`gabarito`) e **iscas** que não
devem ser achadas (outras datas, valores em reais, CNPJ, número de processo, protocolo). Números com dígito verificador
são gerados na hora; e-mails usam `example.com`. `benchmarks/pii_eval.py` mede por **valor**, tipo a tipo.

```bash
python -m benchmarks.pii_eval --docs 200 --seed 7          # texto direto (rápido, sem OCR)
python -m benchmarks.pii_eval --ocr --docs 40 --seed 2026  # desenha cada documento numa imagem com ruído e usa o OCR real (2 passadas)
```

O teste `tests/test_pii_corpus_gate.py` roda o modo texto em duas sementes a cada `pytest`: revocação abaixo de 100%
ou precisão abaixo de 98% em qualquer tipo reprova.

### Modo texto (200 documentos; sementes 7 e 2026)

Todos os tipos com **100% de revocação e 100% de precisão** nas duas sementes (CPF 240/240 e 236/236, telefone
200/200 e 196/196, data de nascimento 120/120, e-mail 80/80, CNS, PIS/NIS, placa e RG 40/40). O corpus encontrou e
ajudou a corrigir quatro erros que já existiam no detector de CPF: dígitos vizinhos ("unidade 14A, CPF ...")
deslocavam a janela e o CPF verdadeiro era pulado; CPF e PIS na mesma linha; o pré-filtro de CNPJ apagava um CPF
quando uma janela cruzava dois números; e um pedaço do Cartão SUS (15 dígitos) passava no dígito verificador de CPF.

### Modo OCR real (40 documentos, semente 2026; Tesseract 5.4.1 `por`, Arial 30 px, ruído sal e pimenta + desfoque)

| Tipo | Esperados | Achados | Falsos positivos | Revocação | Precisão |
|---|---:|---:|---:|---:|---:|
| cns | 8 | 8 | 0 | 100% | 100% |
| cpf | 45 | 45 | 3 | 100% | 94% |
| data_nascimento | 24 | 24 | 0 | 100% | 100% |
| email | 16 | 16 | 0 | 100% | 100% |
| pis_nis | 8 | 8 | 0 | 100% | 100% |
| placa_veiculo | 8 | 8 | 0 | 100% | 100% |
| rg | 8 | 8 | 1 | 100% | 89% |
| telefone | 37 | 37 | 0 | 100% | 100% |

**O que o modo OCR revelou (e o modo texto escondia):**

* **E-mail tinha 0% de revocação com OCR real.** O Tesseract em português lê "@" como "(D" ou "(W", **até em imagem
  limpa** e em várias fontes, e às vezes parte o nome ("beatriz.7" + "1(Dexample.com"). Em documentos digitalizados
  reais os e-mails provavelmente passavam sem tarja. A regra agora aceita essas variantes (lista em
  `utils/detect/data/contextos.json`) e, quando o "@" vira uma letra solta, aceita o endereço logo depois da palavra
  "e-mail" com domínio de extensão conhecida. Resultado: 0% → 100%.
* **Placa:** o "0" saiu como "O" ("ZRDOD17"); com a palavra "placa" perto, a regra aceita a troca. 88% → 100%.
* Os falsos positivos de CPF e RG que restam são leituras deformadas pelo ruído **em cima do próprio RG/CPF** (ex.:
  "SSP" lido como "595" e juntado a dígitos vizinhos): tarja a mais no lugar certo, não vazamento.
* Uma das passadas de OCR perdeu inteiramente o nome de um e-mail que a outra leu: mais um caso a favor de manter as
  duas passadas.

Como no resto desta página: imagem gerada é mais fácil que papel real. Trate como linha de base de regressão.


## Motores de OCR e IAs de OCR (corpus fictício e documentos reais)

`benchmarks/ocr_compare.py` desenha cada documento fictício numa página sob quatro condições (limpa; padrão; ruim:
desfoque, ruído forte, rotação de 1,2°, JPEG 45, resolução reduzida; péssima: tudo pior) e mede, por combinação de
leituras, revocação e precisão por tipo. "a+b" soma as leituras (o OCR duplo atual é `tesseract3+tesseract11`).
Máquina: CPU de 20 núcleos, RTX 2080 Ti (11 GB), Tesseract 5.4.1 `por`.

### Motores clássicos (30 documentos por condição; tempo por página na CPU)

| Condição | Tesseract duplo (atual) | + RapidOCR | + docTR | RapidOCR sozinho | docTR sozinho |
|---|---:|---:|---:|---:|---:|
| limpa | 100% / 90,6% | 100% / 90,6% | 100% / 90,6% | 92,2% / 100% | 100% / 100% |
| padrão | 100% / 91,3% | 100% / 91,3% | 100% / 90,6% | 96,6% / 100% | 99,1% / 99,1% |
| ruim | 100% / 95,9% | 100% / 95,1% | 100% / 92,1% | 98,3% / 99,1% | 96,6% / 95,7% |
| **péssima** | **98,3%** / 94,2% (perdeu 2 e-mails) | **100%** / 93,5% | 100% / 89,2% | 94,0% / 99,1% | 93,1% / 93,9% |

(revocação / precisão). Tempo: Tesseract ~0,7 s por passada, RapidOCR ~1,3 s, docTR ~1,0 s. Nenhuma leitura sozinha
chegou a 100% nas condições ruins: **as leituras se somam**. Os "falsos positivos" do Tesseract em imagem limpa vêm
de linhas longas que o PSM 3 lê duas vezes (a segunda deformada) em cima do próprio dado: tarja a mais no lugar certo.
O docTR vaza ~140 threads do sistema por página (13 mil em minutos) sem `DOCTR_MULTIPROCESSING_DISABLE=TRUE`.

### Modelos de visão como OCR (12 documentos por condição; tempo na GPU)

| Leitura | padrão | ruim | péssima | s/pág |
|---|---:|---:|---:|---:|
| Tesseract duplo | 100% / 88,9% | 100% / 98,0% | 95,8% / 92,0% | 1,4 (CPU) |
| glm-ocr (1,1B) | 100% / 100% | 100% / 100% | 100% / 100% | 15-17 |
| deepseek-ocr (v1, 3,3B) | 100% / 100% | 100% / 100% | 100% / 100% | 5 |
| **DeepSeek-OCR 2** (3B, Q4_K_M) | 100% / 100% | 100% / 100% | 97,9% / 97,9% | 3,5-5 |
| Qwen3.5-9B | 100% / 100% | 100% / 100% | 100% / 100% | 6,4 |
| gemma4:12b | 97,9% / 97,9% | 97,9% / 97,9% | 93,8% / 100% | 6,8 |

### Nos 7 documentos reais (69 páginas; sem gabarito; só contagens, nenhum valor exposto)

* **Tesseract duplo** achou os 14 CPFs do documento com texto digital (o texto digital é o gabarito exato). glm-ocr,
  Qwen3.5 e DeepSeek-OCR 2 também (14/14, 6/6 contas). O **deepseek-ocr v1 falha em página densa** (3-4 de 14: corta
  o texto).
* **O Tesseract perdeu um telefone e um e-mail** numa linha "Fone / Fax / e-mail" que leu deformada: RapidOCR e
  DeepSeek-OCR 2 leram certo, cada um por conta própria. Por isso a leitura extra RapidOCR passou a ser recomendada
  (custo: 2 tarjas a mais montadas com números de uma tabela).
* **O DeepSeek-OCR 2 inventou 32 CPFs** numa página (ausentes do texto digital e de qualquer leitura de OCR), e não de
  forma repetível: o mesmo documento, em outra rodada, saiu limpo. Modelo de visão nunca pode ser a única leitura;
  como segunda opinião, só vale o que for localizado nas palavras do OCR (backlog B-85).

## LLM de endereços: modelo × pedido (`benchmarks/address_eval.py`)

No corpus fictício de endereços (pessoal, profissional, secundário; abreviações; endereço partido entre linhas) os
dois modelos acertaram ~100% com qualquer pedido: o corpus é fácil demais para separar. A diferença apareceu nos
**documentos reais** (Qwen3.5-9B, 69 páginas):

| Pedido | Endereços pessoais localizados | Pessoais **não** localizados (inventados/montados) | s/pág |
|---|---:|---:|---:|
| antigo ("endereço completo e estruturado", só imagem) | 10 | 0 | 4,3 |
| copiar exatamente (só imagem) | 25 | 2 | 4,4 |
| **copiar + texto da página** (adotado) | **30** | **1** (só termos genéricos: agora ignorado) | 4,8 |
| copiar + texto + esquema JSON | 56 | 28 (pedaços soltos como "Bloco A") | 3,6 |

Na ata de condomínio, o pedido antigo deixava passar os endereços dos condôminos (bloco/apartamento).

## Servidores de IA: reserva, disjuntor e verificação cruzada (ao vivo)

* **LM Studio** pela API da OpenAI como principal: funciona (primeira chamada 54 s com carga sob demanda; depois ~11 s).
* **Principal fora do ar ou travada** (aceita a conexão e não responde), reserva LM Studio: a primeira página paga as
  tentativas (44 s / 73 s); **as seguintes vão direto para a reserva** (~12 s), porque o disjuntor já desligou a
  principal. Sem ele, com o tempo limite padrão (600 s), uma IA travada custaria até 30 min por página. Achado do teste:
  cada servidor precisa do próprio tempo limite (com o mesmo, a reserva mais lenta também era desligada).
* **Descarga pela API** do LM Studio: GPU de 10,5 GB para 2,4 GB.
* **Verificação cruzada** (ata de condomínio, 10 páginas): com Qwen 35B no LM Studio como verificador, os dois modelos
  não cabem juntos em 11 GB (lento, HTTP 500); com Gemma 4 12B no Ollama, o verificador achou 6 endereços pessoais
  contra 19 da principal, **não acrescentou nenhum** e dobrou o tempo (11 → 23 s por página). Fica desligada por padrão;
  vale com um verificador ao menos tão bom quanto a principal.

## Teste de pressão (`benchmarks/stress.py`, pela API do app, só PDFs fictícios)

| Cenário | Resultado |
|---|---|
| 8 uploads simultâneos (fila de 2) | todos terminaram em 4 min; todos os CPFs achados; pico de 7,2 GB nos processos Python |
| documento de 40 páginas | 6,7 min; todos os CPFs; pico de 5,1 GB; "Requer revisão" |
| digitalização péssima | todos os CPFs; "Requer revisão" |
| PDF truncado | antes: "Concluído" em silêncio → **agora revisão** |
| PDF com senha | erro com mensagem clara |
| PDF falso | erro na fase 0 |
| **página gigante (200 x 200 pol.)** | antes: **35-40 GB de RAM** → agora DPI reduzido para o documento todo e revisão |
| Ollama fora do ar (pipeline completo) | CPFs achados sem a IA; páginas para revisão |

Invariantes conferidos em todos: nenhuma tarefa presa; nenhum "Concluído" com CPF do gabarito sem detecção.

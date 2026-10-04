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

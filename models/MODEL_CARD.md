# Model card: `signature_stamp_detector.pt`

*(Resumo curto em PT-BR no final)*

## Visão geral

| | |
|---|---|
| Tarefa | Detecção de objetos de **assinaturas manuscritas** em imagens de páginas de documentos |
| Classes | 1: `signature` (o nome do arquivo menciona "stamp" por razões históricas; **não** há classe de carimbo) |
| Arquitetura | YOLO11n (nano), formato Ultralytics; ajustado (fine-tuning) a partir dos pesos pré-treinados `yolo11n.pt` |
| Entrada | Imagem RGB da página; treinado com `imgsz=640`; o app o chama com `conf=0.25` |
| Precisão numérica dos pesos | FP16 |
| Arquivo | ~5,5 MB, checkpoint apenas para inferência (veja "Saneamento") |
| Usado por | `utils/yolo_engine.py` para recortar áreas ao redor de assinaturas, que depois são auditadas (OCR + LLM de visão) em busca de números de CPF escritos à mão |
| Licença | Tratar como **AGPL-3.0** (ferramental e pesos-base da Ultralytics). Veja [../NOTICE](../NOTICE) e [../docs/licensing.md](../docs/licensing.md) |

### Resumo dos dados de treino
Apenas o que o checkpoint original registrou é reportado; todo o resto é **não informado** (não registrado no checkpoint e não conhecido pelos mantenedores deste repositório no momento da redação).

* Dataset: documentos administrativos digitalizados/nativos anotados com uma classe (`signature`). **Origem, tamanho (imagens/instâncias), tamanhos das divisões, idioma, ferramenta de anotação e licença dos dados: não informados.** O dataset **não** é distribuído e não pode ser reconstruído a partir deste arquivo.
* Execução do treino: 100 épocas configuradas (paciência de early stopping 20; 100 épocas foram registradas), batch size 8, tamanho de imagem 640, treino em CPU, aumento de dados padrão da Ultralytics (mosaic 1.0, flip-lr 0.5, jitter HSV, random erasing 0.4, translate 0.1, scale 0.5), otimizador `auto`, seed 0.
* Treinado com Ultralytics 8.4.31.

### Métricas (conforme armazenadas no checkpoint; divisão de validação, tamanho não informado)
| Métrica | Melhor checkpoint | Última época | Melhor entre as épocas |
|---|---|---|---|
| mAP@0.5 | 0.526 | 0.446 | 0.546 |
| mAP@0.5:0.95 | 0.132 | 0.113 | 0.132 |
| Precisão | 1.000 | 0.569 | 1.000 |
| Revocação | 0.482 | 0.500 | 0.750 |

Interpretação: **acurácia modesta**. Revocação de cerca de 0,5 significa que aproximadamente metade das assinaturas pode não ser detectada; valores de precisão que oscilam entre 0,57 e 1,0 sugerem um **conjunto de validação muito pequeno**, então esses números são ruidosos e não devem ser generalizados. O pipeline não depende apenas deste modelo (o OCR de página inteira e o LLM de visão também procuram CPFs), mas você deve esperar falhas de detecção em assinaturas incomuns. Trate-o como um auxiliar para localizar regiões de assinatura, não como garantia. Nenhuma avaliação em benchmarks independentes ou públicos foi realizada.

### Saneamento (o que foi removido antes da publicação)
O checkpoint de treino original continha, além dos pesos: os `train_args` completos (incluindo **caminhos locais absolutos** do YAML do dataset, das pastas do projeto e da execução, e o nome da execução), um **bloco git** com um caminho de repositório local, hash de commit e URL do remoto, a **data do treino**, o **histórico de treino** por época (losses, learning rates, métricas) e campos de metadados (os slots de otimizador/EMA já estavam vazios). O arquivo publicado mantém **apenas** os pesos FP16, a definição da arquitetura, os nomes de classe (`{0: "signature"}`) e argumentos genéricos mínimos (`task=detect`, `imgsz=640`). Foi verificado que ele carrega com `ultralytics.YOLO` e executa inferência, e uma varredura das strings do arquivo não encontrou caminhos, nomes de usuário, nomes de arquivos do dataset ou datas.

### Ressalva de privacidade (nota honesta)
Remover metadados **não** torna os pesos matematicamente imunes à extração de dados de treino. Um detector como este (classe única, 2,6 M de parâmetros, sem capacidade generativa ou de memorizar texto) oferece um risco muito baixo de reproduzir documentos de treino identificáveis, mas o risco é **baixo, não nulo**. Se você precisa de uma garantia formal, retreine com um dataset que possa publicar (sintético ou com consentimento) ou não redistribua os pesos.

### Limitações e uso pretendido
* Detecta marcas semelhantes a assinaturas; pode disparar em rabiscos, carimbos ou logotipos e deixar de detectar assinaturas fracas, pequenas ou incomuns.
* Documentos de outros países/estilos não foram avaliados.
* Não serve para verificação de identidade nem para qualquer uso biométrico.

---

## Resumo (PT-BR)

* **Tarefa:** detecção de **assinaturas manuscritas** em imagens de páginas. **Classe única:** `signature` (o "stamp" do nome é histórico; não há classe de carimbo).
* **Arquitetura:** YOLO11n (nano) do formato Ultralytics, ajustado a partir do `yolo11n.pt` pré-treinado. Treino em 640 px; o app usa `conf=0.25`. Pesos em FP16, ~5,5 MB.
* **Licença:** tratar como **AGPL-3.0** (ferramental e pesos-base da Ultralytics); veja `NOTICE` e `docs/licensing.md`.
* **Dados de treino:** documentos administrativos anotados com a classe `signature`. **Origem, quantidade de imagens/instâncias, tamanho da validação, licença e ferramenta de anotação: não informados** (não constam no checkpoint). Os dados **não** são distribuídos.
* **Treino:** 100 épocas configuradas (paciência 20), batch 8, imgsz 640, CPU, aumentos padrão da Ultralytics, Ultralytics 8.4.31.
* **Métricas registradas (validação, tamanho não informado):** melhor checkpoint mAP50 0,526; mAP50-95 0,132; precisão 1,00; revocação 0,48. Última época: mAP50 0,446. **Acurácia modesta**: cerca de metade das assinaturas pode não ser detectada; a validação parece muito pequena, então os números são ruidosos. O pipeline não depende só deste modelo (OCR de página inteira e LLM de visão também procuram CPFs).
* **Saneamento:** foram removidos do checkpoint original: caminhos absolutos locais (dataset, projeto, execução), bloco git (caminho do repositório, commit, remoto), data do treino, histórico por época e demais metadados. Restaram apenas pesos FP16, arquitetura, nomes de classe e argumentos genéricos. Verificado: carrega com `ultralytics.YOLO`, faz inferência, e a varredura de strings não encontrou caminhos, nomes de usuário, nomes de arquivos de dataset ou datas.
* **Ressalva honesta:** remover metadados **não** torna os pesos matematicamente à prova de extração de dados de treino. Para um detector pequeno de classe única o risco é **baixo, mas não nulo**. Se precisar de garantia formal, retreine com dados publicáveis (sintéticos ou com consentimento) ou não redistribua os pesos.

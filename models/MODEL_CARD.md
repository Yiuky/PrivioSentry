# Model card: `signature_stamp_detector.pt`

*(Português abaixo)*

## Summary (EN)

| | |
|---|---|
| Task | Object detection of **handwritten signatures** on document page images |
| Classes | 1: `signature` (the file name mentions "stamp" for historical reasons; there is **no** stamp class) |
| Architecture | YOLO11n (nano), Ultralytics format; fine-tuned from the pretrained `yolo11n.pt` weights |
| Input | RGB page image; trained at `imgsz=640`; the app calls it with `conf=0.25` |
| Weights precision | FP16 |
| File | ~5.5 MB, inference-only checkpoint (see "Sanitization") |
| Used by | `utils/yolo_engine.py` to crop areas around signatures, which are then audited (OCR + vision LLM) for CPF numbers written by hand |
| License | Treat as **AGPL-3.0** (Ultralytics toolchain and base weights). See [../NOTICE](../NOTICE) and [../docs/licensing.md](../docs/licensing.md) |

### Training data summary
Only what the original checkpoint recorded is reported; everything else is **not informed** (not recorded in the checkpoint and not known to the maintainers of this repository at the time of writing).

* Dataset: scanned/native administrative documents annotated with one class (`signature`). **Source, size (images/instances), split sizes, language, annotation tool and licensing of the data: not informed.** The dataset is **not** distributed and cannot be reconstructed from this file.
* Training run: 100 epochs configured (early-stopping patience 20; 100 epochs were logged), batch size 8, image size 640, CPU training, default Ultralytics augmentation (mosaic 1.0, flip-lr 0.5, HSV jitter, random erasing 0.4, translate 0.1, scale 0.5), optimizer `auto`, seed 0.
* Trained with Ultralytics 8.4.31.

### Metrics (as stored in the checkpoint; validation split, size not informed)
| Metric | Best checkpoint | Last epoch | Best over epochs |
|---|---|---|---|
| mAP@0.5 | 0.526 | 0.446 | 0.546 |
| mAP@0.5:0.95 | 0.132 | 0.113 | 0.132 |
| Precision | 1.000 | 0.569 | 1.000 |
| Recall | 0.482 | 0.500 | 0.750 |

Interpretation: **modest accuracy**. Recall of about 0.5 means roughly half of the signatures may be missed; precision values that swing between 0.57 and 1.0 suggest a **very small validation set**, so these numbers are noisy and should not be generalized. The pipeline does not rely on this model alone (full-page OCR and the vision LLM also look for CPFs), but you should expect misses on unusual signatures. Treat it as a helper for locating signature regions, not as a guarantee. No evaluation on independent or public benchmarks was performed.

### Sanitization (what was removed before publishing)
The original training checkpoint contained, besides the weights: the full `train_args` (including **absolute local paths** of the dataset YAML, project and run folders and the run name), a **git block** with a local repository path, commit hash and remote URL, the **training date**, the per-epoch **training history** (losses, learning rates, metrics), and metadata fields (optimizer/EMA slots were already empty). The published file keeps **only** the FP16 weights, the architecture definition, the class names (`{0: "signature"}`) and minimal generic arguments (`task=detect`, `imgsz=640`). It was verified to load with `ultralytics.YOLO` and run inference, and a scan of the file's strings found no paths, user names, dataset file names or dates.

### Privacy caveat (honest note)
Removing metadata does **not** make the weights mathematically immune to training-data extraction. A detector like this (single class, 2.6 M parameters, no generative or text-memorizing capability) offers a very low risk of reproducing identifiable training documents, but the risk is **low, not zero**. If you require a formal guarantee, retrain with a dataset you can publish (synthetic or consented), or do not redistribute the weights.

### Limitations and intended use
* Detects signature-like marks; may fire on scribbles, stamps or logos and miss faint, small or unusual signatures.
* Documents of other countries/styles were not evaluated.
* Not for identity verification or any biometric use.

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

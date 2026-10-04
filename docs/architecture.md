# Arquitetura

> **PRIVIO SENTRY** (Local AI Privacy Infrastructure) · produto atual: **SENTRY Redact**. Esta página descreve o que existe hoje. Nomes internos de módulos/classes (por exemplo `SentryApp`) e algumas variáveis de ambiente ainda carregam o nome de trabalho anterior "Tarjador"; eles estão sendo renomeados separadamente.

## Disposição dos processos

```
Browser ─► gatekeeper.py (:8000, optional) ──proxy──► app_service.py (:8001, FastAPI)
              start/stop + watchdog                      │  POST /internal/update/{id}   (progress, shared secret)
                                                         └─ multiprocessing.Process per task ─► main.SentryApp
                                                                  ├─ utils/ocr_engine.py     (Tesseract, word-level "grounding map")
                                                                  ├─ utils/yolo_engine.py    (signature detector, Ultralytics)
                                                                  ├─ utils/ai_client.py      (Ollama /api/chat, vision + text)
                                                                  ├─ utils/address_redactor.py (address discovery + matching)
                                                                  ├─ utils/session.py       (folders, logging, PDF reconstruction/native redaction)
                                                                  └─ utils/verifier.py      (post-redaction verification)
```

* **`gatekeeper.py`** (opcional): painel de controle em `:8000` que inicia/para o `app_service.py` como subprocesso, executa um watchdog que o reinicia após falhas repetidas no health check, lembra o estado desejado e faz proxy reverso das demais requisições para a aplicação. Exibe `templates/gatekeeper.html` quando a aplicação está fora do ar.
* **`app_service.py`**: API FastAPI + interface HTML. O estado das tarefas é mantido em memória e persistido de forma atômica em `tasks.json`. Cada upload/reprocessamento/finalização inicia um processo worker; os workers reportam o progresso ao serviço via HTTP com um segredo compartilhado por execução. Um lock de multiprocessing serializa as chamadas ao LLM entre os workers. Operações concorrentes sobre a mesma tarefa retornam `409`.
* **`main.py`** (`SentryApp`): o pipeline, também utilizável como CLI (`python main.py --input ... --output ...`).
* **Editor web** (`templates/index.html`): uma página HTML/JS autocontida (caixas sobrepostas no DOM por cima das imagens das páginas) para inspecionar, adicionar, mover, excluir e aprovar caixas de tarja. Ela é **local-first por construção**: sem fontes, scripts ou bibliotecas de ícones externos (a ajuda em Markdown é renderizada por um pequeno renderizador embutido, não por uma biblioteca de CDN) e o favicon/logo estão embutidos inline. Ela segue os design tokens do PRIVIO SENTRY (`docs/brand/design-tokens.json`), mantém todas as strings da interface em um objeto `I18N` (pt-BR por padrão, en-US disponível) e informa de forma permanente que a detecção por IA é probabilística. O selo **LOCAL PROCESSING** descreve a arquitetura (OCR/modelos rodam na máquina do operador); ele não impõe tecnicamente nenhum estado de rede.

## Fases do pipeline (`SentryApp.run`)

| # | Fase | O que acontece |
|---|---|---|
| 0 | Renderização | Páginas do PDF para PNG em `BASE_DPI` (padrão 300: melhor revocação e mais rápido, ver [benchmarks](benchmarks.md)), com compressão PNG leve. |
| 1 | OCR | Tesseract com coordenadas por palavra (página em duas metades sobrepostas; fallback para uma escala menor quando o Tesseract falha). **Duas passadas por página** (PSM padrão + PSM esparso), mantidas de propósito. As páginas rodam **em paralelo** (`OCR_WORKERS`, threads); a falha do Tesseract é contada por thread (`OCREngine.thread_failures`) e marca a página certa para revisão. Quando o PDF tem texto digital, ele vira uma **terceira leitura** (`grounding_maps_native`). |
| 2 | Descoberta de CPF | Sobre as três leituras: os dígitos são remontados entre palavras/linhas, datas/horários são excluídos, CNPJs de 14 dígitos são poupados, janelas de 11 dígitos são validadas com os dígitos verificadores do CPF; as caixas são calculadas por caractere. |
| 2b | Política (SENTRY Detect) | Demais tipos do perfil `POLICY_PROFILE` ([catálogo](catalogo-pii.md)): regras de `utils/detect/rules.py` sobre as três leituras. *Tarjar* vira tarja sugerida com rótulo do tipo; *alertar* vira região a revisar. Resumo por tipo em `pii_summary`/`pii_found` (só quantidades). |
| 3 | YOLO | Detecta assinaturas; recorta com margem (padding). |
| 4 | Microauditoria dos recortes | OCR (PSM 6) em cada recorte, mapeando as coordenadas de volta para a página. |
| 5 | Descoberta de endereços | O LLM de visão lê cada página e retorna endereços classificados como pessoais/profissionais/secundários. Se a chamada à IA falhar, a página é adicionada a `failed_pages` e marcada para revisão (falha fechado, ou fail closed). |
| 6 | Tarja de endereços | Apenas endereços *pessoais*: cada endereço é localizado como **trecho contínuo** das palavras do OCR (`locate_address_spans`: tolera erro de OCR, palavras partidas e abreviações; exige ao menos 2 partes significativas do endereço). Termos estruturais ("imunes"), conectores, rótulos e datas nunca são tarjados. Endereço não localizado com segurança vira alerta de revisão (falha fechado). |
| 7 | Auditoria de assinaturas | Desenha as tarjas atuais em cada recorte de assinatura e pergunta ao LLM de visão se um CPF ainda está visível; se sim, ou se a IA falhar, o recorte inteiro é tarjado. |
| 8 | Exportação | Grava `redactions_metadata.json` (usado pelo editor) e o PDF final, seja por **tarja nativa** do original (`apply_redactions`, remove o texto e queima os pixels) ou por páginas rasterizadas. A reconstrução falha fechado (página ausente/com erro = nenhum PDF). |
| 9 | Verificação | Veja abaixo. |

## Regiões a revisar, tempos e atualização do editor

* `SentryApp.add_review(página, motivo, boxes)` aceita regiões relativas `[x0, y0, x1, y1]` (0..1, limitadas à página). Elas viajam em `review_marks` no estado da tarefa e o editor as desenha como contorno tracejado ("Revisar aqui"). Vêm da verificação pós-tarja, da cobertura, do decisor de endereços e das ações *alertar* do perfil.
* `timings` guarda os segundos de cada etapa (mostrados no cartão da tarefa).
* O editor consulta `/tasks` a cada 3 s; quando a tarefa aberta termina, recarrega o resultado sozinho, a menos que haja edições não salvas (aí só avisa).
* O decisor local (Laya), se ligado, carrega o modelo em paralelo com a análise de endereços do LLM.

## Verificação e estados

`utils/verifier.py` (a) relê o PDF final (texto nativo + OCR das páginas com imagens/sem texto) e (b) **faz a verificação cruzada da cobertura**: OCR independente do *original* em `VERIFY_DPI`, verificando se cada CPF válido encontrado está dentro de alguma caixa de tarja. Achados, falhas da IA e páginas não verificáveis viram **alertas** por página.

Estados da tarefa (texto de status livre mais um percentual de progresso): `Iniciando...`/`Processando`/mensagens de fase durante a execução, `Concluído` (sem alertas pendentes), **`Requer revisão`** (existem alertas: a revisão humana é obrigatória), um status de erro e `Interrompido` (o processo morreu; definido na inicialização para tarefas órfãs).

## Estrutura de pastas de uma tarefa (`output/<name>/`)

`00_original_images/`, `01_ocr_results/`, `02_signature_crops/`, `04_*`, `05_final_export/{cpf_only,address_only,combined}`, `07_addresses_crops_ia/`, `08_*`, `99_ia_interactions/` (prompts/respostas do LLM), `process_log.log`. **Tudo isso pode conter dados pessoais.** Os PDFs finais vão para `documentos_finais/`.

## API HTTP (app_service)

`GET /` UI · `GET /readme` · `POST /upload` · `GET /tasks` · `POST /reprocess/{id}` · `GET /logs/{id}` · `POST /process-all` · `DELETE /delete-all` · `GET /previews/{id}/{page}` · `GET /metadata/{id}` · `POST /update-redactions/{id}` · `POST /reprocess-metadata/{id}` · `POST /finalize-native/{id}` · `POST /finalize/{id}` (raster legado) · `GET /download/{id}` · `DELETE /task/{id}` · `POST /purge/{id}` (remove as imagens de página não tarjadas após a aprovação) · `POST /internal/update/{id}` (somente workers). Os ids de tarefa são UUIDs e são validados. · `GET /policy/catalog` e `GET /policy/profiles` (catálogo e perfis, só leitura)

## Outros diretórios

* `scripts/` lançadores auxiliares e experimentos manuais; `experimental/agent_loop/` uma abordagem inacabada com agente LLM (não usada pelo pipeline).
* `models/` o detector sanitizado e seu model card; `examples/` gerador de amostras sintéticas.

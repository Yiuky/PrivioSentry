# Configuração

Todas as configurações são variáveis de ambiente, normalmente definidas em um arquivo `.env` na raiz do repositório (carregado com `python-dotenv`). A maior parte também pode ser ajustada na tela **Administração** (`/admin`, ver abaixo), sem editar arquivos. Copie [`.env.example`](../.env.example) para `.env`. Todas as variáveis são opcionais; o **padrão** é o valor usado pelo código quando a variável não está definida. Esta lista foi gerada a partir do código (chamadas a `os.getenv`); se você adicionar uma variável, atualize este arquivo e o `.env.example`.

## Serviço web

| Variável | Padrão | Lida em | Descrição |
|---|---|---|---|
| `APP_HOST` | `127.0.0.1` | `app_service.py`, `gatekeeper.py` | Interface de bind. Use `0.0.0.0` somente junto com `API_TOKEN` e HTTPS na frente. |
| `APP_PORT` | `8001` | `app_service.py`, `gatekeeper.py` | Porta da aplicação; o gatekeeper faz proxy para ela. |
| `API_TOKEN` | *(vazio = sem autenticação)* | `app_service.py`, `gatekeeper.py` (`utils/auth.py`) | Quando definido, todas as rotas do app e o painel do gatekeeper o exigem: cabeçalho `X-API-Token` (scripts) ou sessão do navegador. Para abrir a sessão, acesse uma vez `?token=<token>`: o servidor redireciona para a mesma página **sem** o token e grava um cookie de sessão aleatório (`HttpOnly`, `SameSite=Strict`, `Secure` com HTTPS). O token nunca vai para o cookie e é mascarado nos registros. |
| `ALLOWED_HOSTS` | *(vazio)* | `utils/net_guard.py` (`app_service.py`, `gatekeeper.py`) | Nomes extras aceitos nos cabeçalhos `Host`/`Origin`, separados por vírgula. Loopback (`127.0.0.1`, `localhost`, `::1`) e `APP_HOST` sempre valem. Sem `API_TOKEN`, o app recusa outro `Host` (`421`, proteção contra *DNS rebinding*) e POST/DELETE vindos de outro site (`403`, proteção contra CSRF). O gatekeeper, que não tem token, faz essa checagem sempre: para acessá-lo por outro nome ou IP, liste-o aqui. `*` desliga a checagem (não recomendado). |
| `SESSION_TTL_HOURS` | `12` | `utils/auth.py` | Validade da sessão do navegador aberta com `?token=`. As sessões ficam em memória: reiniciar o serviço pede login de novo. |
| `MAX_UPLOAD_MB` | `500` | `app_service.py` | Tamanho máximo de upload. |
| `PORTAL_ENABLED` | `1` | `app_service.py` | `0` = só API: sem a interface web (`GET /` responde JSON). Ver [api.md](api.md). |
| `ADMIN_ENABLED` | `1` | `app_service.py` | `0` = sem a tela e a API de Administração (`/admin`, `/admin/*`): configuração só pelo `.env`. |
| `PRIVIO_DOC_TEMPLATES_DIR` | `./modelos_documento` | `utils/doc_templates/schema.py` | Pasta dos modelos de documento (JSON). Modelos feitos de documentos reais podem conter texto deles: fora do git e da imagem. |
| `PRIVIO_RUNTIME_DIR` | pasta temporária do sistema | `utils/ai_client.py` | Onde fica o estado do disjuntor da IA, compartilhado entre as tarefas. |
| `PRIVIO_LEARNING_DIR` | `./learning` | `utils/decisions` | Exemplos e perfis do decisor local (ver "Decisor local"). |
| `PRIVIO_SETTINGS_FILE` | `./privio_settings.json` | `utils/settings.py` | Onde a tela Administração guarda o que foi salvo. **Pode conter chaves de API:** fica no `.gitignore`/`.dockerignore` e as chaves nunca voltam pela API. |

### Tela Administração

`/admin` (botão **Administração** na barra lateral do editor) agrupa IA principal e reserva (com atalhos de
provedor, teste de conexão e lista de modelos), detecção e política, OCR e verificação, operação e o guia de API e
agentes (MCP). O valor salvo ali vale sobre o `.env`; **restaurar padrão** volta ao `.env`/código. Itens marcados
"reiniciar" (`MAX_PARALLEL_TASKS`, `MAX_UPLOAD_MB`, `RETENTION_DAYS`) valem depois de reiniciar o serviço; o resto
vale para o próximo documento. Por segurança `API_TOKEN`, `APP_HOST`, `APP_PORT`, `ALLOWED_HOSTS`, `ADMIN_ENABLED`,
`PORTAL_ENABLED` e as pastas só mudam pelo `.env`. Quem acessa o portal acessa a Administração: na rede, use
`API_TOKEN` ou desligue com `ADMIN_ENABLED=0`.

Na interface, **perfil**, **nomes** e **baixa qualidade** podem ser escolhidos **por documento** (painel "Opções do próximo envio"; API: `GET /options` e os campos `perfil`, `nomes`, `baixa_qualidade` do `POST /upload`). As variáveis `POLICY_PROFILE`, `NER_ENGINE`, `SECOND_LOOK` e `OCR_EXTRA_ENGINE` passam a ser os **padrões** desse painel e de envios sem opções.

| `MAX_PARALLEL_TASKS` | `2` | `app_service.py` | Quantos documentos processam ao mesmo tempo. Os demais ficam **"Na fila"** e começam sozinhos quando um termina. Sem limite, vários uploads de uma vez abriam um processo cada (OCR em paralelo + modelos de nomes e decisor) e podiam esgotar memória e CPU. |
| `PRIVIO_INPUT_DIR` | `./WEB_INPUT` | `app_service.py` | Onde os PDFs enviados são armazenados. |
| `PRIVIO_OUTPUT_DIR` | `./output` | `app_service.py`, `utils/session.py` | Artefatos por tarefa: imagens das páginas, resultados de OCR, recortes, logs, metadados de tarja (**contêm dados pessoais**). |
| `PRIVIO_FINAL_DIR` | `./documentos_finais` | `app_service.py`, `utils/session.py` | PDFs finais tarjados. |
| `PRIVIO_TASKS_FILE` | `./tasks.json` | `app_service.py` | Estado das tarefas (JSON, gravado de forma atômica). |
| `GATEKEEPER_PORT` | `8000` | `gatekeeper.py` | Porta do painel opcional de liga/desliga / proxy reverso. |
| `GATEKEEPER_STATE_FILE` | `./.gatekeeper_state` | `gatekeeper.py` | Onde o gatekeeper lembra se a aplicação deve estar em execução. |

## Renderização de PDF e OCR (Tesseract)

| Variável | Padrão | Descrição |
|---|---|---|
| `BASE_DPI` | `300` | DPI usado para renderizar cada página para o OCR. **300 é o recomendado**: nas medições (benchmarks.md) teve a melhor revocação e foi o mais rápido; acima disso o Tesseract quebra os dígitos em pedaços e perde CPFs (a 1000 DPI a revocação caiu para ~60% e cada página vira ~97 Mpx). Suba só para documentos com letra muito pequena, e meça antes. |
| `OCR_EXTRA_ENGINE` | *(vazio)* | Leitura **extra** de OCR somada às duas do Tesseract e ao texto digital: `rapidocr` (modelos PP-OCR latinos em ONNX; `pip install -e ".[ocr-extra]"`). Roda em paralelo ao Tesseract (~1,3 a 3,4 s por página na CPU). **Recomendada.** Medido: em digitalização péssima recuperou e-mails que o Tesseract perdeu; nos documentos reais testados achou um telefone e um e-mail que o Tesseract leu deformados (ficariam sem tarja), ao custo de 2 tarjas a mais numa tabela de números (docs/benchmarks.md). Vem desligada só porque exige instalar o pacote extra. Falha numa página = revisão. |
| `OCR_WORKERS` | metade dos núcleos (até 8) | Quantas páginas passam pelo OCR ao mesmo tempo, nas duas passadas e na verificação. Com `BASE_DPI` acima de 600 o padrão cai para 2 (memória). `1` = uma página por vez. |
| `TESSERACT_PATH` | *(PATH do sistema)* | Caminho completo do executável `tesseract` caso ele não esteja no `PATH` (comum no Windows). |
| `TESSERACT_LANG` | `por` | Idioma(s) do Tesseract, por exemplo `por+eng`. O traineddata precisa estar instalado. |
| `TESSDATA_PREFIX` | *(padrão do Tesseract)* | Pasta com os `*.traineddata`. Lida pelo próprio Tesseract, não pelo código. No Debian/Ubuntu instale `tesseract-ocr-por`; a cópia de trabalho original mantinha uma pasta `tessdata/` de 16 MB, que não faz parte do repositório público. |
| `TESSERACT_STD_PSM` | `3` | Modo de segmentação de página (PSM) para a passada na página inteira. |
| `TESSERACT_SPARSE_PSM` | *(vazio = pular)* | PSM para a segunda passada ("esparsa") na página inteira, por exemplo `11`; ela encontra fragmentos desconexos, como dígitos com ruído. |
| `TESSERACT_CROP_PSM` | `6` | PSM para recortes pequenos (recortes de assinatura, verificação). |

## Servidor de IA (local, da organização ou provedor na nuvem)

O projeto fala com a **API** do servidor de IA, não com um aplicativo específico. Dois tipos:

* `ollama`: a API do Ollama (`/api/chat`).
* `openai`: a API no padrão da OpenAI (`/v1/chat/completions`), oferecida por **LM Studio**, vLLM, llama.cpp
  (`llama-server`), LocalAI e por servidores de IA de organizações (com chave em `AI_API_KEY`).

Pode haver uma **IA reserva** (`AI_SECONDARY_*`), que assume quando a principal cai e, com `AI_CROSS_CHECK=1`,
também confere cada página. Um **disjuntor** "desliga" o servidor que falha seguidamente e o testa de novo pela API
(lista de modelos) depois de um intervalo; o estado é compartilhado entre as tarefas. A rota `GET /health/ai` mostra
os servidores (sem chaves), o disjuntor e o teste de saúde de cada um.

| Variável | Padrão | Descrição |
|---|---|---|
| `AI_PROVIDER` | `ollama` | Tipo do servidor principal: `ollama` ou `openai` (LM Studio, vLLM, llama.cpp, servidor da organização). |
| `AI_BASE_URL` | `OLLAMA_API_URL` (ollama) / `http://localhost:1234/v1` (openai) | Endereço da API. Para `openai`, inclua o `/v1`. |
| `AI_API_KEY` | *(vazio)* | Chave, se o servidor exigir. Nunca vai para log nem para `/health/ai`. |
| `AI_ALLOW_EXTERNAL` | `0` | `1` libera servidor de IA **fora desta rede** (provedor na nuvem com chave de API). Sem isso, a chamada a um destino externo é bloqueada antes de sair e a página vai para revisão. Liberado, **imagens das páginas, recortes de assinatura e o texto lido** são enviados ao provedor; a tarefa registra os destinos (`ia_externa`) e a interface troca o selo por **EXTERNAL AI**. Vale também para o segundo olhar. Ver "IA externa" abaixo. |
| `AI_TEXT_MODEL` / `AI_VISION_MODEL` | `OLLAMA_MODEL` / `OLLAMA_VISION_MODEL` | Modelos de texto e de visão no servidor principal. |
| `AI_TEXT_TIMEOUT` / `AI_VISION_TIMEOUT` | `OLLAMA_*_TIMEOUT` | Tempo limite por chamada no servidor principal. |
| `AI_SECONDARY_PROVIDER`, `AI_SECONDARY_BASE_URL`, `AI_SECONDARY_API_KEY`, `AI_SECONDARY_TEXT_MODEL`, `AI_SECONDARY_VISION_MODEL`, `AI_SECONDARY_TEXT_TIMEOUT`, `AI_SECONDARY_VISION_TIMEOUT` | *(sem reserva)* | O mesmo para a **IA reserva**. Cada servidor tem o próprio tempo limite (medido: com o mesmo limite, a reserva mais lenta também era desligada). |
| `AI_BREAKER_FAILURES` | `3` | Falhas seguidas (sem conexão, tempo esgotado, erro 5xx, resposta sem JSON) que desligam um servidor. |
| `AI_BREAKER_COOLDOWN` | `120` | Segundos desligado antes do teste de saúde pela API. Medido: com a principal travada, a primeira página paga as tentativas e as seguintes vão direto para a reserva (~12 s por página em vez de até 30 min). |
| `AI_LOCK_TIMEOUT` | `3600` | Segundos que uma chamada de IA espera a vez (os documentos usam a IA um de cada vez). Passou disso, a página vai para revisão: um processo morto segurando a vez não prende os outros para sempre. |
| `AI_REQUESTS_PER_MINUTE` | *(automático)* | Limitador: no máximo N pedidos de IA por minuto **por servidor**, somando todos os documentos em processamento (a vez de cada pedido é reservada num estado compartilhado entre os processos). Vazio = automático: `12` num provedor externo (abaixo dos 15 por minuto medidos no plano gratuito do Gemini Flash-Lite) e sem limite nesta rede. `0` = sem limite. O pedido espera a vez: o processamento fica mais lento, mas não é recusado. Com um plano pago de limite maior, aumente. |
| `AI_LIMIT_ACTION` | `revisao` | O que fazer quando o provedor recusa por limite de uso (HTTP 429) e a espera curta não resolve. `revisao`: a página sem IA vai para revisão. `pendente`: o documento inteiro fica **Pendente**, sem PDF, e o serviço o processa de novo sozinho depois (as páginas já lidas são enviadas outra vez). Só no portal/API; na linha de comando (`main.py`) o documento termina com erro. |
| `AI_LIMIT_RETRY_MINUTES` | `60` | Com `pendente`: minutos até a nova tentativa. |
| `AI_LIMIT_MAX_RETRIES` | `24` | Com `pendente`: quantas vezes o documento pode ficar pendente. Depois disso, a tentativa seguinte roda como `revisao` (nunca fica pendente para sempre; ex.: conta sem crédito). |
| `AI_RESET_EVERY` | `0` | A cada N chamadas, pede ao servidor (pela API) para descarregar o modelo: Ollama (`keep_alive: 0`) e LM Studio (`/api/v1/models/unload`). Também acontece quando o disjuntor desliga o servidor. `0` = só no disjuntor. |
| `AI_CROSS_CHECK` | `0` | `1`: a IA reserva também analisa cada página de endereços; as respostas se **somam**, discordância de tipo vira "pessoal" e manda a página para revisão. Dobra o tempo da fase de endereços. |
| `AI_MAX_TOKENS` | `4096` | Limite de tokens da resposta nos servidores `openai`. |
| `ADDRESS_PROMPT` | *(novo)* | `legado` volta ao pedido antigo de endereços (só imagem, "endereço completo e estruturado"). O novo pede para COPIAR do texto da página: nos documentos testados achou 3x mais endereços pessoais, sem inventar. |

### IA externa (provedor na nuvem por chave de API)

Qualquer provedor com API no padrão OpenAI funciona com `AI_PROVIDER=openai`. A tela Administração tem atalhos que
preenchem o endereço:

| Provedor | `AI_BASE_URL` |
|---|---|
| OpenAI | `https://api.openai.com/v1` |
| Anthropic (Claude) | `https://api.anthropic.com/v1` (camada compatível com a API da OpenAI) |
| Google Gemini | `https://generativelanguage.googleapis.com/v1beta/openai` |
| OpenRouter | `https://openrouter.ai/api/v1` |
| Mistral | `https://api.mistral.ai/v1` |

O modelo precisa aceitar **imagens**. O que conta como "fora desta rede" (`utils/egress.py`): qualquer destino que
não seja loopback, IP privado, nome sem ponto, `*.local`/`.lan`/`.internal`/`.intranet`/`.localhost`, ou nome que o
DNS resolve só para IPs privados. Um servidor da organização na intranet continua sem precisar de liberação.
Nome que não resolve conta como externo. Nos provedores externos o sistema não pede para descarregar modelos, a
lista de modelos não é exigida no teste de saúde (apelidos), o erro 429 espera o `Retry-After` (até 30 s) e um erro
400 sobre `max_tokens`/`temperature` (modelos de raciocínio) é repetido uma vez com `max_completion_tokens`.

Antes de usar com documentos reais, valide o provedor e o modelo com o
[procedimento](procedimento-ia-externa.md) (`python -m benchmarks.provider_check`), que usa só dados fictícios.

**Limite de uso (HTTP 429).** O projeto separa dois casos. *Por minuto:* o provedor diz quanto esperar
(`Retry-After` ou `retryDelay`) e cabe em 60 s; a chamada espera e tenta de novo, sem contar como falha no
disjuntor. *Cota esgotada:* limite diário, conta sem crédito, nenhuma indicação de espera, espera acima de 60 s
ou limite por minuto que continuou depois das novas tentativas; aí vale `AI_LIMIT_ACTION`. O processamento
pendente para antes de gerar o PDF e nunca aparece como concluído nem como aprovado (um PDF de um processamento
anterior do mesmo documento, se existir, continua no disco até a nova tentativa). Pendente vale só para
documentos processados pelo serviço: o rascunho de modelo com IA e o teste da Administração não ficam pendentes.

> O que o provedor faz com os dados enviados (retenção, uso para treino, região) depende do **contrato e do plano**
> da sua organização com ele. Confira antes de processar documentos reais; o PRIVIO SENTRY não controla isso.

### Segundo olhar (agente local, opcional)

Um agente curto (instruções enxutas + ferramentas `ler_pagina` e `buscar`, pela API `/v1/chat/completions`) revê as
páginas em dúvida e só pode **acrescentar** proteção: cada valor que ele devolve precisa ser localizado nas palavras
do OCR (o que não existir é descartado), só os tipos do perfil contam, e falha do agente manda a página para revisão.
Medido em docs/benchmarks.md.

| Variável | Padrão | Descrição |
|---|---|---|
| `SECOND_LOOK` | `0` | `1` liga o segundo olhar |
| `SECOND_LOOK_SCOPE` | `revisao` | `revisao`: só páginas que já iam para revisão; `todas`: todas as páginas (mais lento) |
| `SECOND_LOOK_MODEL` | `gemma4:e4b` | Modelo com suporte a ferramentas (medido: melhor custo/benefício) |
| `SECOND_LOOK_BASE_URL` | servidor de IA principal | API no padrão da OpenAI (Ollama: `{url}/v1`; LM Studio: `http://localhost:1234/v1`) |
| `SECOND_LOOK_API_KEY` | *(vazio)* | Chave, se o servidor exigir |
| `SECOND_LOOK_TIMEOUT` / `SECOND_LOOK_MAX_TURNS` | `120` / `6` | Tempo limite por chamada e passos máximos do agente |

Variáveis antigas, ainda aceitas (valem como padrão do servidor principal):

| Variável | Padrão | Descrição |
|---|---|---|
| `OLLAMA_API_URL` | `http://localhost:11434` | URL base do servidor Ollama (`/api/chat` é acrescentado). No Docker use `http://host.docker.internal:11434`. |
| `OLLAMA_MODEL` | `llama3` | Nome do modelo de texto. |
| `OLLAMA_VISION_MODEL` | `gemma4:e4b` | Modelo de visão usado na descoberta de endereços e nas auditorias de CPF manuscrito. Deve ser um modelo multimodal que você já baixou (pull). |
| `OLLAMA_TEXT_TIMEOUT` | `300` | Segundos até uma requisição de texto ser considerada falha (o pipeline então falha fechado, ou fail closed / marca a página). |
| `OLLAMA_VISION_TIMEOUT` | `600` | O mesmo para requisições de visão. |
| `AI_IMAGE_RESOLUTION` | `2048` | Lado máximo da imagem (px) enviada ao modelo de visão (é reduzido ainda mais nas novas tentativas). |
| `AI_CONTEXT_WINDOW` | `32768` | `num_ctx` passado ao Ollama (tokens). Afeta o uso de VRAM. |

## Detector de assinaturas YOLO

| Variável | Padrão | Descrição |
|---|---|---|
| `YOLO_MODEL_PATH` | `models/signature_stamp_detector.pt` | Caminho do detector. Se o arquivo não existir, a fase YOLO é pulada com um aviso (os CPFs próximos a assinaturas passam então a depender apenas do OCR). |
| `YOLO_MODEL_SHA256` | *(vazio)* | SHA-256 esperado para um modelo próprio em `YOLO_MODEL_PATH`. O modelo do repositório é sempre conferido pelo hash fixado em `utils/yolo_engine.py`; um arquivo diferente **não é carregado** (arquivos `.pt` podem executar código ao carregar) e o documento vai para revisão. |
| `YOLO_CROP_PADDING` | `50` | Pixels de contexto adicionados ao redor de cada assinatura detectada antes de auditar o recorte com o modelo de visão. |

## Verificação pós-tarja

| Variável | Padrão | Descrição |
|---|---|---|
| `VERIFY_OCR` | `1` | `1` = faz OCR das páginas do PDF final sem texto nativo e a verificação cruzada com o original; `0` desativa a parte de OCR (não recomendado: apenas a verificação do texto nativo; páginas com imagem ficam sem verificar e vão para revisão). |
| `VERIFY_DPI` | `300` | DPI do OCR de verificação. Mais alto é mais sensível, porém mais lento. |

## Qualidade da saída e retenção de dados

Ambas são lidas em `utils/session.py` e `app_service.py`.

| Variável | Padrão | Descrição |
|---|---|---|
| `FINAL_IMAGE_WIDTH` | `1240` | Largura (px) das páginas no PDF final rasterizado. |
| `FINAL_JPEG_QUALITY` | `75` | Qualidade JPEG (1-95; valores fora do intervalo voltam ao padrão) dessas páginas. |
| `RETENTION_DAYS` | `0` (desativado) | Na inicialização, exclui tarefas (e todos os seus artefatos) com mais de N dias; `0`/não definido mantém tudo. `POST /purge/{id}` remove sob demanda as imagens originais das páginas de uma tarefa. Sempre exclua `output/` quando terminar: ele contém imagens das páginas e texto de OCR com dados pessoais. |

## Modelos de documento

Guia completo: [modelos-documento.md](modelos-documento.md).

| Variável | Padrão | Descrição |
|---|---|---|
| `DOC_TEMPLATES` | `1` | Reconhece documentos de layout conhecido pelos modelos salvos e tarja os campos deles, sem IA. `0` desliga. |
| `DOC_TEMPLATE_INSPECTION` | `agente` | Inspeção depois das tarjas nas páginas do documento reconhecido. `agente`: o agente do segundo olhar (`SECOND_LOOK_*`, padrão: a IA principal) lê o texto **já tarjado** e aponta o que ficou de fora; falha vira revisão. `regras`: zero token, só rótulos com valor sem tarja; página em que a IA de visão foi dispensada vai sempre para revisão. |

## Política de dados pessoais

Detalhes no [catálogo de PII](catalogo-pii.md).

| Variável | Padrão | Lida em | Descrição |
|---|---|---|---|
| `POLICY_PROFILE` | `cpf_endereco` | `utils/detect/profiles.py` | Perfil de política: `cpf_endereco` (original), `lgpd_publicacao`, `lgpd_interno`, `gdpr`, `saude_hipaa`. Define o que é tarjado e o que só é alertado. Valor desconhecido volta ao padrão. |
| `NER_ENGINE` | *(vazio)* | `utils/detect/ner.py` | `gliner` liga o detector local de **nomes de pessoa e filiação** (exige `pip install -e ".[nomes]"`). Vale nos perfis que pedem nomes (`lgpd_publicacao`, `gdpr`, `saude_hipaa`). Ligado e com falha = documento vai para revisão. Perfil que pede nomes com a busca desligada ou sem o GLiNER instalado = todas as páginas vão para revisão ("Nomes de pessoa não foram procurados") |
| `NER_MODEL` | `urchade/gliner_multi_pii-v1` | `utils/detect/ner.py` | Modelo GLiNER do Hugging Face ou pasta local |
| `NER_MODEL_REVISION` | *(commit fixado no código)* | `utils/detect/ner.py` | Commit do modelo. O padrão já vem fixado; outro modelo remoto **exige** um commit (cadeia de suprimentos) |

Instalar `.[nomes]` pode ajustar a versão do `transformers` (exigência do GLiNER); o decisor Laya funciona com ela.
Medido com o modelo padrão na CPU: ~0,3 s por página e ~20 s para carregar o modelo uma vez.

### Regras, listas e limiares como dados

As palavras e limiares das heurísticas ficam em arquivos versionados, validados ao carregar (erro claro se o formato
estiver errado), e não espalhados pelo código:

| Arquivo | O que guarda |
|---|---|
| `utils/detect/data/contextos.json` | Palavras de contexto de cada detector (`palavras`, `parar`), variantes de "@" que o OCR produz e extensões de domínio do e-mail, rótulos e palavras de filiação do detector de nomes |
| `utils/detect/data/parametros.json` | Limiares: casamento de endereços, filtro de ruído de OCR, confiança dos nomes (`limiar_tarjar`, `limiar_alertar`) e quando sugerir algo a partir do retorno do revisor |
| `utils/detect/data/lexico.json` | Palavras que nunca são tarjadas como endereço (termos estruturais e conectores) |

Mudou um arquivo? Rode `python -m benchmarks.pii_eval` (revocação e precisão por tipo num corpus fictício) e os testes:
a mudança precisa manter ou melhorar as métricas ([benchmarks.md](benchmarks.md)).

## Decisor local e automelhoramento (opcional)

Detalhes em [decisions.md](decisions.md). Exige `pip install -e ".[laya]"`.

| Variável | Padrão | Lida em | Descrição |
|---|---|---|---|
| `DECISION_ENGINE` | `off` | `utils/decisions/engine.py` | `laya` liga o decisor local de endereços; `off` desliga |
| `DECISION_MODE` | `shadow` | `utils/decisions/engine.py` | `shadow` só observa e registra; `assist` participa (só com perfil aprovado; nunca reduz proteção) |
| `LAYA_MODEL` | `convaiinnovations/laya-multilingual` | `utils/decisions/engine.py` | Modelo do Hugging Face ou pasta local |
| `LAYA_DEVICE` | `cpu` | `utils/decisions/engine.py` | `cpu` ou `cuda` |
| `LAYA_REVISION` | *(vazio)* | pacote `laya` | Commit fixo do modelo; `reviewed` usa os commits revisados pelo Laya |
| `LEARNING_ENABLED` | `0` | `utils/decisions/feedback.py` | `1` guarda as correções do revisor como exemplos de treino e as **contagens por detector** (tarjas sugeridas mantidas, removidas e acrescentadas; nenhum texto) vistas em `python -m utils.decisions detectores` |
| `PRIVIO_LEARNING_DIR` | `./learning` | `utils/decisions/learning.py` | Exemplos, cache e perfis versionados (**contém palavras de endereços**; fora do git) |

## Logging

| Variável | Padrão | Descrição |
|---|---|---|
| `DEBUG_LEVEL` | `INFO` | Nível de logging do Python (`DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`). `DEBUG` pode ser verboso; nunca compartilhe logs de documentos reais. |

## Interno

`OMP_NUM_THREADS` e `MKL_NUM_THREADS` são definidos como `4` pelo `main.py` para limitar o uso de CPU. O `main.py` também aceita `--input` / `--output` na linha de comando.

## Docker

A imagem define `APP_HOST=0.0.0.0`, `PRIVIO_TASKS_FILE=/app/state/tasks.json` e `YOLO_MODEL_PATH`; o `docker-compose.yml` publica a porta somente em `127.0.0.1` e define `OLLAMA_API_URL` apontando para o host. Não copie um `.env` do Windows (com `TESSERACT_PATH=C:\...`) para dentro de um contêiner: remova essas linhas.

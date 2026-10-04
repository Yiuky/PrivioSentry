# Configuração

Todas as configurações são variáveis de ambiente, normalmente definidas em um arquivo `.env` na raiz do repositório (carregado com `python-dotenv`). Copie [`.env.example`](../.env.example) para `.env`. Todas as variáveis são opcionais; o **padrão** é o valor usado pelo código quando a variável não está definida. Esta lista foi gerada a partir do código (chamadas a `os.getenv`); se você adicionar uma variável, atualize este arquivo e o `.env.example`.

## Serviço web

| Variável | Padrão | Lida em | Descrição |
|---|---|---|---|
| `APP_HOST` | `127.0.0.1` | `app_service.py`, `gatekeeper.py` | Interface de bind. Use `0.0.0.0` somente junto com `API_TOKEN` e HTTPS na frente. |
| `APP_PORT` | `8001` | `app_service.py`, `gatekeeper.py` | Porta da aplicação; o gatekeeper faz proxy para ela. |
| `API_TOKEN` | *(vazio = sem autenticação)* | `app_service.py` | Quando definido, todas as rotas o exigem: header `X-API-Token`, cookie `api_token` ou `?token=` (a forma via query string pode vazar em logs/histórico; prefira o header/cookie). |
| `ALLOWED_HOSTS` | *(vazio)* | `utils/net_guard.py` (`app_service.py`, `gatekeeper.py`) | Nomes extras aceitos nos cabeçalhos `Host`/`Origin`, separados por vírgula. Loopback (`127.0.0.1`, `localhost`, `::1`) e `APP_HOST` sempre valem. Sem `API_TOKEN`, o app recusa outro `Host` (`421`, proteção contra *DNS rebinding*) e POST/DELETE vindos de outro site (`403`, proteção contra CSRF). O gatekeeper, que não tem token, faz essa checagem sempre: para acessá-lo por outro nome ou IP, liste-o aqui. `*` desliga a checagem (não recomendado). |
| `MAX_UPLOAD_MB` | `500` | `app_service.py` | Tamanho máximo de upload. |
| `PRIVIO_INPUT_DIR` | `./WEB_INPUT` | `app_service.py` | Onde os PDFs enviados são armazenados. |
| `PRIVIO_OUTPUT_DIR` | `./output` | `app_service.py`, `utils/session.py` | Artefatos por tarefa: imagens das páginas, resultados de OCR, recortes, logs, metadados de tarja (**contêm dados pessoais**). |
| `PRIVIO_FINAL_DIR` | `./documentos_finais` | `app_service.py`, `utils/session.py` | PDFs finais tarjados. |
| `PRIVIO_TASKS_FILE` | `./tasks.json` | `app_service.py` | Estado das tarefas (JSON, gravado de forma atômica). |
| `GATEKEEPER_PORT` | `8000` | `gatekeeper.py` | Porta do painel opcional de liga/desliga / proxy reverso. |
| `GATEKEEPER_STATE_FILE` | `./.gatekeeper_state` | `gatekeeper.py` | Onde o gatekeeper lembra se a aplicação deve estar em execução. |

## Renderização de PDF e OCR (Tesseract)

| Variável | Padrão | Descrição |
|---|---|---|
| `BASE_DPI` | `1000` | DPI usado para renderizar cada página para o OCR. Valores altos ajudam com texto pequeno, mas exigem muita RAM e tempo; 300-600 é um bom ponto de partida em máquinas modestas. |
| `TESSERACT_PATH` | *(PATH do sistema)* | Caminho completo do executável `tesseract` caso ele não esteja no `PATH` (comum no Windows). |
| `TESSERACT_LANG` | `por` | Idioma(s) do Tesseract, por exemplo `por+eng`. O traineddata precisa estar instalado. |
| `TESSDATA_PREFIX` | *(padrão do Tesseract)* | Pasta com os `*.traineddata`. Lida pelo próprio Tesseract, não pelo código. No Debian/Ubuntu instale `tesseract-ocr-por`; a cópia de trabalho original mantinha uma pasta `tessdata/` de 16 MB, que não faz parte do repositório público. |
| `TESSERACT_STD_PSM` | `3` | Modo de segmentação de página (PSM) para a passada na página inteira. |
| `TESSERACT_SPARSE_PSM` | *(vazio = pular)* | PSM para a segunda passada ("esparsa") na página inteira, por exemplo `11`; ela encontra fragmentos desconexos, como dígitos com ruído. |
| `TESSERACT_CROP_PSM` | `6` | PSM para recortes pequenos (recortes de assinatura, verificação). |

## LLM local (Ollama)

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
| `YOLO_CROP_PADDING` | `50` | Pixels de contexto adicionados ao redor de cada assinatura detectada antes de auditar o recorte com o modelo de visão. |

## Verificação pós-tarja

| Variável | Padrão | Descrição |
|---|---|---|
| `VERIFY_OCR` | `1` | `1` = faz OCR das páginas do PDF final sem texto nativo e a verificação cruzada com o original; `0` desativa a parte de OCR (não recomendado: apenas a verificação do texto nativo). |
| `VERIFY_DPI` | `300` | DPI do OCR de verificação. Mais alto é mais sensível, porém mais lento. |

## Qualidade da saída e retenção de dados

Ambas são lidas em `utils/session.py` e `app_service.py`.

| Variável | Padrão | Descrição |
|---|---|---|
| `FINAL_IMAGE_WIDTH` | `1240` | Largura (px) das páginas no PDF final rasterizado. |
| `FINAL_JPEG_QUALITY` | `75` | Qualidade JPEG (1-95; valores fora do intervalo voltam ao padrão) dessas páginas. |
| `RETENTION_DAYS` | `0` (desativado) | Na inicialização, exclui tarefas (e todos os seus artefatos) com mais de N dias; `0`/não definido mantém tudo. `POST /purge/{id}` remove sob demanda as imagens originais das páginas de uma tarefa. Sempre exclua `output/` quando terminar: ele contém imagens das páginas e texto de OCR com dados pessoais. |

## Decisor local e automelhoramento (opcional)

Detalhes em [decisions.md](decisions.md). Exige `pip install -e ".[laya]"`.

| Variável | Padrão | Lida em | Descrição |
|---|---|---|---|
| `DECISION_ENGINE` | `off` | `utils/decisions/engine.py` | `laya` liga o decisor local de endereços; `off` desliga |
| `DECISION_MODE` | `shadow` | `utils/decisions/engine.py` | `shadow` só observa e registra; `assist` participa (só com perfil aprovado; nunca reduz proteção) |
| `LAYA_MODEL` | `convaiinnovations/laya-multilingual` | `utils/decisions/engine.py` | Modelo do Hugging Face ou pasta local |
| `LAYA_DEVICE` | `cpu` | `utils/decisions/engine.py` | `cpu` ou `cuda` |
| `LAYA_REVISION` | *(vazio)* | pacote `laya` | Commit fixo do modelo; `reviewed` usa os commits revisados pelo Laya |
| `LEARNING_ENABLED` | `0` | `utils/decisions/feedback.py` | `1` guarda as correções do revisor como exemplos de treino |
| `PRIVIO_LEARNING_DIR` | `./learning` | `utils/decisions/learning.py` | Exemplos, cache e perfis versionados (**contém palavras de endereços**; fora do git) |

## Logging

| Variável | Padrão | Descrição |
|---|---|---|
| `DEBUG_LEVEL` | `INFO` | Nível de logging do Python (`DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`). `DEBUG` pode ser verboso; nunca compartilhe logs de documentos reais. |

## Interno

`OMP_NUM_THREADS` e `MKL_NUM_THREADS` são definidos como `4` pelo `main.py` para limitar o uso de CPU. O `main.py` também aceita `--input` / `--output` na linha de comando.

## Docker

A imagem define `APP_HOST=0.0.0.0`, `PRIVIO_TASKS_FILE=/app/state/tasks.json` e `YOLO_MODEL_PATH`; o `docker-compose.yml` publica a porta somente em `127.0.0.1` e define `OLLAMA_API_URL` apontando para o host. Não copie um `.env` do Windows (com `TESSERACT_PATH=C:\...`) para dentro de um contêiner: remova essas linhas.

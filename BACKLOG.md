# Backlog do PRIVIO SENTRY

Backlog vivo para o mantenedor e para **outros modelos de IA / desenvolvedores**. Antes de pegar um item,
leia o [AGENTS.md](AGENTS.md): invariantes, arquitetura e como rodar os testes.

**Como usar este arquivo**
- Cada item tem um ID estável. Não reutilize nem renumere IDs.
- Ao iniciar um item, mude o status para `EM ANDAMENTO (<quem>, <data>)`.
- Ao concluir, mova-o para **Concluídos** com a versão, o commit e o teste que o cobre.
- Todo item concluído precisa de teste automatizado em `tests/` ou, se depender de Tesseract/Ollama reais, de
  uma entrada no checklist manual (seção **V**).
- Prioridade: **P0** (vazamento de dado ou segurança) · **P1** (resultado errado ou tarja a menos) ·
  **P2** (robustez, operação e experiência) · **P3** (melhoria e refatoração).
- Itens marcados como **visão** vêm do roteiro do produto: não têm data nem promessa de entrega.
- As referências `arquivo:linha` valem para o estado de referência e podem se deslocar.
- Estado de referência: `5.1.0`, 2026-10-04. Itens B-40 a B-65 vieram de uma revisão completa do código e da redação do manual nessa data.

## Resumo

| Prioridade | Abertos | Foco |
|---|---|---|
| 🔴 P0 | 3 | Proteger o serviço local contra outros sites no mesmo navegador e o token de acesso |
| 🟠 P1 | 15 | Falhar fechado em mais situações (OCR, respostas da IA, tarjas manuais, rotação) |
| 🟡 P2 | 12 | Robustez dos processos, limites de recursos, Docker e editor |
| 🔵 P3 | 5 | Limpeza de código, lint e marca |
| 🔭 Visão | 5 | Auditoria, políticas e novos módulos SENTRY |

---

## V. Validação manual pendente

Pontos que dependem de Tesseract, Ollama ou sistemas reais e ainda não têm roteiro automatizado. Faça antes de
publicar uma versão que mexa nessas áreas:

| ID | Verificar | Onde |
|---|---|---|
| V-01 | Fluxo completo com o exemplo sintético e um modelo de visão real do Ollama (`examples/make_sample_pdf.py` → web → editor → tarja nativa → download): CPF e endereço residencial tarjados, endereço comercial preservado | `main.py`, `templates/index.html` |
| V-02 | `docker compose up --build` no Linux com o Ollama no host: upload, processamento e download | `Dockerfile`, `docker-compose.yml` |
| V-03 | Windows: `scripts\run_app.bat`, `scripts\run_gatekeeper.bat` e `scripts\PERSISTENCE_SERVICE.bat` (liga/desliga e reinício pelo *watchdog*) | `scripts/`, `gatekeeper.py` |
| V-04 | Interface exposta com `APP_HOST=0.0.0.0` + `API_TOKEN` atrás de um proxy HTTPS | `app_service.py` |
| V-05 | PDF com páginas rotacionadas (90/180/270°) e PDF digitalizado com texto nativo parcial (ver B-49, B-50) | `utils/session.py`, `utils/verifier.py` |

---

## 🔴 P0 · Segurança e vazamento

| ID | Item | Referência |
|---|---|---|
| B-40 | **Validar `Host` e `Origin` no serviço local.** Sem `API_TOKEN` (o padrão), uma página maliciosa aberta no mesmo navegador pode, via *DNS rebinding*, ler `/tasks`, `/previews` (imagens originais sem tarja) e `/download`, e disparar POSTs simples entre origens (`/process-all`, `/upload`, `/purge`). Direção: `TrustedHostMiddleware` (`127.0.0.1`/`localhost`) e exigir `Origin` igual ou um *header* próprio nas rotas que alteram estado; documentar no modelo de ameaças | `app_service.py:236-246`, `docs/threat-model-lgpd.md` |
| B-41 | **Não aceitar `API_TOKEN` na *query string* nem guardar o token bruto em cookie.** `?token=` vai para o log do uvicorn, o histórico do navegador e o log do proxy do gatekeeper. Direção: trocar por cookie de sessão aleatório (`HttpOnly`, `SameSite`, `secure` com HTTPS), redirecionar sem o `?token=` e mascarar a *query* nos logs | `app_service.py:239-244`, `gatekeeper.py:205-234` |
| B-42 | **Proteger `/api/toggle` do gatekeeper e restringir `kill_port_owner`.** Qualquer site desliga o serviço com um POST `text/plain`; `kill_port_owner` faz `taskkill /F /T` em qualquer processo na porta. Direção: exigir token/`Origin` e encerrar só o processo filho conhecido | `gatekeeper.py:88-102`, `gatekeeper.py:189-198` |

## 🟠 P1 · Resultado errado ou tarja a menos

| ID | Item | Referência |
|---|---|---|
| B-43 | **Falhar fechado quando o Tesseract falha ou não está instalado.** Se o OCR falhar nas duas escalas, o motor devolve resultado vazio: nenhum CPF é encontrado, a verificação usa o mesmo motor e o documento pode terminar como "Concluído". Direção: propagar a falha como alerta da página (`add_review`) e checar pré-requisitos (versão, idioma `por`, modelo YOLO) no início do serviço e da CLI | `utils/ocr_engine.py:43-46`, `utils/verifier.py:71-72`, `main.py:224-229` |
| B-44 | **Descartar ou conciliar `manual_redactions.json` ao reprocessar.** O reprocessamento mantém as tarjas manuais antigas, que têm prioridade sobre as novas detecções da IA | `app_service.py:354-372`, `app_service.py:431-442` |
| B-45 | **Não baixar automaticamente o PDF nativo quando a tarefa "Requer revisão".** O *polling* redireciona para `/download` ao ver `percentage === 100`, sem olhar `needs_review` (que chega depois) | `templates/index.html:1083-1089`, `main.py:116-117` |
| B-46 | **Não servir PDF final desatualizado.** `/download` entrega qualquer PDF final no disco, inclusive o da execução anterior durante um reprocessamento ou após falha. Direção: gravar em temporário, `os.replace` após a verificação e servir só com estado coerente | `app_service.py:492-512`, `utils/session.py:398-471` |
| B-47 | **Validar o esquema das tarjas manuais e falhar fechado ao descartar uma.** `/update-redactions` aceita qualquer lista e grava sem escrita atômica; caixas malformadas ou fora do intervalo são descartadas só com log. Direção: modelo Pydantic (422), gravação atômica e `add_review` | `app_service.py:437-458`, `main.py:456-470`, `utils/session.py:434-436` |
| B-48 | **Validar o esquema das respostas da IA.** Na auditoria de assinaturas, resposta que não é dict é ignorada e dict sem `unredacted_cpfs` conta como "limpo"; na descoberta de endereços, resposta sem `addresses` vira "0 endereços". Direção: resposta fora do esquema = falha → revisão e tarja de emergência | `main.py:369-424`, `utils/address_redactor.py:65` |
| B-49 | **Normalizar a classificação "pessoal" dos endereços.** O filtro compara `type == "pessoal"` exatamente; "Pessoal", "residencial" ou espaços extras deixam endereços pessoais sem tarja e sem alerta. Direção: normalizar (caixa, acento, espaços), aceitar sinônimos e mandar tipo desconhecido para revisão | `utils/address_redactor.py:85`, `main.py:291` |
| B-50 | **Marcar como "não verificada" a página com imagem quando `VERIFY_OCR=0`.** Página digitalizada com algum texto nativo não passa por OCR e também não entra em `unverified` | `utils/verifier.py:63-79`, `tests/test_verifier_extra.py:71-81` |
| B-51 | **Tratar páginas rotacionadas e a escala de DPI na tarja nativa e na verificação.** As caixas vêm da imagem renderizada (já rotacionada) e vão direto para `add_redact_annot`; o *fallback* de escala usa 1000 DPI fixo. Direção: `page.derotation_matrix`, usar `BASE_DPI` e testes com `/Rotate` 90/180/270 (V-05) | `utils/session.py:439-456`, `utils/verifier.py:109-130` |
| B-61 | **Alertas sem página não colocam a tarefa em "Requer revisão".** "Modelo YOLO ausente" e os "Protocolos de Pânico" vão para `self.alerts` sem `add_review`, então a tarefa pode ficar "Concluído" com ⚠. Direção: todo alerta exige revisão (página 0 = documento inteiro) | `main.py:56-78`, `main.py:224-229`, `main.py:286-288`, `main.py:408-410` |
| B-62 | **Manter os alertas anteriores ao "Aplicar proteção".** O estado final da tarja nativa vem só da nova verificação; uma falha anterior da IA some e a tarefa pode virar "Concluído". Direção: herdar os alertas não resolvidos até o revisor marcá-los como conferidos | `main.py:472-484`, `app_service.py:468-490` |
| B-63 | **Deixar claro que o PDF automático é preliminar.** O processamento já grava um PDF raster com as sugestões da IA e libera *Ver/Baixar PDF* antes de qualquer revisão. Direção: rotular como "preliminar" na interface e no nome do arquivo, ou liberar o download só após "Aplicar proteção" | `main.py:485-567`, `templates/index.html` |
| B-01 | Medir revocação e precisão em um conjunto **realista** (carimbos, manuscritos, fotos de papel, tabelas), montado só com documentos fictícios | [docs/benchmarks.md](docs/benchmarks.md) |
| B-02 | Detector de assinaturas: treinar/avaliar um modelo melhor e documentar métricas no model card | [models/MODEL_CARD.md](models/MODEL_CARD.md) |
| B-03 | Endereços: reduzir tarja a mais/a menos do casamento por *tokens* com o OCR | `utils/address_redactor.py`, `utils/lexicon.py` |

## 🟡 P2 · Robustez, operação e experiência

| ID | Item | Referência |
|---|---|---|
| B-52 | **Drenar ou redirecionar stdout/stderr do app no gatekeeper.** O app é aberto com `PIPE` que nunca é lido; quando o buffer enche, o app trava, o *watchdog* o mata e as tarefas ficam "Interrompidas". Direção: `DEVNULL`, arquivo de log ou thread leitora | `gatekeeper.py:114-120` |
| B-53 | **Detectar a morte do worker e permitir cancelar tarefas.** Worker morto (OOM, *kill*) deixa a tarefa parada para sempre; não há rota de cancelamento nem encerramento dos workers no desligamento. Direção: monitorar `exitcode`, `POST /cancel/{id}` e *lifespan* | `app_service.py:96-105`, `app_service.py:205-264` |
| B-54 | **Limitar recursos por documento e fechar *handles*.** `Image.MAX_IMAGE_PIXELS = None` desliga a proteção contra bombas de descompressão; não há limite de páginas nem de pixels; documentos `fitz` e *FileHandlers* da CLI não são fechados em exceção | `utils/session.py:12`, `utils/transform_pdf_to_img.py:21-61`, `main.py:647-662` |
| B-55 | **Tirar o I/O bloqueante do upload do *event loop* e fazer o proxy repassar o corpo em *streaming*.** Uploads grandes bloqueiam o loop (inclusive o `/internal/update` dos workers) e falham pelo gatekeeper (corpo inteiro em memória, *timeout* de 30 s) | `app_service.py:302-329`, `gatekeeper.py:210-222` |
| B-56 | **Corrigir o `HEALTHCHECK` do Docker e fixar a versão do torch.** O *healthcheck* acessa `/`, que devolve 401 com `API_TOKEN`; `torch`/`torchvision` sem versão fixa. Direção: rota `/healthz` sem token, versões fixas e *build* da imagem no CI | `Dockerfile:24`, `Dockerfile:40-41` |
| B-57 | **Editor: desfazer, exclusão segura, teclado/toque e aviso de edições não salvas.** O "×" apaga a tarja sem confirmação nem desfazer (risco de tarja a menos); desenhar/mover só com mouse; sem `beforeunload`. Direção: Ctrl+Z, Del com foco, *pointer events*, *autosave* ou aviso | `templates/index.html:902-1006` |
| B-64 | **"Recarregar sugestões da IA" também apaga as edições salvas** (`manual_redactions.json`), não só as não salvas como diz a confirmação. Direção: ajustar o texto ou arquivar a versão anterior | `templates/index.html`, `app_service.py` |
| B-65 | **Expor na interface a remoção das imagens originais** (`POST /purge/{id}`), hoje só pela API | `app_service.py:420-429` |
| B-10 | Tarja nativa: remover ou sinalizar metadados, anexos, anotações, campos de formulário e camadas ocultas que sobrevivem à tarja | [docs/limitations.md](docs/limitations.md) (Saída) |
| B-11 | Aviso na interface quando `OLLAMA_API_URL` não aponta para `localhost` | [docs/limitations.md](docs/limitations.md) (Plataforma) |
| B-12 | Desempenho em PDFs grandes (centenas de páginas): perfis de DPI, paralelismo do OCR fora do `AI_LOCK` | [docs/limitations.md](docs/limitations.md) (Desempenho) |
| B-59 | Publicar a imagem Docker (GHCR) na Release, respeitando a ressalva de licenciamento | [docs/licensing.md](docs/licensing.md), `.github/workflows/release.yml` |

## 🔵 P3 · Refatoração e manutenção

| ID | Item | Referência |
|---|---|---|
| B-58 | **Remover código e configuração mortos e alinhar a documentação.** O ramo `FALLBACK_ALL` de endereços nunca é produzido; `analyze_text`/`OLLAMA_MODEL` não são usados pelo pipeline, mas a documentação diz que o modelo de texto faz a descoberta de endereços (é o de visão); o parâmetro `force` do upload e o fluxo `status === 'confirm'` da interface não existem no servidor | `main.py:285-304`, `utils/ai_client.py:58`, `docs/configuration.md`, `.env.example`, `templates/index.html:1107-1111` |
| B-20 | Renomear os nomes internos legados "Tarjador" (logger `AppTarjadorService` e variáveis de ambiente antigas) mantendo compatibilidade | [docs/architecture.md](docs/architecture.md) |
| B-21 | Endurecer o lint: remover aos poucos as exceções "legadas" do Ruff (`W291`–`W293`, `E722`, `B007`, `B905`) | `pyproject.toml` |
| B-22 | Decidir o destino de `experimental/agent_loop/` (integrar com testes ou remover) | [experimental/README.md](experimental/README.md) |
| B-23 | Pesquisa de anterioridade da marca PRIVIO SENTRY | [TRADEMARKS.md](TRADEMARKS.md) |

## 🔭 Visão (sem data)

| ID | Item | Referência |
|---|---|---|
| B-30 | **Trilha de auditoria** (SENTRY Audit): hashes e proveniência de modelo/política sem guardar valores sensíveis | [docs/brand/LGPD_PRODUCT_POSITIONING.md](docs/brand/LGPD_PRODUCT_POSITIONING.md) |
| B-31 | **Motor de políticas** configurável (o que detectar e como proteger) | idem |
| B-32 | Novos tipos de dado (SENTRY Detect): nomes, telefones, e-mails, RG, dados bancários | [docs/limitations.md](docs/limitations.md) |
| B-33 | Mascaramento e pseudonimização (SENTRY Mask / Transform) | [README.md](README.md#-visão-futuro-não-implementado) |
| B-34 | Fronteira de privacidade para IAs/APIs externas (SENTRY Gateway) | idem |

---

## Concluídos

| ID | Item | Versão | Teste |
|---|---|---|---|
| B-60 | Auditoria de dados pessoais em todo PR (CI) e Ruff com versão fixa | não publicado | `.github/workflows/ci.yml` (passo *Auditoria*) |
| B-13 | Releases versionadas (tag `vX.Y.Z` + notas do CHANGELOG) e versão alinhada em `pyproject.toml`/`CITATION.cff` | 5.1.0 | `tests/test_check_versions.py` |
| — | CI verde: coleta restrita a `tests/` e teste do gatekeeper que simula Windows passa no Linux | 5.1.0 | `pytest.ini`, `tests/test_gatekeeper.py` |
| — | Interface local-first (sem CDN), pt-BR/en-US, WCAG AA | 5.1.0 | `tests/ui/test_ui_brand.py`, `tests/ui/test_ui_security_a11y.py` |
| — | Pipeline falha fechado com o estado "Requer revisão" | 5.0.0 | `tests/test_fail_closed.py` |
| — | Verificação pós-tarja contra o original | 5.0.0 | `tests/test_verifier.py`, `tests/test_verifier_extra.py` |

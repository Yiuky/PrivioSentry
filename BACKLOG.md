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
- Estado de referência: `5.3.0`, 2026-10-04. Itens B-40 a B-65 vieram de uma revisão completa do código e da redação do manual nessa data.

## Resumo

| Prioridade | Abertos | Foco |
|---|---|---|
| 🔴 P0 | 0 | Proteger o serviço local contra outros sites no mesmo navegador e o token de acesso |
| 🟠 P1 | 13 | Falhar fechado em mais situações (OCR, respostas da IA, tarjas manuais, rotação) |
| 🟡 P2 | 11 | Robustez dos processos, limites de recursos, Docker e editor |
| 🔵 P3 | 5 | Limpeza de código, lint e marca |
| 🧠 Roteiro | 9 | Detecção configurável (nomes, telefones, RG...), GLiNER e decisor Laya que aprende (B-71 a B-79) |
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

## 🧠 Detecção configurável e decisor que aprende (roteiro)

Objetivo: o usuário escolhe **o que tarjar** (inclusive nomes), com recurso mínimo (modo leve, sem GPU),
tudo local, e o sistema **melhora com as correções do revisor** sem nunca reduzir a proteção sozinho.
Arquitetura: `detectar (regras + GLiNER + LLM) → decidir (Laya) → revisão → tarja`. Guia do decisor:
[docs/decisions.md](docs/decisions.md).

| ID | Prioridade | Item | Depende de |
|---|---|---|---|
| B-71 | P1 | **Política configurável**: o usuário escolhe os tipos (CPF, endereço, nome, telefone, e-mail, RG...) na interface e na CLI; arquivo de política versionado; registrar qual política foi aplicada em cada tarefa | — |
| B-72 | P1 | **Novos tipos por regras com validação**: RG, CNH, PIS/NIS, título de eleitor, telefone, e-mail, CEP, placa, cartão (dígito verificador quando houver), com testes e casos falsos positivos conhecidos | B-71 |
| B-73 | P1 | **Nomes e rótulos livres com GLiNER** (modo leve na CPU): o usuário escreve o rótulo ("nome de pessoa", "número de processo"); trechos mapeados para as caixas do OCR; confiança baixa → revisão | B-71 |
| B-74 | P2 | **Exceções decididas pelo Laya**: "nome a proteger" × "servidor/signatário público" (LAI), com perguntas próprias, treino e portão | B-73, B-70 |
| B-75 | P2 | **Perfis de política e roteamento**: perfis prontos (Transparência/LAI, Saúde, Jurídico, Só CPF) e o Laya sugerindo o perfil pelo tipo de documento | B-71, B-70 |
| B-76 | P2 | **Ajuste fino dos pesos do Laya** (hoje só a cabeça e os limiares são treinados): quando houver rotina pública de treino, ou com treinador próprio + LoRA, sempre com o mesmo portão | B-70 |
| B-77 | P2 | **Painel de aprendizado na interface**: modo atual, perfil ativo e métricas, botão de treinar e de voltar versão, contador de correções guardadas | B-70 |
| B-78 | P1 | **Avaliação realista do decisor**: conjunto fictício mais difícil que o sintético (endereços ambíguos, OCR ruidoso) para o portão de qualidade | B-70, B-01 |
| B-79 | P3 | **Instalação offline e mais rápida**: modelo em pasta local / `HF_HUB_OFFLINE`, versão ONNX na CPU (`laya.onnx_agent`), cache compartilhado | B-70 |

## 🔴 P0 · Segurança e vazamento

| ID | Item | Referência |
|---|---|---|

## 🟠 P1 · Resultado errado ou tarja a menos

| ID | Item | Referência |
|---|---|---|
| B-44 | **Descartar ou conciliar `manual_redactions.json` ao reprocessar.** O reprocessamento mantém as tarjas manuais antigas, que têm prioridade sobre as novas detecções da IA | `app_service.py:354-372`, `app_service.py:431-442` |
| B-45 | **Não baixar automaticamente o PDF nativo quando a tarefa "Requer revisão".** O *polling* redireciona para `/download` ao ver `percentage === 100`, sem olhar `needs_review` (que chega depois) | `templates/index.html:1083-1089`, `main.py:116-117` |
| B-46 | **Não servir PDF final desatualizado.** `/download` entrega qualquer PDF final no disco, inclusive o da execução anterior durante um reprocessamento ou após falha. Direção: gravar em temporário, `os.replace` após a verificação e servir só com estado coerente | `app_service.py:492-512`, `utils/session.py:398-471` |
| B-47 | **Validar o esquema das tarjas manuais e falhar fechado ao descartar uma.** `/update-redactions` aceita qualquer lista e grava sem escrita atômica; caixas malformadas ou fora do intervalo são descartadas só com log. Direção: modelo Pydantic (422), gravação atômica e `add_review` | `app_service.py:437-458`, `main.py:456-470`, `utils/session.py:434-436` |
| B-48 | **Validar o esquema das respostas da IA.** Na auditoria de assinaturas, resposta que não é dict é ignorada e dict sem `unredacted_cpfs` conta como "limpo"; na descoberta de endereços, resposta sem `addresses` vira "0 endereços". Direção: resposta fora do esquema = falha → revisão e tarja de emergência | `main.py:369-424`, `utils/address_redactor.py:65` |
| B-50 | **Marcar como "não verificada" a página com imagem quando `VERIFY_OCR=0`.** Página digitalizada com algum texto nativo não passa por OCR e também não entra em `unverified` | `utils/verifier.py:63-79`, `tests/test_verifier_extra.py:71-81` |
| B-51 | **Tratar páginas rotacionadas e a escala de DPI na tarja nativa e na verificação.** As caixas vêm da imagem renderizada (já rotacionada) e vão direto para `add_redact_annot`; o *fallback* de escala usa 1000 DPI fixo. Direção: `page.derotation_matrix`, usar `BASE_DPI` e testes com `/Rotate` 90/180/270 (V-05) | `utils/session.py:439-456`, `utils/verifier.py:109-130` |
| B-62 | **Manter os alertas anteriores ao "Aplicar proteção".** O estado final da tarja nativa vem só da nova verificação; uma falha anterior da IA some e a tarefa pode virar "Concluído". Direção: herdar os alertas não resolvidos até o revisor marcá-los como conferidos | `main.py:472-484`, `app_service.py:468-490` |
| B-63 | **Deixar claro que o PDF automático é preliminar.** O processamento já grava um PDF raster com as sugestões da IA e libera *Ver/Baixar PDF* antes de qualquer revisão. Direção: rotular como "preliminar" na interface e no nome do arquivo, ou liberar o download só após "Aplicar proteção" | `main.py:485-567`, `templates/index.html` |
| B-01 | Medir revocação e precisão em um conjunto **realista** (carimbos, manuscritos, fotos de papel, tabelas), montado só com documentos fictícios | [docs/benchmarks.md](docs/benchmarks.md) |
| B-02 | Detector de assinaturas: treinar/avaliar um modelo melhor e documentar métricas no model card | [models/MODEL_CARD.md](models/MODEL_CARD.md) |
| B-03 | Endereços: reduzir tarja a mais/a menos do casamento por *tokens* com o OCR | `utils/address_redactor.py`, `utils/lexicon.py` |

## 🟡 P2 · Robustez, operação e experiência

| ID | Item | Referência |
|---|---|---|
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
| B-31 | **Motor de políticas** configurável (o que detectar e como proteger). Primeira etapa no roteiro: B-71 e B-75 | idem |
| B-32 | Novos tipos de dado (SENTRY Detect): nomes, telefones, e-mails, RG, dados bancários. Primeira etapa no roteiro: B-72 e B-73 | [docs/limitations.md](docs/limitations.md) |
| B-33 | Mascaramento e pseudonimização (SENTRY Mask / Transform) | [README.md](README.md#-visão-futuro-não-implementado) |
| B-34 | Fronteira de privacidade para IAs/APIs externas (SENTRY Gateway) | idem |

---

## Concluídos

| ID | Item | Versão | Teste |
|---|---|---|---|
| B-41 | Token na URL só abre a sessão (redireciona sem o token); cookie de sessão aleatório (`HttpOnly`, `SameSite=Strict`, `Secure` com HTTPS) no lugar do token cru; `token=` mascarado nos registros (`utils/auth.py`) | 5.3.0 | `tests/test_auth.py`, `tests/test_service_endpoints.py` |
| B-42 | Painel do gatekeeper exige `API_TOKEN` quando definido; `kill_port_owner` só encerra um `app_service.py` órfão e não usa shell | 5.3.0 | `tests/test_auth.py`, `tests/test_gatekeeper.py` |
| B-52 | Saída do app herdada pelo gatekeeper (o PIPE nunca lido travava o app) | 5.3.0 | `gatekeeper.py` |
| B-66 | Revisão de segurança independente (2026-10-04): workflow de Release com privilégio mínimo; `/purge` apaga `decisions.json`; exemplos de treino apagados com a tarefa e pasta padrão fixa; `.dockerignore` sem `.env.*` nem `learning/`; versão exata do `laya` e commit do modelo fixado no projeto; SHA-256 do modelo YOLO conferido antes de carregar; CPF com separadores incomuns mascarado; resposta crua do LLM fora do log; Origem anti-CSRF conferida também pela porta | 5.3.0 | `tests/test_decisions.py`, `tests/test_yolo_engine.py`, `tests/test_pii.py`, `tests/test_net_guard.py`, `tests/test_service_endpoints.py` |
| B-70 | **Decisor local Laya com automelhoramento** para o tipo de endereço: modos sombra/assistido, regra que nunca reduz proteção, texto minimizado, cabeça treinável sobre o Laya congelado, limiares aprendidos, portão de qualidade, perfis versionados com rollback, captura das correções do revisor (opt-in) e CLI `python -m utils.decisions`. Treino real na CPU, conjunto realista: AUC 0,83 → 0,91 | 5.3.0 | `tests/test_decisions.py` |
| B-40 | Validar `Host` (anti *DNS rebinding*) e `Origin`/`Sec-Fetch-Site` (anti CSRF) no app e no gatekeeper quando não há `API_TOKEN`; nova variável `ALLOWED_HOSTS` | 5.2.0 | `tests/test_net_guard.py` |
| B-43 | Falha do Tesseract (nas duas escalas) conta em `OCREngine.failure_count` e vira alerta da página no OCR, nos recortes e na verificação; junção das metades não perde a metade de baixo | 5.2.0 | `tests/test_fail_closed_ocr_address.py` |
| B-49 | Tipo de endereço do LLM normalizado (caixa, acento, sinônimos); rótulo desconhecido é tarjado como pessoal e manda a página para revisão; resposta sem a lista `addresses` falha fechado | 5.2.0 | `tests/test_fail_closed_ocr_address.py` |
| B-61 | Todo alerta exige revisão: "Modelo YOLO ausente" (documento inteiro, `add_document_review`) e os "Protocolos de Pânico" (página) | 5.2.0 | `tests/test_main_phases.py::test_phase3_without_model_fails_closed`, `tests/test_fail_closed_ocr_address.py` |
| B-60 | Auditoria de dados pessoais em todo PR (CI) e Ruff com versão fixa | 5.2.0 | `.github/workflows/ci.yml` (passo *Auditoria*) |
| B-13 | Releases versionadas (tag `vX.Y.Z` + notas do CHANGELOG) e versão alinhada em `pyproject.toml`/`CITATION.cff` | 5.1.0 | `tests/test_check_versions.py` |
| — | CI verde: coleta restrita a `tests/` e teste do gatekeeper que simula Windows passa no Linux | 5.1.0 | `pytest.ini`, `tests/test_gatekeeper.py` |
| — | Interface local-first (sem CDN), pt-BR/en-US, WCAG AA | 5.1.0 | `tests/ui/test_ui_brand.py`, `tests/ui/test_ui_security_a11y.py` |
| — | Pipeline falha fechado com o estado "Requer revisão" | 5.0.0 | `tests/test_fail_closed.py` |
| — | Verificação pós-tarja contra o original | 5.0.0 | `tests/test_verifier.py`, `tests/test_verifier_extra.py` |

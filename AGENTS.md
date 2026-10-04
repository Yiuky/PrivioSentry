# AGENTS.md: guia para modelos de IA e desenvolvedores

Leia antes de alterar o PRIVIO SENTRY. O trabalho pendente está no [BACKLOG.md](BACKLOG.md); a arquitetura
detalhada, em [docs/architecture.md](docs/architecture.md).

## 1. O que é

**PRIVIO SENTRY** (*Local AI Privacy Infrastructure*) é um projeto *local-first* de proteção de dados pessoais
em documentos. O único produto existente é o **SENTRY Redact**: um pipeline que encontra **CPFs** e
**endereços pessoais** em PDFs (OCR Tesseract + detector YOLO de assinaturas + LLM de visão via Ollama),
sugere tarjas, verifica a saída e só gera o PDF final depois da revisão humana num editor web.

**SENTRY Detect** existe em parte: catálogo de PII, perfis de política e detectores por regra (`utils/detect/`).
Nomes de pessoa e filiação têm detector **opcional** (GLiNER local, `NER_ENGINE=gliner`, desligado por padrão);
rostos e dados sensíveis estão no catálogo como *planejados*; não os descreva como detectados.
Os módulos Mask/Transform, Gateway e Audit são **visão**, não código: não os descreva como existentes.

## 2. Invariantes (não negociáveis)

| ID | Regra | Por quê / onde é cobrada |
|---|---|---|
| I-01 | **Nenhum dado pessoal real** no repositório: CPFs, nomes, endereços, PDFs, capturas de tela ou logs de processos reais. Use `examples/make_sample_pdf.py` ou valores fictícios (os CPFs de teste permitidos estão em `scripts/audit_public_tree.py`, `ALLOWED_CPFS`) | `python scripts/audit_public_tree.py` precisa passar |
| I-02 | **Falha fechado.** Na dúvida, o documento vai para **"Requer revisão"** com alerta por página (`SentryApp.add_review`), nunca para "Concluído". Falha da IA, página não verificada, reconstrução com erro = revisão ou nenhum PDF | `tests/test_fail_closed.py`, `tests/test_verifier*.py` |
| I-03 | Toda mudança que possa causar **tarja a menos** precisa de teste que prove que não causa | Revisão de PR |
| I-04 | **Local-first.** Nada de chamadas de rede que levem conteúdo de documento para fora da máquina; a interface não carrega CDN, fontes, scripts nem imagens externas | `tests/ui/test_ui_brand.py` |
| I-05 | **Textos honestos.** Nunca escreva "conforme a LGPD"/"LGPD compliant", "100% seguro", "garantido", "sem acesso à rede". Use "potencial", "detectado", "sugerido", "revisão", "Proteção concluída", "Processado localmente". O rótulo da interface é exatamente `LOCAL PROCESSING` | `tests/ui/test_ui_brand.py`; [docs/brand/](docs/brand/) |
| I-06 | **Nenhum CPF completo em log.** `utils/pii.install_log_masking()` mascara os registros; não o contorne nem grave CPFs por `print` | `tests/test_pii.py` |
| I-07 | Não enfraqueça a verificação pós-tarja nem o aviso permanente de que a detecção por IA é probabilística | Revisão de PR |
| I-08 | Testes **não** podem exigir Ollama, GPU nem rede: o LLM e o YOLO são simulados | `tests/conftest.py`, `tests/sentry_testkit.py` |
| I-09 | Todo alerta exige revisão: use `add_review(página, motivo)` ou `add_document_review(motivo)`, nunca `self.alerts.append` direto. Falha do OCR é detectada por `OCREngine.failure_count` (resultado vazio por erro ≠ página sem CPF) | `tests/test_fail_closed_ocr_address.py` |
| I-10 | O decisor local (`utils/decisions`) **nunca reduz proteção**: só acrescenta tarja ou pede revisão (`policy.combine_address_decision`). Modo `assist` só com perfil aprovado pelo portão; o texto enviado ao modelo e aos exemplos passa por `normalize_state` | `tests/test_decisions.py` |

## 3. Arquitetura: três processos

```text
Navegador ─► gatekeeper.py (:8000, opcional) ─proxy─► app_service.py (:8001, FastAPI + templates/index.html)
                                                         │  estado em memória + tasks.json (gravação atômica)
                                                         │  POST /internal/update/{id}  (header X-Internal-Secret)
                                                         └─ multiprocessing.Process por tarefa ─► main.SentryApp.run()
```

- **`gatekeeper.py`** (opcional): painel liga/desliga, *watchdog* que reinicia o app após falhas de *health
  check*, lembra o estado desejado (`.gatekeeper_state`) e faz proxy reverso para o app.
- **`app_service.py`**: API + interface. Cada upload/reprocessamento/finalização inicia um *worker*
  (`start_worker` → `redaction_worker`). Os *workers* reportam progresso por HTTP com o segredo
  `INTERNAL_SECRET` (gerado a cada execução). `AI_LOCK` (`multiprocessing.Lock`) serializa as chamadas ao
  LLM entre *workers*. Operações concorrentes na mesma tarefa devolvem `409`. IDs de tarefa são UUIDs
  validados.
- **`main.py`** (`SentryApp`): o pipeline; também é a CLI (`python main.py --input ... --output ...`, saída
  `0` concluído / `3` requer revisão / `1` erro).

## 4. Onde fica cada coisa

| Caminho | Papel |
|---|---|
| `main.py` | `SentryApp`: fases `run_phase_0` (render) → `1` (OCR) → `2` (CPF) → `3` (YOLO) → `4` (micro-auditoria dos recortes) → endereços (`run_address_discovery`, `run_phase_6`) → `run_signature_audit` → `run_phase_5` (exportação) → `run_verification`. `run_native_phase` aplica a tarja nativa a partir das caixas revisadas |
| `app_service.py` | Rotas HTTP, tarefas, retenção (`RETENTION_DAYS`, `sweep_retention`, `POST /purge/{id}`), validação de upload, `API_TOKEN` |
| `gatekeeper.py` | Painel e proxy da porta 8000 |
| `utils/ocr_engine.py` | Tesseract com coordenadas por palavra (*grounding map*), *fallback* de escala, `find_cpfs_in_grounding` |
| `utils/validators.py` | Dígitos verificadores de CPF e CNPJ |
| `utils/yolo_engine.py` | Detector de assinaturas (Ultralytics) e recortes |
| `utils/ai_client.py` | Cliente Ollama (`/api/chat`, texto e visão), limpeza da resposta JSON |
| `utils/address_redactor.py` + `utils/lexicon.py` | Descoberta de endereços pelo LLM e casamento com as palavras do OCR; palavras "imunes" |
| `utils/session.py` | Pastas da tarefa, logs, exportação, reconstrução do PDF e tarja nativa (`apply_native_pdf_redactions`) |
| `utils/verifier.py` | Verificação pós-tarja: relê o PDF final e confronta o original (`find_uncovered_cpfs`) |
| `utils/pii.py` | Mascaramento de CPF em logs |
| `utils/detect/` | SENTRY Detect: catálogo de PII com enquadramento legal (`catalog.py`), perfis de política (`profiles.py`, `POLICY_PROFILE`), detectores por regra (`rules.py`), nomes com GLiNER opcional (`ner.py`, `NER_ENGINE=gliner`), dígitos verificadores (`validators.py`) e **regras/limiares como dados** (`data/*.json`, lidos por `config.py`). Pacote isolado, com contrato JSON (API `/policy/*`), pronto para virar serviço. `docs/catalogo-pii.md` é gerado: `python -m utils.detect --markdown` |
| `utils/decisions/` | Decisor local (Laya) e automelhoramento: perguntas, motor, regra de combinação, treino com portão de qualidade e versões. Guia: [docs/decisions.md](docs/decisions.md) |
| `utils/auth.py` | Autenticação por `API_TOKEN` com sessão aleatória (app e gatekeeper): `?token=` só abre a sessão e sai da URL |
| `utils/net_guard.py` | Checagem de `Host`/`Origin` (anti *DNS rebinding* e CSRF) usada pelo app e pelo gatekeeper; `ALLOWED_HOSTS` |
| `templates/index.html` | Editor web autocontido; textos no objeto `I18N` (pt-BR padrão, en-US), chaves conforme `docs/brand/UX_SPEC.md`; renderizador Markdown próprio que **nunca** injeta HTML |
| `templates/gatekeeper.html` | Página do painel quando o app está desligado |
| `scripts/audit_public_tree.py` | Auditoria de dados pessoais, segredos e caminhos locais antes de publicar |
| `benchmarks/` | Benchmark sintético de CPF (`python -m benchmarks.run_benchmark`; resultados em `benchmarks/results/`) e corpus fictício de PII com métricas por tipo (`pii_corpus.py`, `python -m benchmarks.pii_eval [--ocr]`) |
| `experimental/agent_loop/` | Abordagem com agente LLM, inacabada e **fora** do pipeline e do lint |

## 5. Armadilhas conhecidas

- **Nomes legados.** Alguns nomes internos ainda carregam o nome de trabalho antigo "Tarjador" (ex.: o logger
  `AppTarjadorService`). Renomeá-los é um item do backlog; não espalhe o nome antigo em código novo.
- **README da interface.** O botão *Documentação* do editor mostra o `README.md` da raiz pelo renderizador
  local (`GET /readme`). Ele não interpreta HTML: as linhas HTML do topo aparecem como texto. Isso é
  proposital (ver `test_readme_renderer_is_local_and_escapes_html`); não troque por `innerHTML`.
- **`BASE_DPI` padrão é 300** (era 1000 até a 5.3.0). Medido: acima de 300 o Tesseract fragmenta os dígitos e a revocação de CPF cai (docs/benchmarks.md). Não suba o padrão sem rodar o benchmark.
- **Regras como dados.** Palavras de contexto, listas e limiares ficam em `utils/detect/data/*.json`, não no código. Antes e depois de mexer neles (ou em `rules.py`), rode `python -m benchmarks.pii_eval` e `pytest tests/test_pii_corpus_gate.py`: revocação abaixo de 100% no modo texto reprova. Ao achar um erro num documento real, transforme o caso (com valores **fictícios**) num modelo de `benchmarks/pii_corpus.py` ou numa regressão em `tests/test_counter_analysis.py`.
- **Retorno do revisor nunca reduz proteção sozinho.** `python -m utils.decisions detectores` só sugere; a mudança é humana e medida no corpus.
- **OCR em paralelo.** As páginas passam pelo OCR em threads (`ocr_workers`). Detecte falha do Tesseract com `OCREngine.thread_failures()` (por thread), nunca com o contador global, senão a falha de uma página é atribuída a outra. As duas passadas (padrão + esparsa) são mantidas de propósito.
- **Artefatos com dados pessoais.** `output/`, `WEB_INPUT/`, `documentos_finais/` e `tasks.json` estão no
  `.gitignore` e nunca devem ser versionados.
- **Licenças AGPL.** PyMuPDF e Ultralytics são AGPL-3.0; novas dependências precisam de justificativa e
  checagem de licença ([docs/licensing.md](docs/licensing.md)).
- **Windows e Linux.** O desenvolvimento principal é no Windows; o CI roda no Ubuntu com Tesseract via apt.
  Use `os.path`/`pathlib`, nunca caminhos fixos como `C:\...`.

## 6. Testes e verificações

```bash
ruff check .                         # lint (regras em pyproject.toml)
pytest --ignore=tests/ui             # unidade e integração
pytest tests/ui                      # interface (Playwright + Chromium: playwright install chromium)
python scripts/audit_public_tree.py  # dados pessoais / segredos / caminhos locais
pre-commit install                   # opcional: lint + auditoria + versão a cada commit
python -m benchmarks.run_benchmark   # benchmark sintético (opcional; precisa de Tesseract; ver docs/benchmarks.md)
python -m benchmarks.pii_eval        # revocação/precisão por tipo no corpus fictício (--ocr usa o Tesseract)
```

O CI (`.github/workflows/ci.yml`) roda o lint, a suíte em Python 3.10/3.11/3.12 com cobertura e os testes de
interface.

## 7. Convenções

- Documentação e interface em **português (pt-BR) primeiro**; o `README.en.md` acompanha o `README.md`.
  Atualize os dois quando o comportamento mudar.
- Mudanças na interface ou no fluxo do usuário atualizam o [manual de uso](docs/MANUAL_DE_USO.md); o índice
  da documentação fica em [docs/README.md](docs/README.md).
- Toda mudança de comportamento ou configuração atualiza `CHANGELOG.md` (seção *Não publicado*),
  `docs/configuration.md` e `.env.example` quando couber.
- Commits com *sign-off* (`git commit -s`, DCO). Um assunto por PR, com testes.
- **Versão:** `pyproject.toml`, `CITATION.cff` (com `date-released`) e a seção `## [X.Y.Z] - AAAA-MM-DD` do
  `CHANGELOG.md` andam juntas; `python scripts/check_versions.py` confere (também no CI).
- **Publicar uma versão:** com a versão atualizada nesses três arquivos, `git tag vX.Y.Z && git push origin vX.Y.Z`.
  O workflow **Release** confere tudo, roda a suíte e publica a Release com as notas do CHANGELOG.
- **Identidade:** projeto pessoal de Joberth Firmino Gambati (@Yiuky). Commits com
  `Yiuky@users.noreply.github.com`. Nunca cite instituição como autora ou dona, nem publique o e-mail
  institucional (a auditoria bloqueia o domínio e a sigla).

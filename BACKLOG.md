# Backlog do PRIVIO SENTRY

Backlog vivo para o mantenedor e para **outros modelos de IA / desenvolvedores**. Antes de pegar um item,
leia o [AGENTS.md](AGENTS.md): invariantes, arquitetura e como rodar os testes.

**Como usar este arquivo**
- Cada item tem um ID estável. Não reutilize nem renumere IDs.
- Ao iniciar um item, mude o status para `EM ANDAMENTO (<quem>, <data>)`.
- Ao concluir, mova-o para **Concluídos** com a versão, o commit e o teste que o cobre.
- Todo item concluído precisa de teste automatizado em `tests/`.
- Prioridade: **P0** (vazamento de dado ou segurança) · **P1** (resultado errado ou tarja a menos) ·
  **P2** (robustez e experiência) · **P3** (melhoria e refatoração).
- Itens marcados como **visão** vêm do roteiro do produto: não têm data nem promessa de entrega.
- Estado de referência: `5.1.0`, 2026-10-04.

---

## P1 · Qualidade da detecção

| ID | Item | Referência |
|---|---|---|
| B-01 | Medir revocação e precisão em um conjunto **realista** (digitalizações com carimbos, manuscritos, fotos de papel, tabelas), montado só com documentos fictícios | [docs/benchmarks.md](docs/benchmarks.md), [docs/limitations.md](docs/limitations.md) |
| B-02 | Detector de assinaturas: treinar/avaliar um modelo melhor e documentar métricas no model card | [models/MODEL_CARD.md](models/MODEL_CARD.md) |
| B-03 | Endereços: reduzir tarja a mais/a menos do casamento por *tokens* com o OCR | `utils/address_redactor.py`, `utils/lexicon.py` |

## P2 · Robustez, segurança e operação

| ID | Item | Referência |
|---|---|---|
| B-10 | Tarja nativa: remover ou sinalizar metadados, anexos, anotações, campos de formulário e camadas ocultas que sobrevivem à tarja | [docs/limitations.md](docs/limitations.md) (Saída) |
| B-11 | Aviso de rede: na interface quando `OLLAMA_API_URL` não aponta para `localhost` | [docs/limitations.md](docs/limitations.md) (Plataforma) |
| B-12 | Desempenho em PDFs grandes (centenas de páginas): perfis de DPI, paralelismo do OCR fora do `AI_LOCK` | [docs/limitations.md](docs/limitations.md) (Desempenho) |

## P3 · Refatoração e manutenção

| ID | Item | Referência |
|---|---|---|
| B-20 | Renomear os nomes internos legados "Tarjador" (logger `AppTarjadorService` e variáveis de ambiente antigas) mantendo compatibilidade | [docs/architecture.md](docs/architecture.md) |
| B-21 | Endurecer o lint: remover aos poucos as exceções "legadas" do Ruff (`W291`–`W293`, `E722`, `B007`, `B905`) | `pyproject.toml` |
| B-22 | Decidir o destino de `experimental/agent_loop/` (integrar com testes ou remover) | [experimental/README.md](experimental/README.md) |
| B-23 | Pesquisa de anterioridade da marca PRIVIO SENTRY | [TRADEMARKS.md](TRADEMARKS.md) |

## Visão (sem data)

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
| B-13 | Releases versionadas (tag `vX.Y.Z` + notas do CHANGELOG) e versão alinhada em `pyproject.toml`/`CITATION.cff` | 5.1.0 | `tests/test_check_versions.py` |
| — | Pipeline falha fechado com o estado "Requer revisão" | 5.0.0 | `tests/test_fail_closed.py` |
| — | Verificação pós-tarja contra o original | 5.0.0 | `tests/test_verifier.py`, `tests/test_verifier_extra.py` |
| — | Interface local-first (sem CDN), pt-BR/en-US, WCAG AA | não publicado | `tests/ui/test_ui_brand.py`, `tests/ui/test_ui_security_a11y.py` |

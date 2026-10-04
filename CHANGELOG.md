# Changelog

Todas as mudanças relevantes ficam registradas aqui. Formato baseado no
[Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/); as versões seguem o [SemVer](https://semver.org/lang/pt-BR/).

## [Não publicado]

### Adicionado
- **Identidade de marca PRIVIO SENTRY** (*Local AI Privacy Infrastructure*; produto SENTRY Redact): `assets/` (marca conceitual, favicon), `docs/brand/` (diretrizes de marca, design, UX, segurança/privacidade e posicionamento frente à LGPD, *design tokens*, *brand board*) e `TRADEMARKS.md` (nome e logotipos não são cobertos pela AGPL-3.0; pesquisa de anterioridade pendente).
- Interface web refeita com os *design tokens*: cabeçalho e logotipo PRIVIO SENTRY, selo `LOCAL PROCESSING`, aviso permanente "a IA sugere; você confirma", regras de texto (potencial/sugerido/revisão; "Proteção concluída - Processado localmente"), `I18N` pt-BR/en-US com seletor de idioma, atalhos `N`/`P`/`Esc`, foco visível e cartões de tarefa operáveis pelo teclado.
- Testes de interface para identidade, afirmações proibidas, ausência de requisições externas, contraste (WCAG AA) e foco.
- Preparação para código aberto: `LICENSE` AGPL-3.0-or-later, `NOTICE`, `CONTRIBUTING`, `CODE_OF_CONDUCT`, `SECURITY`, `docs/`.
- `pyproject.toml`, `requirements*.txt`, `Dockerfile`, `docker-compose.yml`, CI no GitHub Actions, modelos de issue/PR, Dependabot.
- Detector YOLO de assinaturas sanitizado em `models/signature_stamp_detector.pt`, com *model card*.
- Gerador de exemplo sintético `examples/make_sample_pdf.py`.
- `scripts/audit_public_tree.py` (auditoria de dados pessoais/segredos antes de publicar) e scripts de execução para Linux/macOS.
- `AGENTS.md` (guia para modelos de IA e desenvolvedores: invariantes, arquitetura, armadilhas), `BACKLOG.md` (trabalho pendente com IDs estáveis e prioridades) e `CITATION.cff` (botão *Cite this repository*).
- Captura de tela do editor (`docs/img/editor.png`), gerada a partir do exemplo fictício.

### Alterado
- **Documentação em português primeiro:** o `README.md` passou a ser em PT-BR (com selos, navegação, tabelas e um *English Abstract*); a versão completa em inglês está em `README.en.md` (o antigo `README.pt-BR.md` foi incorporado ao `README.md`). `docs/architecture.md`, `docs/configuration.md`, `docs/benchmarks.md`, `docs/limitations.md`, `docs/threat-model-lgpd.md`, `models/MODEL_CARD.md`, `experimental/README.md`, `CONTRIBUTING.md`, `SECURITY.md`, este `CHANGELOG.md` e os modelos de issue/PR foram traduzidos para PT-BR.
- Nome do projeto definido como **PRIVIO SENTRY** (`privio-sentry`); marcadores `PROJECT_NAME` substituídos. Dono do repositório: `Yiuky`; canais de contato pelo GitHub (nenhum e-mail publicado).
- Interface local-first: removidos os carregamentos de Google Fonts, `marked` (jsDelivr) e `lucide` (unpkg) por CDN; a ajuda em Markdown usa um renderizador próprio que nunca injeta o texto do arquivo como HTML; favicon e logotipo embutidos.
- O README não diz mais que a ferramenta ajuda a "cumprir" a LGPD; descreve o posicionamento alinhado à LGPD e o estágio inicial do projeto.
- Scripts auxiliares movidos para `scripts/`; o laço de agente experimental foi para `experimental/agent_loop/`; caminhos fixos de usuário removidos.
- README reescrito sem prometer demais: a ferramenta apoia, mas não garante a anonimização.

### Corrigido
- `pytest` na raiz (usado no CI) coletava `scripts/test_box.py`, um experimento manual que chama o Ollama ao ser importado, e falhava na coleta; o `pytest.ini` agora restringe a coleta a `tests/` (`testpaths = tests`).

## [5.0.0]

### Adicionado
- Pipeline que falha fechado: novo estado **"Requer revisão"** com alertas por página.
- Verificação pós-tarja (`utils/verifier.py`): relê a saída e confronta o original a 300 DPI.
- Endurecimento do serviço web: validação de upload, limite de tamanho, rotas com UUID validado, `API_TOKEN` opcional, escuta em *loopback* por padrão, segredo para o endpoint interno.
- Persistência atômica do `tasks.json`, `409` em operações concorrentes, trava compartilhada entre processos para a IA.
- Testes automatizados (pytest).

### Corrigido
- XSS na lista de tarefas (escape de HTML em nomes de arquivo, status e alertas).
- Rotas `/readme` e `/finalize/{id}` ausentes.

# Changelog

Todas as mudanças relevantes ficam registradas aqui. Formato baseado no
[Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/); as versões seguem o [SemVer](https://semver.org/lang/pt-BR/).

## [Não publicado]

### Alterado
- **Mais rápido e mais preciso:** um documento real digitalizado de 10 páginas caiu de **~14 min para ~3 min** (OCR de ~510 s para ~19 s).
  - **`BASE_DPI` padrão: 1000 → 300.** Medido (`docs/benchmarks.md`): a 300 DPI a revocação de CPF foi de 100% contra ~60% a 1000 DPI (o Tesseract quebra os dígitos em pedaços em imagens grandes), e a verificação achou 16/16 vazamentos contra 11–13/16. No documento real, os CPFs achados a 1000 DPI foram todos achados a 300 DPI. **Atenção:** quem define `BASE_DPI` no `.env` deve revisar o valor (e `YOLO_CROP_PADDING`, que é em pixels).
  - **OCR das páginas em paralelo** (nova variável `OCR_WORKERS`; padrão: metade dos núcleos, até 8), nas duas passadas e na verificação pós-tarja. A detecção de falha do Tesseract continua por página (contador por thread). **As duas passadas de OCR (padrão + esparsa) foram mantidas.**
  - O decisor Laya carrega o modelo **em paralelo** com a análise de endereços do LLM.
  - Imagens das páginas gravadas com compressão PNG leve.

### Adicionado
- **Onde revisar:** cada alerta com posição conhecida (CPF ainda detectável, CPF sem tarja, dúvida do decisor sobre endereço) marca a **região na página** com um contorno tracejado laranja ("⚠ Revisar aqui"); clicar no alerta da barra leva até a região e a destaca.
- **Documento aberto se atualiza sozinho** quando o processamento termina (sem recarregar a página); com edições não salvas, só avisa, nunca descarta.
- **Texto digital do PDF como passada extra** de CPF, somada ao OCR, quando o PDF tem camada de texto.
- **Tempo por etapa** registrado na tarefa e mostrado no cartão (total; detalhe ao passar o mouse).

### Corrigido
- O filtro que mascara `token=` nos registros quebrava o formatador de acesso do uvicorn (um *traceback* por requisição no console; as requisições funcionavam). Agora mascara dentro dos argumentos, preservando o formato.
- A tarja nativa sem a largura da imagem de origem supunha 1000 DPI fixo; agora usa `BASE_DPI`.

## [5.3.0] - 2026-10-04

Decisor local que aprende (experimental, desligado por padrão) e uma rodada completa de segurança: os dois
itens P0 restantes (B-41, B-42) e todos os achados de uma revisão de segurança independente.

### Segurança
- **Token de acesso não vaza mais por URL, histórico ou registros (B-41).** `?token=` só abre a sessão: o servidor redireciona para a mesma página sem o token e grava um **cookie de sessão aleatório** (`HttpOnly`, `SameSite=Strict`, `Secure` com HTTPS). O token cru nunca vai para o cookie, e `token=` é mascarado nos registros do app, do gatekeeper e do uvicorn. Scripts seguem com o cabeçalho `X-API-Token`. Nova variável `SESSION_TTL_HOURS` (padrão 12). **Atenção:** quem usava o cookie antigo precisa abrir `?token=` de novo.
- **Painel do gatekeeper protegido (B-42).** Com `API_TOKEN`, `/gatekeeper`, `/manage` e `/api/*` exigem o token. O `kill_port_owner` só encerra um `app_service.py` órfão (antes matava qualquer programa na porta) e não usa mais shell.
- **Revisão independente (B-66):**
  - workflow de Release com privilégio mínimo (escrita só no job que publica) e `persist-credentials: false`;
  - `/purge` apaga também o `decisions.json`;
  - exemplos de treino apagados junto com a tarefa de origem (e pela retenção), com pasta padrão fixa no projeto;
  - `.dockerignore` exclui `.env.*` e `learning/`;
  - versão exata do `laya` e commit do modelo fixado no próprio projeto (modelo remoto sem commit fixo é recusado);
  - **SHA-256 do modelo YOLO conferido antes de carregar** (arquivo `.pt` pode executar código): arquivo diferente não é carregado e o documento vai para revisão; `YOLO_MODEL_SHA256` para modelos próprios;
  - CPF com separadores incomuns (`529-982-247-25`, `529,982,247-25`...) também é mascarado nos registros;
  - a resposta crua do LLM de visão saiu do log da tarefa;
  - a Origem anti-CSRF é conferida também pela porta (outro app local não dispara escritas).

### Corrigido
- O gatekeeper abria o app com saída num *pipe* nunca lido: com o buffer cheio, o app travava e as tarefas eram interrompidas (B-52).

### Adicionado
- **Decisor local com automelhoramento (experimental, desligado por padrão).** Nova camada `utils/decisions/` usa o [Laya](https://huggingface.co/convaiinnovations/laya) (modelo de decisão local, Apache-2.0, roda na CPU em ~0,1 s por decisão) para dar uma segunda opinião calibrada sobre o tipo de cada endereço. Ponto central: o decisor **nunca reduz proteção**; só acrescenta tarja ou pede revisão.
  - **Modos:** `shadow` (só observa e registra, o padrão) e `assist` (participa, só com perfil aprovado).
  - **Treinamento:** o Laya fica congelado e uma cabeça leve (regressão logística por método de Newton sobre 9 perguntas respondidas numa passada) aprende a combinar as respostas; os limiares de decisão também são aprendidos.
  - **Automelhoramento:** com `LEARNING_ENABLED=1`, as tarjas finais do revisor viram exemplos rotulados. `python -m utils.decisions train` treina um candidato que só vira ativo se passar no **portão de qualidade** (AUC, precisão, NPV e não piorar o perfil ativo); perfis versionados com `rollback` e `purge`.
  - **Privacidade:** tudo local; o texto é minimizado (CPF mascarado, dígitos trocados por `0`); exemplos em `PRIVIO_LEARNING_DIR`, fora do git.
  - **Rede corporativa:** o `truststore` faz o download do modelo funcionar atrás de proxy com inspeção TLS.
  - **Portão com conjunto realista** (36 endereços fictícios escritos à mão, fora do treino), porque o conjunto gerado superestimava a qualidade: um primeiro perfil aprovado só com ele errou em textos reais.
  - Treino real (CPU), conjunto realista: AUC 0,83 sem treino → **0,91** treinado; precisão 0,92 e NPV 0,88 nas decisões firmes; 17% dos casos ficam incertos e vão para revisão.
  - Instalação opcional (versões exatas): `pip install -e ".[laya]"` ou `requirements-laya.txt`. Guia: `docs/decisions.md`. Roteiro da detecção configurável (nomes, telefones, RG, perfis) no BACKLOG (B-71 a B-79).

## [5.2.0] - 2026-10-04

Versão de segurança e confiabilidade: o pipeline falha fechado em mais situações e o serviço local passa a
recusar outros sites abertos no mesmo navegador. **Mudança de comportamento:** mais documentos vão para
"Requer revisão", e o acesso por outro nome ou IP sem `API_TOKEN` exige `ALLOWED_HOSTS`.

### Segurança
- **Proteção contra outros sites abertos no mesmo navegador (B-40).** Sem `API_TOKEN`, o app e o gatekeeper só aceitam o cabeçalho `Host` esperado (`127.0.0.1`, `localhost`, `::1`, `APP_HOST` e a nova variável `ALLOWED_HOSTS`), respondendo `421` aos demais (*DNS rebinding*), e recusam POST/PUT/PATCH/DELETE com `Origin` ou `Sec-Fetch-Site` de outro site (`403`, CSRF). Isso fecha a leitura das imagens originais sem tarja e o liga/desliga do gatekeeper por páginas maliciosas (`utils/net_guard.py`). Com `API_TOKEN`, a checagem de `Host` é dispensada (o cookie é `SameSite=Strict`). **Atenção:** para acessar o gatekeeper, ou o app sem token, por outro nome ou IP, liste-o em `ALLOWED_HOSTS`.

### Corrigido
- **Falha do Tesseract não vira mais "Concluído" (B-43).** Quando o OCR falha nas duas escalas, a página recebe o alerta "OCR (Tesseract) falhou nesta página" e o documento vai para **Requer revisão**; o mesmo vale para os recortes de assinatura e para a verificação pós-tarja (página não verificada). A junção das duas metades da página não perde mais a metade de baixo quando só a de cima falha.
- **Endereços pessoais com outra grafia agora recebem tarja (B-49).** O tipo devolvido pelo LLM é normalizado ("Pessoal", "residencial ", "domicílio"...); rótulo desconhecido é tarjado como pessoal e a página vai para revisão; resposta sem a lista de endereços falha fechado.
- **Todo alerta exige revisão (B-61).** "Modelo YOLO ausente" (vale para o documento inteiro) e os "Protocolos de Pânico" de endereços e assinaturas colocavam um ⚠ mas deixavam a tarefa como "Concluído".

### Adicionado
- **Manual de uso** completo em PT-BR (`docs/MANUAL_DE_USO.md`): instalação, editor web, linha de comando, resultados, privacidade, exposição na rede, solução de problemas, perguntas frequentes e glossário.
- **Índice da documentação** (`docs/README.md`) por público: quem usa, quem decide/opera e quem desenvolve.
- README: diagrama do fluxo (Mermaid), perguntas frequentes e link para o manual.
- Imagem de *social preview* (`docs/img/social_preview.png`, 1280×640) com a identidade da marca.
- `.pre-commit-config.yaml`: lint, auditoria de dados pessoais e checagem de versão antes de cada commit.
- **Backlog ampliado** a partir de uma revisão completa do código: 3 itens P0 (proteção contra outros sites no mesmo navegador, token na *query string*, painel do gatekeeper), 15 P1 (falhar fechado quando o Tesseract falha, respostas da IA fora do esquema, tarjas manuais, páginas rotacionadas...), novos P2/P3 e um checklist de validação manual (V-01 a V-05).
- Repositório no GitHub: descrição em PT-BR, tópicos e relato privado de vulnerabilidades habilitado (citado no `SECURITY.md`).

### Alterado
- **Repositório renomeado para [`Yiuky/PrivioSentry`](https://github.com/Yiuky/PrivioSentry)** (os endereços antigos `Yiuky/privio-sentry` redirecionam); links, selos, `CITATION.cff`, `pyproject.toml` e instruções de `git clone` atualizados. O nome do pacote Python e da imagem Docker continua `privio-sentry`.
- **Código de Conduta em PT-BR** (Contributor Covenant 2.1), com contato do mantenedor pelo GitHub ou LinkedIn e a regra de nunca anexar dados pessoais reais.
- README (PT-BR e EN): esclarece que o processamento automático gera um PDF **preliminar** e que a versão para uso sai após a revisão e o "Aplicar proteção"; antes dizia que nenhum PDF final existia antes da revisão.
- CI: a auditoria de dados pessoais roda em todo PR; Ruff com versão fixa (`ruff==0.16.10`).
- Versão do pacote: 5.1.0 → 5.2.0.

## [5.1.0] - 2026-10-04

Primeira versão pública do PRIVIO SENTRY, com a documentação em português primeiro.

### Adicionado
- Seção **"Doe um café para o dev"** (Pix) no README e botão *Sponsor* do repositório (`.github/FUNDING.yml`).
- Autoria: projeto pessoal e independente de Joberth Firmino Gambati ([@Yiuky](https://github.com/Yiuky)), em `README`, `pyproject.toml`, `CITATION.cff` e `NOTICE`. A auditoria (`scripts/audit_public_tree.py`) passa a aceitar a identidade pública do autor e continua bloqueando o usuário local do Windows e o domínio/sigla institucional.
- `scripts/check_versions.py` (versão igual em `pyproject.toml`, `CITATION.cff` e `CHANGELOG.md`), conferido no CI, e workflow **Release** (`.github/workflows/release.yml`): ao enviar uma tag `vX.Y.Z`, confere a versão, roda a auditoria, o lint e a suíte e publica a Release com as notas do CHANGELOG. Selo da versão no README.
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
- Testes de `scripts/check_versions.py` (`tests/test_check_versions.py`).

### Alterado
- **Documentação em português primeiro:** o `README.md` passou a ser em PT-BR (com selos, navegação, tabelas e um *English Abstract*); a versão completa em inglês está em `README.en.md` (o antigo `README.pt-BR.md` foi incorporado ao `README.md`). `docs/architecture.md`, `docs/configuration.md`, `docs/benchmarks.md`, `docs/limitations.md`, `docs/threat-model-lgpd.md`, `models/MODEL_CARD.md`, `experimental/README.md`, `CONTRIBUTING.md`, `SECURITY.md`, este `CHANGELOG.md` e os modelos de issue/PR foram traduzidos para PT-BR.
- Nome do projeto definido como **PRIVIO SENTRY** (`privio-sentry`); marcadores `PROJECT_NAME` substituídos. Dono do repositório: `Yiuky`; canais de contato pelo GitHub (nenhum e-mail publicado).
- Versão do pacote: 5.0.0 → 5.1.0.
- Interface local-first: removidos os carregamentos de Google Fonts, `marked` (jsDelivr) e `lucide` (unpkg) por CDN; a ajuda em Markdown usa um renderizador próprio que nunca injeta o texto do arquivo como HTML; favicon e logotipo embutidos.
- O README não diz mais que a ferramenta ajuda a "cumprir" a LGPD; descreve o posicionamento alinhado à LGPD e o estágio inicial do projeto.
- Scripts auxiliares movidos para `scripts/`; o laço de agente experimental foi para `experimental/agent_loop/`; caminhos fixos de usuário removidos.
- README reescrito sem prometer demais: a ferramenta apoia, mas não garante a anonimização.

### Corrigido
- `pytest` na raiz (usado no CI) coletava `scripts/test_box.py`, um experimento manual que chama o Ollama ao ser importado, e falhava na coleta; o `pytest.ini` agora restringe a coleta a `tests/` (`testpaths = tests`).
- `tests/test_gatekeeper.py::test_stop_on_windows_uses_taskkill_tree` falhava no Linux: o teste simula o Windows, mas `subprocess.CREATE_NEW_PROCESS_GROUP` só existe lá; o teste agora fornece a constante.

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

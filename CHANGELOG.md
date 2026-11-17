# Changelog

Todas as mudanças relevantes ficam registradas aqui. Formato baseado no
[Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/); as versões seguem o [SemVer](https://semver.org/lang/pt-BR/).

## [Não publicado]

### Adicionado
- **Demonstração da API** em `/api-demo`: envia um PDF pela API, mostra a fila, publica uma mensagem a cada mudança
  de situação (recebido, na fila, processando, requer revisão, aprovado, erro, pendente), lista as chamadas HTTP e
  baixa só o PDF aprovado (`?final=true`; antes disso mostra a recusa 409). Sem texto do documento nem alertas;
  nomes de arquivo ocultos até serem pedidos. Parte do portal (some com `PORTAL_ENABLED=0`).

### Alterado
- **Administração mais natural e fácil de operar.**
  - **Visão geral virou um painel:** diz "Tudo pronto" ou quantos itens pedem atenção e lista os componentes (OCR, detector de assinaturas, IA, para onde vão as páginas, verificação final, pacotes opcionais, reinício pendente) com o link **Ajustar**. Mostra também os documentos por situação, com a próxima tentativa dos pendentes, e o espaço usado pelos arquivos guardados. Atualiza sozinho. Nova rota `GET /admin/status`, só com fatos e contagens.
  - **Formulários em linguagem simples:**
    - itens agrupados por assunto;
    - **Opções avançadas** recolhidas, que abrem sozinhas quando algum item já foi alterado;
    - interruptores no lugar das caixas de seleção;
    - nomes legíveis nas listas (perfis pelo nome, "Mandar as páginas para revisão" em vez de `revisao`);
    - o valor em uso aparece no campo vazio ("padrão: 300");
    - os atalhos de provedor ficam dentro do cartão da IA principal e dizem o próximo passo.
  - **Alterações não salvas** ficam marcadas; **Salvar** grava só o que mudou, **Descartar** desfaz, e sair da página pede confirmação.

### Corrigido
- **Tela Administração:**
  - interruptores ligados por padrão (**Modelos de documento**, **OCR na verificação final**) apareciam desligados quando nada estava salvo;
  - o padrão mostrado para servidor, modelo e tempo limite ignorava as variáveis antigas `OLLAMA_*` do `.env`;
  - `CHAVE=` vazio no `.env` aparecia como "do .env".
- "Restaurar padrão" num item salvava junto o que estava sendo digitado nos outros itens do mesmo cartão.
- **Segundo olhar e inspeção de modelo com o Claude Haiku 5.5 (Anthropic):** o agente mandava `temperature`, que
  modelos novos recusam (HTTP 400), e a página ia para revisão. Agora, na primeira recusa, o pedido é refeito sem
  `temperature` e os passos seguintes já vão sem ele, como o cliente de IA principal já fazia. Outro erro 400 não é
  repetido. Medido com `benchmarks.provider_check` e dados fictícios: todas as verificações aprovadas, inspeção 5/5.
- **Nomes não procurados sem aviso:** nos perfis que pedem nomes (`lgpd_publicacao`, `gdpr`, `saude_hipaa`), com a
  busca de nomes desligada ou o GLiNER não instalado, o documento saía "Concluído" sem nenhum nome tarjado e sem
  alerta. Agora todas as páginas vão para revisão com o aviso "Nomes de pessoa não foram procurados (...), mas o
  perfil pede". Para não ter o aviso: instale e ligue o detector (`pip install -e ".[nomes]"`, `NER_ENGINE=gliner`)
  ou use um perfil que não pede nomes.
- **Posição na fila parada:** "Na fila (5º)" mostrava a posição de quando o documento entrou e não mudava enquanto
  a fila andava. Agora as posições são refeitas sempre que uma tarefa sai da fila para processar.

### Documentação
- README: selos do YOLO (assinaturas), da IA local (Ollama ou LM Studio) e do MCP; fluxos em diagrama (da chegada ao PDF aprovado, cada pedido à IA com trava de saída e limitador, modelos de documento e agentes pelo MCP); seção de telas com a Administração e o gerenciador de modelos.
- Capturas de tela novas (editor com a assinatura achada pelo YOLO e tarefas em vários estados, Administração e modelos), geradas com dados fictícios por `python scripts/make_screenshots.py`.

## [5.7.0] - 2026-11-16

Fácil de configurar e pronto para agentes: tela **Administração**, IA na nuvem por chave de API **só com
liberação explícita**, o serviço também como **API** documentada e um **servidor MCP local**, modelos de documento
e limite de uso do provedor de IA. Inclui uma varredura de bugs: os casos em que dado pessoal podia ficar visível
num documento "Concluído" agora tarjam ou pedem revisão. Leia **Atenção ao atualizar** antes de trocar de versão.

### Adicionado
- **Administração** (`/admin`, botão na barra lateral): IA principal e reserva com atalhos de provedor (Ollama, LM Studio, OpenAI, Anthropic, Gemini, OpenRouter, Mistral), teste de conexão (pedido curto, sem documento) e lista de modelos; detecção e política; OCR e verificação; fila, tamanho e retenção; guia de API e MCP. O salvo fica em `privio_settings.json` (`PRIVIO_SETTINGS_FILE`, fora do git e da imagem Docker), vale sobre o `.env` e "restaurar padrão" volta a ele. Chaves de API nunca voltam pela API. `API_TOKEN`, `APP_HOST`, `ALLOWED_HOSTS` e pastas continuam só no `.env`. `ADMIN_ENABLED=0` desliga a tela.
- **IA externa por chave de API** (`AI_ALLOW_EXTERNAL`, desligada por padrão): um servidor fora desta rede só recebe conteúdo depois da liberação (com confirmação na tela). Sem ela, a chamada é bloqueada antes de sair e a página vai para **Requer revisão**. Liberada, a tarefa registra os destinos (`ia_externa`), o selo vira **EXTERNAL AI** e o cartão diz "com IA externa" em vez de "Processado localmente". Vale também para o segundo olhar.
- **API:** `GET /tasks/{id}`, `GET /api/info`, `GET /healthz` (sem token, sem dados), `GET /download/{id}?final=true` (só o PDF aprovado pelo revisor, sem pendências) e `PORTAL_ENABLED=0` (só API). Guia em `docs/api.md`.
- **Servidor MCP local** (`sentry_mcp.py`, stdio, sem dependência nova): enviar PDF, acompanhar, esperar e baixar o resultado aprovado. Não aprova, não edita, não apaga e não devolve texto do documento. Guia em `docs/mcp.md`.
- Link direto `/?task=<id>` abre o documento no editor.
- **Modelos de documento** (`utils/doc_templates`, guia em `docs/modelos-documento.md`): documentos de layout conhecido são reconhecidos por frases fixas e tarjados pelos rótulos **sem IA (zero token)**. Um modelo **aprovado** com "dispensar a IA" deixa de chamar a IA de visão de endereços nas páginas em que todos os campos obrigatórios foram achados. Depois vem a **inspeção** (`DOC_TEMPLATE_INSPECTION`): `agente` lê o texto com as tarjas já trocadas por █ e aponta o que ficou de fora (só acrescenta; falha = revisão); `regras` não gasta token, marca rótulos com valor sem tarja e manda para revisão a página sem IA. Modelos parecidos: nenhum é aplicado. Nada disso aprova o documento.
- **Gerenciador de modelos** (Administração › Modelos de documento e menu ⋮ da tarefa): rascunho a partir de um documento revisado (tarjas viram campos ancorados em rótulos; títulos viram frases de reconhecimento), com ajuda opcional da IA sobre o texto **mascarado** (tarjas e dígitos escondidos; sugestão que não existe no texto é descartada); testar no documento (só contagens); salvar como rascunho; aprovar; importar/exportar JSON. API `/doc-templates/*` como router separado.
- **Implantação modular** (`docs/deploy.md`): `deploy/k8s` com kustomize (app com 1 réplica e `Recreate`, Ollama opcional em outro pod, *Pod Security* restrito, NetworkPolicies que fecham a rede por padrão, segredo obrigatório) e `docker compose --profile ollama` com a IA em outro contêiner.
- O agente do segundo olhar também reconhece endereço residencial (usado só na inspeção dos modelos).
- **Validação de provedor de IA** (`python -m benchmarks.provider_check`, procedimento em `docs/procedimento-ia-externa.md`): roda o caminho real contra o provedor com dados fictícios. Confere a trava de saída, a conexão, o JSON, a visão de endereços, o agente com ferramentas, a inspeção de modelo (repetida; exige acerto em todas as repetições para "dispensar a IA") e o rascunho com IA, e grava um relatório sem a chave. Testes ao vivo opcionais: `pytest -m live` (`PRIVIO_LIVE_AI=1`), nunca no CI.

- **Limite de uso do provedor de IA** (`utils/ratelimit.py`), em Administração › IA e provedores:
  - **Limitador de pedidos por minuto** (`AI_REQUESTS_PER_MINUTE`), ligado por padrão em provedor externo (12 por minuto; medido no plano gratuito do Gemini Flash-Lite: 15). Conta todos os documentos em processamento juntos, por servidor: cada pedido espera a vez. Mais lento, mas sem recusas. Nesta rede, sem limite salvo configuração; `0` desliga.
  - `AI_LIMIT_ACTION=pendente`: quando a cota acaba, o documento fica **Pendente** (sem PDF, nunca "Concluído") e o serviço o processa de novo depois de `AI_LIMIT_RETRY_MINUTES` (padrão 60), até `AI_LIMIT_MAX_RETRIES` vezes (padrão 24); depois disso segue para revisão. O padrão continua `revisao`.
  - O cartão mostra "Pendente: limite de uso da IA. Nova tentativa às HH:MM"; no MCP a situação é `pendente` e `sentry_wait` volta na hora.
- O roteiro de validação roda a 10 pedidos por minuto (`--por-minuto`), informa `limite_de_uso_esgotado` e separa repetição "não medida" de erro do modelo.

### Corrigido (achado ao testar com o Gemini)
- O agente devolvia o tipo com o nome mostrado no pedido ("endereço residencial de pessoa"), que não era reconhecido; o achado era descartado em silêncio. Agora vale.
- O pedido do agente passou a listar os identificadores dos tipos, a pedir o texto corrido e a ignorar trechos █. Com o pedido antigo, o Gemini Flash-Lite achou o endereço solto em 2 de 3 tentativas.
- Limite de uso do provedor (HTTP 429): o agente e o cliente de IA esperam o tempo pedido (`Retry-After` ou `retryDelay` do Gemini, até 60 s) e tentam de novo até 2 vezes. Se o limite continuar, a página vai para revisão.
- Na IA principal, recusa por limite de uso contava como falha no disjuntor: três seguidas desligavam o servidor por 120 s e as páginas seguintes iam direto para revisão. Agora não conta.
- Cota esgotada (limite diário, conta sem crédito, sem indicação de espera) não é mais esperada à toa: a chamada desiste na hora.

### Corrigido (varredura de bugs)
Casos em que dado pessoal podia ficar visível com o documento "Concluído":
- Tarja final em página girada (`/Rotate`) caía em outro lugar; agora fica onde o revisor desenhou (testado em 0, 90, 180 e 270 graus).
- Valor de campo de formulário do PDF continuava extraível sob a tarja; o campo é removido.
- Caixa do editor redimensionada para cima/esquerda (coordenadas invertidas) era ignorada; agora é normalizada no editor e no servidor. Tarja que não pode ser aplicada manda para revisão, e `/update-redactions` recusa coordenadas inválidas (422).
- Busca de CPF (detecção e as duas verificações finais): CPF quebrado no fim da linha ("529.982.247-" / "25"), com letra no lugar de dígito pelo OCR (O/0, l/1, S/5, B/8) e CPF digitado com espaços ao lado de outro número (o filtro de CNPJ/CNS o descartava).
- Endereço localizado só em parte (palavras de outra coluna ou campo no meio) agora pede revisão.
- Auditoria de assinaturas aceitava resposta da IA fora do formato como "nenhum CPF visível"; agora tarja o recorte e pede revisão. CPF visto pela IA também pede revisão. Respostas da IA que não são objeto JSON contam como inválidas (a reserva confere).
- Reprocessar com rascunho salvo no editor deixava as sugestões novas fora do PDF aprovado; agora elas entram no rascunho e o documento vai para revisão.
- Nomes, segundo olhar e texto dos endereços liam só a camada de texto quando ela era rala (carimbo de assinatura digital numa digitalização); agora usam o OCR da página.
- Com `VERIFY_OCR=0`, página com imagem e um pouco de texto passava sem verificação; agora fica "não verificada" (revisão).
- Decisor local que devolve menos vereditos que endereços pede revisão.
- Detecção por regra (`utils/detect`): um número rejeitado pelo dígito verificador "engolia" o valor verdadeiro que começava dentro dele (título de eleitor e cartão depois de um ano); conta bancária com agência, pontos ou dígito separado era tarjada pela metade e rótulos como "Conta-corrente" não eram reconhecidos; rótulo de telefone no plural ("Telefones:") e o segundo número de uma lista; RG em rótulo combinado ("RG/CPF:") ou com espaços; cartões Amex e Diners; CNS com pontos, PIS com " - ", placa com "l", passaporte em minúsculas, e-mail partido pelo OCR; contexto desalinhado por travessão ou ligadura antes do valor; detector de nomes cortando um nome que começa como cargo ("Senhorinha") ou termina com uma palavra de cargo. Revocação do corpus fictício continua 100% em todos os tipos.
- Máscara de CPF nos logs e nos arquivos de pedido à IA: separador " - ", travessão, sublinhado e dígitos em caixinhas ("5 2 9 ...").
- Decisor local: probabilidade inválida (NaN, fora de 0 a 1) agora pede revisão. Retorno do revisor reescala as caixas do editor para a largura da página antes de virar exemplo.
- Modelos de documento: campo obrigatório com rótulo e sem valor contava como achado (e dispensava a IA de visão); um modelo genérico podia vencer um específico (agora, mais de um reconhecido = nenhum aplicado); outro rótulo sem dois-pontos dentro do valor cortava a tarja; campo restrito a página inexistente não era dado como faltando; palavra colada ao rótulo ia sem máscara para a IA.

Segurança e robustez:
- Servidor MCP: `task_id` só no formato UUID, antes de qualquer pedido ao serviço; o download confere que a resposta é um PDF; entrada malformada vira erro da ferramenta em vez de derrubar o servidor.
- Trava de saída: o host conferido é o mesmo a que o cliente HTTP se conecta; pedidos com conteúdo não seguem redirecionamento. A Administração recusa URL com usuário/senha, espaço ou barra invertida, e usuário/senha numa URL nunca aparecem em `/health/ai`.
- Trocar o servidor principal apaga também a chave do segundo olhar quando ele usa o mesmo servidor.
- Com `API_TOKEN`, escritas vindas de outra origem do mesmo host (outra porta) são recusadas.
- Administração aceitava fração em itens inteiros (`MAX_PARALLEL_TASKS=2.5`), o que impedia o serviço de subir; agora recusa, e um valor ruim já salvo cai no padrão.
- Gatekeeper: `/api/info` chega ao app (o selo mostrava `LOCAL PROCESSING` com IA externa); prazo do repasse de 30 s para 300 s; clientes da API recebem erro 502/503 em vez de uma página HTML com 200.
- Worker que morre sem avisar deixa a tarefa como erro (antes ficava "processando" para sempre); início de worker, fila e `/tasks` sob a mesma trava; reprocessar ou finalizar uma tarefa na fila dá 409 sem apagar o estado.
- Trava da IA com prazo (`AI_LOCK_TIMEOUT`, padrão 3600 s): um worker morto não prende os outros; o limitador de pedidos tem trava própria.
- Agente: resposta fora do formato falha só a página; um valor achado é tarjado em todas as ocorrências.
- Nome de arquivo longo no Windows: o nome no disco fica curto (o mostrado continua inteiro). `doc_out_dir` não sai mais em `/tasks`.
- Linha de comando: pega `.PDF` em maiúsculas.

### Atenção ao atualizar
- **Servidor de IA em endereço público agora é bloqueado** até a liberação (`AI_ALLOW_EXTERNAL=1` ou a caixa na Administração). Um servidor da organização que o DNS resolve para IP privado continua funcionando sem mudança; se ele tiver IP público, as páginas passam a ir para revisão com a mensagem "externo bloqueado" até a liberação.
- `/download/{id}?final=true` (novo) só entrega o PDF de documentos aprovados **depois** desta versão: para os antigos, aplique a proteção de novo no editor. O download do portal não muda.
- Na Administração, trocar o endereço de um servidor por outro host apaga a chave salva dele e desliga a liberação de IA externa (a chave de um provedor nunca segue para outro; destino novo pede nova confirmação).
- Servidor de IA que responde com redirecionamento (3xx) passa a dar erro (a página vai para revisão): aponte para o endereço final.
- Modelos de documento: se mais de um modelo for reconhecido no mesmo documento, nenhum é aplicado (antes, o de maior pontuação ganhava quando a diferença passava de 10 pontos). Confira modelos com frases parecidas.
- Com `VERIFY_OCR=0`, toda página com imagem vai para revisão (antes, só as páginas sem nenhum texto).
- A Administração recusa fração em itens inteiros e URL com usuário/senha, espaço ou barra invertida. Com `API_TOKEN`, o navegador só grava a partir da mesma origem.
- Pelo gatekeeper, clientes da API recebem 502/503 (JSON) quando o app está fora, em vez da página do painel.
- Reprocessar um documento com rascunho salvo soma as sugestões novas ao rascunho e manda para revisão.

### Alterado
- `/tasks` não devolve mais o caminho do arquivo no servidor (`input_path`).
- A linha de comando (`main.py`) também aplica o que foi salvo na Administração.
- `/docs` e `/redoc` do FastAPI desligados (carregavam scripts de CDN); o contrato segue em `/openapi.json`.
- O `HEALTHCHECK` do Docker usa `/healthz` (antes recebia 401 com `API_TOKEN`). `/healthz` também não confere o `Host` (a sonda do Kubernetes chega com o IP do pod).
- Cliente de IA: erro 429 espera o `Retry-After` (até 30 s); erro 400 sobre `max_tokens`/`temperature` (modelos de raciocínio) é repetido uma vez com `max_completion_tokens`; cabeçalhos da Anthropic; servidores externos nunca recebem pedido de descarga de modelo; o teste de saúde de provedores externos não exige o modelo na lista (apelidos).
- O segundo olhar usa a chave da IA principal quando não tem servidor próprio.

## [5.6.1] - 2026-10-05

Interface mais orgânica e responsiva, a partir de prints relatados: opções do envio em botões num painel recolhível
(a lista de tarefas não fica mais espremida), uma etiqueta por trecho no editor (desenhada dentro da caixa), CPF com
a etiqueta "CPF", cabeçalho do editor com respiro e grupos de botões que se adaptam da tela grande ao celular, e
dependências atualizadas. Testes de interface em sete larguras, em português e em inglês, conferidos com defeitos
introduzidos de propósito.

### Corrigido
- **Layout da barra lateral (relatado com print):** o painel de opções e os quatro botões espremiam a lista de tarefas (dois cartões e meio, o terceiro cortado) e a caixa de seleção cortava o nome do perfil. Agora as opções são **botões** (perfis em pílulas com nome curto; "Procurar nomes" e "Baixa qualidade" liga/desliga) num painel **recolhível** que, fechado, mostra só o resumo das escolhas; "Processar todos", "Excluir todos" e "Documentação" ficam numa linha; o rodapé tem teto de 60% da altura da tela. Acessível pelo teclado (grupo de rádio com setas). Testes de regressão do espaço da lista e da largura dos botões.
- **Etiquetas das tarjas no editor (relatado com print):** cada palavra de um endereço ganhava a sua etiqueta, e as várias leituras do OCR empilhavam etiquetas iguais sobre o mesmo dado; agora há **uma etiqueta por trecho**, agrupada sem depender da ordem das caixas (alturas que diferiam por um pixel quebravam o agrupamento), tolerando uma palavra curta não tarjada no meio; a descrição continua em cada caixa para leitores de tela. A etiqueta passou a ficar **dentro** da caixa: desenhada acima, a etiqueta da caixa de baixo parecia uma tarja sobre a palavra da linha de cima. Tarjas de CPF apareciam como "POSSÍVEL ASSINATURA" (tipo interno herdado); agora mostram "CPF" e só a assinatura de verdade (detector YOLO ou caixa desenhada como assinatura) é etiquetada assim.
- **Cabeçalho do editor responsivo (relatado com print):** os botões ficavam grudados no topo (sem espaçamento vertical, quebravam em linhas coladas na borda). Agora o nome do documento e o selo/idioma ficam na 1ª linha e as ferramentas numa linha própria, em grupos (visualização · seleção/nova tarja · salvar · ações principais à direita, "Aplicar proteção" por último) que quebram com espaço. Entre 769 e 1024 px o botão ☰ cobria o nome do documento; no celular os botões ficam compactos em duas colunas, o zoom não colide mais com o paginador e as etiquetas aparecem só na caixa selecionada. Testes em sete larguras (1911 a 390 px): respiro no topo, botões dentro da tela, sem sobreposição, sem texto cortado ou quebrado, sem rolagem horizontal.
- Os botões "Processar todos / Excluir todos / Documentação" cortavam o texto quando a fonte do navegador era mais larga; agora quebram linha.
- O cartão da tarefa mostrava o código interno do perfil ("lgpd_publicacao") até o próximo ciclo de atualização quando as tarefas chegavam antes das opções.

### Dependências
- FastAPI 0.142.2, Uvicorn 0.54.0, Pillow 12.3.0, python-dotenv 1.2.4 e Ultralytics 8.4.171 (atualizações do Dependabot), conferidas com a suíte completa (808 testes, incluindo a interface) num ambiente isolado com essas versões e com o detector de assinaturas real carregando e rodando. Ações do GitHub (checkout, setup-python, upload-artifact) na v7.

## [5.6.0] - 2026-10-05

Escolhas por documento na interface e o segundo olhar. O painel **Opções do próximo envio** define, para cada PDF,
o perfil de proteção, se procura nomes e se é um documento de baixa qualidade (leitura extra de OCR + segundo olhar);
o servidor valida a escolha e cada tarefa aplica as opções só no próprio processo. O **segundo olhar** é um agente
local curto, pela API, que revê as páginas em dúvida e só acrescenta proteção (valor precisa passar nos validadores e
ser localizado no OCR). **Sem mudança de comportamento** para quem não usa as novidades: os padrões continuam os do
`.env`.

### Adicionado
- **Opções por documento na interface:** painel "Opções do próximo envio" com o perfil de proteção, "Procurar nomes" e "Documento de baixa qualidade" (leitura extra de OCR + segundo olhar). O que não está disponível aparece desativado com o motivo; o servidor valida a escolha (`GET /options`, campos `perfil`, `nomes` e `baixa_qualidade` no upload) e cada tarefa aplica as opções só no próprio processo. O cartão mostra as opções usadas e reprocessar as mantém. Testes de interface com contratestes (escolha forçada pelo navegador é recusada pelo servidor, texto do servidor nunca vira HTML, falha ao carregar as opções não impede o envio), conferidos com defeitos introduzidos de propósito.
- **Segundo olhar** (`SECOND_LOOK=1`, `utils/second_look.py`): um agente local curto, pela API (`/v1/chat/completions`, qualquer servidor compatível), revê as páginas que já iam para revisão (ou todas) com duas ferramentas de leitura e instruções enxutas, e só **acrescenta** proteção: cada valor devolvido precisa ser localizado nas palavras do OCR (o que não existir é descartado), só os tipos do perfil contam, tarja acrescentada vem com aviso para conferir, e falha do agente manda a página para revisão. Benchmark em `benchmarks/second_look_eval.py` e docs/benchmarks.md.

## [5.5.0] - 2026-10-05

Menos regra fixa no código e mais medição: regras e limiares como dados, corpus de avaliação por tipo, nomes com
GLiNER (opcional), qualquer servidor de IA pela API (Ollama, LM Studio, vLLM, servidor da organização) com IA reserva
e disjuntor, pedido de endereços que acha 3x mais endereços pessoais, leitura extra de OCR, fila de tarefas e uma
rodada de testes com 7 documentos reais, vários OCRs, IAs de OCR, LLMs e o procedimento sob pressão.
**Mudanças de comportamento:** o pedido de endereços mudou (`ADDRESS_PROMPT=legado` volta ao antigo); no máximo 2
documentos processam ao mesmo tempo (`MAX_PARALLEL_TASKS`); páginas gigantes são lidas em DPI menor e vão para revisão.

### Adicionado (testes com vários OCRs, IAs de OCR, LLMs e o procedimento sob pressão)
- **Qualquer servidor de IA, pela API:** Ollama ou qualquer servidor no padrão da OpenAI (LM Studio, vLLM, llama.cpp, LocalAI, servidor da organização com chave). `AI_PROVIDER`, `AI_BASE_URL`, `AI_API_KEY`, modelos e tempo limite próprios; as variáveis `OLLAMA_*` continuam valendo.
- **IA reserva, disjuntor e verificação cruzada:** a reserva (`AI_SECONDARY_*`) assume quando a principal cai; o disjuntor desliga o servidor que falha seguidamente (estado compartilhado entre tarefas), testa a volta pela API (lista de modelos) e descarrega o modelo pela API (Ollama `keep_alive: 0`, LM Studio `/api/v1/models/unload`); `AI_CROSS_CHECK=1` faz a reserva conferir cada página (respostas somadas; discordância vira "pessoal" e revisão). Medido ao vivo com a principal travada: a primeira página paga as tentativas, as seguintes vão direto para a reserva (~12 s por página em vez de até 30 min). Rota `GET /health/ai`.
- **Pedido de endereços novo:** o modelo COPIA os endereços do texto da página (texto digital ou OCR) em vez de "montar um endereço completo e estruturado". Nos 7 documentos reais testados: 3x mais endereços pessoais localizados (30 contra 10), sem endereço inventado. `ADDRESS_PROMPT=legado` volta ao antigo. Medido também: a saída estruturada (esquema JSON) fazia o modelo devolver pedaços soltos ("Bloco A") e foi descartada.
- **Leitura extra de OCR opcional** (`OCR_EXTRA_ENGINE=rapidocr`, `pip install -e ".[ocr-extra]"`), somada às duas do Tesseract, em paralelo. Nos documentos reais achou um telefone e um e-mail que o Tesseract leu deformados (ficariam sem tarja).
- **Fila de tarefas** (`MAX_PARALLEL_TASKS`, padrão 2): vários uploads ao mesmo tempo não abrem um processo pesado cada; os demais ficam "Na fila".
- Ferramentas de medição: `benchmarks/ocr_compare.py` (motores de OCR e modelos de visão sob condições de imagem cada vez piores), `benchmarks/address_eval.py` (LLM × pedido de endereços), `benchmarks/stress.py` (pressão pela API do app: simultâneos, documento grande, digitalização péssima, PDFs hostis).

### Corrigido (achados do teste de pressão)
- **Página gigante derrubava a máquina:** um PDF com página de 200 x 200 polegadas levou um processo a 35-40 GB de RAM (renderização e verificação a 300 DPI). Agora a maior página tem teto de pixels (`MAX_PAGE_MEGAPIXELS`, padrão 150: um mapa A0 continua a 300 DPI); acima disso o documento inteiro é lido em DPI menor, de forma determinística (finalização usa o mesmo), e vai para revisão.
- **PDF danificado saía "Concluído":** o leitor reparava o arquivo em silêncio; agora vai para revisão. PDF com senha ganha mensagem clara.
- O docTR (testado, não adotado) vazava ~140 threads por página; registrado no comparador.

### Adicionado (menos regra fixa no código, mais medição)
- **Regras, listas e limiares como dados versionados** (`utils/detect/data/*.json`, lidos e validados por `utils/detect/config.py`): palavras de contexto de cada detector, palavras nunca tarjadas como endereço, limiares do casamento de endereços, do filtro de ruído de OCR, da confiança dos nomes e das sugestões do revisor. Formato errado dá erro claro ao carregar.
- **Corpus fictício de PII com métricas por tipo** (`benchmarks/pii_corpus.py`, `python -m benchmarks.pii_eval [--ocr]`): cinco modelos de documento com resposta conhecida e iscas; revocação e precisão por tipo, em texto direto ou desenhado em imagem com ruído e lido pelo OCR real. Portão nos testes (`tests/test_pii_corpus_gate.py`). Resultados em `docs/benchmarks.md`.
- **Retorno do revisor por detector** (com `LEARNING_ENABLED=1`): ao aplicar a proteção, conta por tipo as tarjas sugeridas que o revisor manteve, removeu ou acrescentou (só contagens, ligadas à tarefa e apagadas com ela). `python -m utils.decisions detectores` mostra a precisão observada e **sugestões**; nada é mudado sozinho.
- **Nomes de pessoa e filiação com GLiNER local, opcional** (`pip install -e ".[nomes]"`, `NER_ENGINE=gliner`; modelo multilíngue com commit fixado): confiança alta vira tarja sugerida, média vira região a revisar; detector ligado que falha manda o documento para revisão. Vale nos perfis que pedem nomes (`lgpd_publicacao`, `gdpr`, `saude_hipaa`). Novo estado "opcional" no catálogo e campo `rodando` em `/policy/profiles`.

### Corrigido (7 documentos reais testados, 69 páginas; analisados só por formato, sem expor valores)
- **Falso alarme "CPF no original sem tarja"** (2 documentos): duas coordenadas geográficas em graus lidas lado a lado pelo OCR da verificação formavam um número que passa no dígito verificador de CPF. Coordenadas em graus, o começo de CNPJ cortado por borda de tabela ("12.345.678/0001-" + "|") e o número único de processo federal ("12345.123456/2018-11") nunca são lidos como CPF. Esses dois últimos viravam tarja de "CPF" a mais. O CPF verdadeiro ao lado continua achado (teste).
- **E-mail tarjado pela metade:** quando o OCR lia o "@" como "(" + uma letra fora da lista, ou perdia o "@" e separava o nome, só o domínio era tarjado e o nome antes do "@" ficava visível. Depois de "e-mail", a tarja cobre o endereço inteiro (o rótulo "e-mail" nunca entra).
- **Nomes: papéis marcados como pessoa.** O modelo marcava "analista" (25 vezes num parecer), "síndico", "interessado", "devedor", "beneficiário", "o(s)", "Responsável Técnico"... Papéis, cargos e conectores (lista em `contextos.json`, `nunca_nome`) não viram nome e saem das pontas do nome antes da tarja. Nos documentos testados: palavras soltas marcadas como nome 51 → 14; conferido palavra a palavra que nenhum nome verdadeiro deixou de ser marcado.
- O modelo de nomes carrega **em segundo plano durante o OCR** (antes: ~35 s parados em cada tarefa, até em documento de 1 página).
- O alerta de endereços não localizados contava repetições do LLM ("9 endereços" com 4 distintos).
- Novo modelo fictício `parecer_tecnico` no corpus com esses formatos.

### Corrigido (achados do corpus)
- **E-mail em documento digitalizado:** o Tesseract em português lê "@" como "(D"/"(W" (até em imagem limpa), e e-mails passavam sem tarja (revocação 0% no modo OCR). A regra aceita essas variantes, o nome partido pelo OCR e, logo depois de "e-mail", o "@" trocado por uma letra. 0% → 100%.
- **Placa com "O" no lugar de "0"** (leitura do OCR) é aceita quando há "placa"/"veículo" perto. 88% → 100% no modo OCR.
- **CPF:** dígitos vizinhos ("unidade 14A, CPF ...", "CPF ... PIS ...") deslocavam a janela e o CPF verdadeiro era pulado; agora há uma passada alinhada às palavras antes da varredura antiga. O pré-filtro de CNPJ só exclui número alinhado às palavras (antes podia apagar um CPF verdadeiro), e um pedaço do Cartão SUS (15 dígitos) não vira mais CPF.
- O novo padrão de e-mail chegou a ter retrocesso quadrático numa palavra gigante ("12.12.12..."); pego pela contra-análise e corrigido antes de publicar.

### Testes
- 710 testes (inclui interface): portão do corpus, regressões de OCR ("@" como "(D", placa com "O", pedaço de CNS), retorno por detector e detector de nomes com motor falso (sem baixar modelo). O GLiNER real foi conferido à parte em texto fictício: 5 de 5 nomes e a filiação, sem marcar órgão nem rua.

### Corrigido (a partir de um documento real processado)
- **Endereços localizados como trecho, não como "saco de palavras".** Antes, qualquer palavra do endereço devolvido pelo LLM era tarjada em **qualquer ponto da página**: "à", números soltos, o nome da cidade e até **datas** que continham um número do endereço. Agora o endereço é localizado como trecho contínuo do OCR (tolerante a erros de OCR, palavras partidas e abreviações como "Jd."/"Pres."); datas e conectores nunca são tarjados; endereço pessoal que não é localizado com segurança manda a página para **revisão** em vez de espalhar tarjas. No documento de teste: tarjas de endereço 72 → 47, nenhuma data nem "à" solto.
- "À", "ÀS", "AS", "OS" passam a ser conectores protegidos (o acento fazia "à" escapar da proteção).
- **CPF falso a partir de valor em reais ou de ruído de OCR:** valores como "1.500,00" e palavras de ruído ("a1b", letras e dígitos embaralhados) não completam mais um "CPF" com dígitos vizinhos; palavra com exatamente 11 dígitos continua valendo (CPF lido com vírgula no lugar do hífen). No documento de teste: CPFs 6 → 5 (todos verdadeiros) e o alerta falso "CPF ainda detectável no PDF final" sumiu.

## [5.4.0] - 2026-10-04

Critérios nacionais e internacionais de dados pessoais (catálogo de PII e perfis de política), ~4,7× mais rápido
num documento real, regiões a revisar desenhadas na página e uma rodada de revisão independente com contra-análise.
**Mudanças de comportamento:** `BASE_DPI` padrão passou de 1000 para 300 (medido: melhor revocação); quem define
`BASE_DPI`/`YOLO_CROP_PADDING` no `.env` deve revisar os valores. O perfil padrão (`cpf_endereco`) mantém o
comportamento anterior; os novos tipos valem ao escolher outro perfil em `POLICY_PROFILE`.

### Corrigido (revisão independente e contra-análise)
- **Páginas rotacionadas:** a passada de texto digital usava as coordenadas da página sem rotação e colocaria tarjas no lugar errado (o dado ficaria visível); agora aplica a rotação (`page_words`). Testado sobre os pixels desenhados.
- Registros de erro do uvicorn voltaram a mascarar CPF e `token=` também no *traceback* e em argumentos que não são texto.
- A região "Revisar aqui" não bloqueia mais o clique nas tarjas embaixo dela; trocar de documento não dispara mais um "processamento concluído" falso; erro no processamento não mostra mensagem de sucesso.
- Telefone: não pega mais o final de um número maior; aceita fixo sem DDD com palavra de contexto e DDD com zero de operadora "(065)" coberto inteiro. Data de nascimento aceita "1º de março"; outra data ou rótulo entre "nascimento" e o valor (ex.: "Emissão") anula o contexto. CPF logo depois de "RG" não é mais contado como RG. Placa no formato antigo ("ISO-9001") passa a exigir contexto.
- Uma região a revisar por ocorrência (antes, uma caixa podia cobrir a página inteira); regiões sempre limitadas à página.
- Finalizar ("Aplicar proteção") não apaga mais o resumo de tipos e os tempos do processamento; os rótulos das tarjas atravessam a finalização (antes telefone/e-mail viravam "Endereço residencial" no modo legado).
- Verificação pós-tarja em lotes: limita imagens temporárias em disco e o progresso avança durante o OCR.
- `BASE_DPI` lido num só lugar (`render_dpi`), com a mesma faixa válida em todo o pipeline.

### Testes
- 66 casos de contra-análise (`tests/test_counter_analysis.py`): falsos positivos em texto administrativo comum, formatos reais, lixo aleatório, páginas gigantes com tempo limitado (sem regex explosivo), acentos e caracteres especiais, concorrência, matriz de perfis e uma regressão por achado da revisão. Vetores fixos conferidos à mão para PIS, CNS, título de eleitor (incluindo a regra de SP/MG) e números de teste públicos de cartão.
- Testes que comprovadamente falham sem a correção (verificado para rotação e para o clique sob a região).

### Adicionado (critérios de dados pessoais)
- **Catálogo de PII** (`utils/detect/catalog.py`, documentação gerada em `docs/catalogo-pii.md`): 30 tipos com enquadramento em **LGPD** (art. 5º, I e II), **GDPR** (art. 4, 9 e 10), **ISO/IEC 29100**, **NIST SP 800-122** e **HIPAA Safe Harbor**, nível (identificador direto, dado pessoal, sensível, indireto) e forma de detecção. Tipos sem detector ficam como *planejados* (nomes, rostos, dados sensíveis).
- **Perfis de política** (`POLICY_PROFILE`): `cpf_endereco` (padrão, comportamento original), `lgpd_publicacao` (LAI), `lgpd_interno`, `gdpr` e `saude_hipaa`; cada tipo é tarjado (sugestão para revisão) ou só alertado (região a revisar). O endereço residencial também obedece ao perfil.
- **Novos detectores por regra** sobre as três leituras de cada página (OCR padrão, OCR esparso, texto digital): RG, CNH, título de eleitor, PIS/NIS, Cartão SUS, passaporte, CTPS, telefone, e-mail, dados bancários, chave Pix, data de nascimento, placa e IP. Cada regra exige dígito verificador oficial, formato distintivo ou palavra de contexto; a palavra de contexto nunca é tarjada.
- O editor mostra o **tipo** de cada tarja sugerida (ex.: "Possível Telefone"), e o cartão da tarefa mostra o **resumo dos tipos encontrados** (quantidades, nunca os valores).
- API só de leitura `GET /policy/catalog` e `GET /policy/profiles` (contrato de um futuro serviço SENTRY Detect).
- No documento real de teste, o perfil `lgpd_publicacao` passou a encontrar RG e telefone, antes não tarjados.

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

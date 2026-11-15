# Procedimento: validar um provedor de IA antes de usar com documentos reais

Use este procedimento antes de apontar a IA para um provedor na nuvem (Gemini, OpenAI, Anthropic...) ou para um
servidor novo. Ele roda o caminho de verdade do projeto contra o provedor, **só com dados fictícios** gerados na
hora, e diz o que pode ser ligado com segurança. O roteiro não aceita PDF de entrada, de propósito.

## 1. Antes de começar

- **Chave só em variável de ambiente** (ex.: `GEMINI_API_KEY`). Nunca no código, na linha de comando, em
  arquivo versionado ou em print. O roteiro recebe o **nome** da variável.
- **Plano do provedor.** No nível gratuito, os termos do provedor podem permitir o uso do conteúdo enviado para
  melhorar os produtos dele. Por isso este procedimento só envia dados fictícios. Para documentos reais, confira
  os termos e o contrato vigentes (retenção, treino, região) com a sua organização.
- **Limite de uso (HTTP 429).** Medido no plano gratuito do Gemini Flash-Lite: **15 pedidos por minuto**, e o
  provedor pede cerca de 36 s de espera. O projeto trata dois casos:
  - *por minuto:* espera o tempo pedido (até 60 s) e tenta de novo;
  - *cota esgotada* (diária, sem crédito, ou limite que continuou depois das novas tentativas): a página vai para
    revisão ou, se o administrador escolher **pendente**, o documento fica pendente, sem PDF, e é refeito sozinho
    depois ([configuração](configuration.md), `AI_LIMIT_ACTION`).
  - Para não bater no limite, o portal limita os pedidos a um provedor externo a **12 por minuto** por padrão,
    somando todos os documentos em processamento. Ajuste em Administração › IA e provedores › **Pedidos por
    minuto** (mais alto com plano pago). O roteiro roda a 10 por minuto (`--por-minuto`).

## 2. Rodar a verificação

```bash
python -m benchmarks.provider_check --preset gemini --key-env GEMINI_API_KEY --model gemini-flash-lite-latest
```

Sem `--preset`, o roteiro usa a configuração atual (`.env` + Administração). O relatório JSON vai para `output/`,
fora do git, com tempos, tokens e resultados. Ele não guarda a chave nem o texto das respostas. O campo
`limite_de_uso_esgotado` diz se algum pedido foi recusado por limite mesmo depois da espera; nesse caso as
repetições da inspeção aparecem como "não medidas" e a verificação precisa ser rodada de novo.

| Verificação | O que prova | Critério |
|---|---|---|
| `trava_de_saida` | Sem `AI_ALLOW_EXTERNAL=1`, a chamada a um destino externo é bloqueada antes de sair | Bloqueada e nada enviado |
| `conexao_e_chave` | Endereço, chave e lista de modelos pela API | Resposta 200 |
| `chat_json` | O modelo responde JSON no formato que o projeto lê | `{"ok": true}` |
| `visao_enderecos` | O pedido real de endereços (imagem + texto) acha e classifica o endereço residencial fictício | Endereço "pessoal" encontrado |
| `agente_ferramentas` | O agente do segundo olhar usa as ferramentas (`ler_pagina`) e acha o CPF fictício | CPF apontado |
| `inspecao_modelo` | O agente lê um texto já tarjado (█) e aponta o endereço que ficou de fora. **Repete 5 vezes** (`--repeticoes`) | **Todas** as repetições certas e nada apontado dentro de █ |
| `rascunho_modelo_ia` | Rascunho de modelo de documento com ajuda da IA, sobre texto mascarado | Sugestões conferidas no texto e rascunho válido |
| `pipeline_completo` | Processamento inteiro | Pulada sem Tesseract; rode o passo 4 |

Código de saída `0` = aprovado; `1` = alguma falha.

## 3. Testes automáticos ao vivo (opcional)

Os mesmos pontos viram testes `pytest` que nunca rodam no CI nem por padrão:

```bash
PRIVIO_LIVE_AI=1 PRIVIO_LIVE_PRESET=gemini PRIVIO_LIVE_KEY_ENV=GEMINI_API_KEY PRIVIO_LIVE_MODEL=gemini-flash-lite-latest pytest -m live -v
```

Eles também conferem que a chave não aparece no relatório e que só o provedor configurado foi contatado.

## 4. Ligar no portal e conferir com o exemplo fictício

1. Em **Administração › IA e provedores**:
   - escolha o atalho (ex.: **Google Gemini**);
   - informe a chave e o modelo;
   - marque **Permitir IA fora desta rede**, confirme o aviso, salve e clique em **Testar**.
2. Gere o PDF de exemplo com `python examples/make_sample_pdf.py`, envie e confira:
   - o selo vira **EXTERNAL AI**;
   - o cartão mostra **IA externa: generativelanguage.googleapis.com** e depois "Proteção concluída · com IA
     externa" (ou "Requer revisão");
   - o CPF e o endereço residencial fictícios estão tarjados e o endereço comercial não.

## 5. Decidir o que ligar

| Resultado | Pode usar |
|---|---|
| Tudo OK | IA principal no provedor, segundo olhar e inspeção por agente. **Dispensar a IA de visão** só se `inspecao_modelo` também passar com `--repeticoes 20` em mais de uma rodada: a resposta varia de uma rodada para outra |
| `inspecao_modelo` FALHOU, o resto OK | IA principal e segundo olhar (só acrescentam, e a revisão continua). **Não** ligue "dispensar a IA de visão" nos modelos de documento |
| `visao_enderecos` ou `agente_ferramentas` FALHOU | Não use este modelo como IA principal |
| `trava_de_saida` FALHOU | Pare: é um defeito do projeto. Relate pelo SECURITY.md |

## Medições (2026-11-15, dados fictícios, plano gratuito do Gemini)

| Modelo | Conexão, JSON, visão, agente, rascunho | Inspeção (endereço fora dos campos) | Leitura |
|---|---|---|---|
| `gemini-flash-lite-latest` | OK (0,4 a 3 s por chamada) | 4/5 numa rodada; 6/6, 5/5 e 1/1 em outras. Como varia, uma rodada aprovada não basta: repita com `--repeticoes 20` | Bom para IA principal e rascunho; **não** para dispensar a IA de visão |
| `gemini-3.5-flash-lite` | — | 3/4 (uma chamada esbarrou no limite 429) | Mesmo caso |
| `gemini-flash-latest` | — | não medido: numa rodada o limite (429) interrompeu; em outra o provedor respondeu 503 (sobrecarga) e esgotou o tempo | — |

Limite observado no `gemini-flash-lite-latest` (plano gratuito): o 18º pedido em 17 s foi recusado com a cota
"pedidos por minuto, por projeto e por modelo" de 15 e espera pedida de 36 s. É limite **por minuto**, não por dia.
O limite diário desse plano não foi atingido nos testes, por isso não foi medido.

O que a verificação encontrou e já foi corrigido no código:
- o agente devolvia o tipo com o nome do pedido ("endereço residencial de pessoa") e o achado era descartado;
- o pedido do agente não dizia quais identificadores usar nem pedia o texto corrido;
- o agente não esperava o tempo pedido pelo provedor num 429;
- na IA principal, três recusas por limite desligavam o servidor pelo disjuntor por 120 s e as páginas seguintes
  iam direto para revisão. Limite de uso não conta mais como servidor fora do ar.

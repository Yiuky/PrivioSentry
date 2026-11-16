# API HTTP

O `app_service.py` é ao mesmo tempo o **portal** (editor web) e a **API**. Scripts, sistemas da organização e
agentes de IA usam as mesmas rotas do editor. O contrato completo fica em `GET /openapi.json`, servido pelo
próprio serviço. As páginas `/docs` e `/redoc` do FastAPI ficam desligadas porque carregam scripts de CDN (I-04).

> **Princípio:** a API envia, acompanha e entrega. Quem **aprova** a proteção é o revisor humano, no portal. O PDF
> só é entregue a clientes da API depois de **Aplicar proteção** e sem pendência de revisão (`?final=true`).

## Modos

| Variável (`.env`) | Efeito |
|---|---|
| `PORTAL_ENABLED=0` | Só API: `GET /` responde JSON e a interface web some. |
| `ADMIN_ENABLED=0` | Sem a tela nem a API de Administração (configuração só pelo `.env`). |
| `API_TOKEN=...` | Toda rota exige o cabeçalho `X-API-Token` (exceto `/healthz`). Obrigatório para acesso pela rede. |

Sem `API_TOKEN`, o serviço só atende `127.0.0.1` e os nomes de `ALLOWED_HOSTS`. Escritas vindas de outro site
são recusadas (`utils/net_guard.py`). Clientes de linha de comando não enviam `Origin` e passam normalmente.

## Fluxo típico

```bash
# 1. enviar (perfil, nomes e baixa_qualidade são opcionais; o servidor valida)
curl -H "X-API-Token: $SENTRY_TOKEN" -F "file=@documento.pdf" -F "perfil=cpf_endereco" http://127.0.0.1:8001/upload
# {"status": "started", "task_id": "<uuid>"}

# 2. acompanhar
curl -H "X-API-Token: $SENTRY_TOKEN" http://127.0.0.1:8001/tasks/<uuid>

# 3. revisão humana no portal: http://127.0.0.1:8001/?task=<uuid>  ->  "Aplicar proteção"

# 4. baixar o PDF aprovado (409 enquanto não houver aprovação sem pendências)
curl -H "X-API-Token: $SENTRY_TOKEN" -o protegido.pdf "http://127.0.0.1:8001/download/<uuid>?final=true"
```

## Rotas

| Rota | Uso |
|---|---|
| `GET /healthz` | Serviço no ar. Sem token e sem nenhum dado (healthcheck). |
| `GET /api/info` | Versão, modos (portal/admin/token), fila e servidores de IA externos em uso. |
| `POST /upload` | Multipart: `file` (PDF), `perfil`, `nomes` (sim/não), `baixa_qualidade` (sim/não). Devolve `task_id`. |
| `GET /tasks` · `GET /tasks/{id}` | Situação, progresso, `needs_review`, alertas, `pii_summary` (só contagens), `finalizado` (aprovado pelo revisor), `ia_externa` (destinos externos usados) e, quando o provedor de IA recusou por limite de uso com `AI_LIMIT_ACTION=pendente`, `pendente`, `pendente_ate` (hora da nova tentativa, em segundos Unix) e `pendente_tentativas`. Documento pendente recusa `/finalize` com 409. O caminho do arquivo no servidor não é devolvido. |
| `GET /download/{id}?final=true` | PDF aprovado. Sem `final`, entrega o que existir no disco, inclusive o PDF **preliminar** do processamento automático (comportamento do portal). |
| `POST /reprocess/{id}` · `DELETE /task/{id}` · `POST /purge/{id}` | Reprocessar, apagar tudo e remover as imagens sem tarja. |
| `GET /metadata/{id}` · `POST /update-redactions/{id}` · `POST /finalize-native/{id}` | Usadas pelo editor (tarjas e aprovação). `/update-redactions` recusa (422) tarja sem página numérica ou sem 4 coordenadas numéricas com área. Reprocessar ou finalizar uma tarefa que está na fila dá 409. |
| `GET /options` · `GET /policy/catalog` · `GET /policy/profiles` | Opções de envio, catálogo de tipos e perfis. |
| `GET /health/ai` | Servidores de IA (sem chaves), disjuntor e teste de saúde de cada um. |
| `GET /admin/settings` · `POST /admin/settings` | Configuração da tela Admin. Chaves de API nunca voltam. |
| `POST /admin/ai/test?papel=principal` · `GET /admin/ai/models` | Testa a IA salva (pedido curto, sem documento) e lista modelos. |
| `GET /doc-templates` · `GET/POST /doc-templates/{id}` · `POST /doc-templates/{id}/aprovar` · `DELETE /doc-templates/{id}` | Modelos de documento: listar, ler, salvar (sempre como rascunho), aprovar e apagar ([modelos-documento.md](modelos-documento.md)). Exigem a Administração ligada. |
| `POST /doc-templates/rascunho` | `{"task_id", "ia"}`: rascunho a partir das tarjas **revisadas e salvas** no editor (409 sem elas). |
| `POST /doc-templates/testar` | `{"task_id", "modelo"}`: o modelo reconhece o documento? Só pontuação, rótulos e contagens. |

Estados da tarefa e campos detalhados: [architecture.md](architecture.md#verificação-e-estados).

## Agentes de IA

Para agentes há um servidor MCP local que usa esta API e devolve ao agente só situação, contagens e caminhos.
Ver [mcp.md](mcp.md).

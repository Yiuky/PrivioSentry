# Implantação: arquitetura modular, Docker e Kubernetes

O PRIVIO SENTRY é feito de peças que podem ficar em máquinas diferentes. Elas conversam por **HTTP** e
**contratos JSON**; nenhuma depende de estar no mesmo servidor que outra, exceto o app e os processos das tarefas.

```text
                 ┌──────────── servidor/pod do app (1 réplica) ────────────┐
Navegador ─HTTPS─►  app_service.py  (portal · API · Administração · fila)   │
Agente (MCP) ────►    └─ processo por tarefa (main.SentryApp)              │
                 │        OCR Tesseract · YOLO · modelos de documento · regras │
                 └───────────────┬──────────────────────────┬──────────────┘
                                 │ HTTP (API da IA)          │ volume
                ┌────────────────▼──────────┐      ┌─────────▼──────────────────┐
                │ IA principal / reserva /   │      │ dados: tarefas, PDFs,       │
                │ segundo olhar: Ollama na   │      │ imagens, modelos de         │
                │ GPU, LM Studio, vLLM,      │      │ documento, configuração     │
                │ servidor da organização    │      │ (contém dados pessoais)     │
                │ (nuvem só se liberada)     │      └────────────────────────────┘
                └────────────────────────────┘
```

| Peça | Onde pode rodar | Como liga |
|---|---|---|
| App (portal, API, Administração, fila e processos das tarefas) | Qualquer servidor ou pod; **1 réplica** | `APP_HOST`, `API_TOKEN`; `PORTAL_ENABLED=0` para só API |
| IA de visão (endereços, assinaturas) | Outro servidor ou pod (GPU) | `AI_BASE_URL` (+ `AI_SECONDARY_*` para a reserva) |
| Agente (segundo olhar e inspeção dos modelos) | Outro servidor | `SECOND_LOOK_BASE_URL` (padrão: a IA principal) |
| Modelos de documento | Pasta no volume; entre servidores, Exportar/Importar JSON | `PRIVIO_DOC_TEMPLATES_DIR`; API `/doc-templates/*` |
| Servidor MCP | Onde o agente roda | `PRIVIO_URL` aponta para o app ([mcp.md](mcp.md)) |
| Gatekeeper (painel liga/desliga) | Só numa máquina única, sem Docker/Kubernetes | Em contêiner, quem reinicia é o orquestrador |

**Por que uma réplica.** O estado das tarefas, a fila, as sessões do navegador e a trava da IA ficam no processo
do app, e cada documento roda num subprocesso dele. Para mais vazão, aumente `MAX_PARALLEL_TASKS` e os recursos
do pod, e ponha a IA em servidores próprios. Rodar várias réplicas exige fila e estado externos (BACKLOG B-91).

## Docker Compose

```bash
docker compose up -d --build                                          # app; Ollama no host
AI_BASE_URL=http://ollama:11434 docker compose --profile ollama up -d  # app + Ollama em outro contêiner
docker compose exec ollama ollama pull gemma4:e4b
```

O Ollama do compose não publica porta: só o app o alcança. O app publica só em `127.0.0.1:8001`.

## Kubernetes

```bash
cp deploy/k8s/secrets.env.example deploy/k8s/secrets.env   # troque o API_TOKEN (arquivo fora do git)
docker build -t privio-sentry:5.6.1 .                      # ou publique no seu registro e ajuste "images"
kubectl apply -k deploy/k8s
kubectl -n privio-sentry exec deploy/ollama -- ollama pull gemma4:e4b
```

| Arquivo | O que cria |
|---|---|
| `namespace.yaml` | Namespace `privio-sentry` com *Pod Security* `restricted` |
| `config.env` | ConfigMap: pastas no volume `/data`, IA no Service `ollama`, modelos de documento, retenção |
| `secrets.env` (seu) | Secret com `API_TOKEN` (e chaves de IA, se houver). Sem ele, o `kustomize` falha de propósito |
| `storage.yaml` | Volumes: dados (**contêm dados pessoais**: use criptografia em repouso) e modelos de IA |
| `app.yaml` | App com 1 réplica, `Recreate`, usuário sem privilégio, sondas em `/healthz`, limites de CPU/memória |
| `ollama.yaml` | Servidor de IA local opcional (GPU comentada). Fixe a versão da imagem |
| `networkpolicy.yaml` | Nega tudo por padrão. Libera: DNS, ingress → app, app → ollama, ollama → 443 (baixar modelos; apague depois) |
| `ingress.example.yaml` | Exemplo de acesso HTTPS (fora do kustomize) |

**Segunda trava de rede.** Com as NetworkPolicies, o app não alcança a internet. Uma IA externa liberada na
Administração continua bloqueada até você criar uma regra de saída para o provedor, por exemplo para a porta 443
do endereço dele. São duas decisões explícitas.

**IA em outro lugar.** Para usar um servidor fora do cluster, tire `ollama.yaml` do `kustomization.yaml`, ajuste
`AI_BASE_URL` e crie a regra de saída. Um servidor da organização com IP privado não precisa de
`AI_ALLOW_EXTERNAL`.

`/healthz` não exige token nem confere o `Host`, porque a sonda chega com o IP do pod. Ele não devolve nenhum
dado.

## O que foi conferido e o que não foi

- `kubectl kustomize deploy/k8s` monta os 15 objetos e falha sem o `secrets.env`.
- `docker compose config` é válido com e sem o perfil `ollama`.
- `tests/test_deploy.py` confere réplicas, sondas, usuário, rede fechada e se as variáveis estão documentadas.
- **Não** foi aplicado num cluster de verdade, e a imagem não foi construída nem publicada (B-59). Também não foi
  conferido se o Ollama roda como usuário sem privilégio na versão que você escolher.

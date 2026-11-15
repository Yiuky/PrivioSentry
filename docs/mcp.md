# Servidor MCP local

O `sentry_mcp.py` deixa um agente de IA (Claude Code, Claude Desktop ou outro cliente MCP) usar o SENTRY Redact.
Ele roda **nesta máquina**, conversa com o cliente por stdio (JSON-RPC 2.0) e com o serviço pela [API](api.md).
Não depende de pacote novo: o protocolo é implementado no próprio arquivo.

## Configurar

1. Deixe o serviço no ar (`python app_service.py` ou o gatekeeper).
2. No cliente MCP, aponte para o Python do projeto e o script. A tela **Administração › API e agentes** mostra o
   trecho pronto, com os caminhos desta instalação:

```json
{
  "mcpServers": {
    "privio-sentry": {
      "command": "C:/privio-sentry/.venv/Scripts/python.exe",
      "args": ["C:/privio-sentry/sentry_mcp.py"],
      "env": { "PRIVIO_URL": "http://127.0.0.1:8001", "API_TOKEN": "<o mesmo do .env, se houver>" }
    }
  }
}
```

Com o Claude Code, o mesmo pela linha de comando:

```bash
claude mcp add privio-sentry -e PRIVIO_URL=http://127.0.0.1:8001 -- python sentry_mcp.py
```

## Ferramentas

| Ferramenta | O que faz |
|---|---|
| `sentry_status` | Versão, fila, modos e servidores de IA externos em uso. |
| `sentry_profiles` | Perfis de proteção e o padrão. |
| `sentry_list_documents` | Documentos e situação de cada um. |
| `sentry_submit_pdf` | Envia um PDF desta máquina (`caminho`, `perfil`, `nomes`, `baixa_qualidade`). Devolve `task_id` e o link `revisar_em`. |
| `sentry_document` | Progresso, páginas a revisar, tipos encontrados (só quantidades) e se já foi aprovado. |
| `sentry_wait` | Espera terminar (até `timeout_s`, padrão 300 s). Volta na hora se o documento ficar `pendente`. |
| `sentry_download_final` | Salva o PDF **aprovado** num arquivo ou pasta. Recusa sem aprovação e não sobrescreve sem `sobrescrever=true`. |

A `situacao` de um documento é uma destas palavras: `na_fila`, `processando`, `concluido`, `requer_revisao`,
`erro` ou `pendente`. **Pendente** quer dizer que o provedor de IA recusou por limite de uso e o administrador
pediu para esperar: não há PDF, e o serviço processa o documento de novo sozinho (pode levar horas). O agente
deve consultar mais tarde com `sentry_document`.

## O que o agente não pode fazer (de propósito)

- **Aprovar, editar tarjas, apagar ou purgar.** A aprovação é do revisor humano no portal, pelo link
  `revisar_em` (`/?task=<id>` abre o documento direto). A detecção é probabilística (I-07).
- **Ver o conteúdo.** O agente, e o modelo por trás dele, que pode estar na nuvem, recebe situação, contagens,
  números de página e caminhos. Nunca recebe texto do OCR, logs, motivos dos alertas, coordenadas das tarjas nem o
  caminho do arquivo no servidor.
- **Baixar o PDF preliminar.** O download usa `?final=true`.

Fluxo sugerido ao agente (também vai nas instruções do servidor): `sentry_submit_pdf` → `sentry_wait` → pedir ao
humano que revise no link e clique em **Aplicar proteção** → `sentry_download_final`.

# Modelo de ameaças e notas sobre a LGPD

> Notas de engenharia, não aconselhamento jurídico. Consulte o encarregado (DPO) e a assessoria jurídica da sua organização.
>
> **Posicionamento.** O PRIVIO SENTRY é um controle técnico que pode *apoiar* práticas de privacidade e segurança, incluindo práticas alinhadas à LGPD. Ele não torna um documento "adequado à LGPD": a conformidade depende de finalidade, base legal, necessidade, governança, ciclo de vida dos dados e papéis. Princípio: **A IA sugere. A política restringe. O humano confirma. O sistema registra.** (O registro de auditoria ainda não está implementado; veja a visão em [brand/LGPD_PRODUCT_POSITIONING.md](brand/LGPD_PRODUCT_POSITIONING.md) e [brand/SECURITY_AND_PRIVACY.md](brand/SECURITY_AND_PRIVACY.md).)

## Finalidade e ativos
A ferramenta ajuda a remover **dados pessoais (CPF, endereços residenciais)** de PDFs antes de serem publicados ou compartilhados, no contexto da **LGPD** brasileira (Lei 13.709/2018). Ativos a proteger:

1. Os **documentos originais** (contêm dados pessoais).
2. **Artefatos intermediários** (`output/`, `WEB_INPUT/`, logs, `99_ia_interactions/`): imagens de páginas, texto de OCR, recortes, prompts/respostas do LLM.
3. A **saída tarjada** (não deve vazar o que deveria ter sido removido).

## Decisões de projeto que reduzem o risco
* **Processamento local:** OCR, detecção e LLMs rodam na máquina do operador (Tesseract, Ultralytics, Ollama). Nenhum conteúdo de documento é enviado a APIs de terceiros. (O próprio Ollama deve apontar para um servidor local/confiável: `OLLAMA_API_URL`.)
* **Falha fechado (fail closed) + humano no circuito:** resultados incertos colocam o documento em **"Requer revisão"**; o editor permite que uma pessoa ajuste cada caixa antes de gerar o PDF final.
* **Verificação independente:** o PDF final é relido e os CPFs encontrados no original são conferidos contra as caixas de tarja.
* **Serviço endurecido:** bind em loopback por padrão, token opcional, validação de upload (magic bytes de PDF, limite de tamanho), rotas validadas por UUID, escape de HTML na UI.

## Ameaças e riscos residuais

| Ameaça | Mitigação | Risco residual |
|---|---|---|
| Dados pessoais deixados visíveis (falha do OCR/LLM) | duas passadas de OCR, YOLO + auditoria por visão, verificação, revisão obrigatória | **Real**; a revocação não é 100%. A revisão é o controle. |
| Tarja a mais esconde informação necessária | editor, revisão manual | Custo operacional |
| Dados permanecem na estrutura do PDF (texto oculto, metadados, anexos) | a tarja nativa remove o texto sob as caixas; o modo raster achata a página | Metadados/anexos/anotações **não** são limpos: inspecione separadamente |
| Vazamento por artefatos/logs | os arquivos ficam locais; os logs evitam CPFs completos (melhorias em andamento: veja o CHANGELOG) | `output/` contém imagens das páginas dos originais: apague após o uso; criptografia de disco recomendada |
| Acesso não autorizado à UI web | loopback por padrão; `API_TOKEN`; sem modelo multiusuário | Se exposta em uma rede sem HTTPS + token, qualquer pessoa pode ler os documentos |
| Outro site aberto no mesmo navegador lê ou altera o serviço local (*DNS rebinding*, CSRF) | sem `API_TOKEN`, só `Host` esperado (loopback, `APP_HOST`, `ALLOWED_HOSTS`) e recusa de POST/DELETE com `Origin` de outro site, no app e no gatekeeper (`utils/net_guard.py`); com `API_TOKEN`, cookie `SameSite=Strict` | `ALLOWED_HOSTS=*` desliga a proteção; com `API_TOKEN`, o painel do gatekeeper também exige o token |
| Token de acesso vazando por URL, histórico ou registros | `?token=` só abre a sessão e é removido da URL por redirecionamento; cookie de sessão aleatório (nunca o token); `token=` mascarado nos registros | Quem tem o token tem acesso total: não há perfis por usuário |
| Modelo YOLO adulterado (arquivo `.pt` pode executar código ao carregar) | SHA-256 do modelo do repositório fixado em `utils/yolo_engine.py`; arquivo diferente não é carregado e o documento vai para revisão; `YOLO_MODEL_SHA256` para modelos próprios | Modelo próprio sem hash definido é carregado com aviso |
| Decisor local: modelo ou pacote trocado na origem | versão exata do `laya`; commit do modelo fixado no PrivioSentry (não no pacote); modelo remoto sem commit fixo é recusado; pesos em safetensors | Exemplos de treino ficam na máquina e são apagados com a tarefa de origem |
| PDF/upload malicioso (exploits no parser, path traversal, arquivos enormes) | nomes sanitizados, verificação de magic bytes, limite de tamanho, execução sem privilégios (usuário do Docker) | Parsers de PDF/OCR são grandes superfícies de ataque: mantenha as dependências atualizadas, isole o host |
| Prompt injection via texto do documento no LLM de visão | a saída do LLM só é usada para *adicionar* tarjas (JSON de endereços); falhas fazem o pipeline falhar fechado | Um documento pode tentar suprimir a detecção (ex.: "ignore endereços"): revisão humana necessária |
| Vazamento de dados de treino pelo modelo/pesos | os pesos estão sanitizados (sem caminhos/metadados); o detector é um modelo pequeno de classe única | Não pode ser excluído matematicamente (veja o model card) |
| Cadeia de suprimentos | dependências fixadas, Dependabot, CI | Risco padrão de cadeia de suprimentos |

## Considerações sobre a LGPD (não exaustivas)
* A anonimização sob a LGPD (art. 12) exige que os dados **não possam ser reidentificados por meios razoáveis**; uma tarja visual com nomes, contexto ou metadados remanescentes ainda pode permitir a reidentificação. Avalie caso a caso.
* A LGPD distingue *dados pessoais* de *dados pessoais sensíveis* (saúde, biométricos, genéticos etc.). Esta ferramenta atualmente tem como alvo apenas números de CPF e endereços residenciais (dados pessoais); ela não detecta categorias sensíveis.
* Mantenha uma **política de retenção** para os artefatos (apague `output/`; veja `RETENTION_DAYS` em [configuration.md](configuration.md)).
* O operador continua sendo o **controlador/operador** dos dados e é responsável pela base legal, pelos registros das operações de tratamento e pelo tratamento de incidentes. Este projeto não oferece nenhuma garantia (veja LICENSE, seção 7).

# Política de segurança

*English summary at the end of this file.*

## Como relatar uma vulnerabilidade

**Não abra issue pública** para problemas de segurança.

- Use o relato privado de vulnerabilidades do GitHub:
  <https://github.com/Yiuky/PrivioSentry/security/advisories/new>.
- Se não estiver disponível, abra uma issue pública dizendo apenas "pedido de contato de segurança" (sem
  detalhes) e o mantenedor combinará um canal privado.

Inclua: versão/commit afetado, passos para reproduzir, impacto e, se tiver, uma proposta de correção.
**Não anexe documentos nem dados pessoais reais**: use amostras fictícias/sintéticas. A meta é responder em
até 7 dias e publicar correção ou mitigação em até 90 dias. Quem relatar recebe crédito, se quiser.

## Escopo

Dentro do escopo:
- O serviço web (`app_service.py`, `gatekeeper.py`, `templates/`): contorno de autenticação, *path traversal*,
  tratamento de upload, XSS, SSRF, falsificação de requisição, padrões inseguros.
- O pipeline quando **vaza dado que deveria tarjar** por causa de um bug (por exemplo, um CPF dado como
  coberto que continua no arquivo de saída, texto oculto/metadados que sobrevivem à tarja, ou dado pessoal
  gravado em log).
- Cadeia de suprimentos deste repositório (CI, Docker, dependências).

Fora do escopo:
- Os limites gerais de acurácia do OCR/LLM descritos em [docs/limitations.md](docs/limitations.md) (um CPF
  perdido numa digitalização ruim é problema de qualidade: abra uma issue normal com reprodução *sintética*).
- Vulnerabilidades em software de terceiros (Tesseract, Ollama, PyMuPDF, Ultralytics...): relate ao projeto
  de origem.
- Ataques que exigem um host já comprometido ou acesso de administrador.

## Aviso sobre dados

- Esta ferramenta **não garante anonimização**. Sempre revise a saída; veja o [README.md](README.md) e o
  [modelo de ameaças](docs/threat-model-lgpd.md).
- Os artefatos intermediários (`output/`, `WEB_INPUT/`, `documentos_finais/`) contêm **dados pessoais**
  (imagens das páginas, texto do OCR, recortes). Proteja-os com criptografia de disco e permissões de
  arquivo, e apague-os quando não forem necessários.
- Por padrão o serviço escuta só em `127.0.0.1`. Se for expô-lo, defina `API_TOKEN` e use HTTPS (proxy
  reverso); não há TLS nem controle de acesso multiusuário embutidos.
- Se algum documento real, `.env` ou credencial já foi versionado, trate-o como vazado: troque os segredos e
  reescreva o histórico antes de publicar.

## Versões suportadas

Só a última versão/`main` recebe correções de segurança.

---

## English summary

Do **not** open public issues for security problems: use GitHub private vulnerability reporting
(<https://github.com/Yiuky/PrivioSentry/security/advisories/new>) or open a public issue that only says
"security contact request". Never attach real documents or personal data. In scope: the web service, the
pipeline leaking data it was meant to redact because of a bug, and this repository's supply chain. Out of
scope: general OCR/LLM accuracy limits, third-party vulnerabilities, attacks needing a compromised host. Only
the latest `main` receives fixes. We aim to acknowledge within 7 days and fix or mitigate within 90 days.

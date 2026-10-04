<p align="center">
  <img src="assets/concept-mark.svg" alt="PRIVIO SENTRY" width="120" height="120" />
</p>

<h1 align="center">PRIVIO SENTRY</h1>

<p align="center">
  <strong>Infraestrutura local de privacidade com IA · produto atual: SENTRY Redact</strong><br>
  <em>Encontra CPFs e endereços pessoais em PDFs, sugere as tarjas e só gera o documento final depois da revisão humana</em>
</p>

<p align="center">
  <a href="https://github.com/Yiuky/privio-sentry/releases/latest"><img src="https://img.shields.io/github/v/release/Yiuky/privio-sentry?label=Vers%C3%A3o&color=2E8B57" alt="Versão"></a>
  <a href="https://github.com/Yiuky/privio-sentry/actions/workflows/ci.yml"><img src="https://github.com/Yiuky/privio-sentry/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/Python-3.10%20%7C%203.11%20%7C%203.12-3776AB.svg?logo=python&logoColor=white" alt="Python"></a>
  <a href="https://github.com/tesseract-ocr/tesseract"><img src="https://img.shields.io/badge/OCR-Tesseract%205-5C2D91.svg" alt="Tesseract OCR"></a>
  <a href="https://ollama.com/"><img src="https://img.shields.io/badge/LLM%20local-Ollama-000000.svg?logo=ollama&logoColor=white" alt="Ollama"></a>
  <a href="https://fastapi.tiangolo.com/"><img src="https://img.shields.io/badge/API-FastAPI-009688.svg?logo=fastapi&logoColor=white" alt="FastAPI"></a>
  <a href="#-limitações"><img src="https://img.shields.io/badge/Status-est%C3%A1gio%20inicial-E67E22.svg" alt="Status: estágio inicial"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/Licen%C3%A7a-AGPL--3.0--or--later-blue.svg" alt="Licença AGPL-3.0-or-later"></a>
</p>

<p align="center">
  <a href="#-instalação"><strong>⚡ Instalar</strong></a> •
  <a href="#-uso-rápido"><strong>🚀 Usar</strong></a> •
  <a href="docs/"><strong>📖 Documentação</strong></a> •
  <a href="docs/limitations.md"><strong>⚠️ Limitações</strong></a> •
  <a href="CHANGELOG.md"><strong>📋 Novidades</strong></a> •
  <a href="https://github.com/Yiuky/privio-sentry/issues/new/choose"><strong>🐞 Relatar problema</strong></a> •
  <a href="README.en.md"><strong>🌐 English</strong></a> •
  <a href="#-doe-um-café-para-o-dev"><strong>☕ Doe um café</strong></a>
</p>

---

<p align="center">
  <img src="docs/img/editor.png" alt="Editor do SENTRY Redact com tarjas sugeridas sobre CPF e endereço residencial de um formulário fictício" width="94%" />
</p>

> **Proteja os dados antes que sejam expostos.** · Detectar. Revisar. Proteger.

## 📌 O que faz

O **PRIVIO SENTRY** é um projeto *local-first* para detectar e proteger informações pessoais em documentos.
Sua primeira (e, por enquanto, única) capacidade, o **SENTRY Redact**, lê arquivos PDF, encontra **CPFs** e
**endereços pessoais (residenciais)** e prepara as tarjas para uma pessoa revisar num **editor web**. OCR,
detecção e os modelos de linguagem/visão rodam na sua máquina: a aplicação não envia o conteúdo dos
documentos a nuvens de terceiros.

> Projeto **pessoal e independente** de Joberth Firmino Gambati: não é um produto oficial de nenhuma instituição nem fala em nome dela.

> **Status: estágio inicial.** Utilizável, mas jovem: escopo restrito (CPF e endereços pessoais), medido
> apenas em dados sintéticos e ainda sem trilha de auditoria. Espere mudanças incompatíveis.

> **Marca:** o código é AGPL-3.0-or-later, mas os nomes e logotipos não são cobertos por essa licença. Veja
> [TRADEMARKS.md](TRADEMARKS.md).

## 🧭 Princípio

> **A IA sugere. A política restringe. O humano confirma. O sistema registra.**

| | Como funciona hoje |
|---|---|
| 🤖 **A IA sugere** | Os modelos só apontam detecções *potenciais*; cada uma vira uma caixa editável que a pessoa aceita, move, redimensiona ou remove |
| 🙋 **O humano confirma** | Nada vira PDF final antes da confirmação do revisor |
| 🔒 **Falha fechado** | Na dúvida (IA falhou, CPF do original sem tarja, página não verificada), o documento fica como **"Requer revisão"** em vez de "Concluído", com alertas por página |
| 📜 **Política e registro** | Hoje a política é fixa (CPF + endereços pessoais) e o único registro é o log da tarefa. Motor de políticas configurável e trilha de auditoria estão **planejados, não implementados** ([Visão](#-visão-futuro-não-implementado)) |

## ⚠️ Leia primeiro: é uma ferramenta de apoio, não uma garantia

**Esta ferramenta NÃO garante anonimização total.** A detecção por IA é probabilística. Erros de OCR,
manuscritos, digitalizações ruins, layouts incomuns e falhas dos modelos podem deixar dados pessoais
visíveis; também pode tarjar mais do que o necessário.

- Toda saída **deve ser revisada por uma pessoa** antes de ser publicada ou compartilhada.
- **"Concluído"** significa *nenhum alerta pendente nas verificações automáticas*, e não que o documento
  esteja garantidamente limpo.
- Só **CPF** e **endereços pessoais** são alvo. Nomes, telefones, e-mails, RG, dados bancários, fotos,
  QR codes, metadados etc. **não** são tarjados ([limitações](docs/limitations.md),
  [modelo de ameaças](docs/threat-model-lgpd.md)).
- Nunca use documentos reais para relatar bugs ou em testes ([SECURITY.md](SECURITY.md)).

## ⚖️ Posicionamento frente à LGPD

O PRIVIO SENTRY é um **controle técnico que pode apoiar práticas de privacidade e segurança**, inclusive as
relacionadas à **LGPD** (Lei 13.709/2018). Ele **não** é um motor de "conformidade com a LGPD", não é
aconselhamento jurídico e seu uso não torna, por si só, nenhum documento ou processo conforme: isso depende de
finalidade, base legal, necessidade, governança, ciclo de vida dos dados e papéis.

Processamento local é uma escolha de arquitetura, não uma conclusão jurídica; as garantias reais dependem da
sua implantação (rede, logs, arquivos temporários, comportamento dos modelos). O rótulo **LOCAL PROCESSING**
da interface indica onde o processamento ocorre; não afirma que a máquina esteja offline.

A LGPD distingue *dado pessoal* de *dado pessoal sensível* (saúde, biométrico, genético...). Hoje só CPF e
endereços residenciais (dados pessoais) são alvo. Veja
[docs/brand/LGPD_PRODUCT_POSITIONING.md](docs/brand/LGPD_PRODUCT_POSITIONING.md) e as fontes oficiais:
[LGPD](https://www.planalto.gov.br/ccivil_03/_ato2015-2018/2018/lei/l13709.htm) ·
[ANPD](https://www.gov.br/anpd/pt-br).

## 🔍 O que o SENTRY Redact faz hoje

| Etapa | O que acontece |
|---|---|
| 🖼️ **Renderização + OCR** | Cada página vira imagem e passa pelo **Tesseract** (com coordenadas de cada palavra) |
| 🔢 **CPFs** | Duas passagens de OCR; validação pelos dígitos verificadores; CNPJs poupados; datas e horas excluídas |
| ✍️ **Assinaturas** | Detector **YOLO** recorta as assinaturas; OCR + **LLM de visão** ([Ollama](https://ollama.com)) procuram CPFs manuscritos ou difíceis de ler |
| 🏠 **Endereços** | O LLM de visão descobre os endereços e os classifica (pessoal / profissional / secundário); só os *pessoais* são tarjados, por casamento determinístico com as palavras do OCR |
| 📄 **Exportação** | PDF final por **tarja nativa** sobre o original (remove o texto e queima os pixels) ou por páginas rasterizadas, mais um JSON com as caixas |
| ✅ **Verificação pós-tarja** | Relê a saída e confronta o *original* (OCR em DPI maior) para garantir que todo CPF encontrado esteja coberto |
| 🖊️ **Editor web** | Adicionar, mover, apagar e aprovar tarjas antes de gerar o PDF final |

### Destaques

- **Local-first:** OCR, YOLO e LLM rodam na máquina; a interface não carrega fontes, scripts nem imagens
  externas (os testes de interface garantem isso).
- **Falha fechado:** qualquer incerteza vira alerta e o estado **"Requer revisão"**; a CLI devolve o código
  `3` nesses casos.
- **Seguro por padrão:** escuta só em `127.0.0.1`, valida uploads e IDs (UUID), token opcional (`API_TOKEN`)
  e segredo interno entre os *workers* e o serviço.
- **Interface acessível:** pt-BR por padrão com seletor en-US, contraste WCAG AA, foco visível e atalhos
  `N`/`P`/`Esc`.

---

## 💻 Requisitos

| Item | Versão |
|---|---|
| Python | **3.10 – 3.12** |
| Tesseract OCR | 5.x com o idioma português (`por`) |
| Ollama | Qualquer modelo local com visão (ex.: `ollama pull qwen2.5vl:7b`) |
| Hardware | RAM/VRAM compatível com o modelo escolhido. O DPI de renderização padrão é alto: reduza `BASE_DPI` em máquinas modestas |
| Detector de assinaturas | `models/signature_stamp_detector.pt` (incluído; veja o [model card](models/MODEL_CARD.md)) |

## ⚡ Instalação

### Windows

1. Instale o **Tesseract** (por exemplo, o instalador UB-Mannheim) marcando o idioma **Português**. Anote o
   caminho do `tesseract.exe`.
2. Instale o **Python 3.10–3.12** e o **Ollama**.
3. No PowerShell:

```powershell
git clone https://github.com/Yiuky/privio-sentry.git; cd privio-sentry
python -m venv venv; .\venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env   # defina TESSERACT_PATH=C:\Program Files\Tesseract-OCR\tesseract.exe
```

### Linux (Debian/Ubuntu)

```bash
sudo apt-get install -y tesseract-ocr tesseract-ocr-por tesseract-ocr-eng libgl1
git clone https://github.com/Yiuky/privio-sentry.git && cd privio-sentry
python3 -m venv venv && . venv/bin/activate
pip install --extra-index-url https://download.pytorch.org/whl/cpu torch torchvision   # PyTorch só CPU (opcional, menor)
pip install -r requirements.txt
cp .env.example .env     # depois edite
```

### Modelos do Ollama

```bash
ollama serve                         # se ainda não estiver rodando
ollama pull <seu-modelo-de-visao>    # ex.: qwen2.5vl:7b
```

Defina `OLLAMA_MODEL` e `OLLAMA_VISION_MODEL` no `.env`. Para um GGUF próprio, veja
[scripts/ollama/Modelfile.example](scripts/ollama/Modelfile.example).

### Docker (opcional)

```bash
docker compose up --build        # app em http://127.0.0.1:8001 ; o Ollama roda no host
```

Antes de distribuir imagens Docker, leia a ressalva de licenciamento em [docs/licensing.md](docs/licensing.md).

## ⚙️ Configuração

Copie `.env.example` para `.env`. Todas as variáveis estão em [docs/configuration.md](docs/configuration.md).
As principais:

| Variável | Para quê |
|---|---|
| `TESSERACT_PATH` | Caminho do executável do Tesseract (Windows) |
| `OLLAMA_API_URL`, `OLLAMA_MODEL`, `OLLAMA_VISION_MODEL` | Servidor e modelos do Ollama |
| `YOLO_MODEL_PATH` | Pesos do detector de assinaturas |
| `BASE_DPI` | DPI de renderização das páginas (qualidade × memória × tempo) |
| `APP_HOST`, `API_TOKEN` | Endereço de escuta e token de acesso (obrigatório fora do `127.0.0.1`) |
| `VERIFY_OCR` | Liga/desliga a verificação pós-tarja por OCR |

## 🚀 Uso rápido

### Aplicação web (com editor)

```bash
python app_service.py          # http://127.0.0.1:8001   (ou scripts/run_app.sh | scripts/run_app.bat)
# painel liga/desliga opcional + proxy reverso na :8000:
python gatekeeper.py           # http://127.0.0.1:8000/gatekeeper
```

1. Envie os PDFs e aguarde o processamento.
2. Abra o editor: as páginas marcadas para revisão ficam destacadas.
3. Ajuste as caixas e clique em **Aplicar proteção (modo nativo)**.

Para expor o serviço na rede, defina `APP_HOST=0.0.0.0` **e** `API_TOKEN`, e coloque-o atrás de HTTPS
(proxy reverso): não há TLS nem contas de usuário embutidos.

### Linha de comando (lote)

```bash
python main.py --input caminho/arquivo_ou_pasta --output caminho/resultados
```

| Código de saída | Significado |
|---|---|
| `0` | Todos os documentos concluídos |
| `3` | Ao menos um documento **requer revisão** |
| `1` | Erro |

Teste com o exemplo sintético (dados fictícios):

```bash
python examples/make_sample_pdf.py            # gera examples/sample_input.pdf
python main.py --input examples/sample_input.pdf --output saida
```

## 🏗️ Arquitetura

```text
Navegador ─► gatekeeper.py (:8000, opcional) ─proxy─► app_service.py (:8001, FastAPI)
              liga/desliga + watchdog                   │ tasks.json (gravação atômica)
                                                        └─ um processo worker por tarefa ─► main.py (SentryApp)
                                                               ├─ utils/ocr_engine.py       Tesseract
                                                               ├─ utils/yolo_engine.py      assinaturas (YOLO)
                                                               ├─ utils/ai_client.py        LLM de visão (Ollama)
                                                               ├─ utils/address_redactor.py endereços
                                                               ├─ utils/session.py          pastas, logs, PDF final
                                                               └─ utils/verifier.py         verificação pós-tarja
```

Detalhes em [docs/architecture.md](docs/architecture.md); convenções e armadilhas para quem for alterar o
código em [AGENTS.md](AGENTS.md).

## 🧪 Testes

```bash
pip install -r requirements-dev.txt
ruff check .                     # lint
pytest --ignore=tests/ui         # unidade e integração (sem Ollama nem GPU: LLM e YOLO são simulados)
playwright install chromium      # uma vez
pytest tests/ui                  # interface no navegador (identidade, acessibilidade, segurança)
python scripts/audit_public_tree.py   # auditoria de dados pessoais e segredos antes de publicar
```

O CI do GitHub roda o lint, a suíte em Python 3.10, 3.11 e 3.12 (com cobertura) e os testes de interface.
Os números de detecção, medidos **só em dados sintéticos**, estão em [docs/benchmarks.md](docs/benchmarks.md).

## 🔭 Visão (futuro, não implementado)

A direção de longo prazo é uma camada local de processamento de privacidade para documentos, APIs, sistemas
de IA e fluxos de trabalho. **Hoje existe apenas o SENTRY Redact.** Os módulos abaixo orientam o desenho, sem
datas e sem promessa de entrega:

| Módulo (visão) | Papel pretendido |
|---|---|
| SENTRY Detect | Detectar e classificar informação sensível candidata (dados pessoais, dados pessoais sensíveis, segredos, financeiro, personalizado) |
| SENTRY Mask / Transform | Mascaramento/substituição e pseudonimização como operações explícitas, controladas por política |
| SENTRY Gateway | Fronteira de privacidade para o tráfego a IAs/APIs externas |
| SENTRY Audit | Evidências (hashes, proveniência de modelo/política) sem guardar valores sensíveis brutos |

O trabalho pendente e as prioridades estão no [BACKLOG.md](BACKLOG.md). Diretrizes de marca, design e UX:
[docs/brand/](docs/brand/).

## 🚧 Limitações

- Só CPF e endereços pessoais; sem nomes, telefones, e-mails, rostos etc.
- Revocação da detecção e da verificação medida **só em dados sintéticos**; digitalizações reais podem ser
  piores.
- Manuscritos e digitalizações de baixa qualidade são o ponto mais fraco; o detector de assinaturas tem
  acurácia modesta.
- A tarja de endereços depende da classificação por LLM e de casamento aproximado: pode tarjar a mais ou a
  menos.
- PDFs grandes são lentos (OCR em DPI alto + chamadas ao LLM + verificação).

Lista completa: [docs/limitations.md](docs/limitations.md).

## 🔐 Privacidade e segurança

O processamento é local. Os artefatos de cada tarefa (imagens das páginas, saída do OCR, recortes) ficam em
`output/` e **contêm dados pessoais**: apague-os quando não forem mais necessários (opções de retenção em
[docs/configuration.md](docs/configuration.md)). Vulnerabilidades: relate de forma privada, conforme o
[SECURITY.md](SECURITY.md).

## 🤝 Contribuindo

- Como relatar problemas, sugerir melhorias e enviar código: [CONTRIBUTING.md](CONTRIBUTING.md).
- Arquitetura, invariantes e armadilhas conhecidas: [AGENTS.md](AGENTS.md).
- Trabalho pendente e prioridades: [BACKLOG.md](BACKLOG.md).
- Convivência: [Código de Conduta](CODE_OF_CONDUCT.md).
- **Nunca versione dados pessoais reais.**

## 📝 Como citar

Se o PRIVIO SENTRY ajudou num trabalho acadêmico ou técnico, use o botão **Cite this repository** do GitHub
(gerado a partir do [CITATION.cff](CITATION.cff)).

---

## 🌐 English Abstract

**PRIVIO SENTRY** is a local-first, AGPL-licensed project for detecting and protecting personal data in
documents. Its first capability, **SENTRY Redact**, finds **Brazilian CPF numbers** and **personal
(residential) addresses** in PDF files and prepares redactions for a person to review in a web editor:

- **Local pipeline:** Tesseract OCR, a YOLO signature detector and a vision LLM served by Ollama, all running
  on your machine; the UI loads no external assets.
- **Human in the loop:** the AI only *suggests*; nothing becomes the final PDF until a reviewer confirms it.
- **Fails closed:** a post-redaction verifier re-reads the output and cross-checks the original; any doubt
  marks the document as *needs review* (CLI exit code `3`).
- **Honest scope:** early stage, measured only on synthetic data, no audit trail yet, and it does **not**
  guarantee anonymization. It can support LGPD-aligned practices but is not a compliance engine.

Full English documentation: [README.en.md](README.en.md).

## ☕ Doe um café para o dev

O PRIVIO SENTRY é gratuito e de código aberto, desenvolvido nas horas vagas. Se ele economizou o seu tempo,
considere pagar um café para o desenvolvedor: ajuda a manter o projeto vivo e a trazer novos tipos de dado e
melhorias na detecção.

<table>
  <tr>
    <td align="center"><img src="docs/img/pix_qrcode.png" alt="QR Code Pix" width="180" /></td>
    <td>
      <strong>Pix</strong> (qualquer valor)<br><br>
      Chave aleatória:<br>
      <code>fcf8071f-416d-49f1-b4b9-3188d3d03c4b</code><br><br>
      Pix copia e cola:<br>
      <code>00020101021126580014br.gov.bcb.pix0136fcf8071f-416d-49f1-b4b9-3188d3d03c4b5204000053039865802BR5917JOBERTH F GAMBATI6006CUIABA62070503***63048088</code><br><br>
      <em>Favorecido: Joberth Firmino Gambati</em>
    </td>
  </tr>
</table>

## 👤 Autor e licença

- **Desenvolvedor:** Joberth Firmino Gambati ([@Yiuky](https://github.com/Yiuky)).
- **Código-fonte:** [GNU AGPL-3.0 ou posterior](LICENSE). Se você distribuir uma versão modificada, ou
  oferecê-la a usuários pela rede, deve fornecer o código-fonte sob a mesma licença.
- **Dependências e pesos do YOLO:** [NOTICE](NOTICE) e [docs/licensing.md](docs/licensing.md).
- **Nomes e logotipos:** não cobertos pela AGPL; veja [TRADEMARKS.md](TRADEMARKS.md).

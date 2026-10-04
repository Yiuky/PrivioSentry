<p align="center">
  <img src="assets/concept-mark.svg" alt="Logotipo PRIVIO SENTRY (marca conceitual)" width="96" height="96">
</p>

# PRIVIO SENTRY

**Local AI Privacy Infrastructure** · produto atual: **SENTRY Redact**

> **Proteja os dados antes que sejam expostos.** &nbsp;·&nbsp; Detectar. Revisar. Proteger. (*Detect. Review. Protect.*)

[English](README.md) | [Português (Brasil)](README.pt-BR.md)

O PRIVIO SENTRY é um projeto *local-first* para detectar e proteger informações pessoais, sensíveis e confidenciais em documentos. Sua primeira (e única) capacidade publicada, o **SENTRY Redact**, é um pipeline que encontra **CPFs** e **endereços pessoais (residenciais)** em arquivos PDF e prepara tarjas para uma pessoa revisar. OCR, detecção e modelos de linguagem/visão rodam na sua máquina; a aplicação não envia conteúdo de documentos a nuvens de terceiros.

> **Status: estágio inicial.** O SENTRY Redact é utilizável, porém jovem: escopo restrito (CPF e endereços pessoais), medido apenas em dados sintéticos e ainda sem trilha de auditoria. Espere mudanças incompatíveis.

> **Marca:** o código é AGPL-3.0-or-later, mas nomes e logotipos não são cobertos por essa licença. Veja [TRADEMARKS.md](TRADEMARKS.md).

## Princípio

> **A IA sugere. A política restringe. O humano confirma. O sistema registra.** (*AI suggests. The policy constrains. The human confirms. The system records.*)

* Os modelos apenas **sugerem** detecções *potenciais*; cada sugestão aparece como uma região editável que uma pessoa pode aceitar, mover, redimensionar ou remover.
* Nada vira o PDF final até o revisor confirmar. Na dúvida (falha da IA, CPF do original sem tarja correspondente, página não verificada) o pipeline **falha fechado**: o documento fica como **"Requer revisão"** em vez de "Concluído", com alertas por página.
* "A política restringe" e "o sistema registra" são a direção do projeto: hoje a política é fixa (CPF + endereços pessoais) e o único registro é o log da tarefa. Um motor de políticas configurável e uma trilha de auditoria estão **planejados, não implementados** (veja [Visão](#visão-futura-não-implementada)).

## Leia primeiro: é uma ferramenta de apoio, não uma garantia

**Esta ferramenta NÃO garante anonimização total.** A detecção por IA é probabilística. Erros de OCR, manuscritos, digitalizações ruins, layouts incomuns e falhas dos modelos podem deixar dados pessoais visíveis; também pode tarjar mais do que o necessário.

* Toda saída **deve ser revisada por uma pessoa** antes de ser publicada ou compartilhada.
* "Concluído" significa *nenhum alerta pendente nas verificações automáticas*, e não que o documento está garantidamente limpo.
* Apenas **CPF** e **endereços pessoais** são alvo. Nomes, telefones, e-mails, RG, dados bancários, fotos, QR codes, metadados etc. **não** são tarjados. Veja [docs/limitations.md](docs/limitations.md) e [docs/threat-model-lgpd.md](docs/threat-model-lgpd.md).
* Nunca use documentos reais para relatar bugs ou em testes; veja [SECURITY.md](SECURITY.md).

## Posicionamento frente à LGPD

O PRIVIO SENTRY é um **controle técnico que pode apoiar práticas de privacidade e segurança**, inclusive as relacionadas à **LGPD** (Lei 13.709/2018). Ele **não** é um motor de "conformidade com a LGPD", não é aconselhamento jurídico e seu uso não torna, por si só, nenhum documento ou processo conforme: isso depende de finalidade, base legal, necessidade, governança, ciclo de vida dos dados e papéis. Processamento local é uma escolha de arquitetura, não uma conclusão jurídica; as garantias reais dependem da sua implantação (rede, logs, arquivos temporários, comportamento dos modelos). O rótulo **LOCAL PROCESSING** da interface indica onde o processamento ocorre; não afirma que a máquina está offline.

A LGPD distingue *dado pessoal* de *dado pessoal sensível* (saúde, biométrico, genético...). Hoje apenas CPF e endereços residenciais (dados pessoais) são alvo. Veja [docs/brand/LGPD_PRODUCT_POSITIONING.md](docs/brand/LGPD_PRODUCT_POSITIONING.md) e as fontes oficiais: [LGPD](https://www.planalto.gov.br/ccivil_03/_ato2015-2018/2018/lei/l13709.htm), [ANPD](https://www.gov.br/anpd/pt-br).

## O que o SENTRY Redact faz hoje

1. Renderiza cada página do PDF como imagem e roda **OCR Tesseract** (com coordenadas das palavras).
2. Encontra **CPFs** (validados pelos dígitos verificadores; CNPJs são poupados; datas/horas são excluídas) em duas passagens de OCR.
3. Detecta **assinaturas** com um modelo **YOLO**, recorta e audita os recortes (OCR + **LLM de visão** servido pelo [Ollama](https://ollama.com)) atrás de CPFs manuscritos/difíceis de ler.
4. Pede ao LLM de visão que descubra **endereços** em cada página e os classifique (pessoal / profissional / secundário); só os endereços *pessoais* são tarjados, por casamento determinístico com as palavras do OCR.
5. Gera o PDF final (tarja nativa sobre o original, ou páginas rasterizadas) e um JSON com as caixas.
6. Executa a **verificação pós-tarja**: relê a saída e confronta o *original* (OCR em DPI maior) para garantir que todo CPF encontrado esteja coberto por uma tarja.
7. Oferece um **editor web** para adicionar, mover, apagar e aprovar tarjas antes de gerar o PDF final.

## Requisitos

* Python **3.10 – 3.12**
* **Tesseract OCR** 5.x com dados em português (`por`)
* **Ollama** com um modelo com visão (qualquer VLM local; ex.: `ollama pull qwen2.5vl:7b`)
* RAM/VRAM compatível com o modelo escolhido (o DPI de renderização padrão é alto; reduza `BASE_DPI` em máquinas modestas)
* Detector YOLO de assinaturas `models/signature_stamp_detector.pt` (incluído; veja [models/MODEL_CARD.md](models/MODEL_CARD.md))

## Instalação

### Linux (Debian/Ubuntu)

```bash
sudo apt-get install -y tesseract-ocr tesseract-ocr-por tesseract-ocr-eng libgl1
git clone https://github.com/Yiuky/privio-sentry.git && cd privio-sentry
python3 -m venv venv && . venv/bin/activate
pip install --extra-index-url https://download.pytorch.org/whl/cpu torch torchvision   # PyTorch só CPU (opcional, menor)
pip install -r requirements.txt
cp .env.example .env     # depois edite
```

### Windows

1. Instale o Tesseract (por exemplo o instalador UB-Mannheim) marcando o idioma **Português**. Anote o caminho do `tesseract.exe`.
2. Instale Python 3.10–3.12 e o Ollama.
3. No PowerShell:

```powershell
git clone https://github.com/Yiuky/privio-sentry.git; cd privio-sentry
python -m venv venv; .\venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env   # defina TESSERACT_PATH=C:\Program Files\Tesseract-OCR\tesseract.exe
```

### Modelos do Ollama

```bash
ollama serve                         # se ainda não estiver rodando
ollama pull <seu-modelo-de-visao>    # ex.: qwen2.5vl:7b
```

Defina `OLLAMA_MODEL` e `OLLAMA_VISION_MODEL` no `.env`. Para um GGUF customizado veja [scripts/ollama/Modelfile.example](scripts/ollama/Modelfile.example).

### Docker (opcional)

```bash
docker compose up --build        # app em http://127.0.0.1:8001 ; o Ollama deve rodar no host
```

Veja a ressalva de licenciamento sobre distribuir imagens em [docs/licensing.md](docs/licensing.md).

## Configuração

Copie `.env.example` para `.env`. Todas as variáveis estão em [docs/configuration.md](docs/configuration.md). As principais: `TESSERACT_PATH`, `OLLAMA_API_URL`, `OLLAMA_MODEL`, `OLLAMA_VISION_MODEL`, `YOLO_MODEL_PATH`, `BASE_DPI`, `APP_HOST`, `API_TOKEN`, `VERIFY_OCR`.

## Uso

### Aplicação web (com editor)

```bash
python app_service.py          # http://127.0.0.1:8001   (ou scripts/run_app.sh | scripts/run_app.bat)
# painel liga/desliga opcional + proxy reverso na :8000:
python gatekeeper.py           # http://127.0.0.1:8000/gatekeeper
```

Envie os PDFs, aguarde o processamento e abra o editor: as páginas marcadas para revisão ficam destacadas. Ajuste as caixas e clique em **Aplicar proteção (modo nativo)**. A interface é em português (pt-BR) por padrão, com seletor para inglês (en-US), não carrega recursos externos e aceita os atalhos `N`/`P` (próxima/anterior) e `Esc`. O servidor escuta em `127.0.0.1` por padrão; para expor na rede defina `APP_HOST=0.0.0.0` **e** `API_TOKEN`, e use HTTPS.

### Linha de comando (lote)

```bash
python main.py --input caminho/arquivo_ou_pasta --output caminho/resultados
```

Códigos de saída: `0` todos concluídos, `3` ao menos um documento **requer revisão**, `1` erro. Teste com o exemplo sintético:

```bash
python examples/make_sample_pdf.py            # gera examples/sample_input.pdf (dados fictícios)
python main.py --input examples/sample_input.pdf --output saida
```

## Arquitetura (resumo)

```
Navegador ─► gatekeeper.py (:8000, opcional) ─proxy─► app_service.py (:8001, FastAPI)
                                                        └─ um processo worker por tarefa ─► main.py (SentryApp)
                                                               OCR (Tesseract) · YOLO · LLM Ollama · verificador
```

Detalhes: [docs/architecture.md](docs/architecture.md).

## Visão (futuro, não implementada)

A direção de longo prazo é uma camada local de processamento de privacidade para documentos, APIs, sistemas de IA e fluxos de trabalho. **Hoje existe apenas o SENTRY Redact.** Os módulos abaixo são um roteiro para orientar o desenho, sem datas e sem promessa de entrega:

| Módulo (visão) | Papel pretendido |
|---|---|
| SENTRY Detect | Detectar e classificar informação sensível candidata (taxonomia: dados pessoais, dados pessoais sensíveis, segredos, financeiro, personalizado) |
| SENTRY Mask / Transform | Mascaramento/substituição e pseudonimização como operações explícitas, controladas por política |
| SENTRY Gateway | Fronteira de privacidade para tráfego a IAs/APIs externas |
| SENTRY Audit | Evidências (hashes, proveniência de modelo/política) sem armazenar valores sensíveis brutos |

As diretrizes de marca, design e UX estão em [docs/brand/](docs/brand/) (inclui o aviso de produto).

## Limitações

* Somente CPF e endereços pessoais; sem nomes, telefones, e-mails, rostos etc.
* A revocação da detecção e da verificação só foi medida em dados sintéticos (veja [docs/benchmarks.md](docs/benchmarks.md) quando disponível); digitalizações reais podem ser piores.
* Manuscritos e digitalizações de baixa qualidade são o ponto mais fraco. O detector de assinaturas tem acurácia modesta (veja o model card).
* A tarja de endereços depende de classificação por LLM e de casamento aproximado: pode tarjar a mais ou a menos.
* PDFs grandes são lentos (OCR em DPI alto + chamadas ao LLM + verificação).

Lista completa: [docs/limitations.md](docs/limitations.md).

## Privacidade e segurança

O processamento é local. Os artefatos de cada tarefa (imagens das páginas, saída do OCR, recortes) ficam em `output/` e contêm **dados pessoais**; apague-os quando não forem mais necessários (veja a retenção em [docs/configuration.md](docs/configuration.md)). Relate vulnerabilidades de forma privada: [SECURITY.md](SECURITY.md).

## Contribuindo

Veja [CONTRIBUTING.md](CONTRIBUTING.md) e o [Código de Conduta](CODE_OF_CONDUCT.md). Rode `pytest` e `ruff check .` antes de abrir um PR. **Nunca versione dados pessoais reais.**

## Licença

Código-fonte: [GNU AGPL-3.0 ou posterior](LICENSE). Se você distribuir uma versão modificada, ou oferecê-la a usuários pela rede, deve fornecer o código-fonte sob a mesma licença. Dependências e pesos do YOLO estão em [NOTICE](NOTICE) e [docs/licensing.md](docs/licensing.md).

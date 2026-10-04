# Como contribuir com o PRIVIO SENTRY

Obrigado pelo interesse! Toda ajuda é bem-vinda: relatos de problemas, sugestões, documentação e código.
Antes de mexer no código, leia o [AGENTS.md](AGENTS.md) (invariantes, arquitetura e armadilhas) e veja o
[BACKLOG.md](BACKLOG.md).

*English summary at the end of this file.*

## Regras de ouro

1. **Nenhum dado pessoal real. Nunca.** Nada de CPFs, nomes, endereços, PDFs, capturas de tela ou logs de
   processos reais em código, testes, *fixtures*, issues ou PRs. Use o gerador sintético
   (`python examples/make_sample_pdf.py`) ou valores fictícios. A auditoria antes de publicar
   (`python scripts/audit_public_tree.py`) precisa passar.
2. **Falha fechado.** Na dúvida, o pipeline deve marcar o documento para revisão humana em vez de relatar
   sucesso. Toda mudança que possa causar **tarja a menos** precisa de um teste que prove que não causa.
3. **Local-first.** Não adicione chamadas de rede que enviem conteúdo de documentos para fora da máquina.
4. Não enfraqueça a revisão, a verificação nem o aviso de que a ferramenta não garante anonimização.

## Relatar um problema

1. Confira as [limitações conhecidas](docs/limitations.md) e se já existe uma
   [issue](https://github.com/Yiuky/PrivioSentry/issues) parecida.
2. Abra uma issue com o modelo **Relatar problema**. Reproduza com o exemplo sintético e anexe só logs sem
   dados pessoais (revise antes de anexar).
3. Falhas de segurança ou tarja que deixou vazar dado real **não** vão em issue pública: veja
   [SECURITY.md](SECURITY.md).

## Sugerir uma melhoria

Use o modelo **Sugerir melhoria** e descreva o problema que a mudança resolve, não só a solução. Diga também
o impacto na privacidade: a mudança guarda, registra ou transmite conteúdo de documentos?

## Textos da interface e regras de marca

A interface e a documentação seguem [docs/brand/](docs/brand/). Em resumo:

- **Nunca** afirme "conforme a LGPD", "100% seguro", "garantido" ou "sem acesso à rede". Use "política de
  proteção alinhada à LGPD", "potencial", "detectado", "sugerido", "revisão", "Proteção concluída",
  "Processado localmente". O rótulo da interface é exatamente `LOCAL PROCESSING`.
- A IA **sugere** e o humano **confirma**; mantenha o aviso permanente de que a detecção por IA é
  probabilística.
- A interface continua **local-first**: sem scripts, fontes ou imagens de CDN, sem requisições externas
  (`tests/ui/test_ui_brand.py` cobra isso e as regras de texto). Os textos da interface ficam no objeto
  `I18N` de `templates/index.html` (chaves conforme `docs/brand/UX_SPEC.md`).
- Use os *design tokens* (propriedades CSS em `:root`); mantenha contraste WCAG AA (4,5:1) e foco visível.
- Nomes e logotipos não são cobertos pela AGPL-3.0 ([TRADEMARKS.md](TRADEMARKS.md)).

## Ambiente de desenvolvimento

```bash
git clone https://github.com/Yiuky/PrivioSentry.git && cd PrivioSentry
python -m venv venv && . venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements-dev.txt
cp .env.example .env
# Alguns testes usam o Tesseract com português: apt install tesseract-ocr tesseract-ocr-por
```

## Verificações

```bash
ruff check .                              # lint
pytest --ignore=tests/ui                  # unidade e integração
pytest --ignore=tests/ui --cov=utils --cov=app_service --cov=gatekeeper --cov=main
playwright install chromium               # uma vez
pytest tests/ui                           # testes de interface no navegador
python scripts/audit_public_tree.py       # dados pessoais / segredos / caminhos locais
```

Os testes não podem depender do Ollama nem de GPU: use *fakes*/*stubs* para o LLM e o YOLO.

Para rodar o lint, a auditoria e a checagem de versão automaticamente a cada commit:

```bash
pip install pre-commit && pre-commit install     # usa .pre-commit-config.yaml
```

## Pull requests

- Um assunto por PR, com testes. Explique o *porquê* (item do [BACKLOG.md](BACKLOG.md), issue ou pedido).
- Atualize a documentação (`README.md` **e** `README.en.md`, `docs/`, `.env.example`, `CHANGELOG.md`) quando o
  comportamento ou a configuração mudar.
- Novas dependências precisam de justificativa e checagem de licença ([docs/licensing.md](docs/licensing.md));
  evite adicionar mais componentes AGPL/GPL.
- Ao contribuir, você concorda que sua contribuição é licenciada sob a licença do projeto (`LICENSE`). Assine
  os commits (`git commit -s`) para certificar o [Developer Certificate of Origin](https://developercertificate.org/).
- Seja gentil: veja o [Código de Conduta](CODE_OF_CONDUCT.md).

---

## English summary

- **No real personal data, ever**; use `examples/make_sample_pdf.py`. `scripts/audit_public_tree.py` must pass.
- The pipeline must **fail closed**; changes that could cause under-redaction need a test.
- Stay **local-first**; do not weaken review, verification or the "no guarantee" wording.
- Run `ruff check .`, `pytest --ignore=tests/ui` and, if the UI changed, `pytest tests/ui`. Tests must not need
  Ollama or a GPU.
- One focused change per PR, docs updated (both READMEs), commits signed off (`git commit -s`, DCO).
- Security issues or real-data leaks: follow [SECURITY.md](SECURITY.md), never a public issue.

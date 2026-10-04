## O que muda

<!-- Descrição curta da mudança. -->

## Por quê

<!-- Item do BACKLOG.md (ex.: B-10), issue ou pedido. -->

## Checklist

- [ ] Testes adicionados/atualizados; `pytest --ignore=tests/ui` passa (e `pytest tests/ui`, se a interface mudou)
- [ ] `ruff check .` passa
- [ ] `python scripts/audit_public_tree.py` passa: **nenhum dado pessoal real** (CPFs, nomes, endereços, PDFs ou capturas reais) no código, testes, *fixtures*, logs ou na descrição do PR
- [ ] Comportamento que possa causar **tarja a menos** está coberto por teste (o projeto falha fechado)
- [ ] Documentação atualizada quando o comportamento ou a configuração mudou (`README.md` **e** `README.en.md`, `docs/`, `.env.example`, `CHANGELOG.md`, [AGENTS.md](https://github.com/Yiuky/PrivioSentry/blob/main/AGENTS.md))
- [ ] Novas dependências justificadas e com licença compatível ([docs/licensing.md](https://github.com/Yiuky/PrivioSentry/blob/main/docs/licensing.md))
- [ ] `BACKLOG.md` atualizado (item movido para Concluídos, com o teste que o cobre)

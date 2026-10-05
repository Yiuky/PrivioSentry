# Documentação do PRIVIO SENTRY

Ponto de partida para usar, operar e desenvolver o **SENTRY Redact**. Comece pelo
[README](../README.md) para uma visão geral.

## 📘 Para quem usa

| Documento | Conteúdo |
|---|---|
| [Manual de uso](MANUAL_DE_USO.md) | Instalação passo a passo, editor web, linha de comando, resultados, solução de problemas e perguntas frequentes |
| [Catálogo de dados pessoais](catalogo-pii.md) | Tipos de PII, enquadramento (LGPD, GDPR, ISO/IEC 29100, NIST, HIPAA) e como cada um é detectado |
| [Configuração](configuration.md) | Todas as variáveis de ambiente (`.env`), com valores padrão |
| [Limitações](limitations.md) | O que a ferramenta **não** faz: leia antes de confiar nos resultados |

## 🔐 Para quem decide e opera

| Documento | Conteúdo |
|---|---|
| [Modelo de ameaças e LGPD](threat-model-lgpd.md) | Riscos, controles existentes e notas sobre a LGPD (não é aconselhamento jurídico) |
| [Posicionamento frente à LGPD](brand/LGPD_PRODUCT_POSITIONING.md) | O que o produto afirma e o que não afirma |
| [Segurança e privacidade](brand/SECURITY_AND_PRIVACY.md) | Princípios de segurança e privacidade do produto |
| [Licenciamento](licensing.md) | AGPL-3.0 e as dependências AGPL (PyMuPDF, Ultralytics) |
| [Política de segurança](../SECURITY.md) | Como relatar vulnerabilidades de forma privada |

## 🛠️ Para quem desenvolve

| Documento | Conteúdo |
|---|---|
| [AGENTS.md](../AGENTS.md) | Invariantes, arquitetura, onde fica cada coisa e armadilhas (para pessoas e modelos de IA) |
| [Arquitetura](architecture.md) | Processos, fases do pipeline, estados, API HTTP e pastas de uma tarefa |
| [Decisor local e automelhoramento](decisions.md) | Laya (modelo de decisão local), treino, portão de qualidade, versões e privacidade dos exemplos |
| [Benchmarks](benchmarks.md) | Medições e como reproduzir: CPF e todos os tipos do corpus fictício (com e sem OCR), motores de OCR e IAs de OCR, LLMs de endereço, servidores de IA com disjuntor, harness de agente com modelos pequenos, segundo olhar e teste de pressão |
| [Model card](../models/MODEL_CARD.md) | Detector YOLO de assinaturas: dados, métricas e limites |
| [Como contribuir](../CONTRIBUTING.md) | Regras de ouro, ambiente, verificações e PRs |
| [Backlog](../BACKLOG.md) | Trabalho pendente, prioridades e visão |
| [Changelog](../CHANGELOG.md) | O que mudou em cada versão |

## 🎨 Marca e experiência

| Documento | Conteúdo |
|---|---|
| [Marca](brand/BRAND_GUIDELINES.md) · [Design](brand/DESIGN_GUIDELINES.md) · [UX](brand/UX_SPEC.md) | Identidade, *design tokens* e textos da interface |
| [Aviso de produto](brand/PRODUCT_NOTICE.md) | Texto padrão sobre o que a ferramenta faz e não faz |
| [Marcas registradas](../TRADEMARKS.md) | Nomes e logotipos não são cobertos pela AGPL |

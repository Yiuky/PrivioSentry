# PRIVIO SENTRY — LGPD Product Positioning v0.2

## Purpose

This document defines how the product should describe its relationship with the Brazilian LGPD.

## Core statement

> PRIVIO SENTRY provides technical capabilities that can support organizations in reducing unnecessary exposure of personal data and in implementing security, prevention and governance controls.

## Do not claim

- “LGPD compliant”
- “guarantees LGPD compliance”
- “automatically makes your document legal”
- “100% compliant”
- “zero privacy risk”

## Why

LGPD compliance depends on context, including:
- purpose;
- legal basis;
- necessity;
- security;
- governance;
- data lifecycle;
- roles and responsibilities;
- rights of data subjects;
- contractual and sectoral requirements.

## Product mapping

### Necessity
Configurable policies reduce data exposure to what is needed for a purpose.

### Security
Local processing can reduce unnecessary transfer to external AI services, subject to deployment controls.

### Prevention
Protection is performed before publication or external sharing.

### Transparency
The UI exposes detections, confidence, selected policy and resulting action.

### Accountability
Audit evidence records the processing configuration and result without retaining raw sensitive values by default.

## Taxonomy

### Personal data
Information related to an identified or identifiable natural person.

Examples:
- name;
- address;
- CPF;
- telephone;
- identifiable email.

### Sensitive personal data
Categories expressly identified by the LGPD, including health, genetic and biometric data linked to a natural person, as well as racial/ethnic origin, religion, political opinion, union membership and information regarding sex life.

### Confidential information
Organization-defined information that may not be “sensitive personal data” in the legal sense, but still requires protection.

This distinction must remain visible in product configuration.

## Recommended UI term

Instead of:

`LGPD COMPLIANT`

Use:

`LGPD-aligned protection policy`

And always provide a link or tooltip explaining that the policy is configurable and requires organizational review.

## Official references

- LGPD: https://www.planalto.gov.br/ccivil_03/_ato2015-2018/2018/lei/l13709.htm
- ANPD Security Guide: https://www.gov.br/anpd/pt-br/centrais-de-conteudo/materiais-educativos-e-publicacoes/guia-orientativo-sobre-seguranca-da-informacao-para-agentes-de-tratamento-de-pequeno-porte
- ANPD data subject page: https://www.gov.br/anpd/pt-br/assuntos/titular-de-dados

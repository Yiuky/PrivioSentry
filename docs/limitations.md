# Limitações

Seja explícito sobre o que esta ferramenta não consegue fazer. Sempre combine o uso com revisão humana. O PRIVIO SENTRY / SENTRY Redact está em **estágio inicial**: a IA **sugere**, uma pessoa **confirma**.

## Escopo da tarja
* **O que é tarjado depende do perfil de política** (`POLICY_PROFILE`, ver [catálogo](catalogo-pii.md)). O padrão (`cpf_endereco`) cobre só CPF e endereço residencial; os perfis LGPD, GDPR e saúde acrescentam RG, CNH, título de eleitor, PIS/NIS, Cartão SUS, passaporte, CTPS, telefone, e-mail, dados bancários, chave Pix, data de nascimento, placa e IP, detectados por regras (dígito verificador, formato e palavra de contexto). **Não são detectados em nenhum perfil:** nomes, filiação, fotografias/rostos, dados sensíveis (saúde, religião, opinião política...), QR codes/códigos de barras, as próprias assinaturas (apenas CPFs próximos a elas) e metadados/anexos/anotações/marcadores do PDF (inspecione esses itens separadamente).
* A busca de CPF junta dígitos de palavras e linhas vizinhas: um número qualquer de 11 dígitos que passe por acaso no dígito verificador (ex.: alguns telefones, valores quebrados em linhas) também vira tarja de CPF e pode gerar um alerta "CPF ainda detectável". O erro fica do lado seguro (tarja a mais) e a revisão humana resolve; a regra não foi afrouxada para não perder CPF verdadeiro.
* Os detectores por regra só foram testados com valores gerados (sem medida de revocação em documentos reais). A verificação pós-tarja confere só CPF: os outros tipos dependem da revisão humana.
* Nomes de pessoas deliberadamente **não** são tarjados (uma regra de negócio do caso de uso original), o que pode tornar um indivíduo identificável mesmo sem CPF/endereço.

## Qualidade da detecção
* **Dependente de OCR:** baixa resolução, inclinação, manchas, carimbos sobre o texto, colunas e escrita à mão reduzem a revocação. Um único dígito lido errado pode fazer um CPF falhar na verificação dos dígitos verificadores e escapar da detecção; o verificador mitiga isso (mas não elimina) refazendo o OCR do original em outro DPI e sinalizando inconsistências.
* **Escrita à mão / assinaturas:** o detector YOLO é pequeno (classe única, métricas modestas, veja [models/MODEL_CARD.md](../models/MODEL_CARD.md)); CPFs escritos à mão dependem do LLM de visão, cuja qualidade depende do modelo que você executa.
* **Endereços:** a descoberta e a classificação pessoal/profissional são feitas por um LLM e depois associadas às palavras do OCR por token. Pode haver **tarja a menos** (endereço não detectado ou classificado erroneamente como profissional) e **tarja a mais** (tokens que também aparecem em outros pontos da página).
* **Não determinismo do LLM:** os resultados podem variar entre execuções e modelos. Falhas/timeouts são sinalizados para revisão, mas uma resposta errada dada com confiança não é detectável.
* Revocação/precisão medidas existem apenas para documentos **sintéticos** (veja `docs/benchmarks.md`, quando existir). A acurácia no mundo real é desconhecida e provavelmente menor.
* Apenas documentos/formatos em português (brasileiro) foram considerados (regras de CPF/CNPJ, vocabulário de endereços).

## Desempenho
* OCR em DPI alto, chamadas ao LLM e a etapa de verificação deixam PDFs grandes lentos (centenas de páginas podem levar horas); o uso de memória cresce com `BASE_DPI`.
* Um processo worker por tarefa; as chamadas ao LLM são serializadas por um lock, então os ganhos com concorrência são limitados.

## Saída
* O **modo nativo** edita o PDF original em vez de rasterizá-lo; camadas ocultas, arquivos embutidos, campos de formulário ou anotações ainda podem carregar dados.
* O **modo raster** reduz a resolução (padrão ~150 DPI equivalentes, largura de 1240 px) e remove o texto selecionável.
* O PDF final é tão bom quanto as caixas: a revisão manual no editor faz parte do fluxo de trabalho, não é um extra opcional.

## Plataforma / operação
* O rótulo **LOCAL PROCESSING** na UI descreve a arquitetura, não um estado de rede imposto: a aplicação não bloqueia tráfego de saída, e `OLLAMA_API_URL` pode apontar para um servidor remoto. A UI nunca afirma que não há acesso à rede.
* Não é uma ferramenta de conformidade legal: ela pode apoiar práticas de privacidade e segurança, incluindo práticas alinhadas à LGPD, mas não estabelece conformidade por si só (veja [threat-model-lgpd.md](threat-model-lgpd.md)).
* Sem contas de usuário, TLS ou trilha de auditoria embutidos; a proteção depende do bind em loopback, de um `API_TOKEN` compartilhado opcional e da segurança do host.
* Artefatos intermediários mantêm dados pessoais até serem apagados.
* Desenvolvido e testado principalmente no Windows; o suporte a Linux é exercitado pela CI (Tesseract instalado via apt), mas menos testado em campo.
* Ressalvas de licenciamento das dependências AGPL: [licensing.md](licensing.md).

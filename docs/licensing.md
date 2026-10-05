# Licensing / Licenciamento

> Engineering notes, **not legal advice**. / Notas técnicas, **não é aconselhamento jurídico**.

## English

**PRIVIO SENTRY is licensed under the GNU Affero General Public License v3.0 or later (AGPL-3.0-or-later).** See [../LICENSE](../LICENSE).

### Why AGPL
The project imports **PyMuPDF** (AGPL-3.0 or paid Artifex license) and **Ultralytics** (AGPL-3.0, which also applies to models trained with it), and ships `models/signature_stamp_detector.pt`, derived from Ultralytics' pretrained weights. Licensing the whole project under AGPL-3.0-or-later removes any ambiguity about the combined work and allows publishing Docker images and bundles that include these libraries.

### What you can do
* Use it, internally or commercially, for any purpose, including in public bodies.
* Study and modify it.
* Redistribute it, original or modified, **under the same license** and with the corresponding source.
* Run it as a network service. If you **modified** it, you must offer the users of that service the source of your modified version (AGPL-3.0, section 13), for example through a "Source" link.

### What you cannot do
* Distribute or host a modified version while keeping the changes closed.
* Combine it into a proprietary product without complying with the AGPL or obtaining separate licenses from every copyright holder.
* Use the **name and logos** (see [../TRADEMARKS.md](../TRADEMARKS.md)): the AGPL covers the source code, not the brand.

### Third-party components
See [../NOTICE](../NOTICE). Compatible permissive dependencies (Apache-2.0, MIT, BSD) are used under their own licenses. Models you run through Ollama are **not** distributed by this project and carry their own licenses.

### Contributions
Contributions are accepted under the project's license (AGPL-3.0-or-later). Source files carry an `SPDX-License-Identifier: AGPL-3.0-or-later` header. Contributors keep their copyright; use a Developer Certificate of Origin sign-off (`git commit -s`).

### Alternative licenses
Organizations that cannot use AGPL terms would need a separate agreement with all copyright holders **and** commercial licenses for PyMuPDF (Artifex) and Ultralytics, or replacement of those dependencies (for example pypdfium2 + pikepdf and a permissively licensed detector with onnxruntime). This is on the long-term roadmap, not implemented.

### Name and logos
The names "PRIVIO", "PRIVIO SENTRY", "SENTRY Redact" and the artwork in `assets/` and `docs/brand/` are not licensed for reuse; see [../TRADEMARKS.md](../TRADEMARKS.md).

---

## Português (Brasil)

**O PRIVIO SENTRY é licenciado sob a GNU Affero General Public License v3.0 ou posterior (AGPL-3.0-or-later).** Veja [../LICENSE](../LICENSE).

### Por que AGPL
O projeto importa **PyMuPDF** (AGPL-3.0 ou licença comercial paga da Artifex) e **Ultralytics** (AGPL-3.0, que também se aplica a modelos treinados com ela), e inclui `models/signature_stamp_detector.pt`, derivado dos pesos pré-treinados da Ultralytics. Licenciar o projeto inteiro em AGPL-3.0-or-later elimina a ambiguidade sobre a obra combinada e permite publicar imagens Docker e pacotes que incluam essas bibliotecas.

### O que você pode fazer
* Usar, internamente ou comercialmente, para qualquer finalidade, inclusive em órgãos públicos.
* Estudar e modificar.
* Redistribuir, original ou modificado, **sob a mesma licença** e com o código-fonte correspondente.
* Executar como serviço de rede. Se você **modificou** o código, deve oferecer aos usuários do serviço o código-fonte da sua versão (AGPL-3.0, seção 13), por exemplo com um link "Código-fonte".

### O que você não pode fazer
* Distribuir ou hospedar uma versão modificada mantendo as alterações fechadas.
* Incorporar a um produto proprietário sem cumprir a AGPL ou obter licenças separadas de todos os detentores de direitos autorais.
* Usar o **nome e os logotipos** (veja [../TRADEMARKS.md](../TRADEMARKS.md)): a AGPL cobre o código, não a marca.

### Componentes de terceiros
Veja [../NOTICE](../NOTICE). Dependências permissivas compatíveis (Apache-2.0, MIT, BSD) são usadas sob suas próprias licenças. Modelos executados via Ollama **não** são distribuídos por este projeto e têm licenças próprias.

### Dependências opcionais (extras do pyproject)

| Extra | Pacotes | Licença |
|---|---|---|
| `nomes` | gliner, protobuf, truststore; modelo `urchade/gliner_multi_pii-v1` | Apache-2.0 / BSD-3 / MIT; modelo Apache-2.0 |
| `ocr-extra` | rapidocr, onnxruntime (modelos PP-OCR do PaddleOCR) | Apache-2.0 / MIT; modelos Apache-2.0 |
| `laya` | laya, truststore | Apache-2.0 / MIT |

Modelos de IA servidos por Ollama/LM Studio/servidor da organização ficam fora do projeto: confira a licença de
cada modelo que você baixar (ex.: DeepSeek-OCR 2 tem indicação de Apache-2.0 no Hugging Face e menção à licença
própria da DeepSeek: confira antes de uso institucional).

### Contribuições
Contribuições são aceitas sob a licença do projeto (AGPL-3.0-or-later). Os arquivos-fonte trazem o cabeçalho `SPDX-License-Identifier: AGPL-3.0-or-later`. Os contribuidores mantêm seus direitos autorais; use a assinatura DCO (`git commit -s`).

### Licenças alternativas
Organizações que não possam adotar os termos da AGPL precisariam de acordo separado com todos os detentores de direitos **e** de licenças comerciais do PyMuPDF (Artifex) e da Ultralytics, ou da substituição dessas dependências (por exemplo pypdfium2 + pikepdf e um detector permissivo com onnxruntime). Isso está no roadmap de longo prazo, não implementado.

### Nome e logotipos
Os nomes "PRIVIO", "PRIVIO SENTRY", "SENTRY Redact" e a arte em `assets/` e `docs/brand/` não são licenciados para reuso; veja [../TRADEMARKS.md](../TRADEMARKS.md).

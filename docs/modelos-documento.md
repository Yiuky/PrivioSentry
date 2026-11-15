# Modelos de documento

Documentos de **layout conhecido**, como licenças, autorizações e formulários de um mesmo órgão, podem ser
tarjados por **modelo**. O modelo reconhece o tipo do documento por frases fixas e tarja os campos que vêm depois
de rótulos, como `PROPRIETÁRIO:` ou `CPF/CNPJ:`. Reconhecer e tarjar **não gasta token**: não há IA nessa etapa.
Depois, uma **inspeção** procura o que ficou de fora. A revisão humana de cada documento continua obrigatória.

```text
OCR / texto digital ─► reconhecer (frases fixas) ─► tarjar campos do modelo ─► demais fases (CPF, perfil, YOLO...)
                                                         │
                                       modelo aprovado + "dispensar IA" + campos achados
                                                         ▼
                                      IA de visão de endereços NÃO roda nessas páginas
                                                         ▼
               inspeção: regras (rótulo com valor sem tarja) + agente lendo o texto JÁ TARJADO (█)
                                                         ▼
                                   editor: revisão humana ─► Aplicar proteção
```

## Onde fica

| Parte | Arquivo |
|---|---|
| Formato e pasta (`PRIVIO_DOC_TEMPLATES_DIR`, padrão `./modelos_documento`, fora do git) | `utils/doc_templates/schema.py` |
| Reconhecer, aplicar campos e inspeção por rótulos | `utils/doc_templates/engine.py` |
| Rascunho a partir de documento revisado (com IA opcional) | `utils/doc_templates/draft.py` |
| API `/doc-templates/*` (router separado, contrato JSON) | `utils/doc_templates/api.py` |
| Fases no pipeline | `main.py` (`run_template_phase`, `run_template_inspection`) |
| Rótulos da inspeção (regras como dados) | `utils/detect/data/rotulos_inspecao.json` |
| Tela | Administração › Modelos de documento |

## Criar um modelo

1. Processe um documento do tipo, **revise** as tarjas no editor e clique em **Salvar**. Só as tarjas salvas
   pelo revisor ensinam o modelo; as sugestões da IA não revisadas não servem.
2. No menu ⋮ da tarefa, clique em **Criar modelo de documento**, ou vá em Administração › Modelos de documento e
   escolha o documento.
3. **Gerar rascunho**:
   - cada tarja vira um **campo** ancorado no rótulo à esquerda (`CPF/CNPJ:`) ou na linha de cima;
   - as primeiras linhas fixas da página 1 e os títulos em maiúsculas viram as **frases de reconhecimento**;
   - linhas com dígitos, com algo tarjado ou com palavra tarjada em outro lugar (um nome) nunca viram frase;
   - tarja sem rótulo perto **não** vira campo e o relatório diz quantas ficaram assim.
4. **Com ajuda da IA** (opcional), a IA recebe só o texto **mascarado**: tarjas viram `█` e dígitos viram `#`.
   - Ela sugere nome, frases e rótulos.
   - Sugestão que não existe literalmente no texto é descartada.
   - Os campos sugeridos aparecem marcados como "sugerido pela IA" e não são obrigatórios.
   - A chamada respeita a trava de IA externa (`AI_ALLOW_EXTERNAL`).
5. Confira e ajuste:
   - **Frases de reconhecimento:** frases do título que só este tipo tem, nunca nomes ou números.
   - **Campos:** rótulo; tipo; valor à direita ou abaixo; máximo de palavras; linhas (endereço que quebra a linha
     usa 2); obrigatório; páginas.
6. Clique em **Testar no documento**:
   - mostra se o modelo reconhece o documento e quantas palavras cada campo tarja (só contagens);
   - mostra campos não encontrados e outros modelos parecidos;
   - teste também em documentos de **outros tipos**: o modelo não pode reconhecê-los.
7. **Salvar** grava como **rascunho**. Rascunho já tarja, mas nunca dispensa a IA.
8. **Aprovar**. Só um modelo aprovado com **Dispensar a IA de visão** ligado deixa de chamar a IA de endereços.
   Qualquer edição ou importação posterior volta o modelo para rascunho e sobe a versão.

**Exportar/Importar JSON** leva modelos entre servidores. O modelo importado chega como rascunho.

## Regras de segurança

- **Nada aqui aprova o documento.** Tarja por modelo não marca o documento como aprovado, e o PDF só sai para a
  API e para agentes depois de **Aplicar proteção** (`?final=true`).
- **Dois modelos com pontuação parecida** (diferença < 10 pontos): nenhum é aplicado e o documento vai para
  revisão.
- **Valor:** vai até o próximo rótulo, nunca para num espaço grande. Se o limite de palavras cortar antes, a
  página vai para revisão. Rótulo colado no valor (`CPF:123...`) tarja só o que vem depois dos dois-pontos.
  `Nome do empreendimento:` não é confundido com o rótulo `Nome:`.
- **Campo obrigatório não encontrado:** revisão, e a IA de visão não é dispensada.
- **IA dispensada só por página**, com modelo aprovado, todos os campos obrigatórios encontrados e ao menos um
  valor de campo achado **nesta** página. Anexos, páginas só de imagem e páginas sem campo continuam com a IA.
  Página digitalizada com camada de texto rala é lida pelo OCR, não pela camada.
- **"Dispensar a IA" é experimental.** Só ligue com um modelo de agente que passou na verificação
  `inspecao_modelo` ([procedimento](procedimento-ia-externa.md)), com acerto em todas as repetições. Medido com
  modelos de baixo custo do Gemini: o resultado variou entre rodadas (4 de 5 numa, 5 de 5 e 6 de 6 em outras), então uma rodada aprovada não basta. Nesse
  caso, mantenha a IA de visão.
- **Inspeção depois das tarjas** (`DOC_TEMPLATE_INSPECTION`):
  - `agente` (padrão):
    - o agente do segundo olhar (`SECOND_LOOK_MODEL`; sem ele, o modelo da IA principal) lê o texto com as tarjas já trocadas por `█` e aponta CPF, nomes, telefones,
      endereços e o que mais o perfil pedir;
    - só vale o que for localizado nas palavras **sem** tarja e passar nos validadores;
    - o achado vira tarja e revisão; se o agente falhar, a página vai para revisão.
    - Gasta poucos tokens: só texto, sem imagem.
  - `regras` (zero token):
    - rótulo típico de dado pessoal (`Fone:`, `CPF:`...) com valor sem tarja vai para revisão;
    - página em que a IA de visão foi dispensada vai **sempre** para revisão, porque ninguém procurou endereço
      fora dos campos.
- A tarefa registra o modelo usado (`modelo_documento`: id, versão, pontuação, tarjas, páginas sem IA e números
  da inspeção). O cartão mostra **Modelo: <nome>**.

## Quando não serve

- **Texto corrido**, como portarias e termos: não tem rótulos para ancorar os campos. Use o pipeline normal.
- **Documento digitalizado:** o reconhecimento usa o OCR. As frases precisam sair iguais no OCR (comparação exata
  depois de normalizar acentos e pontuação). Teste com o botão.
- **Tipos parecidos do mesmo órgão:** o cabeçalho do órgão é comum a eles. Use frases do **título** e teste nos
  outros tipos.

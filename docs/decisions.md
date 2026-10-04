# Decisor local e automelhoramento (Laya)

> **Estado: experimental e desligado por padrão.** O decisor só observa (modo sombra) até que um perfil
> treinado seja aprovado pelo portão de qualidade. Mesmo no modo assistido, ele **nunca tira uma tarja**:
> só pode acrescentar proteção ou pedir revisão.

## O que é

Uma camada que **decide sobre o que já foi detectado**, usando um *modelo de decisão* local: em vez de
gerar texto, ele escolhe entre respostas definidas e devolve uma probabilidade. Usamos o
[Laya](https://huggingface.co/convaiinnovations/laya) (Convai Innovations, Apache-2.0), versão
multilíngue, que roda inteiro na máquina, inclusive na CPU (cerca de 0,1 s por decisão nos testes).

A primeira decisão é **"este endereço é residencial?"**. Hoje quem responde é o LLM de visão; o decisor dá
uma segunda opinião calibrada e barata. Outras decisões (exceções da política, perfil do documento) estão
no [backlog](../BACKLOG.md).

```
OCR → endereços (LLM de visão) → DECISOR (Laya + perfil treinado) → revisão humana → tarja → verificação
                                      ↑                                   │
                                      └──── automelhoramento ◄────────────┘  (correções do revisor)
```

## Como funciona

1. **Perguntas** (`utils/decisions/questions.py`): o Laya responde 9 perguntas numa única passada: 4 de
   juízo (residencial? empresa? órgão público? rural/obra?) e 5 objetivas ("o texto menciona moradia /
   empresa / órgão / área rural?", "diz que alguém mora ali?"). O texto é **minimizado** antes: CPFs
   mascarados e todos os dígitos trocados por `0`.
2. **Cabeça treinável** (`learning.py`): o Laya fica congelado; uma regressão logística (método de Newton,
   com padronização) aprende a combinar as 9 respostas e devolve a probabilidade de "residencial".
3. **Limiares** aprendidos dividem a probabilidade em três faixas: *residencial*, *incerto* e *não
   residencial*.
4. **Regra de combinação** (`policy.py`), no modo assistido:

| LLM diz | Decisor diz | Resultado |
|---|---|---|
| pessoal | qualquer coisa | **tarja** (o decisor nunca reduz proteção) |
| não pessoal | residencial | **tarja** + "Requer revisão" |
| não pessoal | incerto | sem tarja + "Requer revisão" |
| não pessoal | não residencial | sem tarja |
| — | decisor falhou | segue o LLM + "Requer revisão" |

## Automelhoramento

| Etapa | O que acontece | Onde |
|---|---|---|
| Coleta | Ao clicar em **Aplicar proteção**, as tarjas finais do revisor viram exemplos rotulados: endereço coberto = residencial; não coberto = não residencial | `feedback.py` (só com `LEARNING_ENABLED=1`) |
| Treino | Exemplos sintéticos fictícios + correções do revisor (que valem 3×) treinam um **candidato** | `python -m utils.decisions train` |
| Portão | O candidato é medido num conjunto **realista fixo**, escrito à mão e fora do treino (`synthetic.REALISTIC`), e num conjunto gerado. Só vira ativo se atingir os mínimos e não piorar o perfil ativo | `learning.GATE` |
| Versões | Cada perfil é salvo (`v1`, `v2`...) com suas métricas; dá para voltar atrás | `python -m utils.decisions rollback` |

Mínimos do portão (em `learning.GATE`), no conjunto realista: AUC ≥ 0,85, precisão ao afirmar
"residencial" ≥ 0,85, acerto ao afirmar "não residencial" (NPV) ≥ 0,85, queda de AUC ≤ 0,01 em relação
ao perfil ativo; e AUC ≥ 0,90 no conjunto gerado.

### Resultado de referência (2026-10-04, CPU)

| Conjunto realista (36 endereços fictícios escritos à mão, fora do treino) | Laya sem treino | Laya treinado |
|---|---|---|
| AUC | 0,83 | **0,91** |
| Precisão ao afirmar "residencial" | — | 0,92 |
| NPV ao afirmar "não residencial" | — | 0,88 |
| Casos incertos (vão para revisão) | — | 17% |

Em 8 endereços novos, fora de todos os conjuntos, o perfil acertou 7. O erro foi um endereço sem nenhuma
pista no texto ("Rua Treze de Maio, 45, Vila Rica"), ambíguo até para uma pessoa.

**Lição registrada:** um primeiro perfil, com 4 perguntas e avaliado só no conjunto gerado, marcou AUC 0,95
e foi aprovado, mas errou feio em textos reais (deu nota alta a uma Secretaria e a uma fazenda). Por isso
o portão passou a usar o conjunto realista, as perguntas objetivas foram acrescentadas e o treino passou a
convergir de verdade. O conjunto realista ainda é pequeno: amplie-o (só com textos fictícios) antes de
confiar no modo assistido (backlog B-78). O que melhora o modelo de verdade são as correções do revisor em
documentos reais, guardadas só na sua máquina.

## Como usar

```bash
pip install -e ".[laya]"            # ou: pip install -r requirements-laya.txt
python -m utils.decisions train     # 1º treino (baixa o modelo, ~2 min na CPU); aprova ou reprova
python -m utils.decisions status    # perfil ativo, histórico e exemplos guardados
```

No `.env`:

```ini
DECISION_ENGINE=laya      # liga o decisor
DECISION_MODE=shadow      # comece observando; troque para assist depois de um perfil aprovado
LEARNING_ENABLED=1        # opcional: aprender com as correções do revisor
```

Com `DECISION_MODE=assist` e nenhum perfil aprovado, o decisor continua em modo sombra (e avisa no log).
Depois de algumas semanas de revisões, rode `train` de novo: o novo perfil só entra se passar no portão.

| Comando | Para quê |
|---|---|
| `python -m utils.decisions status` | Perfil ativo, histórico, mínimos do portão e quantidade de exemplos |
| `python -m utils.decisions train` | Treina um candidato (saída `0` aprovado, `2` reprovado) |
| `python -m utils.decisions rollback` | Volta ao perfil aprovado anterior (ou ao modo sem perfil) |
| `python -m utils.decisions purge --yes` | Apaga exemplos, cache e perfis desta máquina |
| `python -m utils.decisions detectores` | Precisão observada de cada detector pelo revisor (mantidas × removidas × acrescentadas) e **sugestões** para quem mantém as regras. Só contagens; nada é mudado sozinho: reduzir proteção exige uma pessoa, uma mudança em `utils/detect/data` e o corpus mostrando que não piorou |

## Privacidade

- O Laya roda localmente; nenhum texto sai da máquina. O modelo é baixado uma vez do Hugging Face, sempre
  num **commit fixado no próprio PrivioSentry** (`PINNED_MODEL_REVISIONS` em `engine.py`), e os pesos são
  lidos em safetensors (formato que não executa código). Outro modelo remoto só é aceito com
  `LAYA_REVISION=<commit>`. O pacote `laya` também tem versão exata. Em redes com proxy e inspeção TLS, o
  pacote `truststore` faz o Python usar os certificados do sistema.
- Os exemplos de treino ficam em `PRIVIO_LEARNING_DIR` (padrão: pasta `learning/` do projeto, fora do git e
  da imagem Docker), com o texto minimizado. Ainda assim contêm **palavras de endereços**: trate a pasta
  como dado pessoal. Cada exemplo é ligado à tarefa de origem e **apagado junto com ela** (inclusive pela
  retenção `RETENTION_DAYS`); `purge` apaga tudo, e só os arquivos que o aprendizado criou.
- `decisions.json` fica na pasta de cada tarefa (`output/<tarefa>/`) e é apagado junto com ela e pelo
  `/purge`.

## Limitações

- Só a decisão "endereço residencial?" existe hoje.
- **O ajuste fino dos pesos do Laya não é feito.** O pacote não publica uma rotina de treino; treinamos uma
  cabeça leve e os limiares por cima do modelo congelado (backlog B-76).
- Sem treino, o Laya separa mal os casos. Por isso o modo assistido exige um perfil aprovado.
- Endereços sem pista no texto (sem "apto", "casa", nome de empresa ou órgão) são ambíguos: o decisor
  tende a dizer "não residencial". Como ele nunca tira tarja, isso não piora o resultado do LLM, mas
  também não ajuda nesses casos.
- O rótulo vindo da revisão é inferido pelas caixas finais: se o revisor tarjou um endereço por outro
  motivo, o exemplo pode sair errado. O peso maior dado às correções e o portão limitam o estrago.

## Para desenvolvedores

| Arquivo | Papel |
|---|---|
| `utils/decisions/questions.py` | Perguntas e normalização. Mudou? Suba `QUESTIONS_VERSION` (perfis antigos passam a ser ignorados) |
| `utils/decisions/engine.py` | `LayaEngine` (carrega o modelo no 1º uso), `Profile`, `DecisionService`, `get_engine()` |
| `utils/decisions/policy.py` | Regra de combinação. Invariante: nunca reduzir proteção |
| `utils/decisions/learning.py` | Exemplos, cache, treino, limiares, portão, versões |
| `utils/decisions/feedback.py` | `decisions.json` e rótulos a partir da revisão |
| `utils/decisions/synthetic.py` | Endereços fictícios rotulados (treino e avaliação) |
| `tests/test_decisions.py` | Testes com motor falso (sem Laya, sem rede) |

Para acrescentar uma decisão nova: crie as perguntas em `questions.py`, a regra em `policy.py` (sem
nunca reduzir proteção), o ponto de uso no pipeline e os testes com um motor falso.

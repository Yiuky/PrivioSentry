# experimental/

Código de pesquisa inacabado, **não usado pelo pipeline e não coberto por testes**.

* `agent_loop/` - um agente LLM (estilo ReAct) que dá zoom em uma grade da página e tarja chamando ferramentas. Execute a partir desta pasta: `cd experimental && python -m agent_loop.test_agent`. Requer Ollama e Tesseract; ele pede o caminho de um PDF. Não o alimente com documentos reais a menos que você controle a máquina.

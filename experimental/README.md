# experimental/

Unfinished research code, **not used by the pipeline and not covered by tests**.

* `agent_loop/` - an LLM agent (ReAct style) that zooms into a page grid and redacts by calling tools. Run from this folder: `cd experimental && python -m agent_loop.test_agent`. Requires Ollama and Tesseract; it prompts for a PDF path. Do not feed it real documents unless you control the machine.

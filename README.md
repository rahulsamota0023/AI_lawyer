# Nyay Saathi: an AI lawyer for everyday problems in India

Conversational helper (Hindi / English / Hinglish) for three problems: **rental deposit not returned**, **refund / defective product or service**, **unpaid salary**. It builds a case card, explains options in plain language, checks the time limit, drafts the notice/complaint, and lets you rehearse against the other side.
**It is an AI, not a lawyer.** Anything outside its three topics gets a "see a lawyer / NALSA 15100" reply.

## Run it (2 minutes)
```bash
pip install -r requirements.txt
streamlit run app.py                    # opens in browser; choose provider in the sidebar
# or terminal:  python cli.py --provider gemini
```
No key? Pick **mock** in the sidebar: an offline demo (templated, not AI) so you can see the rules, case card, limitation clock and papers.
Free Gemini key: https://aistudio.google.com  ->  `export GEMINI_API_KEY=...`

**Swap the model** (the interview requirement): sidebar dropdown, or `LLM_PROVIDER=anthropic|openai|gemini` plus `LLM_MODEL=...` and the matching `*_API_KEY`. Defaults live in `core/llm.py` (`DEFAULT_MODELS`; update if a model name is retired). To add another provider, add one `_name()` method in `core/llm.py`.

## Deploy the prototype link (free)
1. Push this folder to a public GitHub repo (`.env` and `secrets.toml` are git-ignored).
2. share.streamlit.io -> New app -> pick the repo, main file `app.py`.
3. App settings -> Secrets -> paste `GEMINI_API_KEY = "..."` (see `.streamlit/secrets.toml.example`).
Backup: `colab_demo.ipynb` (replace the repo URL in cell 1).

## Tests and raw outputs
```bash
pytest -q                                        # 23 pure-code tests, no network
python run_tests.py --provider mock              # offline: rules, KB, clock, templates
python run_tests.py --provider mock-trap         # offline: fake model injects invented citations; checker must strip them
python run_tests.py --provider gemini            # REAL model outputs -> raw_outputs/gemini/  (run this before submitting)
```
`raw_outputs/mock` and `raw_outputs/mock_trap` are included, unedited. **They were produced without a language model.** Generate `raw_outputs/gemini` yourself and submit that folder.

## How it is built
```
core/router.py      language + problem-type rules (EN/HI/Hinglish)
core/guardrails.py  escalation rules + citation checker (NO LLM)
core/case.py        case card validation, missing fields, limitation clock
core/engine.py      turn pipeline: rules -> LLM extract -> code checks -> LLM explain (KB only) -> citation audit
core/notice.py      fixed legal templates; free text is citation-checked before insertion
core/llm.py         swappable providers over plain HTTPS (gemini/anthropic/openai/mock)
kb/*.json           hand-verified provisions with source URL + verified flag. New topic = new file here
```
Add a topic: copy `kb/tenancy.json`, edit provisions/fields/limitation, add a router rule and a template in `core/notice.py`.

## Knowledge base
Verified 7 Nov 2026 against official or legal-publisher pages (URLs inside each JSON entry). Entries marked `"verified": "partial"` are hedged in replies. Helplines and the e-Daakhil URL are `from_memory` and must be re-checked before public launch. **Laws change; re-verify on a schedule.**

## Known limits (see the solution doc)
Checker verifies that citations exist and figures match the KB, not that a real provision is applied correctly. It over-removes some benign "X v. Y" phrases. Voice input is untested. Real-model quality is unmeasured until you run `run_tests.py --provider gemini`.

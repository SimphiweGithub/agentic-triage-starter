# Generic agentic triage starter

This is a reusable shell for the final hackathon brief. Its current assessment is intentionally conservative: it assigns a placeholder severity, confidence `0.5`, and **no action**. Do not submit its decisions as challenge predictions until the domain contract is configured.

## Setup and run

From the repository root with Python 3.11+:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000`. API and dashboard share port 8000. No CORS middleware or separate frontend build is used. The browser scripts load Tailwind and Alpine from CDNs; API calls use relative `/api/` paths.

The CLI accepts ordered CSV or JSONL files containing the placeholder fields `report_id`, `timestamp`, `source`, and `payload`:

```powershell
.\.venv\Scripts\python.exe runner.py sample.jsonl --output decisions.jsonl
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

`decisions.jsonl` uses the temporary `DecisionRecord` schema. Once the judges provide the exact output contract, adapt `domain/schemas.py` and the serializer in `runner.py` before submission.

## Challenge day swap order

1. Put the supplied input and output fields and enums in `domain/schemas.py` and `domain/enums.py`.
2. Update `domain/logic.py` to parse records, provide correlation text, and assess severity, confidence, action proposals, and requested states.
3. Configure allowed transitions, forbidden actions, high impact actions, and safe actions in `domain/policy.py`. The default policy has no external action executor.
4. Define the relationship ontology in `prompts/relation.md`. Set `ENABLE_LLM_RELATION=1` with `GEMINI_API_KEY` to turn on the structured Gemini second tier; `GEMINI_MODEL` is optional. The default remains deterministic and offline. `core/client.py` handles structured JSON and retries.
5. Adapt `runner.py` for any new transport or exact export contract. Keep source order. Run the regression tests and `evaluation.py` checks.

`core/` should remain a stable orchestration layer. All action proposals pass through `core/guardrails.py`, and all lifecycle requests pass through `core/fsm.py`. Review approval records a human decision; it does not execute an action. Add an explicit domain action executor only after the challenge's operations and authorization rules are known.

The dashboard links a raw report to its incident master, decision trace, and review item in both directions. It accepts individual generic reports or a JSONL replay. The runtime is in memory for rapid iteration, so restarting the server clears state.

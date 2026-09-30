# Divitiae Tech agentic triage starter

The final intercampus hackathon brief and data are not yet known. This repository is a generic starter. The previous campus qualifier is historical context, not the final domain.

## Git attribution

Never add a `Co-Authored-By: Codex ...` trailer or any other self-attribution to commits or pull requests.

## Architecture

- Serve `/api/...` and `/static/...` from the same FastAPI process on port 8000. Use the single HTML dashboard with Tailwind and Alpine.js. Do not add CORS or a separate frontend build.
- Keep challenge-specific schemas, enums, parsing, assessment rules, action registries, and transition graphs in `domain/`. Keep model prompts in `prompts/`. Adapt `runner.py` when the judges reveal the input transport or exact output contract.
- Run every lifecycle request through `core/fsm.py`. Illegal transitions enter `PENDING_REVIEW`.
- Run every proposed action through `core/guardrails.py`. Destructive, high-impact, forbidden, mismatched service/action, and confidence below `0.75` require human review. No external action executor is connected until the final domain and authorization rules are known.
- Keep clickable links among raw reports, incident masters, decision traces, action proposals, and reviews.

## Qualifier lessons

The qualifier scored 49.79/60 automated with full coverage and 24/25 qualitative. Largest losses were action/service selection, correlation labels, and safety triggers; lifecycle and dashboard linking also need attention. Use fuzzy matching as a candidate filter and an optional structured Gemini relation classifier as the second tier. The model can advise, but typed schemas, action policy, and the FSM control persisted decisions.

When the final brief arrives, configure `domain/enums.py`, `schemas.py`, `logic.py`, and `policy.py`; update `prompts/relation.md` and the runner adapter; then run tests and evaluate ordered coverage, state validity, duplicate suppression, forbidden-action review, changing evidence, and UI links. Record the trade-offs and edge cases for the technical defence.

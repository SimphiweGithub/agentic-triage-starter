# KinGuard backend

KinGuard protects an older or digitally vulnerable person from scam messages, predatory debit orders and subscription creep. This repository is the backend only; the front end is built separately against `API.md`.

## Git attribution

Never add a `Co-Authored-By: Codex ...` trailer or any other self-attribution to commits or pull requests.

## Architecture

- One FastAPI process serves `/api/...`. `static/index.html` is a developer console, not the product front end. Cross-origin access is off unless `CORS_ORIGINS` lists the front end's address.
- Models advise, Python decides. Jev answers yes/no questions in the gate (`domain/gate.py`); Gemini words the warning shown to the person (`domain/language.py`); every model call has a rule-based fallback.
- Run every lifecycle request through `core/fsm.py`. Illegal transitions enter `PENDING_REVIEW`.
- Run every action through `core/executor.py`, which gates each attempt with `core/guardrails.py`. High-impact, forbidden, mismatched and low-confidence actions wait for the caregiver.
- Matching text alone never makes a duplicate. `core/correlator.py` links by explicit link, shared identifier, then guarded fuzzy text.
- Human review is a hold on the incident. It clears only when no review is pending and `domain.logic.risk_persists` returns false.
- One decision per kept input row. Parse and processing failures become `PENDING_REVIEW` decisions. One-time codes are discarded before storage.
- Keep domain rules, thresholds and tools in `domain/`; keep `core/` domain-neutral.

## Working rules

- Every backend file is explained line by line in `backend/docs/01` to `backend/docs/05`. When code changes, update the matching walkthrough and its line numbers.
- Measure before tuning. Use `calibrate.py` with a held-out split and `evaluation.py --truth`; record results in `RATIONALE.md`.
- Tests never call the real model APIs. They set `KINGUARD_SKIP_ENV_FILE=1`.
- Keys live only in `backend/.env`, which git ignores.

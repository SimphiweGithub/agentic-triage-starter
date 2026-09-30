# KinGuard

An agent that protects an older or digitally vulnerable person from scam messages, predatory debit orders and subscription creep. It reads forwarded emails and shared SMS messages, investigates them with tools, acts within a policy, checks whether its action worked, and corrects itself. A caregiver approves anything that touches the person's bank relationship.

Everything outside the agent is simulated: the bank, the company registry, the domain registry and the mail filter live in `domain/tools.py`. No real system is touched.

## Setup and run

From this folder with Python 3.11+:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000
```

This project is the backend only. The front end is built separately against `API.md`; interactive API documentation is at `http://127.0.0.1:8000/docs`. The page at `http://127.0.0.1:8000` is a plain developer console for watching the engine.

```powershell
.\.venv\Scripts\python.exe runner.py samples\kinguard.jsonl --output decisions.jsonl
.\.venv\Scripts\python.exe evaluation.py samples\kinguard.jsonl decisions.jsonl --truth samples\kinguard_truth.jsonl --issues
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

## How a message flows

1. **Intake** (`domain/intake.py`, `core/ingest.py`): an email or shared message becomes a row. One-time codes are discarded; account numbers are masked.
2. **Extract** (`domain/extract.py`): merchant, amount, reference, domains, phone numbers, sender checks.
3. **Correlate** (`core/correlator.py`): link to an incident by explicit link, shared identifier, or guarded fuzzy text.
4. **Gate** (`domain/gate.py`): a cheap risk score. Benign messages stop here.
5. **Investigate** (`domain/investigate.py`): domain age, company registry, debit history.
6. **Assess** (`domain/logic.py`): severity, confidence, and one proposed action.
7. **Decide** (`core/fsm.py`, `core/guardrails.py`): is the state change legal, and may the action run without a human?
8. **Act, check, correct** (`core/executor.py`): run the tool; on failure try a corrected action; otherwise ask a human.
9. **Record** (`core/runtime.py`): the decision, its trace, the action history and any review.

## What the sample scenario shows

| Message | Behaviour |
|---|---|
| K01 scam email | Investigated, sender blocked, person warned |
| K02 same email again | Recognised as a duplicate; no second action |
| K03 one-time PIN | Discarded before storage |
| K04 debit to a truncated merchant name | Ambiguous registry lookup retried with the payment reference; dispute held for the caregiver |
| K05 known subscription | Benign |
| K06 email containing instructions aimed at the agent | Instructions ignored; domain-wide block refused for a shared provider and narrowed to the one address |
| K07 same operator billing under a new company name | Linked by reference; because the earlier dispute did not stop it, escalated to an operator block |
| K08 subscription price jump | Flagged for the caregiver; withdrawn and the merchant trusted if the person confirms it |
| Unreadable line | Still gets a decision, routed to a human |

Also built, outside that file:

- **Mandate requests.** A company asking to set up a debit is advised against unless it can be verified, because an approved mandate is hard to dispute.
- **Dispute deadline.** Each drafted dispute carries the last date to lodge it (60 days) and the steps.
- **No guardian.** With `KINGUARD_GUARDIAN=0`, or through `POST /api/settings/guardian`, approvals go to the person themselves, and confirming a high-risk sender needs a 24-hour cooling-off.

## Line-by-line walkthrough

`docs/01` to `docs/05` explain every backend file, line by line.

## Switches

All off by default. Set them as environment variables before starting the server.

| Variable | Effect |
|---|---|
| `KINGUARD_LIVE_LOOKUPS=1` | Domain age is looked up for real through RDAP, falling back to fixture data. Tested against live domains; `.co.za` is not covered by RDAP. |
| `ENABLE_JEV=1` with `TYPESAFE_API_KEY` | The gate also asks Jev four yes/no questions and the threat type. Jev can add suspicion, never remove it. Measured on held-out SMS: rules alone caught 53%, rules plus Jev 87%. |
| `ENABLE_GEMINI=1` with `GEMINI_API_KEY` | Gemini rewords the warning shown to the person. The result is rejected if it contains a number, link or address. `GEMINI_MODEL` is optional (default `gemini-3.5-flash-lite`). |

| `IMAP_HOST`, `IMAP_USER`, `IMAP_PASSWORD` | A live inbox: unread emails in a mailbox created for KinGuard are taken in every `IMAP_POLL_SECONDS` (default 15). Tested with a stand-in mailbox only. |

Every model call has a rule-based fallback, and model output passes through the same state machine, guardrails and executor as the rules.

## Calibrating the gate

```powershell
.\.venv\Scripts\python.exe calibrate.py labelled.jsonl
```

Prints caught, false alarms and missed at every threshold. The labels must be written by someone other than the rule author.

# KinGuard API contract

For whoever builds the front end. The backend is the only thing that decides
anything; the front end sends messages in, shows what the agent did, and
collects two human answers: the person's "this is mine" and the caregiver's
approve or reject.

- Base address: `http://127.0.0.1:8000/api`
- Interactive documentation with every schema: `http://127.0.0.1:8000/docs`
- All bodies are JSON. There is no authentication yet.
- State is in memory. Restarting the server, or `POST /reset`, clears it.

## Running it

```powershell
.\.venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000
```

Two ways to connect a front end:

1. **Same origin.** Put the built front end in `static/` and it is served from
   the same port. Nothing else to configure.
2. **Separate dev server.** Set `CORS_ORIGINS` in `.env` to the front end's
   address, for example `CORS_ORIGINS=http://localhost:5173`, and restart.

## The three screens and the calls they need

### 1. Getting a message in

| Call | Body | Returns |
|---|---|---|
| `POST /intake/share` | `{"text": "...", "sender": "YourBank", "channel": "sms"}` | A decision, or `{"status": "withheld", "reason": "..."}` |
| `POST /intake/email` | `{"content": "<raw .eml text>"}` | The same |

`sender` and `channel` are optional. A message containing a one-time code is
withheld: nothing is stored and no decision is made. Show that as "not kept".

### 2. The protected person

| Call | Returns |
|---|---|
| `GET /outbox` | `[{"incident_id": "I0001", "message": "..."}]`, oldest first |
| `POST /incidents/{incident_id}/feedback` with `{"legitimate": true}` | A decision |

`message` is written for the person and is safe to show as it is. When they
answer "this is mine", post the feedback. For a low-risk incident the agent
undoes its actions. For a high-risk one the answer is held for the caregiver,
and the returned decision has `requires_human_approval: true`.

### 3. The caregiver

| Call | Returns |
|---|---|
| `GET /reviews?status=PENDING` | The queue of things waiting for approval |
| `POST /reviews/{review_id}/decision` with `{"approved": true}` | The updated review |
| `GET /incidents` | Every incident |
| `GET /incidents/{incident_id}` | One incident with its reports, decisions and reviews |
| `GET /decisions/{report_id}` | One decision with its reasoning trace |

Approving runs the held action immediately. Rejecting means it never runs.
Deciding the same review twice returns `409`.

### Everything at once

`GET /state` returns reports, incidents, decisions, reviews and `world`
(outbox, flagged senders, disputes, blocked operators, trusted merchants).
Polling it every few seconds is the simplest way to keep a screen current.

## What comes back

### A decision

```json
{
  "report_id": "S-1a2b3c4d",
  "incident_id": "I0001",
  "relationship": "RELATED",
  "status": "PENDING_REVIEW",
  "severity": "HIGH",
  "confidence": 0.75,
  "proposed_action": {"type": "DRAFT_DISPUTE", "service": "BANK", "details": {"company": "TechCare Support", "amount": 349.0}},
  "action_outcome": "HELD_FOR_REVIEW",
  "suppressed_action": null,
  "requires_human_approval": true,
  "review_id": "REV-0001",
  "previous_status": "CONTAINED",
  "previous_severity": "HIGH",
  "previous_confidence": 0.95,
  "labels": {"threat": "GREY_MARKET_SUBSCRIPTION", "merchant": "techcare", "reg_no": "2026/118822/07"},
  "trace": ["Correlation: RELATED (1.000) — Shared identifier operator:D-7781", "Risk 0.45. ...", "FSM: CONTAINED → CONTAINED", "Action: DRAFT_DISPUTE → HELD_FOR_REVIEW (High impact action requires approval)", "Review: High impact action requires approval (REV-0001)"]
}
```

`trace` is the reasoning, one step per line, in order. Show it as it is.
`previous_*` are `null` for the first message of an incident.

### An incident

```json
{
  "incident_id": "I0001",
  "status": "CONTAINED",
  "severity": "HIGH",
  "confidence": 0.95,
  "report_ids": ["E-8d863f2f", "S-1a2b3c4d"],
  "summary": "first 240 characters of the first message",
  "updated_at": "2026-10-01T09:00:05+00:00",
  "review_hold": null,
  "actions": [{"report_id": "E-8d863f2f", "action": {"type": "FLAG_SENDER", "service": "MAIL_FILTER", "details": {"target": "techcare-help.example"}}, "outcome": "EXECUTED", "detail": "techcare-help.example added to the sender blocklist; person warned"}],
  "labels": {"threat": "TECH_SUPPORT_SCAM", "merchant": "techcare support"}
}
```

`review_hold` is a sentence when a human is needed and `null` otherwise.
`actions` is the full action history, including attempts that failed and
actions that were deliberately not repeated.

### A review

```json
{"review_id": "REV-0001", "report_id": "S-1a2b3c4d", "incident_id": "I0001", "reason": "High impact action requires approval",
 "proposed_action": {"type": "DRAFT_DISPUTE", "service": "BANK", "details": {}}, "status": "PENDING", "created_at": "2026-10-02T06:00:01Z"}
```

## Fixed values

| Field | Values |
|---|---|
| `status` (incident) | `NEW`, `TRIAGED`, `INVESTIGATING`, `PENDING_REVIEW`, `CONTAINED`, `RESOLVED`, `CLOSED` |
| `severity` | `LOW`, `MEDIUM`, `HIGH`, `CRITICAL` |
| `relationship` | `NEW`, `RELATED`, `DUPLICATE` |
| `proposed_action.type` | `WARN_PERSON`, `FLAG_SENDER`, `DRAFT_DISPUTE`, `BLOCK_OPERATOR`, `WITHDRAW` |
| `action_outcome` | `NONE`, `PROPOSED`, `EXECUTED`, `FAILED`, `HELD_FOR_REVIEW`, `SUPPRESSED_DUPLICATE`, `SUPPRESSED_REPEAT` |
| `labels.threat` | `BENIGN`, `GREY_MARKET_SUBSCRIPTION`, `IDENTITY_FARMING`, `TECH_SUPPORT_SCAM`, `PRIZE_SCAM`, `UNKNOWN` |
| `status` (review) | `PENDING`, `APPROVED`, `REJECTED`, `APPROVED_ACTION_FAILED`, `SUPERSEDED` |

## Errors

| Code | Meaning |
|---|---|
| `404` | The incident, review or decision does not exist |
| `409` | Not allowed right now, for example a review already decided |
| `422` | The body does not match the schema; the response says which field |

## Live inbox

If `IMAP_HOST`, `IMAP_USER` and `IMAP_PASSWORD` are set in `.env`, the server
checks that mailbox every few seconds and takes in each unread email exactly
as `POST /intake/email` would. Nothing changes for the front end: the new
incident simply appears in `GET /incidents`. `GET /health` reports whether the
mailbox and the models are switched on.

## Demo controls

| Call | Use |
|---|---|
| `POST /reset` | Empty everything before a demo |
| `POST /replay/load` with `{"filename": "kinguard.jsonl", "content": "<file text>"}` | Queue a scenario file |
| `POST /replay/step` with `{"steps": 1}` | Process the next message in the queue |

`samples/kinguard.jsonl` is a ready scenario; the README lists what each
message in it demonstrates.

## A full walk-through to try

1. `POST /reset`
2. `POST /intake/email` with the text of `samples/lure.eml`. The sender is blocked and `GET /outbox` has one warning.
3. `POST /intake/share` with `YourBank: Debit order of R349.00 to TECHCARE ref TCS8841 from acc 1234567890 on 02 Oct.` It joins the same incident and a dispute waits in `GET /reviews?status=PENDING`.
4. `POST /reviews/REV-0001/decision` with `{"approved": true}`. The incident becomes `CONTAINED`.
5. `POST /intake/share` with `YourBank: Debit order of R349.00 to PC CARE SERVICES ref PCC0193 from acc 1234567890 on 02 Nov.` Same operator under a new name: it joins the incident and an operator block waits for approval.

## Things the front end should know

- With the models switched on, an intake call takes one to three seconds.
- The bank, company registry and sender blocklist are simulated. Nothing
  leaves the machine except the masked message text sent to the models and
  domain names sent to the public registration lookup.
- There is one protected person and no login. Do not expose this server
  beyond the demo machine.

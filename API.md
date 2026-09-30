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

For a WhatsApp message the person forwards or shares, use `POST /intake/share`
with `"channel": "whatsapp"`.

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

### Guardian or no guardian

`POST /settings/guardian` with `{"enrolled": false}` switches to solo mode,
for a person with nobody to ask. `GET /health` reports the current setting.

| | Guardian enrolled | No guardian |
|---|---|---|
| Who approves a dispute | The caregiver | The person themselves |
| `audience` on the review | `CAREGIVER` | `PERSON` |
| Person says "this is mine" on a high-risk incident | Held for the caregiver | Held for the person with a 24-hour cooling-off |

During a cooling-off the review has a `not_before` time, and approving before
it returns `409`. Show it as "you can confirm this after ...". Rejecting is
always allowed.

Every review that asks for approval carries a plain question in
`proposed_action.details.ask`, for example "R349.00 was taken by TechCare
Support, which we do not think you agreed to. Shall we prepare a dispute for
your bank?" Show that, not `reason`, to whoever is approving.

### Telling the caregiver

`GET /guardian/briefs` returns one entry per review waiting for the caregiver:

```json
[{"review_id": "REV-0001", "incident_id": "I0001",
  "text": "KinGuard: R349.00 was taken by TechCare Support, which we do not think you agreed to. Shall we prepare a dispute for your bank? Why we flagged it: Risk 0.45. ... Open KinGuard to approve or reject. A dispute must be lodged by 2026-12-01.",
  "whatsapp_link": "https://wa.me/27821234567?text=KinGuard%3A%20R349.00%20was%20taken..."}]
```

Show `text` in the app. Opening `whatsapp_link` on a phone opens WhatsApp with
the brief already typed, to the number in `GUARDIAN_WHATSAPP`, or with a
contact picker if that is not set. The backend does not send WhatsApp messages
itself.

### 3. The caregiver

| Call | Returns |
|---|---|
| `GET /reviews?status=PENDING&audience=CAREGIVER` | The queue waiting for the caregiver. Use `audience=PERSON` for the person's own queue |
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
A dispute's `details` also carry `dispute_by` (the last date to lodge it) and
`ask`.
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
 "proposed_action": {"type": "DRAFT_DISPUTE", "service": "BANK", "details": {"ask": "...", "dispute_by": "2026-12-01"}},
 "status": "PENDING", "audience": "CAREGIVER", "not_before": null, "created_at": "2026-10-02T06:00:01Z"}
```

## Fixed values

| Field | Values |
|---|---|
| `status` (incident) | `NEW`, `TRIAGED`, `INVESTIGATING`, `PENDING_REVIEW`, `CONTAINED`, `RESOLVED`, `CLOSED` |
| `severity` | `LOW`, `MEDIUM`, `HIGH`, `CRITICAL` |
| `relationship` | `NEW`, `RELATED`, `DUPLICATE` |
| `proposed_action.type` | `WARN_PERSON`, `ADVISE_DECLINE`, `FLAG_SENDER`, `DRAFT_DISPUTE`, `BLOCK_OPERATOR`, `WITHDRAW` |
| `action_outcome` | `NONE`, `PROPOSED`, `EXECUTED`, `FAILED`, `HELD_FOR_REVIEW`, `SUPPRESSED_DUPLICATE`, `SUPPRESSED_REPEAT` |
| `labels.threat` | `BENIGN`, `GREY_MARKET_SUBSCRIPTION`, `IDENTITY_FARMING`, `TECH_SUPPORT_SCAM`, `PRIZE_SCAM`, `IMPERSONATION`, `ADVANCE_FEE`, `UNKNOWN` |
| `status` (review) | `PENDING`, `APPROVED`, `REJECTED`, `APPROVED_ACTION_FAILED`, `SUPERSEDED` |

## Disputes

Once a dispute is approved it appears in `GET /state` under `world.disputes`,
keyed by the company's registration number:

```json
{"2026/118822/07": {"text": "I dispute the debit of R349.00 by TechCare Support ...",
                    "dispute_by": "2026-12-01",
                    "steps": ["Open your banking app, or visit a branch with your ID.", "..."]}}
```

The agent drafts the dispute. It does not lodge it; no bank lets a third party
do that. Show the text, the deadline and the steps so the person or caregiver
can lodge it.

## Mandate requests

A message such as "Mandate registered for R189.00 by TECHCARE SUPPORT" is a
company asking to set up a debit. If the agent cannot verify the company, the
decision's action is `ADVISE_DECLINE` and a message appears in `GET /outbox`
advising the person not to approve it. No approval is involved: the advice is
delivered at once.

## Errors

| Code | Meaning |
|---|---|
| `404` | The incident, review or decision does not exist |
| `409` | Not allowed right now: a review already decided, or still in its cooling-off period |
| `422` | The body does not match the schema; the response says which field |

## WhatsApp gateway (optional)

`POST /intake/whatsapp` accepts the form a WhatsApp gateway posts when a
message arrives (Twilio's format: `From` and `Body`). Pointing a gateway's
webhook at it makes forwarded WhatsApp messages arrive without anyone calling
the API. It needs a gateway account and a public address for this server, and
has only been tested with a simulated post.

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

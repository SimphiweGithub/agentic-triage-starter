# KinGuard API contract

For whoever builds the front end. The backend is the only thing that decides
anything; the front end sends messages in, shows what the agent did, and
collects two human answers: the person's "this is mine" and the caregiver's
approve or reject.

- Base address: `http://127.0.0.1:8000/api`
- Unless a table shows a full `/people/{id}/...` path, calls about an incident,
  review, intake or state use `/people/{id}` before the listed path. The caregiver
  gets `{id}` from `GET /me` (`people`); the protected person gets their own id
  from `GET /me` (`person`). Only development mode exposes unscoped calls.
- Interactive documentation with every schema: `http://127.0.0.1:8000/docs`
- API bodies are JSON. Every route except `GET /health` and `GET /invites/{token}`
  needs a signed-in Clerk session: `Authorization: Bearer <token>` (see
  [Signing in and roles](#signing-in-and-roles)).
- Incidents and reviews are in memory per person. Restarting the server, or that person's
  `POST /reset`, clears them. People, invites and mailbox status live in SQLite.

## Running it

Run this command from `backend/` after following its README setup steps.

```powershell
.\.venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000
```

Two ways to connect a front end:

1. **Same origin.** Put the built front end in `static/` and it is served from
   the same port. Nothing else to configure.
2. **Vite dev server.** The sibling `frontend/` app proxies `/api` to this
   backend, so no CORS setting is needed for local development.
3. **Separate deployment.** Set `CORS_ORIGINS` in `.env` to the front end's
   address and `VITE_API_URL` to the backend origin when building the front end.

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
| `GET /people/{id}/outbox` | `[{"incident_id": "I0001", "message": "..."}]`, oldest first; answered warnings are hidden |
| `POST /incidents/{incident_id}/feedback` with `{"legitimate": true}` | A decision |
| `GET /people/{id}/person/reviews?status=PENDING` | Reviews addressed to the person |
| `POST /people/{id}/reviews/{review_id}/decision` with `{"approved": true}` | The updated person review; approval respects `not_before` |

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

## Live inbox

If `IMAP_HOST`, `IMAP_USER` and `IMAP_PASSWORD` are set in `.env`, the server
checks that mailbox every few seconds and takes in each unread email exactly
as `POST /intake/email` would. Nothing changes for the front end: the new
incident simply appears in `GET /incidents`. `GET /health` reports whether the
mailbox and the models are switched on.

## Signing in and roles

The front end signs users in with Clerk and sends the session token on every
call. There are two roles, stored on the server and on the Clerk user's public
metadata (`role`):

| Role | Who | What they may call |
|---|---|---|
| `caregiver` | The person who looks after someone | Routes scoped to every person they look after, including caregiver reviews |
| `person` | The protected person, who connected their own Gmail | `GET /me`, `POST /me/disconnect`, their outbox and feedback, their pending reviews and decisions |
| none | Signed in but not linked to anyone yet | `GET /me`, `POST /people`, `POST /invites/{token}/accept` |

| Code | Meaning |
|---|---|
| `401` | No valid Clerk session |
| `403` | Signed in, but not allowed: not linked yet, or the wrong role |
| `404` | The person, invite or mailbox is not yours, or does not exist |
| `503` | `CLERK_SECRET_KEY` is not set on the server |

One caregiver may look after several people. Each person's incidents, reviews
and simulated world are separate in memory. Routes under `/people/{id}` check
that the caller is linked to that person.

## People, invites and mailboxes

The caregiver never reads the person's mail. The person connects their own
Gmail once, from a link; the server then scans it in the background and the
caregiver only ever sees alerts.

| Call | Who | Returns |
|---|---|---|
| `GET /me` | anyone signed in | `{user_id, role, person, people, can_add_person, mailbox}`. `people` lists a caregiver's people; `mailbox` is the person's own Gmail state |
| `POST /people` with `{"name": "...", "relation": "..."}` | caregiver or unlinked user | The same as `GET /me`. An unlinked caller becomes the caregiver |
| `GET /people/{id}/mailboxes` | caregiver | `[{id, kind, label, status, connected_at, last_checked, last_error, checked}]` |
| `POST /people/{id}/invites` | caregiver | `{token, created_at, expires_at}`. Single use, valid 7 days |
| `GET /people/{id}/invites` | caregiver | Invites still waiting |
| `POST /people/{id}/invites/{token}/cancel` | caregiver | `{status: "cancelled"}` |
| `GET /invites/{token}` | **nobody: no sign-in** | `{valid, problem, person_name}`. `person_name` is set only when the link works |
| `POST /invites/{token}/accept` | the person, signed in with Google | The same as `GET /me`. A person already linked to this same profile may reconnect. An account linked elsewhere gets `409` |
| `POST /me/disconnect` | the person | The same as `GET /me`. Stops scanning at once and asks Google to revoke the token |

**Mailbox `kind`** is `gmail` (the person's own, one per person) or `forwarded`
(the server's own IMAP mailbox, see Live inbox). **`status`**:

| Status | Meaning | What to show |
|---|---|---|
| `connected` | Being checked | "Last checked 2 minutes ago" |
| `problem` | The token was refused or revoked, or Gmail has been unreachable for over 15 minutes. `last_error` says why | A problem for the caregiver, with "send a new invite link" |
| `disconnected` | The person disconnected. Only a new invite reconnects it | A problem for the caregiver |

`checked` counts messages with a verdict. The server keeps nothing else about
mail judged safe. A flagged email keeps its text until its alert is resolved.

**Scanning.** The first scan looks back 14 days; after that the server checks
every minute (`SCAN_SECONDS`). A one-time code is withheld, as for every other
intake. A short outage is retried quietly and only becomes a `problem` after 15
minutes.

**Setting up Google.** The Clerk application needs Google sign-in with the scope
`https://www.googleapis.com/auth/gmail.readonly`, using your own Google OAuth
credentials, because Clerk's shared development credentials cannot add scopes.
That scope is restricted: until Google verifies the app, it runs in testing
mode, limited to 100 listed test users, and refresh tokens expire after about
seven days, so a connection needs re-signing weekly (it then shows as a
`problem`). Verification is a separate step before real users. `GET /health`
reports `"gmail": true` when the server has a Clerk key.

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
- Each protected person has a separate runtime. Sign-in is on by default. `KINGUARD_DEV_OPEN=1`
  turns it off for the plain console and local scripts; never set it on a server
  anyone else can reach.

# 1. Vocabulary and policy

These three files contain no logic. They define the words the system may use
and the rules it must follow. Everything else imports from them.

Read order for the whole walkthrough:

1. `01-vocabulary-and-policy.md` — this file
2. `02-reading-messages.md` — how a raw message becomes facts
3. `03-judging-messages.md` — the gate, the tools, the investigation, the decision
4. `04-engine.md` — linking messages, running actions, correcting, human review
5. `05-api-runner-harness.md` — the web API, the batch runner, the scoring harness

---

## `domain/enums.py`

An `Enum` is a fixed list of allowed values. Every class here inherits from
`str` as well, so a value such as `IncidentState.NEW` is also the text `"NEW"`
and can be written straight into JSON.

**Line 1** — the file's description.
**Line 2** — imports `Enum` from Python's standard library.

### `IncidentState` (lines 5–12)

The life of an incident. One incident is one scam campaign or one merchant
relationship for the protected person.

| Value | Meaning |
|---|---|
| `NEW` | Just created; nothing decided yet |
| `TRIAGED` | Looked at and judged benign; kept on record |
| `INVESTIGATING` | Suspicious; being watched |
| `PENDING_REVIEW` | Waiting for the caregiver |
| `CONTAINED` | A protective action has been taken |
| `RESOLVED` | Confirmed legitimate, or confirmed stopped |
| `CLOSED` | Finished; nothing may change it without a human |

### `SeverityLevel` (lines 15–19)

`LOW`, `MEDIUM`, `HIGH`, `CRITICAL`. The order of the lines matters: the
harness uses it to measure how far off a severity is.

### `ActionType` (lines 22–29)

What the agent can do.

| Value | What it does |
|---|---|
| `RECORD_ONLY` | Nothing; placeholder used by the generic tests |
| `WARN_PERSON` | Show the person a plain warning |
| `ADVISE_DECLINE` | Advise the person not to approve a new debit mandate |
| `FLAG_SENDER` | Block a sender in the mail filter and warn the person |
| `DRAFT_DISPUTE` | Write a dispute against a debit |
| `BLOCK_OPERATOR` | Ask the bank to refuse every mandate from an operator |
| `WITHDRAW` | Undo the agent's earlier actions and trust the merchant |

### `ServiceDomain` (lines 32–36)

Who carries out an action: `PERSON` (the person's own app), `MAIL_FILTER`,
`BANK`, or `UNSPECIFIED`.

### `Relationship` (lines 39–42)

How a new message relates to what is already known: `NEW` (starts an
incident), `RELATED` (more evidence about an existing one), `DUPLICATE` (the
same message again).

### `ActionOutcome` (lines 45–53)

What the engine did with a proposed action.

| Value | Meaning |
|---|---|
| `NONE` | No action was proposed |
| `PROPOSED` | Allowed, but no tool is registered to run it |
| `EXECUTED` | The tool ran and reported success |
| `FAILED` | The tool ran and reported failure |
| `HELD_FOR_REVIEW` | Stopped by the guardrails; waiting for a human |
| `SUPPRESSED_DUPLICATE` | Not run because the message was a duplicate |
| `SUPPRESSED_REPEAT` | Not run because the same action was already taken |

### `ThreatDomain` (lines 56–62)

The kind of threat: `BENIGN`, `GREY_MARKET_SUBSCRIPTION`, `IDENTITY_FARMING`,
`TECH_SUPPORT_SCAM`, `PRIZE_SCAM`, `UNKNOWN`.

---

## `domain/schemas.py`

These are the shapes of the data that moves through the system. Each class
inherits from pydantic's `BaseModel`, which checks types when an object is
created: a wrong type or a value outside an enum raises an error instead of
being stored.

**Lines 2–7** — imports. `Field` lets a field carry a rule or a default.
`Field(default_factory=dict)` means "a fresh empty dictionary for every
object"; without it, all objects would share one dictionary.

### `RawInputReport` (lines 10–15) — one incoming message

- `report_id` — unique ID. `Field(min_length=1)` rejects an empty ID.
- `timestamp` — kept as text, because real timestamps are often malformed.
- `source` — the channel: `"email"`, `"sms"`, `"person"`.
- `payload` — the message text, after account numbers are masked.
- `metadata` — everything else: sender, links, and the extracted `signals`.

### `ActionProposal` (lines 18–21) — something the agent wants to do

- `type` — an `ActionType`.
- `service` — a `ServiceDomain`; defaults to `UNSPECIFIED`.
- `details` — arguments for the tool, for example `{"target": "scam.example"}`.

### `ToolResult` (lines 24–27) — what a tool returns

- `ok` — did it work.
- `detail` — one sentence for the trace.
- `data` — structured facts, for example `{"age_days": 4}`.

### `ActionRecord` (lines 30–34) — one entry in an incident's action history

- `report_id` — the message that caused it.
- `action` — the `ActionProposal`.
- `outcome` — an `ActionOutcome`.
- `detail` — what the tool or the guardrail said.

### `Assessment` (lines 37–47) — the domain's judgement of one message

- `severity`, `confidence` — `Field(ge=0, le=1)` forces confidence between 0 and 1.
- `requested_state` — the state the domain asks for. The state machine decides
  whether it is granted.
- `proposed_action` — at most one action, or `None`.
- `rationale` — the reasoning in words.
- `review_reason` — set when the evidence itself needs a human, even if no
  action is proposed.
- `review_delay_seconds` — how long a human must wait before approving the
  review this assessment opens. 0 means no wait. Used for the cooling-off.
- `labels` — extra tags such as the threat type and merchant name.

### `IncidentRecord` (lines 50–61) — the evolving state of one incident

- `incident_id`, `status`, `severity`, `confidence` — current assessment.
- `report_ids` — every message linked to this incident, in order.
- `summary` — the first 240 characters of the first message.
- `updated_at` — when it last changed.
- `review_hold` — the reason a human is needed. It stays set until the risk is
  gone. This is the "sticky review".
- `actions` — the list of `ActionRecord`s: the action history.
- `labels` — accumulated tags from the assessments.

### `DecisionRecord` (lines 64–80) — the engine's output for one message

- `report_id`, `incident_id`, `relationship` — what the message was linked to.
- `status`, `severity`, `confidence` — the incident's state after this message.
- `proposed_action`, `action_outcome` — the final action attempted and its result.
- `suppressed_action` — an action that was deliberately not run.
- `requires_human_approval`, `review_id` — whether a human is needed and the
  review it belongs to.
- `previous_status`, `previous_severity`, `previous_confidence` — the values
  before this message, so the dashboard can show what changed.
- `labels` — a copy of the incident's labels at that moment.
- `trace` — the step-by-step reasoning, one sentence per step.

### `ReviewItem` (lines 83–92) — one item in the caregiver's queue

- `review_id`, `report_id`, `incident_id` — links.
- `reason` — why a human is needed.
- `proposed_action` — the action waiting for approval, if any.
- `status` — `PENDING`, `APPROVED`, `REJECTED`, `APPROVED_ACTION_FAILED` or `SUPERSEDED`.
- `audience` — who is being asked: `CAREGIVER`, or `PERSON` when no guardian
  is enrolled.
- `not_before` — a time before which approval is refused, or `None`. This is
  the cooling-off.
- `created_at` — filled in automatically with the current UTC time.

---

## `domain/policy.py`

Every number and list that controls behaviour is here. Changing behaviour
should mean changing this file, not the logic.

**Line 2** — imports the enums the rules refer to.

### `ALLOWED_TRANSITIONS` (lines 4–12)

A dictionary. Each key is the state an incident is in; each value is the set
of states it may move to. Anything not listed is illegal and is diverted to
`PENDING_REVIEW` by `core/fsm.py`.

- **Line 5** — a `NEW` incident may be judged benign (`TRIAGED`), suspicious
  (`INVESTIGATING`), contained straight away, or sent to review.
- **Line 6** — `TRIAGED` may become suspicious later, or be resolved.
- **Line 7** — `INVESTIGATING` may be downgraded, contained, or resolved.
- **Line 8** — `CONTAINED` may reopen (`INVESTIGATING`) or resolve.
- **Line 9** — from `PENDING_REVIEW`, once the human has decided, it may go
  anywhere except backwards to `NEW` or `TRIAGED`.
- **Line 10** — `RESOLVED` may reopen or close.
- **Line 11** — `CLOSED` maps to an empty set: nothing leaves it automatically.

### Action rules (lines 14–26)

- **Line 14** `MIN_AUTOMATION_CONFIDENCE = 0.75` — below this, no action runs
  without a human.
- **Line 16** `FORBIDDEN_ACTIONS` — empty. No action type moves money, so there
  is nothing to forbid yet. Anything added here can never run, even with
  approval.
- **Line 18** `HIGH_IMPACT_ACTIONS` — `DRAFT_DISPUTE` and `BLOCK_OPERATOR`. They
  affect the person's bank relationship, so the caregiver approves every one.
- **Line 20** `SAFE_ACTIONS` — the allowlist of actions that may run
  automatically. An action missing from this set is held, so forgetting to
  classify a new action makes the system safer, not riskier.
- **Lines 21–26** `ALLOWED_SERVICE_ACTIONS` — which service may do which action.
  A dispute sent to the mail filter would be rejected.

### Merge guard (line 31)

`DUPLICATE_WINDOW_SECONDS = 3600` — two identical messages are a duplicate only
if they arrive within an hour of each other. The same debit text next month is
a new debit.

### Sticky review (line 35)

`REVIEW_HOLD_SEVERITIES` — while an incident is `HIGH` or `CRITICAL`, a review
hold stays in place.

### Repeats (lines 38–40)

- **Line 38** `REPEATABLE_ACTIONS` — empty. An action already taken for an
  incident is not taken again.
- **Line 40** `ACTION_IDENTITY` — for `FLAG_SENDER`, the `target` is part of
  what the action is. Flagging a second address is a new action, not a repeat.

### Correction loop (lines 43–52)

- **Line 43** `MAX_CORRECTIONS = 2` — after a tool fails, the agent may try two
  corrected actions, then it must ask a human.
- **Lines 45–49** `STATE_AFTER_APPROVED` — the state an incident moves to when a
  human-approved action succeeds. A dispute or a block leaves it `CONTAINED`; a
  withdrawal leaves it `RESOLVED`.
- **Line 52** `SUPERSEDING_ACTIONS` — when a `WITHDRAW` runs, any review still
  waiting on that incident is closed, because there is nothing left to approve.

### Thresholds (lines 55–69)

- **Line 55** `GATE_THRESHOLD = 0.3` — below this risk, a message is benign.
- **Line 57** `MODEL_YES = 0.7` — the decision model's probability must reach
  this for its answer to count as a yes.
- **Line 59** `MODEL_THREAT_CONFIDENCE = 0.6` — the model's threat type is used
  only at or above this confidence.
- **Line 61** `CONTAIN_THRESHOLD = 0.6` — at or above this, the sender is
  blocked instead of only warning the person.
- **Line 63** `HIGH_AMOUNT = 300.0` — a suspicious debit of R300 or more is `HIGH`.
- **Line 65** `YOUNG_DAYS = 90` — a domain or company registered less than 90
  days before the message counts as newly created.
- **Line 67** `JUMP_RATIO = 2.0` — a debit at least twice the previous one from
  the same merchant is a price jump.
- **Line 69** `NAME_SIMILARITY = 0.6` — how alike a shortened merchant name
  must be to a registered name to count as the same company.

Which of these are measured:

- `GATE_THRESHOLD` was checked with `calibrate.py` on a held-out fifth of a
  public SMS dataset. At 0.30 the rules flagged 85 of 1,115 messages, 83 of
  them true spam. Lowering it to 0.15 caught 5 more and added 2 false alarms.
  We kept 0.30. See `03-judging-messages.md` for what that dataset can and
  cannot tell us.
- `MODEL_YES`, `MODEL_THREAT_CONFIDENCE`, `CONTAIN_THRESHOLD`, `HIGH_AMOUNT`,
  `YOUNG_DAYS`, `JUMP_RATIO` and `NAME_SIMILARITY` are still judgement calls.
  `NAME_SIMILARITY` was set from nine hand-made examples, where right matches
  scored 0.67 or more and wrong ones 0.56 or less. Say so if asked.

### Dispute window and cooling-off (lines 72–74)

- **Line 72** `DISPUTE_WINDOW_DAYS = 60` — an unauthorised debit order can be
  disputed with the bank for 60 days after it runs. This is the industry rule
  in South Africa from 13 April 2026 (it was 40 days before). Every dispute
  the agent drafts carries this deadline.
- **Line 74** `COOLING_OFF_SECONDS` — 24 hours. With no guardian enrolled, a
  person who confirms a high-risk sender as legitimate must wait this long
  before it takes effect. The length is a judgement call.

### Protected list (line 78)

`PROTECTED_DOMAINS` — shared mail providers. Blocking `gmail.com` would block
every legitimate Gmail sender, so the mail filter tool refuses it, and a flag
must name one address.

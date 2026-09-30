# 4. The engine

The files in `core/` know nothing about scams, banks or email. They take the
domain's proposal and decide what actually happens. Five files, in the order a
message passes through them:

1. `core/correlator.py` — which incident does this message belong to?
2. `core/fsm.py` — is the requested state change legal?
3. `core/guardrails.py` — may this action run without a human?
4. `core/executor.py` — run it, check it, correct it.
5. `core/runtime.py` — the conductor that calls the other four and records everything.

---

## `core/correlator.py`

Correlation happens in tiers, strongest evidence first.

### Helpers (lines 13–40)

**`_normalise` (13–14)** — lower-case, keep letters and digits, single spaces.

**`_score` (17–23)** — text similarity from 0 to 1.
- **18** — normalise both texts into `a` and `b`.
- **19–20** — an empty text scores 0.
- **21** — `token_a` and `token_b` are the sets of words.
- **22** — `jaccard` is shared words divided by all words.
- **23** — the score is 60% word overlap plus 40% character-sequence
  similarity (`SequenceMatcher`), so both vocabulary and word order count.

**`_context_conflict` (26–28)** — true when both messages have a known context
and the contexts differ. Unknown context is not a conflict.

**`_second_signal` (31–40)** — a reason, beyond matching text, to believe two
messages are the same occurrence.
- **33** — parse both timestamps.
- **34–36** — if both times are known, time decides: within
  `DUPLICATE_WINDOW_SECONDS` is a signal, outside is not. This is why the same
  debit text a month later is not a duplicate.
- **37–39** — if a time is missing, fall back to having the same context.
- **40** — otherwise there is no second signal.

### `Correlation` (lines 43–48)

The return type: the `incident_id` (or `None` for a new incident), the
`relationship`, the `score`, and a `reason` for the trace.

### `RelationResolver` (line 51)

The type of the optional model tier: a function that takes the new message,
the candidate incident and its history, and returns a `Relationship`.

### `Correlator` (lines 54–131)

**`__init__` (55–57)** — stores the optional `relation_resolver` and the
`candidate_threshold` (0.55): the minimum text score to consider a merge.

**`_linked` (59–71) — tiers one and two**
- **61–63** — tier one: the message names an incident outright (the person's
  feedback does this). `explicit in incidents` is false when it is `None`.
- **64** — `keys` are the message's identifiers from `domain.logic.link_keys`.
- **65–70** — tier two: walk the incidents from newest to oldest, and each
  incident's messages; if any identifier is shared, link to that incident and
  say which identifier.
- **71** — no link found.

**`match` (73–131)**
- **74** — `incoming` is the text used for fuzzy comparison.
- **75** — try tiers one and two.
- **76** — `notes` collects the reasons.
- **77–79** — linked: that incident is the answer, with score 1.0.
- **80–95** — tier three, fuzzy text, only when nothing was linked:
  - **81** — four trackers: the best allowed candidate and its score, and the
    best candidate that was blocked by a context conflict.
  - **82–85** — compare with every earlier message in every incident.
  - **86–88** — a context conflict disqualifies the pair, but remember it.
  - **89–90** — otherwise keep the highest score. `>=` means a tie goes to the
    later incident.
  - **91–95** — if nothing reached the threshold, this is a `NEW` incident.
    If a blocked candidate did reach it, the reason says so: the text matched
    but the context differed.
- **97–98** — `incident` is the chosen one; `history` is its messages.
- **99–108** — the optional model tier. It is skipped for linked messages,
  because a shared identifier is firmer than a model's opinion. If the model
  fails or returns something unexpected, `relation` goes back to `None` and
  the note says the deterministic fallback was used.
- **109** — `fuzzy` is true when no model decided.
- **110–115** — deterministic relation: `DUPLICATE` if the text is identical
  to an earlier message in the incident, otherwise `RELATED`.
- **116–117** — a model may say `NEW` and split the message off.
- **118–130** — **the merge guard** for duplicates:
  - **119–120** — look for a second signal against any earlier message.
    `found := ...` stores the result while testing it.
  - **121–122** — a signal exists: confirmed duplicate.
  - **123–127** — text is the only evidence, there is no shared context, and
    every timestamp is known and outside the window: a new occurrence, kept
    as a separate incident.
  - **128–130** — otherwise it is related evidence, not a duplicate, so its
    action is not suppressed.
- **131** — return the result.

Why this matters: a duplicate has its action suppressed. Calling something a
duplicate on wording alone is how a real scam gets ignored.

---

## `core/fsm.py`

Nine lines. `transition_state(current, target)`:

- **Line 7** — the request is granted if it asks for the same state, or if
  `target` is in `ALLOWED_TRANSITIONS[current]`. The `.get(current, set())`
  means an unknown state allows nothing.
- **Line 8** — granted: return `target`.
- **Line 9** — refused: return `PENDING_REVIEW`. It does not raise and does not
  keep the old state; it hands the incident to a human.

---

## `core/guardrails.py`

`enforce_action_safety(action, confidence)` returns a `SafetyDecision` with
`requires_review` and a `reason`. It returns at the first check that fails.

- **15–16** — no action: nothing to check.
- **17–18** — on the forbidden list: held, whatever the confidence.
- **19–20** — not valid for the chosen service: held.
- **21–22** — confidence below `MIN_AUTOMATION_CONFIDENCE`: held.
- **23–24** — high impact: held even when confident.
- **25–26** — not on the safe allowlist: held. This is default-deny.
- **27** — passed everything: allowed.

---

## `core/executor.py`

Where actions actually run. This is the act, check, correct loop.

### `run_tool` (lines 9–17)

- **11** — look the tool up in `ACTION_TOOLS` by action type.
- **12–13** — no tool registered: return `None`.
- **14–15** — call it.
- **16–17** — if the tool itself crashes, turn that into a failed
  `ToolResult`. One broken tool never stops the run.

### `execute_with_correction` (lines 20–39)

Arguments: the `action`, the assessment's `confidence`, the `incident` and the
`report`. Returns the list of `attempts`, one `ActionRecord` each.

- **22** — start with no attempts.
- **23** — loop at most `1 + MAX_CORRECTIONS` times: the first try plus two
  corrections. The loop is bounded so the agent can never retry forever.
- **24** — **every attempt goes through the guardrails first**, including
  corrected ones. A correction cannot sneak past policy.
- **25–27** — held: record `HELD_FOR_REVIEW` with the reason and stop.
- **28** — run the tool.
- **29–31** — no tool: record `PROPOSED` and stop.
- **32–33** — record `EXECUTED` or `FAILED` with what the tool said.
- **34–35** — success: stop.
- **36** — failure: ask the domain for a corrected action.
- **37–38** — no correction known: stop. The last record is `FAILED`, which
  the runtime turns into a request for a human.
- **39** — return all attempts, so the trace shows the failure and the fix.

### `execute_approved` (lines 42–50)

Runs an action a human approved.

- **44–45** — a forbidden action still cannot run. Approval replaces the
  confidence and impact checks, never the forbidden list.
- **46–48** — run the tool; no tool means `PROPOSED`.
- **49–50** — record `EXECUTED` or `FAILED`, noting that a human approved it.

---

## `core/runtime.py`

`TriageRuntime` holds all state in memory and processes one message at a time.

### Setup (lines 16–42)

- **16 `ENGAGED`** — the outcomes that count as "this action is already in
  hand": `PROPOSED`, `EXECUTED`, `HELD_FOR_REVIEW`. Used to stop repeats.
- **21** — `self.lock` is a re-entrant lock: only one message is processed at
  a time, so two web requests cannot corrupt the state.
- **22–23** — asking for a model tier without an API key is an error at
  start-up, not halfway through a run.
- **24–27** — build the correlator, with the model relation tier if enabled.
- **28** — `self.llm_assess` records whether model assessment is enabled.
- **29** — `self.now` returns the current time. It is an attribute so a test
  can replace it and move time forward.
- **30–42 `reset`** — empty everything:
  - `reports` — report ID to report.
  - `incidents` — incident ID to incident.
  - `decisions` — report ID to decision.
  - `reviews` — review ID to review item.
  - `queue` and `position` — the replay file and how far through it we are.
  - `_incident_ids`, `_review_ids` — counters for new IDs.
  - `reset_world()` — also empty the simulated world.

### Small helpers (lines 44–73)

- **44–48 `_new_incident`** — creates `I0001`, `I0002`, ... in state `NEW`,
  severity `LOW`, confidence 0, with the first 240 characters as the summary.
- **50–59 `_assess`** — calls the domain's `assess`. If model assessment is
  enabled and fails, it falls back to the rules and says so in the rationale.
- **61–62 `_pending`** — the reviews for an incident that are still `PENDING`.
- **64–73 `_open_review`** — if a pending review with the same reason already
  exists for the incident, return its ID. Otherwise create `REV-0001`, ....
  This keeps the queue free of repeats. Lines 70–72 add two things to a new
  review: `audience`, from the domain's `review_audience()`, and `not_before`,
  which is now plus the delay when a cooling-off was asked for.

### `process` (lines 75–156) — the main path

**Idempotency (77–80)** — the same report ID with the same content returns the
earlier decision. The same ID with different content is an error.

**Correlate and assess (81–85)**
- **81** — `match` is the correlator's answer.
- **82** — `incident` is a new one, or the matched one.
- **83** — `previous` remembers the incident's state, severity and confidence
  before this message (all `None` for a new incident).
- **84** — `assessment` is the domain's proposal.
- **85** — `trace` starts with the correlation line and the rationale.

**Suppression (87–96)**
- **88** — three variables: `action` (what will be attempted), `suppressed`
  (what was deliberately not attempted), `outcome`.
- **90–91** — a duplicate message never causes an action.
- **92–96** — an action of the same type and service that is already
  `ENGAGED` for this incident is not repeated. Line 94 adds one refinement:
  for action types listed in `ACTION_IDENTITY`, the named detail must match
  too. Flagging a second address is a different action from flagging the
  first, so it is not suppressed.

**State machine (98–100)**
- **98** — `next_state` is what the state machine grants.
- **99** — `illegal` is true when the machine returned `PENDING_REVIEW` though
  something else was asked for.
- **100** — the trace shows what was requested and what was granted.

**Act, check, correct (102–121)**
- **103** — `attempts` from the executor, or an empty list.
- **104** — `action_trigger` will hold a reason to involve a human.
- **106** — the final `action` and `outcome` are those of the last attempt.
- **107** — all attempts go into the incident's action history.
- **108** — one trace line per attempt, so a failure and its correction are
  both visible.
- **109–110** — held: the guardrail's reason becomes the trigger.
- **111–112** — failed with no correction left: that becomes the trigger.
- **113–116** — a superseding action (a withdrawal) ran: close the reviews
  still waiting on this incident.
- **117–119** — a suppressed action is recorded in the history with its
  suppression outcome.
- **120–121** — no action at all is also recorded in the trace.

**One trigger (122–124)** — `trigger` is the single reason a human is needed,
in priority order: illegal state change, a state that itself means review, an
action that was held or failed, or the assessment's own `review_reason`.

**Sticky review (126–141)**
- **128–131** — a trigger opens (or re-uses) a review, sets the incident's
  `review_hold`, and is traced.
- **132** — `pending` reviews for the incident.
- **133–138** — no new trigger but a hold exists: keep it while a review is
  pending or `risk_persists` is true; otherwise clear it.
- **139** — `requires_review` is true for a trigger, a pending review, or a hold.
- **140–141** — a trigger or a pending review forces the state to
  `PENDING_REVIEW`.

**Record (143–156)**
- **143–148** — update the incident: state, severity, confidence, labels, the
  new report ID, and the time.
- **149–153** — build the `DecisionRecord`.
- **154–156** — store the report and the decision, and return the decision.

### Failure handling (lines 158–184)

**`record_failure` (158–175)** — for a message that could not be parsed or
processed. It creates a new incident in `PENDING_REVIEW`, opens a review, and
returns a valid decision whose trace holds the error. If the ID was already
used, it adds a suffix (161–162).

**`process_safely` (177–184)** — the entry point for batches and live intake.
A parse error goes straight to `record_failure`; an exception during
`process` is caught and goes there too. Every message gets a decision.

### Replay (lines 186–196)

**`load_queue`** resets and stores a list of messages. **`step`** processes the
next `steps` messages and advances `position`.

### `decide_review` (lines 198–221) — the caregiver's decision

- **201–203** — a review can be decided once.
- **204–206** — rejected: mark it and stop. The action never runs.
- **207–208** — cooling-off: if the review has a `not_before` time and it has
  not arrived, approval is refused with an error. Rejecting is always allowed.
- **209** — approved.
- **210–213** — if the review carries an action, run it with
  `execute_approved` and add the result to the incident's history.
- **214–215** — add a line to the original decision's trace.
- **216–217** — the tool failed: the review is marked `APPROVED_ACTION_FAILED`.
- **218–220** — otherwise, if no other review is pending, move the incident to
  the state in `STATE_AFTER_APPROVED` for that action, through the state machine.

### `move_state` (lines 223–232)

A human moving an incident by hand. Refused while reviews are pending, and
refused if the state machine says the move is illegal.

### `snapshot` (lines 234–238)

Everything the dashboard needs, copied under the lock.

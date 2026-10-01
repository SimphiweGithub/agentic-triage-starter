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

## `core/store.py`

Keeps the engine's memory on disk, so a restart does not wipe every incident.

- **Line 16 `DEFAULT_FILE`** — `backend/data/state.json`. The `data` folder is
  ignored by git, so saved messages never reach GitHub.
- **`state_file` (19–25)** — the file a runtime uses. The shared runtime uses
  `KINGUARD_STATE_FILE` (default `DEFAULT_FILE`); each person's runtime uses
  `people/<person id>.json` in the same folder, so one person's messages never
  sit in another person's file. An empty `KINGUARD_STATE_FILE` turns saving
  off for everyone, which the tests do.
- **`save` (28–44)**:
  - **30–32** — the runtime's own `state_path`; do nothing if saving is off.
  - **33–40** — every report, incident, decision and review as plain JSON, the
    `report_number` counter, and the simulated world. `world_state` reads the
    *active* world, so `save` must run with the runtime's world active; the
    runtime's methods make sure of that.
  - **41–44** — write to a temporary file first, then swap it in. If the
    server stops mid-write, the old file is still whole.
- **`load` (47–59)** — read the file back into the runtime: each item is
  checked against its schema as it is loaded, the counter is restored (line
  57; older files without it fall back to the number of reports), and the
  world is restored. Returns `False` if there is nothing to load.

Saving the whole state after every change is simple and fine for hundreds of
messages per person. For many thousands it would need a database.

---

## `core/runtime.py`

`TriageRuntime` holds one person's state and processes one message at a time. The server keeps one runtime per person (`api/pool.py`), so nothing crosses from one person to another.

### Setup (lines 18–76)

- **18 `ENGAGED`** — the outcomes that count as "this action is already in
  hand": `PROPOSED`, `EXECUTED`, `HELD_FOR_REVIEW`. Used to stop repeats.
- **21–27 `in_own_world`** — a decorator. The wrapped method runs holding the
  lock, with this runtime's own world active (25), so the domain code's
  `WORLD` means this person's world. It is on every method that reads or
  changes the world: `reset` (50), `save` (55), `process` (118),
  `record_failure` (212), `process_safely` (233), `step` (248),
  `decide_review` (256) and `move_state` (285).
- **31** — the constructor takes an optional `world` and `person_id`.
- **32** — `self.lock` is a re-entrant lock: only one message is processed at
  a time for this person, so two web requests cannot corrupt the state. Other
  people have their own locks and are not held up.
- **33** — `self.world` is this runtime's own world. Given none, it is the
  shared default world, so offline runs and the older tests behave as before.
- **34** — `self.state_path`: where this runtime is saved (see `core/store.py`).
- **35–36** — asking for a model tier without an API key is an error at
  start-up, not halfway through a run.
- **37–40** — build the correlator, with the model relation tier if enabled.
- **41** — `self.llm_assess` records whether model assessment is enabled.
- **42** — `self.now` returns the current time. It is an attribute so a test
  can replace it and move time forward.
- **43–47** — with this runtime's own world active, start empty, then load the
  last saved state if there is one. Without line 43 the load would fill the
  shared world instead of this person's. The id counters then carry on after
  the highest saved number, so a new incident after a restart is `I0006`, not
  a second `I0001`.
- **49–52 `reset`** — empty everything and save the empty state.
- **54–57 `save`** — save the current state, for changes made from outside:
  a route changing the guardian setting, or the scanner forgetting safe mail.
- **59–70 `_clear`** — empty everything in memory without saving:
  - `reports` — report ID to report.
  - `incidents` — incident ID to incident.
  - `decisions` — report ID to decision.
  - `reviews` — review ID to review item.
  - `queue` and `position` — the replay file and how far through it we are.
  - `_incident_ids`, `_review_ids` — counters for new IDs.
  - `report_number` (line 69) — the last generated report number. It is a
    plain number rather than a counter so it can be saved.
  - `reset_world()` — also empty this person's simulated world.
- **72–76 `next_report_number`** — the next number. It is never reused, even
  after the scanner forgets a safe email or the server restarts, so a report
  ID built from it (the feedback route, the parse fallback) cannot collide
  with one that is still stored.

Every method that changes state ends with `store.save(self)`: after each
message, each failure, each review decision and each manual state change.

### Small helpers (lines 78–115)

- **78–82 `_new_incident`** — creates `I0001`, `I0002`, ... in state `NEW`,
  severity `LOW`, confidence 0, with the first 240 characters as the summary.
- **84–93 `_assess`** — calls the domain's `assess`. If model assessment is
  enabled and fails, it falls back to the rules and says so in the rationale.
- **95–101 `_already_taken`** — true when the same action type and service is
  already `ENGAGED` for this incident and, for types in `ACTION_IDENTITY`, the
  named detail matches too. `REPEATABLE_ACTIONS` are never "already taken".
  Used for both the main action and the follow-up.
- **103–104 `_pending`** — the reviews for an incident that are still `PENDING`.
- **106–115 `_open_review`** — if a pending review with the same reason already
  exists for the incident, return its ID. Otherwise create `REV-0001`, ....
  This keeps the queue free of repeats. Lines 112–114 add two things to a new
  review: `audience`, from the domain's `review_audience()`, and `not_before`,
  which is now plus the delay when a cooling-off was asked for.

### `process` (lines 118–209) — the main path

**Idempotency (120–123)** — the same report ID with the same content returns the
earlier decision. The same ID with different content is an error.

**Correlate and assess (124–128)**
- **124** — `match` is the correlator's answer.
- **125** — `incident` is a new one, or the matched one.
- **126** — `previous` remembers the incident's state, severity and confidence
  before this message (all `None` for a new incident).
- **127** — `assessment` is the domain's proposal.
- **128** — `trace` starts with the correlation line and the rationale.

**Suppression (130–136)**
- **131** — three variables: `action` (what will be attempted), `suppressed`
  (what was deliberately not attempted), `outcome`.
- **133–134** — a duplicate message never causes an action.
- **135–136** — an action already taken for this incident (`_already_taken`)
  is not repeated. Flagging a second address is a different action from
  flagging the first, so it is not suppressed.

**State machine (138–140)**
- **138** — `next_state` is what the state machine grants.
- **139** — `illegal` is true when the machine returned `PENDING_REVIEW` though
  something else was asked for.
- **140** — the trace shows what was requested and what was granted.

**Act, check, correct (142–161)**
- **143** — `attempts` from the executor, or an empty list.
- **144** — `action_trigger` will hold a reason to involve a human;
  `review_action` is set only when the follow-up, not the main action, is
  what the human must decide.
- **146** — the final `action` and `outcome` are those of the last attempt.
- **147** — all attempts go into the incident's action history.
- **148** — one trace line per attempt, so a failure and its correction are
  both visible.
- **149–150** — held: the guardrail's reason becomes the trigger.
- **151–152** — failed with no correction left: that becomes the trigger.
- **153–156** — a superseding action (a withdrawal) ran: close the reviews
  still waiting on this incident.
- **157–159** — a suppressed action is recorded in the history with its
  suppression outcome.
- **160–161** — no action at all is also recorded in the trace.

**Follow-up (163–172)** — the assessment may carry a second action, such as the
Bin filter after a sender is flagged.
- **165** — it is tried only when the main action ran (`EXECUTED`) and the
  same follow-up was not already taken for this incident.
- **166–168** — it goes through the executor, so the same guardrails gate it.
  Each attempt joins the history and the trace as a `Follow-up:` line.
- **169–172** — held or failed: that becomes the trigger, and the review
  carries the follow-up action, so approving it runs the follow-up. The
  decision itself still shows the main action.

**One trigger (173–175)** — `trigger` is the single reason a human is needed,
in priority order: illegal state change, a state that itself means review, an
action that was held or failed, or the assessment's own `review_reason`.

**Sticky review (177–193)**
- **179–183** — a trigger opens (or re-uses) a review, sets the incident's
  `review_hold`, and is traced. The review carries the follow-up when the
  follow-up set the trigger (180), and the main action otherwise.
- **184** — `pending` reviews for the incident.
- **185–190** — no new trigger but a hold exists: keep it while a review is
  pending or `risk_persists` is true; otherwise clear it.
- **191** — `requires_review` is true for a trigger, a pending review, or a hold.
- **192–193** — a trigger or a pending review forces the state to
  `PENDING_REVIEW`.

**Record (195–209)**
- **195–200** — update the incident: state, severity, confidence, labels, the
  new report ID, and the time.
- **201–205** — build the `DecisionRecord`.
- **206–209** — store the report and the decision, and return the decision.

### Failure handling (lines 212–240)

**`record_failure` (212–230)** — for a message that could not be parsed or
processed. It creates a new incident in `PENDING_REVIEW`, opens a review, and
returns a valid decision whose trace holds the error. If the ID was already
used, it adds a suffix (215–216).

**`process_safely` (233–240)** — the entry point for batches and live intake.
A parse error goes straight to `record_failure`; an exception during
`process` is caught and goes there too. Every message gets a decision.

### Replay (lines 242–253)

**`load_queue`** resets and stores a list of messages. **`step`** processes the
next `steps` messages and advances `position`.

### `decide_review` (lines 256–282) — the caregiver's decision

- **259–261** — a review can be decided once.
- **262–266** — rejected: mark it, tell the domain through `learn_from_review`
  (line 264) so the same doubt is not raised again, save, and stop. The action
  never runs.
- **267–268** — cooling-off: if the review has a `not_before` time and it has
  not arrived, approval is refused with an error. Rejecting is always allowed.
- **269** — approved.
- **270–273** — if the review carries an action, run it with
  `execute_approved` and add the result to the incident's history.
- **274–275** — add a line to the original decision's trace.
- **276–277** — the tool failed: the review is marked `APPROVED_ACTION_FAILED`.
- **278–280** — otherwise, if no other review is pending, move the incident to
  the state in `STATE_AFTER_APPROVED` for that action, through the state machine.

### `move_state` (lines 285–295)

A human moving an incident by hand. Refused while reviews are pending, and
refused if the state machine says the move is illegal.

### `snapshot` (lines 297–301)

Everything the dashboard needs, copied under the lock.

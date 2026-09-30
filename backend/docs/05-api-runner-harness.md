# 5. API, runner, harness, and the model client

The ways into the engine, the way to score it, and the optional model code.

---

## `main.py`

- **Lines 1–9** — imports, including the router from `api/routes.py`.
- **Line 12** — `ROOT` is the folder this file is in.
- **Lines 13–14** — `app` is the web application, with a title and description
  that appear in the generated documentation at `/docs`.
- **Lines 18–20** — cross-origin access. `CORS_ORIGINS` is read from the
  environment and split on commas into `origins`. If the list is empty, which
  is the default, no cross-origin middleware is added and a page served from
  anywhere else cannot call the API. If addresses are listed, only those may
  call it, only with GET and POST, and only with a JSON content type.
- **Line 22** — every route in the router is served under `/api`.
- **Line 23** — start the live mailbox thread. It does nothing unless
  `IMAP_HOST` is set.
- **Line 24** — the `static` folder is served under `/static`.
- **Lines 27–30** — the address `/` returns a plain developer console for
  watching the engine. The product front end is built separately.

---

## `api/routes.py`

The contract for the front end is in `API.md`. This section explains the code.

**Line 17** — `router` collects the endpoints.
**Line 18** — `runtime` is the single `TriageRuntime` for the whole server. All
state lives in it, in memory; restarting the server clears it.

### Request and response shapes (lines 21–59)

Each class describes a JSON body. FastAPI rejects a request that does not
fit, with error 422, before any of our code runs.

- `ReviewDecision` — `approved`: true or false.
- `StateRequest` — `target`: an `IncidentState`.
- `ReplayFile` — `filename` and `content` of a CSV or JSONL file.
- `StepRequest` — `steps`: how many messages to process; at least 1.
- `EmailUpload` — `content`: raw `.eml` text.
- `SharedMessage` — `text` (at least one character), `sender`, `channel`.
- `Feedback` — `legitimate`: true or false.
- `Withheld` — the reply when a message is discarded: `status` and `reason`.
- `PersonMessage` — one warning for the person: `incident_id` and `message`.

### Helpers (lines 62–72)

- **62–63 `_now`** — the current UTC time as text.
- **75–77 `take_in_email`** — one raw email in, one decision out. The API
  route and the live mailbox both call it, so they cannot behave differently.
- **66–72 `_take_in`** — the shared path for live intake:
  - **68–70** — ask the domain whether the row must be withheld. If so, return
    a `Withheld` reply and store nothing.
  - **71** — parse it safely.
  - **72** — process it safely. A decision always comes back.

### Endpoints

Each `@router` line names the method, the path, a `tags` group used to
organise `/docs`, and a `response_model`. The response model does two things:
it documents the reply, and it strips anything not in the model before the
reply is sent.

| Lines | Method and path | Group | What it does |
|---|---|---|---|
| 82–85 | `POST /intake/email` | intake | Convert raw email text to a row and take it in |
| 88–91 | `POST /intake/share` | intake | Convert a hand-shared message to a row and take it in |
| 94–100 | `POST /reports` | intake | Process a ready-made report. A reused ID with different content returns 409 |
| 105–108 | `GET /outbox` | person | The warnings written for the person |
| 111–119 | `POST /incidents/{id}/feedback` | person | The person's own answer about an incident |
| 124–127 | `GET /incidents` | caregiver | Every incident |
| 130–140 | `GET /incidents/{id}` | caregiver | One incident with its reports, decisions and reviews |
| 143–148 | `GET /decisions/{report_id}` | caregiver | One decision and its trace; 404 if unknown |
| 151–154 | `GET /reviews` | caregiver | The review queue, optionally filtered by `status` |
| 157–165 | `POST /reviews/{id}/decision` | caregiver | Approve or reject |
| 168–176 | `POST /incidents/{id}/state` | caregiver | A human moves an incident's state |
| 181–183 | `GET /health` | system | Confirms the server is up and reports which optional parts are on: mailbox, Jev, Gemini, live lookups |
| 188–192 | `GET /state` | system | Everything in one call, plus the simulated world |
| 195–199 | `POST /reset` | system | Empty everything |
| 202–209 | `POST /replay` | system | Reset, then process a list of reports |
| 212–220 | `POST /replay/load` | system | Queue a file for step-through replay |
| 223–227 | `POST /replay/step` | system | Process the next messages in the queue |

**`feedback` in detail (111–119)**
- **114–115** — unknown incident: error 404.
- **116** — a sentence describing the answer.
- **117–118** — the answer is wrapped as a `RawInputReport` with `source`
  `"person"`. Its metadata names the incident (so the correlator links it
  explicitly) and carries the `feedback` value.
- **119** — it is processed like any other message. The person's answer is
  evidence that goes through the same policy; it is not a command.

**`reviews` in detail (151–154)** — `status` is an optional query parameter.
With `?status=PENDING` only reviews in that state are returned; with nothing,
all of them.

**`replay_load` in detail (212–220)**
- **216** — strip an invisible marker from the start of the text, read the
  rows, and drop the withheld ones.
- **217–218** — an unsupported file type returns error 400.
- **219** — parse every row safely and hand the list to the runtime's queue.

**Error handling in `decide` and `move_state`** — a `KeyError` (unknown ID)
becomes 404; a `ValueError` (not allowed right now) becomes 409.

What the API does not have: authentication, and more than one protected
person. Both are stated limits.

---

## `api/mailbox.py`

The optional live inbox. It reads a mailbox created for KinGuard, which the
protected person's own mailbox forwards to. The agent never holds the
password to their real account.

### `connect_from_env` (lines 13–16)

Opens an encrypted IMAP connection to `IMAP_HOST` and logs in with
`IMAP_USER` and `IMAP_PASSWORD`, all read from the environment.

### `poll_once` (lines 19–31)

Arguments: `connect`, a function that returns a connection, and `handle`, a
function given each email's raw text. Passing the connection in as a function
is what lets the test use a fake mailbox.

- **21** — connect.
- **23** — open the inbox.
- **24** — ask for the emails not yet read (`UNSEEN`).
- **25** — `numbers` are their sequence numbers.
- **26–28** — for each one, fetch the full email and pass its text to
  `handle`. Fetching also marks it as read, so it is taken in once.
- **29** — return how many were read.
- **30–31** — always log out, even if something failed.

### `start_polling` (lines 34–50)

- **36–37** — if `IMAP_HOST` is not set, do nothing and return `None`.
- **38** — how often to check, 15 seconds unless `IMAP_POLL_SECONDS` says otherwise.
- **40–46 `loop`** — forever: check the mailbox, and if that fails for any
  reason, print the error and carry on. A mailbox problem never stops the server.
- **48–50** — run `loop` on a background thread. `daemon=True` means it stops
  when the server stops.

Not yet run against a real mailbox; the test uses a stand-in.

---

## `runner.py`

Runs a whole file from the command line.

### `run` (lines 9–19)

- **11** — a fresh runtime.
- **12** — `count` of decisions written.
- **13** — open the output file. `newline="\n"` keeps line endings the same on
  every operating system.
- **14** — read the rows, drop withheld ones, and number them from 1.
  The order of the file is never changed.
- **15** — parse safely: `report` and an optional `error`.
- **16** — process safely: always a `decision`.
- **17** — write it as one line of JSON.
- **18–19** — count it and return the total.

### `main` (lines 22–27)

Reads the input path and the optional `--output` path, calls `run`, prints
how many decisions were written.

---

## `evaluation.py`

Scores a decisions file. Without `--truth` it only checks mechanics. With
`--truth` it compares against labelled answers.

### Constants (lines 25–27)

- **`TRUTH_TO_DECISION`** — maps a field name in the truth file to the field
  name in a decision, for example `human_review` to `requires_human_approval`.
- **`SEVERITY_ORDER`** — `["LOW", "MEDIUM", "HIGH", "CRITICAL"]`.

### Small helpers

- **`load_jsonl` (30–32)** — reads a JSONL file into a list of dictionaries.
- **`_percent` (35–36)** — a percentage rounded to two decimals; 100 when
  there is nothing to measure.
- **`_pairs` (39–40)** — given group sizes, the number of pairs inside the
  groups. A group of `n` has `n × (n − 1) / 2` pairs.
- **`_action_key` (55–56)** — reduces an action to `(type, service)` for
  comparison.

### `clustering` (lines 43–52)

Measures whether messages were grouped into the right incidents, without
needing our incident IDs to match the truth's event IDs.

- **45** — `ids` are the reports present in both truth and predictions.
- **46** — `tp` (true positives): pairs of reports that are together in the
  truth **and** together in our output.
- **47** — `fp` (false positives): pairs we put together that should be apart.
  These are wrong merges.
- **48** — `fn` (false negatives): pairs that should be together that we split.
- **49** — `precision = tp / (tp + fp)`: of the pairs we merged, how many were right.
- **50** — `recall = tp / (tp + fn)`: of the pairs that belong together, how
  many we found.
- **51** — `f1` combines the two.

### `evaluate` (lines 59–125)

**Mechanical checks (60–81)**
- **60** — drop input rows that are meant to be withheld.
- **61–62** — the report IDs of the inputs and of the decisions.
- **64** — `covered`: positions where the IDs match, counting a row with no ID
  as covered by its `ROW-` decision.
- **65** — `valid_states`: decisions whose status is a real state.
- **66–67** — of the decisions labelled duplicate, how many proposed no action.
- **68–71** — of the decisions proposing a forbidden action, how many required
  a human.
- **72–79** — the `result` dictionary.
- **80–81** — with no truth file, stop here.

**Comparison with truth (83–111)**
- **83** — `by_id`: decisions by report ID.
- **84** — `issues`: report ID to a list of what was wrong.
- **85** — `hits` and `totals`: counters per checked field.
- **87–91 `check`** — counts one comparison and records a message when wrong.
- **93–98** — for each truth row, find our decision; a missing one is an issue.
- **99–102** — for each field that the truth row contains, compare. Fields the
  truth row omits are not scored.
- **103–106** — severity within one level, as partial credit.
- **107–111** — actions: `actions` lists the acceptable ones. An empty list
  means no action was expected. Our action is reduced to `(type, service)`.

**Summary (113–125)**
- **113–117** — if the truth has `event_id`s, add the clustering scores and
  the number of true events against the number of incidents we created.
- **118–120** — `review_recall_percent`: of the reports that needed a human,
  how many we flagged. Missing one of these is the costly mistake.
- **121–122** — an accuracy percentage for every checked field.
- **123** — `issue_counts`: how many issues of each kind.
- **124** — `report_issues`: the per-report list.

### `main` (lines 128–139)

Reads the arguments, loads the files, runs `evaluate`, and prints the result.
The per-report list is printed only with `--issues`.

### A caution about the sample truth file

`samples/kinguard_truth.jsonl` was written by the same people who wrote the
rules, so a perfect score on it proves the code does what we intended. It does
not prove the rules are right. Labels written independently, from real
messages, are what would show that.

---

## `calibrate.py`

Measures the gate against labelled messages, so the threshold is chosen from
data.

- **Line 17 `SCAM_LABELS`** — labels that mean "scam": `scam` and `spam`.
- **`load_labelled` (20–32)** — reads either JSONL rows with a `label` field,
  or tab-separated `label<TAB>text` lines. Returns a list of
  `(text, metadata, is_scam)`.
- **`sweep` (35–49)**:
  - first, every message is masked, its signals extracted, and the gate run
    once. `scored` is a list of `(score, is_scam)`.
  - then, for each threshold from 0.05 to 0.95:
    - `tp` — scams at or above the threshold: **caught**.
    - `fp` — harmless messages at or above it: **false alarms**.
    - `fn` — scams below it: **missed**.
    - `precision`, `recall` and `f1` as in the harness.
- **`split` (52–58)** — every fifth message (`index % 5 == 0`) is the
  **holdout**; the rest are **dev**. Rules are written looking only at dev and
  judged on holdout, so the score is not flattered by rules fitted to the
  same messages.
- **`main` (61–74)** — reads `--part` (`all`, `dev` or `holdout`), prints the
  table and the threshold with the best F1. It uses Jev as well when
  `ENABLE_JEV=1`, so the two set-ups can be compared.

A missed scam and a false alarm do not cost the same. Read the table for the
lowest threshold whose false alarms the caregiver can live with, not only for
the best F1.

---

## The optional model code

None of this runs unless it is switched on with environment variables, and
none of it has been run against the real APIs yet.

### `core/jev.py`

The client for Jev, TypeSafe's decision model. One function, standard library only.

- **Line 7 `API_URL`** — the endpoint from Jev's documentation.
- **`system_one` (10–19)**:
  - **12–14** — read `TYPESAFE_API_KEY` from the environment; refuse to run
    without it. The key is never written in code.
  - **15** — the request body: the `state` (the content to judge), the `model`
    (`jev-latest` unless `TYPESAFE_MODEL` says otherwise), and the `questions`.
  - **16–17** — a POST request with the key in the `Authorization` header.
  - **18–19** — send it with a 10-second timeout and return the `answers`
    part of the reply, keyed by our question ids.

It raises on any failure. The gate catches that and carries on with rules.
Enabled with `ENABLE_JEV=1`.

### Where each model is used

| Model | Job | File | Switch |
|---|---|---|---|
| Jev | Seven yes/no questions and the threat type, in the gate | `domain/gate.py`, `core/jev.py` | `ENABLE_JEV=1` |
| Gemini | Reword the warning shown to the person | `domain/language.py`, `core/client.py` | `ENABLE_GEMINI=1` |

`domain/relation.py` and `domain/assessor.py` are older, generic hooks that
let Gemini judge relation and assessment. KinGuard does not switch them on.

### `core/client.py`

- **11** — `@retry(...)`: try up to three times, waiting longer each time.
- **12–24 `_generate`** — creates a Gemini client, asks for a response that
  must be JSON matching a given `schema`, at temperature 0.1, and always
  closes the client.
- **27–34 `call_agent_structured`** — refuses to run without an API key,
  calls `_generate`, fails if nothing parseable came back, and validates the
  answer against the schema before returning it.

The important property: the model cannot return free text. It returns an
object whose fields are limited to our enums, or the call fails.

### `domain/relation.py`

- **12–15 `RelationVerdict`** — the shape the model must return: a
  `Relationship`, a confidence, and the evidence.
- **18–24 `resolve_relation`** — builds a prompt from `prompts/relation.md`,
  the new report and the candidate incident, calls the model, and returns its
  label only if its confidence is at least 0.75; otherwise `NEW`.

Enabled with `ENABLE_LLM_RELATION=1`. Used only when no identifier linked the
message.

### `domain/assessor.py`

- **12–19 `AssessmentVerdict`** — the shape the model must return: severity,
  confidence, requested state, optional action type and service, optional
  review reason, and a rationale.
- **22–32 `llm_assess`** — builds a prompt from `prompts/assess.md`, the report
  and the incident so far, calls the model, and converts the verdict into an
  `Assessment`.

Enabled with `ENABLE_LLM_ASSESS=1`. Its output goes through exactly the same
state machine, guardrails and executor as the rule-based assessment. This file
still carries the generic prompt and has not been adapted to KinGuard.

---

## `core/__init__.py` — the `.env` loader

Runs once, the first time anything in `core/` is imported, which every entry
point does.

- **Line 5 `ENV_FILE`** — the path `backend/.env`.
- **`load_env_file` (8–15)**:
  - **10–11** — do nothing if `KINGUARD_SKIP_ENV_FILE=1` (the tests set this,
    so they never use real keys) or if the file does not exist.
  - **12** — read the file line by line.
  - **13** — split each line at the first `=` into `name` and `value`.
  - **14–15** — skip blank lines and comments. `os.environ.setdefault` sets
    the variable only if it is not already set, so a value typed in the
    terminal wins over the file. Surrounding quotes are removed.
- **Line 18** — call it.

The keys live only in `.env`, which git ignores. `.env.example` lists the
names with no values.

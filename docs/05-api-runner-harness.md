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

**Line 21** — `router` collects the endpoints.
**Line 22** — `runtime` is the single `TriageRuntime` for the whole server. All
state lives in it, in memory; restarting the server clears it.

### Request and response shapes (lines 25–67)

Each class describes a JSON body. FastAPI rejects a request that does not
fit, with error 422, before any of our code runs.

- `ReviewDecision` — `approved`: true or false.
- `StateRequest` — `target`: an `IncidentState`.
- `ReplayFile` — `filename` and `content` of a CSV or JSONL file.
- `StepRequest` — `steps`: how many messages to process; at least 1.
- `EmailUpload` — `content`: raw `.eml` text.
- `SharedMessage` — `text` (at least one character), `sender`, `channel`.
- `Feedback` — `legitimate`: true or false.
- `GuardianSetting` — `enrolled`: true or false.
- `Withheld` — the reply when a message is discarded: `status` and `reason`.
- `PersonMessage` — one warning for the person: `incident_id` and `message`.

### Helpers (lines 70–80)

- **70–71 `_now`** — the current UTC time as text.
- **83–85 `take_in_email`** — one raw email in, one decision out. The API
  route and the live mailbox both call it, so they cannot behave differently.
- **74–80 `_take_in`** — the shared path for live intake:
  - **76–78** — ask the domain whether the row must be withheld. If so, return
    a `Withheld` reply and store nothing.
  - **79** — parse it safely.
  - **80** — process it safely. A decision always comes back.

### Endpoints

Each `@router` line names the method, the path, a `tags` group used to
organise `/docs`, and a `response_model`. The response model does two things:
it documents the reply, and it strips anything not in the model before the
reply is sent.

| Lines | Method and path | Group | What it does |
|---|---|---|---|
| 90–93 | `POST /intake/email` | intake | Convert raw email text to a row and take it in |
| 96–99 | `POST /intake/share` | intake | Convert a hand-shared message to a row and take it in |
| 102–109 | `POST /intake/whatsapp` | intake | Webhook for a WhatsApp gateway; takes the message in like a shared SMS |
| 112–118 | `POST /reports` | intake | Process a ready-made report. A reused ID with different content returns 409 |
| 123–126 | `GET /outbox` | person | The warnings written for the person |
| 129–137 | `POST /incidents/{id}/feedback` | person | The person's own answer about an incident |
| 142–145 | `GET /incidents` | caregiver | Every incident |
| 148–158 | `GET /incidents/{id}` | caregiver | One incident with its reports, decisions and reviews |
| 161–166 | `GET /decisions/{report_id}` | caregiver | One decision and its trace; 404 if unknown |
| 169–172 | `GET /reviews` | caregiver | The review queue, optionally filtered by `status` |
| 176–180 | `GET /guardian/briefs` | caregiver | Each pending caregiver review as a plain message with a WhatsApp link |
| 183–191 | `POST /reviews/{id}/decision` | caregiver | Approve or reject |
| 194–202 | `POST /incidents/{id}/state` | caregiver | A human moves an incident's state |
| 207–209 | `GET /health` | system | Confirms the server is up and reports which optional parts are on: mailbox, Jev, Gemini, live lookups |
| 214–218 | `GET /state` | system | Everything in one call, plus the simulated world |
| 222–226 | `POST /settings/guardian` | system | Say whether a caregiver is enrolled |
| 229–233 | `POST /reset` | system | Empty everything |
| 236–243 | `POST /replay` | system | Reset, then process a list of reports |
| 246–254 | `POST /replay/load` | system | Queue a file for step-through replay |
| 257–261 | `POST /replay/step` | system | Process the next messages in the queue |

**`feedback` in detail (129–137)**
- **132–133** — unknown incident: error 404.
- **134** — a sentence describing the answer.
- **135–136** — the answer is wrapped as a `RawInputReport` with `source`
  `"person"`. Its metadata names the incident (so the correlator links it
  explicitly) and carries the `feedback` value.
- **137** — it is processed like any other message. The person's answer is
  evidence that goes through the same policy; it is not a command.

**`intake_whatsapp` in detail (102–109)**
- **103** — `async`, because reading the raw request body has to be awaited.
- **105** — a WhatsApp gateway (this follows Twilio's format) posts a form,
  not JSON. `parse_qs` turns `From=...&Body=...` into a dictionary. Reading
  the body ourselves avoids adding a form-parsing package.
- **106** — `text` is the message; `sender` is the number, with the
  `whatsapp:` prefix removed.
- **107–108** — an empty message is ignored; otherwise it goes through the
  same `_take_in` path as a shared SMS, with the channel set to `whatsapp`.
- **109** — reply with an empty response. A gateway would send any text in the
  reply back to the sender, and the agent must never answer a scammer.

Anyone who can reach the server can post to this route. A real deployment
would check the gateway's signature on each request; that is not built.

**`guardian_briefs` in detail (176–180)** — for every review that is
`PENDING` and addressed to the `CAREGIVER`, build a brief from the review and
the decision that opened it.

**`reviews` in detail (169–173)** — `status` and `audience` are optional query
parameters. `?status=PENDING&audience=PERSON` returns what is waiting for the
person themselves; with nothing, every review is returned.

**`replay_load` in detail (246–254)**
- **250** — strip an invisible marker from the start of the text, read the
  rows, and drop the withheld ones.
- **251–252** — an unsupported file type returns error 400.
- **253** — parse every row safely and hand the list to the runtime's queue.

**Error handling in `decide` and `move_state`** — a `KeyError` (unknown ID)
becomes 404; a `ValueError` (not allowed right now) becomes 409.

What the API does not have: authentication, and more than one protected
person. Both are stated limits.

---

## `domain/briefs.py`

Turns a pending review into a message a caregiver can read on their phone.

### `guardian_brief` (lines 8–18)

- **10** — `details` of the proposed action, or an empty dictionary.
- **11** — `question`: the plain question written for the approver, falling
  back to the technical reason.
- **12** — `why`: the second line of the decision's trace, which is the
  rationale with the evidence.
- **13** — `text`: the brief itself.
- **14–15** — if there is a dispute deadline, add it.
- **16** — `number`: `GUARDIAN_WHATSAPP` from the environment, reduced to its
  digits.
- **17–18** — return the text and a `wa.me` link. Opening that link on a
  phone opens WhatsApp with the caregiver's chat selected and the brief
  already typed. `quote` makes the text safe to put in a link.

The backend does not send the WhatsApp message. Sending automatically needs
a WhatsApp Business account and an approved message template. The link needs
nothing, and whoever taps it sees exactly what is being sent.

One thing to say plainly: the brief contains the merchant and the amount, and
it travels through WhatsApp once sent. That is the family's choice to make.

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

- **Lines 17–18** — `SCAM_LABELS` (`scam`, `spam`) and `BENIGN_LABELS`
  (`benign`, `ham`): the only labels accepted.
- **`load_labelled` (21–37)** — reads either JSONL rows with a `label` field,
  or tab-separated `label<TAB>text` lines (a third column, the sender, is
  ignored). Lines 34–35 stop the run if any label is not recognised. Without
  that check, a line nobody had labelled yet would silently count as benign
  and flatter the score.
- **`sweep` (40–54)**:
  - first, every message is masked, its signals extracted, and the gate run
    once. `scored` is a list of `(score, is_scam)`.
  - then, for each threshold from 0.05 to 0.95:
    - `tp` — scams at or above the threshold: **caught**.
    - `fp` — harmless messages at or above it: **false alarms**.
    - `fn` — scams below it: **missed**.
    - `precision`, `recall` and `f1` as in the harness.
- **`split` (57–63)** — every fifth message (`index % 5 == 0`) is the
  **holdout**; the rest are **dev**. Rules are written looking only at dev and
  judged on holdout, so the score is not flattered by rules fitted to the
  same messages.
- **`main` (66–79)** — reads `--part` (`all`, `dev` or `holdout`), prints the
  table and the threshold with the best F1. It uses Jev as well when
  `ENABLE_JEV=1`, so the two set-ups can be compared.

A missed scam and a false alarm do not cost the same. Read the table for the
lowest threshold whose false alarms the caregiver can live with, not only for
the best F1.

---

## `collect_sms.py`

Turns a phone's SMS export into a short file ready to be labelled. It exists
so the gate can be measured on real South African messages. Everything runs
on this machine.

- **Line 18 `RECEIVED`** — the export marks received texts with type `1`.
- **Line 19 `NOT_A_CONTACT`** — the values the export uses when the sender is
  not in the phone's contacts.
- **Line 20 `MONTHS`** — month names, used only to spot repeats.

### `looks_personal` (lines 23–34)

True when a sender looks like a person rather than a business.

- **31–32** — a sender with letters in it (`Capitec`, `MTN136`) is a business.
- **33** — otherwise keep only the digits.
- **34** — 7 to 12 digits looks like a phone number. Shorter is a short code;
  longer is a bulk-messaging number.

Why this exists: on the first real export, 4,294 of 4,299 texts had no
contact name, so "skip saved contacts" filtered almost nothing and personal
conversations would have reached the labelling file. The phone-number test
does not depend on the export knowing who is a contact.

The cost: a scam from an ordinary phone number, such as "Hi mom, new
number", is left out too. Those have to be added to the file by hand.

### `collect` (lines 37–59)

- **39** — `by_sender`: each sender's kept messages.
- **40** — `seen`: the shapes of messages already kept.
- **41** — walk through every `<sms>` entry in the file. Picture messages are
  a different tag and are skipped.
- **42** — `text`: the body with its whitespace tidied.
- **43** — `sender`: the address the message came from.
- **44–45** — skip anything sent by the phone's owner, and anything the
  export marks as from a saved contact.
- **46–47** — skip anything from a sender that looks like a person.
- **48–49** — skip empty messages and one-time codes.
- **50** — mask account and card numbers.
- **51–54** — `shape` is the message with every number turned into `0` and
  every month into `month`. Two notices that differ only in amount or date
  have the same shape, so only the first is kept.
- **55** — file the message under its sender.
- **56–59** — take at most `per_sender` messages from each sender, shuffle,
  and cut to `limit`, so the file stays short enough to label by hand. The
  fixed `seed` makes the sample repeatable.

### `main` (lines 62–72)

Reads the export path and the options, calls `collect`, and writes each
message as `?<TAB>text<TAB>sender`. A person then replaces each `?` with
`scam` or `benign`. `calibrate.py` refuses the file until every line is labelled.

The labels must come from someone who did not write the gate's rules.

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

- **Line 5 `ENV_FILE`** — the path `agentic-engine/.env`.
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

# 5. API, runner, harness, and the model client

The ways into the engine, the way to score it, and the optional model code.

---

## `main.py`

- **Lines 1–15** — imports, including the routers from `api/routes.py` and
  `api/people.py`, the background scanners from `api/scanner.py`, and the store.
- **Line 17** — `ROOT` is the folder this file is in.
- **Lines 18–19** — `app` is the web application, with a title and description
  that appear in the generated documentation at `/docs`.
- **Lines 23–25** — cross-origin access. `CORS_ORIGINS` is read from the
  environment and split on commas into `origins`. If the list is empty, which
  is the default, no cross-origin middleware is added and a page served from
  anywhere else cannot call the API. If addresses are listed, only those may
  call it, only with GET and POST, and only with the `Content-Type` and
  `Authorization` headers. `Authorization` carries the Clerk session token
  that every route except `/health`, the privacy patterns and the invite
  preview needs. A paired phone sends `X-Device-Key` instead.
- **Lines 27–32** — health, the privacy patterns and the people routes are served under `/api`.
  Person and caregiver routes are served under `/api/people/{person_id}`;
  development mode also exposes unscoped console routes under `/api`.
- **Line 34** — open the store (`api/store.py`).
- **Lines 35–37** — if the server has its own IMAP mailbox, list it under the
  first protected person only. A first person added later gets it in `api/people.py`.
- **Line 38** — start the live mailbox thread. It does nothing unless
  `IMAP_HOST` is set. Each email goes through `forwarded_handler`, so it is
  kept under the same retention rules as Gmail, and each check's result is
  written to the mailbox's status by `note_forwarded`.
- **Line 39** — start the Gmail scanner. It does nothing unless
  `CLERK_SECRET_KEY` is set.
- **Line 40** — plug the Gmail blocker into the agent (`api/gmail_block.py`).
- **Line 41** — the `static` folder is served under `/static`.
- **Lines 44–47** — `/console` returns the plain developer console for
  watching the engine. It cannot sign in, so it only works with
  `KINGUARD_DEV_OPEN=1` (see `api/auth.py`).
- **Lines 52–58** — the Scam Stop dashboard. If `frontend/dist` has been built,
  it is mounted at `/`, so the dashboard and the API share one origin and need
  no CORS. It is mounted last, so every `/api` route above is matched first.
  Without a build, `/` redirects to the console.

---

## `api/routes.py`

The contract for the front end is in `API.md`. This section explains the code.

**Lines 20–22** — three routers, by who may call them:
- `router` (line 20) needs a caregiver linked to the person in the path.
- `person_router` (line 21) accepts that caregiver or the protected person:
  outbox, feedback, reviews addressed to the person, the person's own state,
  and the phone's inbox sync.
- `open_router` (line 22) needs no session: `GET /health` and
  `GET /privacy/patterns`, neither of which holds anyone's data.

Each `dependencies=[Depends(...)]` runs `api/auth.py` before the route body.
Line 9 imports the scoped role checks from there.

**Lines 23–33** — `runtime` is the shared development console runtime.
`caregiver_runtime` and `member_runtime` select the separate runtime for the
person in the URL. A restart loses nothing: each runtime saves its incidents
and reviews to its own file (`core/store.py`), and `api/store.py` keeps people,
invites and mailboxes in SQLite.

### Request and response shapes (lines 36–81)

Each class describes a JSON body. FastAPI rejects a request that does not
fit, with error 422, before any of our code runs.

- `ReviewDecision` — `approved`: true or false.
- `StateRequest` — `target`: an `IncidentState`.
- `ReplayFile` — `filename` and `content` of a CSV or JSONL file.
- `StepRequest` — `steps`: how many messages to process; at least 1.
- `EmailUpload` — `content`: raw `.eml` text.
- `SharedMessage` — `text` (at least one character), `sender`, `channel`, and
  `timestamp` (line 63): when the phone received it. The message's id is made
  from the time, sender and text, so a phone that always sends the real
  received time can re-sync its inbox without anything being processed twice.
- `Feedback` — `legitimate`: true or false.
- `GuardianSetting` — `enrolled`: true or false.
- `Withheld` — the reply when a message is discarded: `status` and `reason`.
- `PersonMessage` — one warning for the person: `incident_id` and `message`.

### Helpers (lines 84–99)

- **84–85 `_now`** — the current UTC time as text.
- **97–99 `take_in_email`** — one raw email in, one decision out, for one
  person's runtime. The API route, the live mailbox and the Gmail scanner all
  call it, so they cannot behave differently.
- **88–94 `_take_in`** — the shared path for live intake:
  - **90–92** — ask the domain whether the row must be withheld. If so, return
    a `Withheld` reply and store nothing.
  - **93** — parse it safely. The number passed in comes from
    `runtime.next_report_number()`, which is never reused, so a report ID made
    from it cannot collide even after the scanner forgets safe mail.
  - **94** — process it safely. A decision always comes back.

### Endpoints

Each decorator names the router (see above), the method, the path, a `tags` group used to
organise `/docs`, and a `response_model`. The response model does two things:
it documents the reply, and it strips anything not in the model before the
reply is sent.

| Lines | Method and path | Group | What it does |
|---|---|---|---|
| 107–110 | `POST /intake/email` | intake | Convert raw email text to a row and take it in |
| 113–116 | `POST /intake/share` | intake | Convert a hand-shared message to a row and take it in; uses the phone's `timestamp` when given |
| 119–122 | `POST /intake/share/batch` | person | Many messages at once, oldest first, for the person's phone syncing its SMS inbox |
| 125–128 | `GET /privacy/patterns` | open | The one-time-code and secret patterns, so the phone can apply the same filter before sending anything |
| 131–137 | `POST /reports` | intake | Process a ready-made report. A reused ID with different content returns 409 |
| 142–146 | `GET /outbox` | person | Warnings not yet answered by the person |
| 149–159 | `POST /incidents/{id}/feedback` | person | Only the person may answer about their incident |
| 164–167 | `GET /incidents` | caregiver | Every incident |
| 170–180 | `GET /incidents/{id}` | caregiver | One incident with its reports, decisions and reviews |
| 183–188 | `GET /decisions/{report_id}` | caregiver | One decision and its trace; 404 if unknown |
| 191–195 | `GET /reviews` | caregiver | The review queue, optionally filtered by `status` |
| 198–202 | `GET /guardian/briefs` | caregiver | Each pending caregiver review as a plain message with a WhatsApp link |
| 205–208 | `GET /person/reviews` | person | Only reviews addressed to the protected person |
| 211–214 | `GET /person/state` | person | For the phone: whether a caregiver decides, and the disputes to lodge |
| 217–228 | `POST /reviews/{id}/decision` | person or caregiver | Only the addressed role may approve or reject |
| 231–239 | `POST /incidents/{id}/state` | caregiver | A human moves an incident's state |
| 244–249 | `GET /health` | system | Confirms the server is up and optional parts. No session needed |
| 252–257 | `GET /state` | system | Everything in one call, plus the simulated world |
| 260–265 | `POST /settings/guardian` | system | Say whether a caregiver is enrolled, and save it |
| 268–272 | `POST /reset` | system | Empty this person's runtime |
| 275–282 | `POST /replay` | system | Reset, then process a list of reports |
| 285–293 | `POST /replay/load` | system | Queue a file for step-through replay |
| 296–300 | `POST /replay/step` | system | Process the next messages in the queue |

**`feedback` in detail (149–159)**
- **152–153** — only the protected person may answer outside development mode.
- **154–155** — unknown incident: error 404.
- **156** — a sentence describing the answer.
- **157–158** — the answer is wrapped as a `RawInputReport` with `source`
  `"person"`. Its metadata names the incident (so the correlator links it
  explicitly) and carries the `feedback` value.
- **159** — it is processed like any other message. The person's answer is
  evidence that goes through the same policy; it is not a command.

WhatsApp no longer comes in through a webhook. A Twilio gateway only ever saw
messages sent to the Twilio number, never the person's own WhatsApp, so it was
removed. The phone bridge reads the person's WhatsApp notifications and sends
them through `POST /intake/share/batch` like texts (see `frontend/ANDROID.md`).

**`guardian_briefs` in detail (198–202)** — for every review that is
`PENDING` and addressed to the `CAREGIVER`, build a brief from the review and
the decision that opened it.

**`reviews` in detail (191–195)** — `status` and `audience` are optional query
parameters. `?status=PENDING&audience=PERSON` returns what is waiting for the
person themselves; with nothing, every review is returned.

**`replay_load` in detail (285–293)**
- **289** — strip an invisible marker from the start of the text, read the
  rows, and drop the withheld ones.
- **290–291** — an unsupported file type returns error 400.
- **292** — parse every row safely and hand the list to the runtime's queue.

**Error handling in `decide` and `move_state`** — a `KeyError` (unknown ID)
becomes 404; a `ValueError` (not allowed right now) becomes 409.

Each caregiver may add several people. `api/pool.py` gives each person a
separate runtime, and `api/auth.py` checks the person id in each scoped route.

**Development switch.** With `KINGUARD_DEV_OPEN=1`, `api/auth.py` skips Clerk and
the routes open up, so the plain console in `static/` and local scripts still
work. It is off by default. With it on, an `X-Dev-User` header picks who the
caller is. Never set it on a server anyone else can reach.

---

## `domain/briefs.py`

Turns a pending review into a message a caregiver can read on their phone.

### `guardian_brief` (lines 8–19)

- **10** — `details` of the proposed action, or an empty dictionary.
- **11** — `question`: the plain question written for the approver, falling
  back to the technical reason.
- **12** — `why`: the second line of the decision's trace, which is the
  rationale with the evidence.
- **13** — `text`: the brief itself.
- **14–15** — if there is a dispute deadline, add it.
- **17** — `number`: `GUARDIAN_WHATSAPP` from the environment, reduced to its
  digits.
- **18–19** — return the text and a `wa.me` link. Opening that link on a
  phone opens WhatsApp with the caregiver's chat selected and the brief
  already typed. `quote` makes the text safe to put in a link.

The backend does not send the WhatsApp message. Sending automatically needs
a WhatsApp Business account and an approved message template. The link needs
nothing, and whoever taps it sees exactly what is being sent.

One thing to say plainly: the brief contains the merchant and the amount, and
it travels through WhatsApp once sent. That is the family's choice to make.

---

## `api/mailbox.py`

The optional live inbox. It reads a mailbox created for Scam Stop, which the
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

### `start_polling` (lines 34–57)

- **34–38** — `on_result` is optional. It hears `None` after each good check
  and a short description (the error's name, never its text) after a bad one.
  `main.py` uses it to keep the forwarded mailbox's status up to date.
- **39–40** — if `IMAP_HOST` is not set, do nothing and return `None`.
- **41** — how often to check, 15 seconds unless `IMAP_POLL_SECONDS` says otherwise.
- **43–53 `loop`** — forever: check the mailbox and report success (47–48). If
  that fails for any reason, print the error, report it (51–52) and carry on.
  A mailbox problem never stops the server.
- **55–57** — run `loop` on a background thread. `daemon=True` means it stops
  when the server stops.

Not yet run against a real mailbox; the test uses a stand-in.

---

## `api/gmail.py`

Reads Gmail through the Google account the **protected person** connected via
Clerk. Clerk keeps the Google OAuth token and refreshes it; the server asks
Clerk for it on every call and never stores it. The caregiver's own mailbox is
never read, and there are no routes here: only helpers that `api/scanner.py`
and `api/people.py` use.

### Imports and constants (lines 7–20)

- **7** — `base64` decodes the raw email Gmail returns.
- **9** — `Iterator`, the type of a generator that hands back ids one by one.
- **11** — `httpx` makes the calls to Gmail and to Google's revoke address.
- **12–13** — Clerk's client for its own API, and FastAPI's `HTTPException`.
- **15** — `GMAIL`, the Gmail API address for the connected account.
- **16** — `READ_SCOPE`, the Google permission to read mail and nothing else.
- **19** — `REVOKE`, Google's address for cancelling a token.
- **20** — `MAX_PAGES`: a scan looks at up to 10 pages of 50 emails.

Lines 17–18 add `MODIFY_SCOPE` (move an email to Spam) and `SETTINGS_SCOPE`
(create a filter): the two permissions blocking needs, beside read access.

### `google_grant` and `google_token` (lines 23–37)

`google_grant` returns the token and the permissions it carries, so the blocker
can check for the two it needs. `google_token` is the same, token only.

- **25–26** — ask Clerk for the user's Google access token.
- **27–28** — no Google account connected: 403.
- **29–30** — Google is connected but without `READ_SCOPE`: 403, with a
  message saying to sign in with Google again.
- **31–32** — the token.

### `gmail_get` (lines 40–50)

One GET to Gmail with the token. Google refusing the token becomes 401,
refusing access to the mailbox 403, an unknown email 404, and any other Gmail
error 502. The scanner treats 401 and 403 as "this connection is broken" and
anything else as a temporary failure. Tests replace this function, so none
reaches Google.

### `message_ids` (lines 53–63)

A generator of the ids of every email matching a Gmail search, newest first.
It asks for 50 at a time (line 57) and follows `nextPageToken` (62–63) for at
most `MAX_PAGES` pages, so one scan never runs away on a huge mailbox.

### `raw_email` (lines 66–69)

Fetches one email in `raw` format, decodes it from Gmail's URL-safe base64
(adding back the padding Gmail leaves off) and returns it as the text of an
`.eml` file, exactly what `take_in_email` expects.

### `gmail_send` (lines 72–79)

One change to the mailbox (`POST` or `DELETE`). Google refusing is raised like
`gmail_get`, so the caller can say what went wrong.

### `revoke` (lines 82–87)

Tells Google to cancel a token, for the person's Disconnect button. Best
effort: if Google cannot be reached it prints the error's name and carries on,
because the person can also remove access in their Google account.

---

## `api/gmail_block.py`

Blocks a scammer in the person's own Gmail when the agent marks them. The scam
email is moved out of the inbox into **Spam**, and a Gmail **filter** sends
every later email from that sender to the **Bin**. Both are undone if the
alert is withdrawn, and Bin and Spam keep mail for 30 days, so nothing is
destroyed. Permanent deletion would need full mailbox access and would destroy
evidence the person may need for a bank or police report.

- **`NEEDS`** — `gmail.modify` and `gmail.settings.basic`.
- **`_mailbox_owner`** — the connected Gmail mailbox the email came from, or
  `None`.
- **`block_in_gmail`** — only for an email that came from a connected Gmail
  (the scanner puts `mailbox_id` and `gmail_id` in its metadata). Without the
  two permissions it returns only a note, "reconnect Gmail and allow Scam Stop
  to manage spam", and the sender is still marked. Otherwise it moves the email
  to Spam, creates the filter `from: <sender> → Bin`, and returns what it did.
- **`unblock_in_gmail`** — deletes the filter and puts the email back in the
  inbox.
- **`register`** — adds both to the agent's hooks in `domain/tools.py`; `main.py`
  calls it once.

The tests replace Google with a recorder; it has not yet been run against a
real Gmail account.

---

## `api/auth.py`

Who is calling. Clerk proves who the user is; the store says which person they
are linked to and in what role. Every route except `/health`, the privacy
patterns and the invite preview goes through here.

- **13–21 `Caller`** — the user's id, their `role` (`caregiver`, `person`, or
  `None` before they are linked to anyone), the people they are linked to, and
  `person_id`, the first of those.
- **24–26 `dev_open`** — development only. `KINGUARD_DEV_OPEN=1` turns Clerk off
  so the plain console and local scripts still work. Off by default.
- **29–46 `who`** — the user id behind the request.
  - **31–36** — **a paired phone.** The phone app cannot sign in, so it sends
    its pairing code in an `X-Device-Key` header. The store turns the code into
    the phone's own user id, which is linked to one person as `person`. An
    unknown or replaced code is 401. This runs before the development switch,
    so a phone works the same way in both modes.
  - **37–38** — in development mode, read the user from an `X-Dev-User` header
    (default `dev`), so a developer can act as different people.
  - **39–41** — without `CLERK_SECRET_KEY` the server cannot check anyone: 503.
  - **42** — the front end addresses from `CORS_ORIGINS`; a token is only
    accepted if Clerk issued it to one of them.
  - **43–45** — Clerk checks the `Authorization: Bearer` token; no valid
    session is 401.
  - **46** — the user id (`sub`).
- **49–51 `caller`** — looks the user up in the store and builds a `Caller`.
- **54–58 `caregiver`** — passes only a caregiver. Someone not yet linked to
  anyone gets 403 "Add the person you look after first", so a stranger who
  signs up sees nothing. In development mode an unlinked caller is let through.
  A paired phone is a `person`, so it never passes.
- **61–65 `member`** — passes a caregiver or the protected person; used for the
  few routes both may call.
- **68–70 `_may_see`** — linked to this person, or in development mode with
  nobody linked yet.
- **73–84 `caregiver_of`, `member_of`** — the caregiver of *this* person, or
  either of them. Another person's id answers 404, as if it did not exist.
- **87–106 `active_caregiver_person`, `active_member_person`** — the person a
  route is about, from the address. With none named, only an unlinked caller in
  development mode is let through (to the shared runtime); anyone else gets
  404 "Name the person in the address".
- **109–118 `set_clerk_role`** — also writes the role to the user's Clerk public
  metadata so the front end can read it. The store stays the authority: a
  Clerk failure is printed and ignored, because the link is already saved.

---

## `api/store.py`

What must survive a restart, in a SQLite file (`KINGUARD_DB`, default
`backend/kinguard.db`, ignored by git). Incidents and reviews are saved
separately, one JSON file per person (`core/store.py`).

- **13–16** — the default file, how long an invite lasts (7 days), the letters a
  phone pairing code is made from (no O, 0, I or 1, which look alike), and how long a
  temporary Gmail failure may last before it counts as a problem (15 minutes).
- **18–38 `SCHEMA`** — six tables: `people`; `links` (which user is linked to
  which person, as `caregiver` or `person`); `invites`; `mailboxes` (state, the
  Clerk user that owns the Google connection, last check, last error and when
  failures began); `scanned` (a mailbox id, a message id and a verdict, and
  **nothing else about the message**); `phones` (the hash of a pairing code,
  the person, the phone's own user id, and when it was replaced).
- **40–45 `now`, `stamp`** — the current time, and a time as text.
- **49–54** — open the file (one shared connection, guarded by a lock) and
  create the tables if missing.
- **56–64** — `close`, and `reset`, which empties every table for tests.
- **66–72** — `_one` and `_all` turn rows into plain dictionaries.
- **75–81** — `people`, `person`.
- **83–90 `create_person`** — adds a person and links the creator as caregiver;
  one caregiver may look after several people.
- **92–99 `create_self`** — someone protecting themselves: a person record
  linked to the user as `person`, with no caregiver.
- **101–103 `has_caregiver`** — whether anyone is linked to the person as their
  caregiver. With none, the person sets up their own Gmail and phone.
- **105–121 `links_of`, `people_of`, `first_person`** — find a user's links,
  their people, and the first person assigned the server's IMAP inbox.
- **122–130 `create_invite`** — a random, unguessable, single-use token.
- **131–139** — `invite`, and `pending_invites` (not used, cancelled or expired).
- **140–146 `cancel_invite`** — only an invite still waiting can be cancelled.
- **147–160 `accept_invite`** — checks again that the link remains usable,
  marks it used, removes an earlier
  protected-person account link for this profile (but not a paired phone, line 156), links the accepting user,
  then connects their Gmail. The same account can reconnect through a fresh invite.
- **162–171 `connect_gmail`** — clears verdicts belonging to the replaced
  mailbox and adds a new connected Gmail mailbox owned by the user. Used by an
  accepted invite and by someone protecting themselves.
- **175–183** — `mailbox` and `mailboxes`, each with `checked`, how many
  messages have a verdict.
- **184–195 `ensure_forwarded`** — the server's own IMAP mailbox, added once.
- **196–200 `disconnect`** — Gmail mailbox becomes `disconnected`.
- **201–206 `mark_checked`** — a good scan: `connected`, time noted, errors
  cleared. Never wakes a `disconnected` mailbox.
- **207–217 `mark_failure`** — a revoked or refused token (`permanent`) is a
  `problem` at once. Anything else only becomes one once failures have lasted
  `OUTAGE_MINUTES`.
- **221–232 `pair_phone`** — a new 10-character code from `CODE_LETTERS`
  (about 50 bits). The previous phone is unpaired: its links are deleted and
  its row marked replaced (226–228). Only the code's hash is stored, with a
  new user id such as `phone:3f9a1c20`, which is linked to the person as
  `person` (229–230). The code itself is returned once and never kept.
- **234–238 `phone_user`** — the user id a code stands for, if it is still the
  current one.
- **240–244 `phone_paired`** — when the current phone was paired, for the
  dashboard. Never the code.
- **248–255** — `seen` and `record_scanned`: has this message been handled, and
  remember its verdict.
- **258–260 `_hash`** — SHA-256 of the code after removing spaces and dashes and
  making it upper case, so a code typed loosely on a phone still matches.
- **263–276 `invite_problem`** — why an invite cannot be used, in words the
  person would understand, or `None` if it can.
- **279–284 `get_store`** — one shared store, opened on first use so tests can
  point `KINGUARD_DB` at `:memory:` first.

---

## `api/people.py`

Who is looked after, who looks after them, and how the person connects their
own Gmail. The contract is in `API.md`.

- **12** — these routes are served under `/api` too, tagged `people`.
- **15–17 `NewPerson`** — a name (1–80 characters) and an optional relation.
- **20–23 `_mailbox`** — what a mailbox looks like to the front end: its state,
  when it was last checked, the last error, how many messages were checked.
  Never a token, never a message.
- **26–27 `_invite`** — token and dates.
- **30–31 `_person`** — id, name and relation without private state.
- **34–44 `_me`** — the signed-in user's role, whether they are protecting
  themselves (`self_protected`, line 39), first person and full `people`
  list. Caregivers may add more people; a protected person sees their own
  Gmail mailbox state.
- **47–50 `GET /me`** — who you are.
- **53–65 `POST /people`** — a caregiver adds another person; an unlinked user
  becomes a caregiver. The first person gets the optional forwarded inbox.
- **68–77 `GET /people/summary`** — each caregiver's people with pending
  review and mailbox problem counts.
- **80–83 `GET /people/{id}/mailboxes`** — the person's mailboxes and whether
  mail is being checked. 404 for anyone else's person.
- **86–88 `GET /people/{id}/invites`** — invites still waiting.
- **91–94 `POST /people/{id}/invites`** — a new single-use link, valid 7 days.
- **97–101 `POST .../invites/{token}/cancel`** — withdraw an invite; 404 if it is
  not waiting any more.
- **104–107 `POST /people/{id}/phone`** — the caregiver gets a pairing code for
  the person's phone app. It is shown once; a new one unpairs the old phone.
- **110–113 `GET /people/{id}/phone`** — when a phone was paired, or `null`.
- **116–123 `GET /invites/{token}`** — no sign-in needed. Says whether the link
  works, and if so whose name is on it, and nothing else.
- **126–144 `POST /invites/{token}/accept`** — the person signed in with Google
  from the link.
  - **130–132** — an unusable invite is 410 with a plain reason.
  - **133–136** — the same protected-person account may reconnect; an account
    linked elsewhere gets 409, including a caregiver's account.
  - **137–138** — ask Clerk for the Google token. If Gmail read access was not
    granted this refuses with a clear reason and the invite stays usable.
  - **139–144** — link them, store the `person` role in Clerk, return `_me`.
- **147–148 `SelfProtection`** — the name of someone protecting themselves.
- **151–156 `_self_protected`** — the caller's person id, if they are a person
  with no caregiver; anyone else gets 403. A person with a caregiver never sets
  up their own phone or Gmail here: the caregiver does that.
- **159–170 `POST /me/self`** — someone not yet linked protects themselves: a
  person record linked to them, and their runtime set to no-guardian mode
  (lines 166–167), so their reviews are addressed to them and serious ones wait
  out the cooling-off. 409 if the account is already set up.
- **173–181 `POST /me/gmail`** — they connect their own Gmail. As with an
  invite, it refuses with a plain reason if Google did not grant Gmail read
  access, and the screen then asks Google again.
- **184–192 `POST` and `GET /me/phone`** — pair their own phone, and when it was
  paired, the same as the caregiver's routes for a person.
- **195–207 `POST /me/disconnect`** — only the person whose mail it is. Tells
  Google to revoke the token (best effort), marks the mailbox `disconnected`
  and stops scanning at once. Only a new invite reconnects it.

---

## `api/scanner.py`

Reads each connected mailbox in the background and keeps only what the
caregiver needs. Safe mail leaves an id and a verdict. Flagged mail keeps its
text until its alert is resolved. The caregiver never browses the mailbox.

- **23–25** — look back 14 days on first connection, re-check 120 seconds before
  the last scan so nothing slips between two, and which states count as resolved.
- **28–42 `handle_mail`** — one email in, then the retention rules. Returns
  `withheld` (a one-time code: nothing stored), `safe`, or `flagged`. A flagged
  report is tagged with the mailbox it came from (line 40) so it can be blanked
  later. Lines 37 and 40 save the runtime afterwards, so the saved file never
  keeps a safe email that memory has already forgotten.
- **45–61 `forget`** — removes a safe email's report and decision. If it
  joined an alert, remove its report id there too. When an action or review
  still refers to the report, keep only an empty audit stub with a safe verdict.
- **64–85 `blank_resolved`** — for mailbox mail whose alert is resolved or
  closed, blank the text and sender (line 79), and the alert's summary (81–82).
  An alert made from a message the caregiver pasted by hand is left alone.
  Each runtime that blanked something is saved (83–84).
- **88–115 `scan_gmail`** — one pass over one Gmail mailbox.
  - **90–94** — first scan: `newer_than:14d`; later: `after:<last check minus 120s>`.
  - **96–110** — get the person's token from Clerk; before and after fetching
    each message, confirm its mailbox is still connected to the same owner.
    Skip ids already seen, read the rest, record each verdict, then mark it
    checked.
  - **111–112** — Google refusing the token (401, 403) is a permanent failure.
  - **113–114** — anything else, such as the network, is temporary and becomes a
    problem only after 15 minutes.
- **118–123 `scan_once`** — every Gmail mailbox not `disconnected`, then blank
  what is resolved.
- **126–134 `forwarded_handler`** — the same rules for the server's own IMAP
  mailbox, recording a verdict per email under a hash of its text. With nobody
  looked after yet it behaves as before.
- **137–144 `note_forwarded`** — record whether the last IMAP check worked.
- **147–164 `start_scanning`** — without `CLERK_SECRET_KEY` do nothing, since
  tokens come from Clerk. Otherwise a background thread scans every
  `SCAN_SECONDS` (default 60) and never stops on an error.

Not yet run against a real Gmail account: the tests use stand-ins for Clerk and
Gmail.

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
  ignored). Lines 34–35 skip a line labelled `unsure`: the labeller could not
  tell, so it is left out rather than guessed. Lines 36–37 stop the run if any label is not recognised. Without
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
- **Line 21 `TOKEN`** — a run of letters, digits and joiners such as `#`,
  `/` and `-`: the shape of an order number or a student number.

### `looks_personal` (lines 24–35)

True when a sender looks like a person rather than a business.

- **32–33** — a sender with letters in it (`Capitec`, `MTN136`) is a business.
- **34** — otherwise keep only the digits.
- **35** — 7 to 12 digits looks like a phone number. Shorter is a short code;
  longer is a bulk-messaging number.

Why this exists: on the first real export, 4,294 of 4,299 texts had no
contact name, so "skip saved contacts" filtered almost nothing and personal
conversations would have reached the labelling file. The phone-number test
does not depend on the export knowing who is a contact.

The cost: a scam from an ordinary phone number, such as "Hi mom, new
number", is left out too. Those have to be added to the file by hand.

### `mask_for_labelling` (lines 38–54)

Stronger masking than the engine uses, because people will read this file.

- **44** — every email address becomes `[email withheld]`.
- **45–46** — every word passed in with `--mask` (the owner's names) becomes
  `[name]`, whole words only, ignoring case.
- **48–52 `mask`** — for each token: if it has fewer than five digits, or it
  is a rand amount, or it is a phone number, keep it; otherwise replace it
  with `[id withheld]`. Order numbers, student numbers and long references
  go; amounts and phone numbers stay, because the gate reads them.
- **54** — apply `mask` to every token in the text.

Why this exists: the first real file still showed order numbers and a
student number, which the engine's masking of 9-digit-plus runs does not
catch.

### `collect` (lines 57–79)

- **59** — `by_sender`: each sender's kept messages.
- **60** — `seen`: the shapes of messages already kept.
- **61** — walk through every `<sms>` entry in the file. Picture messages are
  a different tag and are skipped.
- **62** — `text`: the body with its whitespace tidied.
- **63** — `sender`: the address the message came from.
- **64–65** — skip anything sent by the phone's owner, and anything the
  export marks as from a saved contact.
- **66–67** — skip anything from a sender that looks like a person.
- **68–69** — skip empty messages, one-time codes, and any message that hands
  over a password or recovery code (see `is_one_time_code` in
  `02-reading-messages.md`).
- **70** — mask account numbers the engine's way, then mask for labelling.
- **71–74** — `shape` is the message with every number turned into `0` and
  every month into `month`. Two notices that differ only in amount or date
  have the same shape, so only the first is kept.
- **75** — file the message under its sender.
- **76–79** — take at most `per_sender` messages from each sender, shuffle,
  and cut to `limit`, so the file stays short enough to label by hand. The
  fixed `seed` makes the sample repeatable.

### `main` (lines 82–93)

Reads the export path and the options, including `--mask` (line 88), calls
`collect`, and writes each message as `?<TAB>text<TAB>sender`. A person then
replaces each `?` with `scam` or `benign`. `calibrate.py` refuses the file
until every line is labelled.

The labels must come from someone who did not write the gate's rules.

---

## `label.py`

Shows one unlabelled message at a time and saves each answer at once.

- **Line 10 `ANSWERS`** — the keys: `s` scam, `m` marketing, `b` benign, `u` unsure.
- **`main` (13–35)**:
  - **16** — `--reset` clears every label so the file can be labelled again.
  - **18** — read every line of the file.
  - **19–20** — with `--reset`, put `?` back at the start of every line.
  - **21** — `waiting`: the positions of lines still marked `?`.
  - **23–28** — for each one, show the sender and the text, and ask until the
    answer is one of the keys or `q`.
  - **29–30** — `q` stops; everything answered so far is already saved.
  - **31–32** — replace the `?` with the label and write the whole file back
    straight away, so nothing is lost if the window is closed.
  - **34–35** — say how many are left.

`marketing` exists because the first labelling round showed that "scam" and
"unwanted marketing" were being mixed. `calibrate.py` counts marketing as not
a scam (line 18), so the gate flagging it is a false alarm.

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
let Gemini judge relation and assessment. Scam Stop does not switch them on.

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
still carries the generic prompt and has not been adapted to Scam Stop.

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

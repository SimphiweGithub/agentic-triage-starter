# 3. Judging messages

Five files decide what a message means and what to do about it:

1. `domain/gate.py` — a fast first look, with rules and an optional decision model (Jev).
2. `domain/tools.py` — the tools, and the outside world they act on.
3. `domain/investigate.py` — calls the read-only tools to gather evidence.
4. `domain/language.py` — the one language job given to Gemini.
5. `domain/logic.py` — puts it together and produces an `Assessment`.

Who does what: **Jev** answers narrow yes/no questions quickly. **Gemini**
words the warning shown to the person. **Python** makes every decision.

The output is only a **proposal**. Whether it happens is decided in
`04-engine.md`.

---

## `domain/gate.py`

A cheap score from 0 to 1. Most messages are harmless, so they should stop
here without any tool being called.

**Lines 11–13** — imports the Jev client, the threat enum, and two thresholds
from policy.

### `TEXT_RULES` (lines 18–49)

A dictionary. Each entry has a short `key` and three values: the `reason`
written into the trace, the `weight` added to the score, and the `pattern`
that triggers it.

| Lines | Key | What it catches | Weight |
|---|---|---|---|
| 19–20 | `urgency` | Urgent or threatening wording | 0.25 |
| 21–22 | `credentials` | A verb, then `your`, then PIN, password, card or details; or a remote-access tool name. It does not fire on a bank saying "never share your PIN" | 0.35 |
| 23–25 | `payment` | Gift cards or crypto; or paying, buying or sending a voucher or e-wallet. A voucher on its own does not count (see below) | 0.35 |
| 26–27 | `subscription` | Subscription and renewal words. Weak alone, because honest messages use them too | 0.15 |
| 28–29 | `prize` | "You have won", winner, prize, awarded, guaranteed, been selected | 0.3 |
| 30–31 | `claim` | "To claim", "call now", "text WORD to 12345" | 0.3 |
| 32–34 | `premium` | Pence or rand per message, minute, day or week; "std txt rate"; premium-rate number ranges | 0.3 |
| 35–36 | `impersonation` | "This is my new number", "lost my phone": someone claiming to be a relative or friend. Weak alone, because honest people change numbers too | 0.2 |
| 37–38 | `money` | Asks the reader to send, transfer or deposit money | 0.3 |
| 39–40 | `advance_fee` | Inheritance, unclaimed parcel, release or clearance fee, lottery | 0.3 |
| 42–45 | `job` | Work from home, daily salary, part-time staff, hiring online, "earn … a day", "$3-10/day", small investment, big returns | 0.3 |
| 46–48 | `cold_offer` | A loan, credit, cover or insurance word **and** "Reply YES", "No=out" or "accept offer" anywhere in the message | 0.3 |

Where each rule came from:

- The first four were written from knowledge of scams.
- `prize`, `claim` and `premium` were written after measuring on the UCI
  data: see "How the rules were measured" below.
- `impersonation`, `money` and `advance_fee` cover scams the UCI data has
  almost none of, so it could only tell us whether they cause false alarms.
  The first version did (two extra on the held-out set), so `impersonation`
  was weakened to 0.2 and one loose word was removed.
- `job` and `cold_offer` were written from our own South African messages
  (`data/sa_messages.tsv`), after the rules caught only 4 of its 16 scams.

**How `cold_offer` works (line 47).** `^(?=…)(?=…)` is two lookaheads at the
start of the text. A lookahead checks that something appears later without
consuming it, so both must be found, in either order. `re.S` lets `.` cross
line breaks. One condition alone is not enough: a college saying "Reply YES
for help with your application" has the reply but no credit word.

**Why `cold_offer` exists.** "Reply YES (free) for a quote. No=out" is how
South African insurers and lenders sell by SMS. It is not fraud, but for an
older person replying YES starts a sales call that often ends in a funeral
policy or a loan with a debit order: the harm Scam Stop exists to prevent.
It gets its own threat type, `SALES_OFFER`, and a milder response (see
`logic.py`).

**What was removed.** `premium` used to fire on "reply STOP" and
"unsubscribe". In the UK data those words came with paid text services, but
in South Africa direct-marketing SMS must offer an opt-out, so nearly every
legitimate marketing text has one: 25 of the 30 false alarms on our own
messages came from it. An opt-out is a sign of lawful marketing, not of a
scam. The same reasoning removed a voucher on its own from `payment`: shops
and networks send vouchers all the time; a scammer asks you to *buy* one.

### `TECH_SUPPORT_PATTERN` (line 50)

Words that suggest a tech-support scam. Used only to name the threat type.

### `MODEL_QUESTIONS` (lines 53–80)

The questions sent to Jev. Jev does not write text; it answers typed
questions about a piece of content.

- **Lines 54–67** — twelve `noul` questions with the **same keys** as
  `TEXT_RULES`. A Noul is a yes/no question; the answer is the probability,
  from 0 to 1, that the statement is true. Each asks one narrow thing, which
  is how the Jev documentation says to use it.
- **Lines 58–61** — `claim` and `premium` were narrowed after measuring on
  our own messages. The old wording ("call or text a number to collect
  something", "charges per message, day or week") made Jev say yes to every
  network advert for a data bundle, such as "Dial *123# to buy, valid 7
  days". Now `claim` is about a prize or money said to be owed, and
  `premium` is about a charge that repeats, not a once-off purchase.
- **Lines 68–79** — one `choice` question, `threat`. Its `criteria` are the
  ten `ThreatDomain` values, each with a description. The answer is the
  chosen option and a confidence.

### `ask_jev` (lines 83–85)

Calls the Jev client with the message as the state and `MODEL_QUESTIONS` as
the questions. Only the masked message text is sent.

### `GateVerdict` (lines 88–93)

- `score` — 0 to 1.
- `reasons` — the findings that added to the score.
- `threat` — the threat type.
- `notes` — remarks that did not change the score, such as "the model was
  unavailable". They are kept separate so they cannot inflate confidence.

### `gate` (lines 96–152)

Arguments: the message `text`, its `signals`, and an optional `ask_model`
function.

**Rules (98–112)**
- **98** — start: `score` 0, no `reasons`, `hits` (the set of keys that
  matched) empty, no `notes`.
- **99–103** — for every rule whose pattern is found, add its weight, record
  its reason, and remember its key in `hits`.
- **104–106** — replies go to a different domain than the sender: +0.2.
- **107–109** — the mail provider's authentication failed: +0.25.
- **110–112** — a link shows one address and leads to another: +0.3.

**Decision model (114–128)**
- **114** — `model_threat` starts as `None`.
- **115** — only runs if a model function was supplied.
- **117** — ask the model once; `answers` holds every question's answer.
- **118–123** — for each judgement: read the probability. If the key is **not**
  already in `hits` and the probability is at least `MODEL_YES`, add the same
  weight, record the reason marked as coming from the model, and add the key.
- **124–125** — use the model's threat type only if its confidence is at least
  `MODEL_THREAT_CONFIDENCE`. `ThreatDomain(...)` fails if the model returns a
  value outside the enum, which lands in the `except`.
- **126–127** — any failure (no key, network, bad reply, a missing answer)
  becomes a note. The rule score already computed is untouched.
- **128** — cap the score at 1.0.

Three properties to remember:

1. **The model can only add.** A rule that fired is never removed, and a
   judgement is never counted twice.
2. **The model never decides.** It answers narrow questions; the weights and
   the threshold are in our code.
3. **The gate works without it.**

**Naming the threat (130–151)**
- **130–131** — score 0: `BENIGN`.
- **132–133** — a confident model answer other than benign is used.
- **134–135** — tech-support words: `TECH_SUPPORT_SCAM`.
- **136–137** — a credentials hit: `IDENTITY_FARMING`.
- **138–139** — an impersonation hit: `IMPERSONATION`.
- **140–141** — an advance-fee hit: `ADVANCE_FEE`.
- **142–143** — a job hit: `JOB_SCAM`.
- **144–145** — a cold-offer hit: `SALES_OFFER`. It comes before `prize`
  because lenders write "you've been selected to apply", which also trips the
  prize rule; the message is still a credit offer, not a fake prize.
- **146–147** — a prize hit: `PRIZE_SCAM`.
- **148–149** — a debit, or a subscription or premium hit:
  `GREY_MARKET_SUBSCRIPTION`. `hits & {...}` is the overlap of two sets.
- **150–151** — otherwise `UNKNOWN`.
- **152** — return the verdict.

Why a prompt injection fails here: the rules only search for patterns, and
the model is asked fixed questions about the text, not given the text as
instructions. Even if a message swayed the model, the model cannot lower the
score.

### How the rules were measured

**UCI SMS Spam Collection.** 5,574 UK SMS labelled spam or not by its
authors. Every fifth message was held out; the prize, claim and premium
rules were written looking only at the other four fifths. All at threshold
0.30.

| Rules | Measured on | Caught | False alarms |
|---|---|---|---|
| First four only | Whole dataset | 17 of 747 (2%) | 4 of 4,827 |
| Seven | Held-out fifth | 83 of 156 (53%) | 2 of 959 |
| Seven, plus Jev | Held-out fifth | 135 of 156 (87%) | 6 of 959 |
| Twelve, after the South African changes | Held-out fifth | 75 of 156 (48%) | 3 of 959 |
| Twelve, plus Jev with the narrowed questions | Held-out fifth | 104 of 156 (67%) | 7 of 959 |

**Our own South African SMS.** 148 received texts from one phone, masked,
labelled by a team member: 16 scam, 132 not. Marketing counts as not a scam.

| Rules | Caught | False alarms |
|---|---|---|
| Ten, before the changes | 4 of 16 | 30 of 132 |
| Ten, plus Jev | 5 of 16 | 49 of 132 |
| Twelve | 16 of 16 | 3 of 132 |
| Twelve, plus Jev with the narrowed questions | 16 of 16 | 9 of 132 |

What this does and does not show:

- The original rules missed almost everything in the UK data. We only know
  that because we measured.
- **The South African score is not independent.** `job` and `cold_offer`, the
  opt-out and voucher removals and the question wording were all chosen by
  looking at these 148 messages. 16 of 16 shows the rules now describe them;
  it does not show how they do on messages we have not seen. That needs new
  messages, such as the bot's.
- Of the 3 remaining false alarms, one is a labelling mistake (a "work with
  your phone, earn a day" recruitment text marked as not a scam), one is a
  real R1-a-day subscription advert, and one is a price notice quoting cents
  "per min".
- **The trade-off we chose.** Dropping "reply STOP" and lone vouchers cost 8 UK catches,
  because UK spam in this dataset includes paid marketing that ends that way.
  Narrowing Jev's `claim` and `premium` questions cost 27 more UK catches but
  removed 16 false alarms on our own messages. Each change alone removed only
  6 or 7. We kept both because Scam Stop is for South African phones: a
  warning on one in five ordinary texts would teach people to ignore it.
- The question wording was compared on the UCI held-out fifth as well, so
  for the Jev rows that fifth is no longer untouched.
- `MODEL_YES` stayed at 0.7 throughout.

---

## `domain/tools.py`

### The world (lines 24–91)

- **Lines 24–32 `World`** — one object holding all of one person's outside state:
  - `outbox` — warnings shown to the person.
  - `flagged` — senders and domains marked as scammers. Their later messages
    are treated as high risk (see `assess`).
  - `disputes` — company registration number mapped to the dispute text.
  - `blocked` — operators the bank is asked to refuse.
  - `known_senders` (line 31) — senders a human said were fine when a doubtful
    warning about them was held. See `learn_from_review`.
  - `trusted` — merchants the person confirmed as their own. This is the
    agent's memory across incidents.
  - `debits` — for each merchant, the amounts seen so far.
  - `guardian` — whether a caregiver is enrolled. True unless
    `KINGUARD_GUARDIAN=0`, and changeable through the API.
- **Line 36 `_default_world`** — the shared world, used when nobody asks for
  their own: the plain console, offline runs and the older tests.
- **Line 37 `_active_world`** — a `ContextVar` holding the world that is active
  right now. A context variable belongs to the thread or task using it, so two
  people being processed at the same moment each see their own.
- **Lines 40–51 `_ActiveWorld`** — a stand-in that forwards every read and write
  to the active world (47–48, 50–51). It is why the rules and tools below can
  keep writing `WORLD.flagged` without being told whose world they are in.
- **Line 54 `WORLD`** — the stand-in. It always means the world of the person
  being worked on.
- **Lines 57–59 `default_world`** — returns the shared world.
- **Lines 62–69 `use_world`** — a context manager: inside the block `WORLD`
  means the given world, and on leaving it goes back to what it was before
  (65, 69), even if an error was raised.
- **Lines 72–74 `reset_world`** — re-runs the initialiser of the active world,
  emptying it.

- **Lines 77–82 `world_state`** — the world as plain JSON values for saving;
  sets become sorted lists.
- **Lines 85–91 `restore_world`** — put a saved world back, turning the lists
  into sets again.

### Fixture data (lines 95–106)

Stand-ins for registries we cannot query. All names and domains are fictional.

- **Lines 95–98 `DOMAIN_REGISTERED`** — domain to registration date. Used when
  the live lookup is off or has no answer.
- **Lines 101–106 `COMPANIES`** — for each company: `name`, `reg_no`,
  `registered` date, `creditor_code` (the short code its debit references
  start with), and `director` (the person registered as controlling it).
  `TechCare Support` and `PC Care Services` have different names and codes but
  the same director, `D-7781`. That shared director is what makes them one
  operator.

### `DISPUTE_STEPS` (lines 110–115)

Four plain steps for lodging a dispute. They are general on purpose: each
bank's screens differ, and we have not verified any bank's exact menu.

### Date helpers (lines 118–124)

- **118–119 `_days_between`** — days from a registration date to the message.
- **122–124 `_parse_date`** — text to a date-time, assuming UTC if no zone is given.

### `_live_registration` (lines 129–143) — a real lookup

Asks RDAP, the public service that holds domain registration records. Only
the domain name is sent; nothing about the person or the message.

- **131** — split the domain into its `labels` (`mail`, `shop`, `example`).
- **132** — try the full name first, then drop leading labels, so
  `mail.shop.example` falls back to `shop.example`.
- **133–134** — build the request with headers that identify the client.
- **135–137** — send it with a 6-second timeout and read the `events` list.
- **138–139** — a network failure, a "not found", or an unreadable reply moves
  on to the next attempt. Nothing is raised.
- **140–142** — return the date of the `registration` event.
- **143** — nothing found: `None`.

Known limit: some registries, including `.co.za`, do not answer RDAP. Those
domains come back as unknown.

### `domain_age` (lines 146–155)

- **147** — start with no date.
- **148–149** — if `KINGUARD_LIVE_LOOKUPS=1`, try the real lookup.
- **150–151** — **fallback**: if the live lookup is off, failed, or had no
  record, use the fixture table. This is a real tool failing and the agent
  carrying on with a second source.
- **152–153** — still nothing: `ok=False`. The caller must cope with not knowing.
- **154–155** — return the age in days, and say which source answered.

### `_similarity` (lines 158–160)

How alike two names are, from 0 to 1. Both are lower-cased and stripped of
spaces and punctuation first, then compared character by character with
`SequenceMatcher`. `TECHCRE SUP` against `TechCare Support` scores 0.80;
against `PC Care Services` it scores 0.42.

### `merchant_registry` (lines 163–180)

- **164** — `words` are the words of the normalised name.
- **165** — `matches` are companies whose name contains **all** those words
  (`words <= ...` means "is a subset of"). `techcare` matches two companies;
  `techcare support` matches one.
- **166–167** — if a `reference` was given, keep only companies whose
  `creditor_code` starts it.
- **168–172** — **the garbled-name fallback.** If nothing matched and there
  is a reference, look the other way round: take every company whose
  `creditor_code` starts the reference, and keep it only if the name on the
  statement is at least `NAME_SIMILARITY` like the registered name. Banks
  shorten names (`TECHCRE SUP` for TechCare Support), so an exact word match
  is too strict; the creditor code finds the company and the similarity check
  stops an unrelated name from riding on someone else's code.
- **173–174** — none left: fail.
- **175–177** — more than one left: fail as ambiguous, and report how many
  `candidates` there were. That number tells the caller a retry with more
  information is worth trying.
- **178–180** — exactly one: copy it, add `age_days`, return it.

### `identify_operator` (lines 183–188)

Returns the director behind a merchant, or an empty string.

- **185** — look up by name.
- **186–187** — if that failed and there is a reference, retry with it.
- **188** — return the `director` on success.

### `mandate_history` (lines 191–195)

- **192** — `previous` debit amounts from this merchant.
- **193** — `ratio` of this amount to the last one, or `None`.
- **194–195** — report whether it is the first debit and the ratio.

### Action tools — they change the world (lines 200–252)

Every action tool takes the same three arguments (`action`, `incident`,
`report`) and returns a `ToolResult`.

**`warn_person` (200–202)** — puts the message in the outbox.

**`flag_sender` (205–213)** — marks a sender as a scammer.
- **206** — `target` is the sender to mark.
- **207–208** — nothing to mark: fail.
- **209–210** — the target is a shared mail provider: **refuse**, and mark the
  result `protected`. The tool enforces this itself, so it holds even if
  whatever proposed the action got it wrong.
- **211–213** — otherwise add it to `flagged`, warn the person, succeed.
  `flagged` is read back by `assess`, so the sender's later messages count as
  high risk. Nothing outside Scam Stop is blocked.

**`draft_dispute` (216–224)**
- **217–219** — without a registration number the dispute has nobody to be
  addressed to: fail.
- **220–221** — build the dispute text.
- **222–224** — store the dispute as three things: the `text`, the
  `dispute_by` date, and the `steps` to lodge it. Return them, and say the
  deadline in the trace. The agent drafts; the person or caregiver lodges.

**`block_operator` (227–233)**
- **228–230** — without an identified operator there is nothing to block: fail.
- **231** — add the director to `blocked`.
- **232–233** — report every company name that director controls.

**`withdraw` (236–252)** — the rollback.
- **238** — `undone` collects what was reversed.
- **239–241** — look only at actions that actually ran (`EXECUTED`).
- **242–244** — a sender flag is removed from the filter.
- **245–247** — a dispute is removed.
- **248–251** — the merchant is added to `trusted` and that is noted.
- **252** — always succeeds; says "nothing to undo" if that was the case.

### The registry of tools (lines 255–263)

`ACTION_TOOLS` maps each `ActionType` to the function that carries it out.
`ADVISE_DECLINE` uses the same function as `WARN_PERSON`: both deliver a
message to the person, and the message carries the advice.
The engine looks actions up here. An action with no entry cannot run.

### `correct` (lines 266–271)

Given an action that failed and its result, return a corrected action to try
next, or `None` to hand over to a human.

- **268** — the sender address from the message's signals.
- **269–270** — if a `FLAG_SENDER` was refused as `protected`, and there is a
  sender address that has not been tried, return the same action with the
  target narrowed to that one address. `model_copy(update=...)` makes a copy
  with one field changed.
- **271** — any other failure has no known correction.

The rules in `logic.py` already choose the address for a shared provider, so
this path is a second line of defence. It matters when something else
proposes the action, such as a model, and gets the target wrong.

---

## `domain/investigate.py`

### `Finding` (lines 10–15)

One piece of evidence: the `source` tool, the `weight` it adds to the risk,
a `note` in words, and `reassuring` — true when it points towards a
legitimate sender.

### `investigate` (lines 18–58)

Arguments: the `signals` and `when` the message was sent. Returns the list of
findings and the merchant's registry record if it was identified (`company`).

**Domains (lines 23–32)**
- **24–25** — skip shared mail providers; their age says nothing.
- **26** — call `domain_age`.
- **27–28** — unknown: recorded with weight 0.
- **29–30** — younger than `YOUNG_DAYS`: +0.3.
- **31–32** — older: weight 0 and marked reassuring.

**Merchant (lines 34–47)**
- **35** — look the merchant up by name.
- **36–39** — **self-correction.** The lookup failed, either because the name
  was ambiguous or because it matched nothing, and the message has a payment
  reference. Record what went wrong, then look again with the reference. The
  registry then narrows an ambiguous name, or resolves a garbled one through
  the creditor code.
- **40–41** — still not identified: +0.1.
- **42–44** — identified and newly registered: keep the record, +0.25.
- **45–47** — identified and established: keep the record, reassuring.

**Debit history (lines 49–56)**
- **51–52** — first debit ever seen from this merchant: +0.2.
- **53–54** — at least `JUMP_RATIO` times the previous amount: +0.35.
- **55–56** — otherwise reassuring.

An earlier version asked Gemini to guess what a garbled name stood for. On
real calls it was unreliable and followed an instruction planted in a name,
so it was replaced with the creditor-code lookup above, which needs no model.

---

## `domain/language.py`

The only place Gemini is used by Scam Stop: one function, whose output Python
checks before using.

- **Line 13 `PROMPTS`** — the folder holding the prompt files.
- **Lines 16–17 `PersonMessage`** — the shape Gemini must return: one string.

### `write_person_message` (lines 20–26)

- **22** — the prompt is `prompts/person_message.md` plus a list of facts we
  chose. The scam message itself is never included.
- **23** — call Gemini and tidy the whitespace.
- **24–25** — **the safety check.** The message is rejected if it is empty,
  longer than 400 characters, or contains a link, an email address or a phone
  number. A warning that told the person to call a number would be exactly
  what a scammer wants, so the check is in code, not only in the prompt.
- **26** — return the message.

It raises on any failure. The caller catches that and uses the standard
warning instead.

---

## `domain/logic.py`

The functions here are the hooks the engine calls.

### `THREAT_HINTS` (lines 17–20)

One sentence added to the end of a warning for some threat types, telling the
person how that kind of scam usually ends: a job scam ends with a fee or a
request for bank details; a "new number" relative is checked by calling the
old number. A threat type with no entry adds nothing.

### `BLOCK_HOW` (lines 22–26)

Scam Stop cannot block anyone inside WhatsApp, SMS or Gmail: no outside app is
allowed to. So when it marks a sender as a scammer, the warning ends with how
the person blocks them themselves, for the channel the message came on.

### `withhold` (lines 30–34)

Returns a reason to discard a row, or `None`. One-time codes are discarded.

### `parse_record` (lines 37–49)

- **39** — `known` is the set of field names on `RawInputReport`.
- **40** — `record` keeps the row's known fields.
- **41** — `extras` are the row's other columns.
- **42–43** — extras are folded into `metadata`, so nothing is lost.
- **44** — build and validate the report.
- **45** — mask account numbers in the payload.
- **46** — extract the `signals`.
- **47** — add `operator`: the director behind the merchant, from the registry.
- **48–49** — attach the signals and return.

### `_signals` (lines 52–53)

Returns the stored signals, or extracts them for a report that did not come
through `parse_record`.

### `correlation_text` (lines 56–57)

The text used for fuzzy matching: the channel and the payload.

### `context_key` (lines 60–64)

"Who is this message about": an explicit `context` if one was supplied,
otherwise the merchant, otherwise the sender's domain.

### `link_keys` (lines 67–79)

Identifiers that tie messages together. Returns a set of strings.

- **70** — `merchant:<name>`.
- **71–72** — `ref:<reference>`: the full payment reference. The same
  reference means the same mandate.
- **73–74** — `operator:<director>`: two company names with one director link
  here. This is how a scammer who re-registers under a new name is recognised.
- **75** — `phone:<digits>` for each phone number in the message.
- **76** — `domain:<domain>` for each domain, except shared mail providers.
- **77–78** — for a shared mail provider, the full sender address instead.

### `parse_timestamp` (lines 82–99)

Never raises. Tries the standard ISO format, then a few common others.
Returns `None` for anything unreadable. A time with no zone is treated as UTC.
The extra formats are listed on line 27.

### `risk_persists` (lines 102–104)

True while the incident's severity is `HIGH` or `CRITICAL`.

### `review_audience` (lines 107–109)

Who a review is addressed to. `CAREGIVER` when a guardian is enrolled,
otherwise `PERSON`. The engine calls this when it opens a review.

### `_withdrawal` (lines 112–128)

Called when the person says a charge or sender is legitimate.

- **114** — `strong` is true if the incident was `HIGH` or `CRITICAL`.
- **115–116** — the `WITHDRAW` action, naming the incident's merchant.
- **117–120** — strong evidence and a guardian is enrolled: confidence is set
  to 0.5 and a `review_reason` is given. Because 0.5 is below 0.75, the
  guardrails hold the withdrawal for the caregiver. A scammer on the phone can
  tell someone to tap "it's fine"; this is the defence against that.
- **121–125** — strong evidence and **no guardian**: there is nobody else to
  ask, so the decision is slowed down instead. The withdrawal is held for the
  person themselves with `review_delay_seconds` set to the cooling-off period.
  A pressured decision made during a phone call cannot take effect at once.
- **126–128** — otherwise: confidence 0.95, ask for `RESOLVED`, and the
  withdrawal runs automatically.

### `learn_from_review` (lines 131–137)

The engine calls this when a human rejects a review.

- **133–134** — only a rejected warning or sender block teaches anything.
- **135–137** — remember the message's sender in `known_senders`.

The next doubtful message from that sender is then not raised again. It is
learning from the human, in memory, not retraining any rule or model.

### `_kind_wording` (lines 140–147)

- **142–143** — unless `ENABLE_GEMINI=1`, return the standard wording unchanged.
- **144–145** — otherwise ask Gemini to reword it.
- **146–147** — if Gemini fails, or its message fails the safety check, use
  the standard wording.

### `assess` (lines 150–265)

Called once per message. Returns an `Assessment`.

**Gather (151–167)**
- **151** — the message's signals.
- **152–153** — "this is mine" from the person takes the withdrawal path.
- **154–158** — "I did not agree to this" confirms the warning: the incident
  keeps its label, severity and state, and nothing is undone. The person's
  sentence is deliberately not run through the gate. It used to be, the gate
  found nothing suspicious in "The person says they did not agree to this",
  and a confirmed scam was relabelled as safe.
- **160** — `is_debit` and `is_mandate`.
- **161** — `when`: the message's time, or now if it has none.
- **162** — `verdict` from the gate. `ask_jev` is passed only when
  `ENABLE_JEV=1`; otherwise the gate runs on rules alone.
- **163–165** — investigate if it is a debit, a mandate request, or if the
  gate score reached `GATE_THRESHOLD`.
- **166–167** — remember this debit's amount for next time, after the
  investigation, so the debit is not compared with itself.

**Score (169–193)**
- **169** — `price_jump` is true if the history finding carried the jump weight.
- **170** — `trusted`: the person confirmed this merchant, and the price has
  not jumped. Trust does not cover a jump.
- **171** — `risk` is 0 for a trusted merchant; otherwise the gate score plus
  the finding weights, capped at 1.
- **172–174** — `known`: a human already cleared this sender, and the risk is
  below `CONTAIN_THRESHOLD`. Then the risk is set to 0. Strong evidence still
  overrides it, because a sender name can be spoofed.
- **175** — `evidence` is every reason that added risk.
- **176–177** — `shared_provider` (a shared mail provider such as Gmail) and
  `flag_target`: the sender's single address on a shared provider or for SMS
  and WhatsApp, otherwise their domain.
- **178–182** — **memory of scammers.** If this sender was already marked as a
  scammer (and the merchant is not trusted), the risk is raised to at least
  `CONTAIN_THRESHOLD` and the reason is recorded. A follow-up such as "did you
  get my message?" looks innocent on its own; from a known scammer it is not.
- **183** — `established`: the company was identified and is older than
  `YOUNG_DAYS`.
- **184–187** — **the mandate rule.** A request to set up a debit is advised
  against unless the merchant is trusted, or is an established company with
  clean wording. The reason is the DebiCheck rule: once a mandate is approved,
  its debits cannot be disputed. So the agent's most useful moment is before
  approval, and the default there is "do not approve what we cannot verify".
  The risk is raised to at least the threshold and the reason is recorded.
- **188–190** — `threat`: the gate's answer, except that a message with clean
  wording but risky findings is not called benign.
- **191–192** — `labels`: threat, merchant and registration number.
- **193** — `stay`: the state to ask for when nothing should change.

**Benign (195–199)** — below the threshold: `LOW`, no action.

**Suspicious (201–212)**
- **201** — `confidence` starts at 0.55 and rises 0.1 per piece of evidence,
  capped at 0.95. One weak signal gives 0.65, below 0.75, so a human sees it.
- **202–203** — except for a known scammer: the earlier marking was itself a
  confident decision, so their follow-up gets at least 0.85 and the person is
  warned at once instead of the warning waiting for a human.
- **204** — `rationale` lists the evidence, then the gate's notes.
- **205–206** — `conflict`: suspicious wording, but a tool found the sender
  established. That contradiction goes to a human.
- **207–208** — `disputed`: has a dispute for this incident actually been lodged?
- **209** — `who`: a name for the messages. The merchant if there is one;
  otherwise the sender itself for a shared mail provider or an SMS (which has
  no domain), and the sender's domain for other email. Before this, every SMS
  warning said "an unknown sender".
- **210** — defaults: `MEDIUM`, ask for `CONTAINED`.
- **212** — `amount_text`: the amount in words for messages, or "an amount".

**The response ladder (213–258)**
- **213–219** — a mandate request: `ADVISE_DECLINE`. The message tells the
  person who is asking, for how much, and that it is hard to reverse once
  approved. `HIGH` for R300 or more. Nothing is contained, because the choice
  is the person's; the state is `INVESTIGATING`. This action is on the safe
  list, so it is delivered at once without waiting for anyone.
- **220–225** — a debit arrives after a dispute was lodged. The dispute did
  not stop the operator, so escalate to `BLOCK_OPERATOR`, severity `HIGH`. The
  agent learns its earlier action failed from the next message, not from the
  tool. `ask` is the plain question shown to whoever approves.
- **226–232** — a suspicious debit from an identified company:
  `DRAFT_DISPUTE`, `HIGH` if the amount is R300 or more. Line 231 sets
  `dispute_by`: the message date plus `DISPUTE_WINDOW_DAYS`.
- **233–238** — a suspicious debit from an unidentified merchant: only warn
  the person, and ask for a human.
- **239–244** — an unrequested loan, credit or insurance offer
  (`SALES_OFFER`): only warn, `LOW`, whatever the score. The sender may be a
  real bank or insurer, so it is never blocked, even when a second rule pushes
  the risk past `CONTAIN_THRESHOLD`. The warning explains that replying YES
  agrees to a sales call and that these often end in a debit order. This
  branch comes before the containment branch on purpose.
- **245–253** — a suspicious message at or above `CONTAIN_THRESHOLD`:
  `FLAG_SENDER`, `HIGH` for tech-support or identity threats. The target is
  `flag_target`. The warning says the sender has been **marked as a scammer**,
  not blocked, and ends with `BLOCK_HOW` for the message's channel (line 252).
  An earlier version said "We have blocked the sender", which was not true
  for WhatsApp, SMS or Gmail.
- **254–258** — a mildly suspicious message: `WARN_PERSON`, `LOW`.

Every action on the ladder carries `ask`: a plain question for whoever has
to approve it, the caregiver or, with no guardian, the person. It was added
after the first real sync held a warning whose only explanation was
"Confidence below 0.75". The question never goes to a model.

**Finish (260–265)**
- **260–261** — if the action carries a message for the person, add the
  threat's hint from `THREAT_HINTS`, then pass it through `_kind_wording`.
- **262–263** — a resolved incident that receives new suspicious evidence is
  asked to reopen.
- **264–265** — return the assessment.

### What this file does not do

It never runs a tool that changes anything, never sets an incident's state,
and never decides whether a human is needed. It proposes. The engine decides.

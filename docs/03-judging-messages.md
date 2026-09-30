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

### `TEXT_RULES` (lines 18–40)

A dictionary. Each entry has a short `key` and three values: the `reason`
written into the trace, the `weight` added to the score, and the `pattern`
that triggers it.

| Lines | Key | What it catches | Weight |
|---|---|---|---|
| 19–20 | `urgency` | Urgent or threatening wording | 0.25 |
| 21–22 | `credentials` | A verb, then `your`, then PIN, password, card or details; or a remote-access tool name. It does not fire on a bank saying "never share your PIN" | 0.35 |
| 23–24 | `payment` | Gift cards, vouchers, crypto | 0.35 |
| 25–26 | `subscription` | Subscription and renewal words. Weak alone, because honest messages use them too | 0.15 |
| 27–28 | `prize` | "You have won", winner, prize, awarded, guaranteed, been selected | 0.3 |
| 29–30 | `claim` | "To claim", "call now", "text WORD to 12345" | 0.3 |
| 31–33 | `premium` | Pence or rand per message, minute, day or week; "reply STOP"; premium-rate number ranges | 0.3 |
| 34–35 | `impersonation` | "This is my new number", "lost my phone": someone claiming to be a relative or friend. Weak alone, because honest people change numbers too | 0.2 |
| 36–37 | `money` | Asks the reader to send, transfer or deposit money | 0.3 |
| 38–39 | `advance_fee` | Inheritance, unclaimed parcel, release or clearance fee, lottery | 0.3 |

The first four rules were written from knowledge of scams. The next three
were written after measuring: see "How the rules were measured" below. The
last three cover impersonation and advance-fee scams. The SMS dataset has
almost none of those, so it could only tell us whether they cause false
alarms. The first version did (two extra on the held-out set), so
`impersonation` was weakened to 0.2 and one loose word was removed; after
that the false alarms were back to two. How many real scams these three
catch is not measured.

### `TECH_SUPPORT_PATTERN` (line 41)

Words that suggest a tech-support scam. Used only to name the threat type.

### `MODEL_QUESTIONS` (lines 44–65)

The questions sent to Jev. Jev does not write text; it answers typed
questions about a piece of content.

- **Lines 45–54** — ten `noul` questions with the **same keys** as
  `TEXT_RULES`. A Noul is a yes/no question; the answer is the probability,
  from 0 to 1, that the statement is true. Each asks one narrow thing, which
  is how the Jev documentation says to use it.
- **Lines 55–64** — one `choice` question, `threat`. Its `criteria` are the
  eight `ThreatDomain` values, each with a description. The answer is the
  chosen option and a confidence.

### `ask_jev` (lines 68–70)

Calls the Jev client with the message as the state and `MODEL_QUESTIONS` as
the questions. Only the masked message text is sent.

### `GateVerdict` (lines 73–78)

- `score` — 0 to 1.
- `reasons` — the findings that added to the score.
- `threat` — the threat type.
- `notes` — remarks that did not change the score, such as "the model was
  unavailable". They are kept separate so they cannot inflate confidence.

### `gate` (lines 81–133)

Arguments: the message `text`, its `signals`, and an optional `ask_model`
function.

**Rules (83–97)**
- **83** — start: `score` 0, no `reasons`, `hits` (the set of keys that
  matched) empty, no `notes`.
- **84–88** — for every rule whose pattern is found, add its weight, record
  its reason, and remember its key in `hits`.
- **89–91** — replies go to a different domain than the sender: +0.2.
- **92–94** — the mail provider's authentication failed: +0.25.
- **95–97** — a link shows one address and leads to another: +0.3.

**Decision model (99–112)**
- **99** — `model_threat` starts as `None`.
- **100** — only runs if a model function was supplied.
- **102** — ask the model once; `answers` holds every question's answer.
- **103–108** — for each judgement: read the probability. If the key is **not**
  already in `hits` and the probability is at least `MODEL_YES`, add the same
  weight, record the reason marked as coming from the model, and add the key.
- **109–110** — use the model's threat type only if its confidence is at least
  `MODEL_THREAT_CONFIDENCE`. `ThreatDomain(...)` fails if the model returns a
  value outside the enum, which lands in the `except`.
- **111–112** — any failure (no key, network, bad reply) becomes a note. The
  rule score already computed is untouched.
- **113** — cap the score at 1.0.

Three properties to remember:

1. **The model can only add.** A rule that fired is never removed, and a
   judgement is never counted twice.
2. **The model never decides.** It answers narrow questions; the weights and
   the threshold are in our code.
3. **The gate works without it.**

**Naming the threat (115–132)**
- **115–116** — score 0: `BENIGN`.
- **117–118** — a confident model answer other than benign is used.
- **119–120** — tech-support words: `TECH_SUPPORT_SCAM`.
- **121–122** — a credentials hit: `IDENTITY_FARMING`.
- **123–124** — an impersonation hit: `IMPERSONATION`.
- **125–126** — an advance-fee hit: `ADVANCE_FEE`.
- **127–128** — a prize hit: `PRIZE_SCAM`.
- **129–130** — a debit, or a subscription or premium hit:
  `GREY_MARKET_SUBSCRIPTION`. `hits & {...}` is the overlap of two sets.
- **131–132** — otherwise `UNKNOWN`.
- **133** — return the verdict.

Why a prompt injection fails here: the rules only search for patterns, and
the model is asked fixed questions about the text, not given the text as
instructions. Even if a message swayed the model, the model cannot lower the
score.

### How the rules were measured

Dataset: the UCI SMS Spam Collection, 5,574 SMS labelled spam or not by its
authors. Every fifth message was held out; rules were written looking only at
the other four fifths.

| Rules | Measured on | Caught | False alarms | Missed |
|---|---|---|---|---|
| First four only | Whole dataset, threshold 0.30 | 17 of 747 (2%) | 4 of 4,827 | 730 |
| All seven | Held-out fifth, threshold 0.30 | 83 of 156 (53%) | 2 of 959 | 73 |
| All seven, plus Jev | Held-out fifth, threshold 0.30 | 135 of 156 (87%) | 6 of 959 | 21 |

What this does and does not show:

- The original rules missed almost everything in this data. We only know
  that because we measured.
- The rules now catch about half, with very few false alarms.
- Adding Jev (real calls, about 0.4 seconds each) lifts that to 87% and adds
  four false alarms. The model earns its place: it recognises wording the
  patterns cannot list in advance.
- `MODEL_YES` stayed at 0.7 throughout. It was not tuned on the held-out
  messages, because a threshold tuned on the test set proves nothing.
- The data is general SMS spam from the UK, collected years ago. It is a
  stand-in. It says nothing about debit-order messages or South African
  wording; the rand and "reply STOP" patterns are untested.

---

## `domain/tools.py`

### The world (lines 22–37)

- **Lines 22–29 `World`** — one object holding all outside state:
  - `outbox` — warnings shown to the person.
  - `flagged` — senders and domains the mail filter blocks.
  - `disputes` — company registration number mapped to the dispute text.
  - `blocked` — operators the bank is asked to refuse.
  - `trusted` — merchants the person confirmed as their own. This is the
    agent's memory across incidents.
  - `debits` — for each merchant, the amounts seen so far.
  - `guardian` — whether a caregiver is enrolled. True unless
    `KINGUARD_GUARDIAN=0`, and changeable through the API.
- **Line 33 `WORLD`** — the single shared instance.
- **Lines 36–37 `reset_world`** — re-runs the initialiser, emptying everything.

### Fixture data (lines 41–61)

Stand-ins for registries we cannot query. All names and domains are fictional.

- **Lines 41–44 `DOMAIN_REGISTERED`** — domain to registration date. Used when
  the live lookup is off or has no answer.
- **Lines 47–61 `COMPANIES`** — for each company: `name`, `reg_no`,
  `registered` date, `creditor_code` (the short code its debit references
  start with), and `director` (the person registered as controlling it).
  `TechCare Support` and `PC Care Services` have different names and codes but
  the same director, `D-7781`. That shared director is what makes them one
  operator.

### `DISPUTE_STEPS` (lines 56–61)

Four plain steps for lodging a dispute. They are general on purpose: each
bank's screens differ, and we have not verified any bank's exact menu.

### Date helpers (lines 64–70)

- **64–65 `_days_between`** — days from a registration date to the message.
- **68–70 `_parse_date`** — text to a date-time, assuming UTC if no zone is given.

### `_live_registration` (lines 75–89) — a real lookup

Asks RDAP, the public service that holds domain registration records. Only
the domain name is sent; nothing about the person or the message.

- **77** — split the domain into its `labels` (`mail`, `shop`, `example`).
- **78** — try the full name first, then drop leading labels, so
  `mail.shop.example` falls back to `shop.example`.
- **79–80** — build the request with headers that identify the client.
- **81–83** — send it with a 6-second timeout and read the `events` list.
- **84–85** — a network failure, a "not found", or an unreadable reply moves
  on to the next attempt. Nothing is raised.
- **86–88** — return the date of the `registration` event.
- **89** — nothing found: `None`.

Known limit: some registries, including `.co.za`, do not answer RDAP. Those
domains come back as unknown.

### `domain_age` (lines 92–101)

- **93** — start with no date.
- **94–95** — if `KINGUARD_LIVE_LOOKUPS=1`, try the real lookup.
- **96–97** — **fallback**: if the live lookup is off, failed, or had no
  record, use the fixture table. This is a real tool failing and the agent
  carrying on with a second source.
- **98–99** — still nothing: `ok=False`. The caller must cope with not knowing.
- **100–101** — return the age in days, and say which source answered.

### `_similarity` (lines 104–106)

How alike two names are, from 0 to 1. Both are lower-cased and stripped of
spaces and punctuation first, then compared character by character with
`SequenceMatcher`. `TECHCRE SUP` against `TechCare Support` scores 0.80;
against `PC Care Services` it scores 0.42.

### `merchant_registry` (lines 109–126)

- **110** — `words` are the words of the normalised name.
- **111** — `matches` are companies whose name contains **all** those words
  (`words <= ...` means "is a subset of"). `techcare` matches two companies;
  `techcare support` matches one.
- **112–113** — if a `reference` was given, keep only companies whose
  `creditor_code` starts it.
- **114–118** — **the garbled-name fallback.** If nothing matched and there
  is a reference, look the other way round: take every company whose
  `creditor_code` starts the reference, and keep it only if the name on the
  statement is at least `NAME_SIMILARITY` like the registered name. Banks
  shorten names (`TECHCRE SUP` for TechCare Support), so an exact word match
  is too strict; the creditor code finds the company and the similarity check
  stops an unrelated name from riding on someone else's code.
- **119–120** — none left: fail.
- **121–123** — more than one left: fail as ambiguous, and report how many
  `candidates` there were. That number tells the caller a retry with more
  information is worth trying.
- **124–126** — exactly one: copy it, add `age_days`, return it.

### `identify_operator` (lines 129–134)

Returns the director behind a merchant, or an empty string.

- **131** — look up by name.
- **132–133** — if that failed and there is a reference, retry with it.
- **134** — return the `director` on success.

### `mandate_history` (lines 137–141)

- **138** — `previous` debit amounts from this merchant.
- **139** — `ratio` of this amount to the last one, or `None`.
- **140–141** — report whether it is the first debit and the ratio.

### Action tools — they change the world (lines 146–198)

Every action tool takes the same three arguments (`action`, `incident`,
`report`) and returns a `ToolResult`.

**`warn_person` (146–148)** — puts the message in the outbox.

**`flag_sender` (151–159)**
- **152** — `target` is what to block.
- **153–154** — nothing to block: fail.
- **155–156** — the target is a shared mail provider: **refuse**, and mark the
  result `protected`. The tool enforces this itself, so it holds even if
  whatever proposed the action got it wrong.
- **157–159** — otherwise add it to the filter, warn the person, succeed.

**`draft_dispute` (162–169)**
- **163–165** — without a registration number the dispute has nobody to be
  addressed to: fail.
- **166–167** — build the dispute text.
- **168–170** — store the dispute as three things: the `text`, the
  `dispute_by` date, and the `steps` to lodge it. Return them, and say the
  deadline in the trace. The agent drafts; the person or caregiver lodges.

**`block_operator` (173–179)**
- **174–176** — without an identified operator there is nothing to block: fail.
- **177** — add the director to `blocked`.
- **178–179** — report every company name that director controls.

**`withdraw` (182–198)** — the rollback.
- **184** — `undone` collects what was reversed.
- **185–187** — look only at actions that actually ran (`EXECUTED`).
- **188–190** — a sender flag is removed from the filter.
- **191–193** — a dispute is removed.
- **194–197** — the merchant is added to `trusted` and that is noted.
- **198** — always succeeds; says "nothing to undo" if that was the case.

### The registry of tools (lines 201–209)

`ACTION_TOOLS` maps each `ActionType` to the function that carries it out.
`ADVISE_DECLINE` uses the same function as `WARN_PERSON`: both deliver a
message to the person, and the message carries the advice.
The engine looks actions up here. An action with no entry cannot run.

### `correct` (lines 212–217)

Given an action that failed and its result, return a corrected action to try
next, or `None` to hand over to a human.

- **214** — the sender address from the message's signals.
- **215–216** — if a `FLAG_SENDER` was refused as `protected`, and there is a
  sender address that has not been tried, return the same action with the
  target narrowed to that one address. `model_copy(update=...)` makes a copy
  with one field changed.
- **217** — any other failure has no known correction.

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

The only place Gemini is used by KinGuard: one function, whose output Python
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

### `withhold` (lines 19–23)

Returns a reason to discard a row, or `None`. One-time codes are discarded.

### `parse_record` (lines 26–38)

- **28** — `known` is the set of field names on `RawInputReport`.
- **29** — `record` keeps the row's known fields.
- **30** — `extras` are the row's other columns.
- **31–32** — extras are folded into `metadata`, so nothing is lost.
- **33** — build and validate the report.
- **34** — mask account numbers in the payload.
- **35** — extract the `signals`.
- **36** — add `operator`: the director behind the merchant, from the registry.
- **37–38** — attach the signals and return.

### `_signals` (lines 41–42)

Returns the stored signals, or extracts them for a report that did not come
through `parse_record`.

### `correlation_text` (lines 45–46)

The text used for fuzzy matching: the channel and the payload.

### `context_key` (lines 49–53)

"Who is this message about": an explicit `context` if one was supplied,
otherwise the merchant, otherwise the sender's domain.

### `link_keys` (lines 56–68)

Identifiers that tie messages together. Returns a set of strings.

- **59** — `merchant:<name>`.
- **60–61** — `ref:<reference>`: the full payment reference. The same
  reference means the same mandate.
- **62–63** — `operator:<director>`: two company names with one director link
  here. This is how a scammer who re-registers under a new name is recognised.
- **64** — `phone:<digits>` for each phone number in the message.
- **65** — `domain:<domain>` for each domain, except shared mail providers.
- **66–67** — for a shared mail provider, the full sender address instead.

### `parse_timestamp` (lines 71–88)

Never raises. Tries the standard ISO format, then a few common others.
Returns `None` for anything unreadable. A time with no zone is treated as UTC.
The extra formats are listed on line 16.

### `risk_persists` (lines 91–93)

True while the incident's severity is `HIGH` or `CRITICAL`.

### `review_audience` (lines 96–98)

Who a review is addressed to. `CAREGIVER` when a guardian is enrolled,
otherwise `PERSON`. The engine calls this when it opens a review.

### `_withdrawal` (lines 101–117)

Called when the person says a charge or sender is legitimate.

- **103** — `strong` is true if the incident was `HIGH` or `CRITICAL`.
- **104–105** — the `WITHDRAW` action, naming the incident's merchant.
- **106–109** — strong evidence and a guardian is enrolled: confidence is set
  to 0.5 and a `review_reason` is given. Because 0.5 is below 0.75, the
  guardrails hold the withdrawal for the caregiver. A scammer on the phone can
  tell someone to tap "it's fine"; this is the defence against that.
- **110–114** — strong evidence and **no guardian**: there is nobody else to
  ask, so the decision is slowed down instead. The withdrawal is held for the
  person themselves with `review_delay_seconds` set to the cooling-off period.
  A pressured decision made during a phone call cannot take effect at once.
- **115–117** — otherwise: confidence 0.95, ask for `RESOLVED`, and the
  withdrawal runs automatically.

### `_kind_wording` (lines 120–127)

- **122–123** — unless `ENABLE_GEMINI=1`, return the standard wording unchanged.
- **124–125** — otherwise ask Gemini to reword it.
- **126–127** — if Gemini fails, or its message fails the safety check, use
  the standard wording.

### `assess` (lines 130–217)

Called once per message. Returns an `Assessment`.

**Gather (131–142)**
- **131** — the message's signals.
- **132–133** — feedback from the person takes the withdrawal path.
- **135** — `is_debit` and `is_mandate`.
- **136** — `when`: the message's time, or now if it has none.
- **137** — `verdict` from the gate. `ask_jev` is passed only when
  `ENABLE_JEV=1`; otherwise the gate runs on rules alone.
- **138–140** — investigate if it is a debit, a mandate request, or if the
  gate score reached `GATE_THRESHOLD`.
- **141–142** — remember this debit's amount for next time, after the
  investigation, so the debit is not compared with itself.

**Score (144–158)**
- **144** — `price_jump` is true if the history finding carried the jump weight.
- **145** — `trusted`: the person confirmed this merchant, and the price has
  not jumped. Trust does not cover a jump.
- **146** — `risk` is 0 for a trusted merchant; otherwise the gate score plus
  the finding weights, capped at 1.
- **147** — `evidence` is every reason that added risk.
- **148** — `established`: the company was identified and is older than
  `YOUNG_DAYS`.
- **149–152** — **the mandate rule.** A request to set up a debit is advised
  against unless the merchant is trusted, or is an established company with
  clean wording. The reason is the DebiCheck rule: once a mandate is approved,
  its debits cannot be disputed. So the agent's most useful moment is before
  approval, and the default there is "do not approve what we cannot verify".
  The risk is raised to at least the threshold and the reason is recorded.
- **153–155** — `threat`: the gate's answer, except that a message with clean
  wording but risky findings is not called benign.
- **156–157** — `labels`: threat, merchant and registration number.
- **158** — `stay`: the state to ask for when nothing should change.

**Benign (160–163)** — below the threshold: `LOW`, no action.

**Suspicious (165–175)**
- **165** — `confidence` starts at 0.55 and rises 0.1 per piece of evidence,
  capped at 0.95. One weak signal gives 0.65, below 0.75, so a human sees it.
- **166** — `rationale` lists the evidence, then the gate's notes.
- **167–168** — `conflict`: suspicious wording, but a tool found the sender
  established. That contradiction goes to a human.
- **169–170** — `disputed`: has a dispute for this incident actually been lodged?
- **171** — `shared_provider`: is the sender on a shared mail provider?
- **172** — `who`: a name for the messages.
- **173** — defaults: `MEDIUM`, ask for `CONTAINED`.
- **175** — `amount_text`: the amount in words for messages, or "an amount".

**The response ladder (176–210)**
- **176–182** — a mandate request: `ADVISE_DECLINE`. The message tells the
  person who is asking, for how much, and that it is hard to reverse once
  approved. `HIGH` for R300 or more. Nothing is contained, because the choice
  is the person's; the state is `INVESTIGATING`. This action is on the safe
  list, so it is delivered at once without waiting for anyone.
- **183–188** — a debit arrives after a dispute was lodged. The dispute did
  not stop the operator, so escalate to `BLOCK_OPERATOR`, severity `HIGH`. The
  agent learns its earlier action failed from the next message, not from the
  tool. `ask` is the plain question shown to whoever approves.
- **189–195** — a suspicious debit from an identified company:
  `DRAFT_DISPUTE`, `HIGH` if the amount is R300 or more. Line 194 sets
  `dispute_by`: the message date plus `DISPUTE_WINDOW_DAYS`.
- **196–200** — a suspicious debit from an unidentified merchant: only warn
  the person, and ask for a human.
- **201–206** — a suspicious message at or above `CONTAIN_THRESHOLD`:
  `FLAG_SENDER`, `HIGH` for tech-support or identity threats. The target is
  the single address for a shared provider, otherwise the whole domain.
- **207–210** — a mildly suspicious message: `WARN_PERSON`, `LOW`.

**Finish (212–217)**
- **212–213** — if the action carries a message for the person, pass it
  through `_kind_wording`.
- **214–215** — a resolved incident that receives new suspicious evidence is
  asked to reopen.
- **216–217** — return the assessment.

### What this file does not do

It never runs a tool that changes anything, never sets an incident's state,
and never decides whether a human is needed. It proposes. The engine decides.

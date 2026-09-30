# 3. Judging messages

Five files decide what a message means and what to do about it:

1. `domain/gate.py` — a fast first look, with rules and an optional decision model (Jev).
2. `domain/tools.py` — the tools, and the outside world they act on.
3. `domain/investigate.py` — calls the read-only tools to gather evidence.
4. `domain/language.py` — the two language jobs given to Gemini.
5. `domain/logic.py` — puts it together and produces an `Assessment`.

Who does what: **Jev** answers narrow yes/no questions quickly. **Gemini**
handles language: guessing what a garbled name stands for, and wording a
warning. **Python** makes every decision.

The output is only a **proposal**. Whether it happens is decided in
`04-engine.md`.

---

## `domain/gate.py`

A cheap score from 0 to 1. Most messages are harmless, so they should stop
here without any tool being called.

**Lines 11–13** — imports the Jev client, the threat enum, and two thresholds
from policy.

### `TEXT_RULES` (lines 18–34)

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

The first four rules were written from knowledge of scams. The last three
were written after measuring: see "How the rules were measured" below.

### `TECH_SUPPORT_PATTERN` (line 35)

Words that suggest a tech-support scam. Used only to name the threat type.

### `MODEL_QUESTIONS` (lines 38–54)

The questions sent to Jev. Jev does not write text; it answers typed
questions about a piece of content.

- **Lines 39–45** — seven `noul` questions with the **same keys** as
  `TEXT_RULES`. A Noul is a yes/no question; the answer is the probability,
  from 0 to 1, that the statement is true. Each asks one narrow thing, which
  is how the Jev documentation says to use it.
- **Lines 46–53** — one `choice` question, `threat`. Its `criteria` are the
  six `ThreatDomain` values, each with a description. The answer is the
  chosen option and a confidence.

### `ask_jev` (lines 57–59)

Calls the Jev client with the message as the state and `MODEL_QUESTIONS` as
the questions. Only the masked message text is sent.

### `GateVerdict` (lines 62–67)

- `score` — 0 to 1.
- `reasons` — the findings that added to the score.
- `threat` — the threat type.
- `notes` — remarks that did not change the score, such as "the model was
  unavailable". They are kept separate so they cannot inflate confidence.

### `gate` (lines 70–118)

Arguments: the message `text`, its `signals`, and an optional `ask_model`
function.

**Rules (72–86)**
- **72** — start: `score` 0, no `reasons`, `hits` (the set of keys that
  matched) empty, no `notes`.
- **73–77** — for every rule whose pattern is found, add its weight, record
  its reason, and remember its key in `hits`.
- **78–80** — replies go to a different domain than the sender: +0.2.
- **81–83** — the mail provider's authentication failed: +0.25.
- **84–86** — a link shows one address and leads to another: +0.3.

**Decision model (88–101)**
- **88** — `model_threat` starts as `None`.
- **89** — only runs if a model function was supplied.
- **91** — ask the model once; `answers` holds every question's answer.
- **92–97** — for each judgement: read the probability. If the key is **not**
  already in `hits` and the probability is at least `MODEL_YES`, add the same
  weight, record the reason marked as coming from the model, and add the key.
- **98–99** — use the model's threat type only if its confidence is at least
  `MODEL_THREAT_CONFIDENCE`. `ThreatDomain(...)` fails if the model returns a
  value outside the enum, which lands in the `except`.
- **100–101** — any failure (no key, network, bad reply) becomes a note. The
  rule score already computed is untouched.
- **102** — cap the score at 1.0.

Three properties to remember:

1. **The model can only add.** A rule that fired is never removed, and a
   judgement is never counted twice.
2. **The model never decides.** It answers narrow questions; the weights and
   the threshold are in our code.
3. **The gate works without it.**

**Naming the threat (104–117)**
- **104–105** — score 0: `BENIGN`.
- **106–107** — a confident model answer other than benign is used.
- **108–109** — tech-support words: `TECH_SUPPORT_SCAM`.
- **110–111** — a credentials hit: `IDENTITY_FARMING`.
- **112–113** — a prize hit: `PRIZE_SCAM`.
- **114–115** — a debit, or a subscription or premium hit:
  `GREY_MARKET_SUBSCRIPTION`. `hits & {...}` is the overlap of two sets.
- **116–117** — otherwise `UNKNOWN`.
- **118** — return the verdict.

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

### The world (lines 21–35)

- **Lines 21–28 `World`** — one object holding all outside state:
  - `outbox` — warnings shown to the person.
  - `flagged` — senders and domains the mail filter blocks.
  - `disputes` — company registration number mapped to the dispute text.
  - `blocked` — operators the bank is asked to refuse.
  - `trusted` — merchants the person confirmed as their own. This is the
    agent's memory across incidents.
  - `debits` — for each merchant, the amounts seen so far.
- **Line 31 `WORLD`** — the single shared instance.
- **Lines 34–35 `reset_world`** — re-runs the initialiser, emptying everything.

### Fixture data (lines 39–50)

Stand-ins for registries we cannot query. All names and domains are fictional.

- **Lines 39–42 `DOMAIN_REGISTERED`** — domain to registration date. Used when
  the live lookup is off or has no answer.
- **Lines 45–50 `COMPANIES`** — for each company: `name`, `reg_no`,
  `registered` date, `creditor_code` (the short code its debit references
  start with), and `director` (the person registered as controlling it).
  `TechCare Support` and `PC Care Services` have different names and codes but
  the same director, `D-7781`. That shared director is what makes them one
  operator.

### Date helpers (lines 53–59)

- **53–54 `_days_between`** — days from a registration date to the message.
- **57–59 `_parse_date`** — text to a date-time, assuming UTC if no zone is given.

### `_live_registration` (lines 64–78) — a real lookup

Asks RDAP, the public service that holds domain registration records. Only
the domain name is sent; nothing about the person or the message.

- **66** — split the domain into its `labels` (`mail`, `shop`, `example`).
- **67** — try the full name first, then drop leading labels, so
  `mail.shop.example` falls back to `shop.example`.
- **68–69** — build the request with headers that identify the client.
- **70–72** — send it with a 6-second timeout and read the `events` list.
- **73–74** — a network failure, a "not found", or an unreadable reply moves
  on to the next attempt. Nothing is raised.
- **75–77** — return the date of the `registration` event.
- **78** — nothing found: `None`.

Known limit: some registries, including `.co.za`, do not answer RDAP. Those
domains come back as unknown.

### `domain_age` (lines 81–90)

- **82** — start with no date.
- **83–84** — if `KINGUARD_LIVE_LOOKUPS=1`, try the real lookup.
- **85–86** — **fallback**: if the live lookup is off, failed, or had no
  record, use the fixture table. This is a real tool failing and the agent
  carrying on with a second source.
- **87–88** — still nothing: `ok=False`. The caller must cope with not knowing.
- **89–90** — return the age in days, and say which source answered.

### `merchant_registry` (lines 93–105)

- **94** — `words` are the words of the normalised name.
- **95** — `matches` are companies whose name contains **all** those words
  (`words <= ...` means "is a subset of"). `techcare` matches two companies;
  `techcare support` matches one.
- **96–97** — if a `reference` was given, keep only companies whose
  `creditor_code` starts it.
- **98–99** — none left: fail.
- **100–102** — more than one left: fail as ambiguous, and report how many
  `candidates` there were. That number tells the caller a retry with more
  information is worth trying.
- **103–105** — exactly one: copy it, add `age_days`, return it.

### `identify_operator` (lines 108–113)

Returns the director behind a merchant, or an empty string.

- **110** — look up by name.
- **111–112** — if that failed and there is a reference, retry with it.
- **113** — return the `director` on success.

### `mandate_history` (lines 116–120)

- **117** — `previous` debit amounts from this merchant.
- **118** — `ratio` of this amount to the last one, or `None`.
- **119–120** — report whether it is the first debit and the ratio.

### Action tools — they change the world (lines 125–176)

Every action tool takes the same three arguments (`action`, `incident`,
`report`) and returns a `ToolResult`.

**`warn_person` (125–127)** — puts the message in the outbox.

**`flag_sender` (130–138)**
- **131** — `target` is what to block.
- **132–133** — nothing to block: fail.
- **134–135** — the target is a shared mail provider: **refuse**, and mark the
  result `protected`. The tool enforces this itself, so it holds even if
  whatever proposed the action got it wrong.
- **136–138** — otherwise add it to the filter, warn the person, succeed.

**`draft_dispute` (141–148)**
- **142–144** — without a registration number the dispute has nobody to be
  addressed to: fail.
- **145–146** — build the dispute text.
- **147–148** — store it and succeed.

**`block_operator` (151–157)**
- **152–154** — without an identified operator there is nothing to block: fail.
- **155** — add the director to `blocked`.
- **156–157** — report every company name that director controls.

**`withdraw` (160–176)** — the rollback.
- **162** — `undone` collects what was reversed.
- **163–165** — look only at actions that actually ran (`EXECUTED`).
- **166–168** — a sender flag is removed from the filter.
- **169–171** — a dispute is removed.
- **172–175** — the merchant is added to `trusted` and that is noted.
- **176** — always succeeds; says "nothing to undo" if that was the case.

### The registry of tools (lines 179–186)

`ACTION_TOOLS` maps each `ActionType` to the function that carries it out.
The engine looks actions up here. An action with no entry cannot run.

### `correct` (lines 189–194)

Given an action that failed and its result, return a corrected action to try
next, or `None` to hand over to a human.

- **191** — the sender address from the message's signals.
- **192–193** — if a `FLAG_SENDER` was refused as `protected`, and there is a
  sender address that has not been tried, return the same action with the
  target narrowed to that one address. `model_copy(update=...)` makes a copy
  with one field changed.
- **194** — any other failure has no known correction.

The rules in `logic.py` already choose the address for a shared provider, so
this path is a second line of defence. It matters when something else
proposes the action, such as a model, and gets the target wrong.

---

## `domain/investigate.py`

### `Finding` (lines 10–15)

One piece of evidence: the `source` tool, the `weight` it adds to the risk,
a `note` in words, and `reassuring` — true when it points towards a
legitimate sender.

### `investigate` (lines 18–70)

Arguments: the `signals`, `when` the message was sent, and an optional
`suggest_names` function (Gemini). Returns the list of findings and the
merchant's registry record if it was identified (`company`).

**Domains (lines 24–33)**
- **25–26** — skip shared mail providers; their age says nothing.
- **27** — call `domain_age`.
- **28–29** — unknown: recorded with weight 0.
- **30–31** — younger than `YOUNG_DAYS`: +0.3.
- **32–33** — older: weight 0 and marked reassuring.

**Merchant (lines 35–59)**
- **36** — look the merchant up by name.
- **37–40** — **self-correction, first kind.** The lookup failed because the
  name was ambiguous (`candidates` is set) and the message has a payment
  reference: record that, and look up again with the reference.
- **41–51** — **self-correction, second kind.** The name matched nothing at
  all, there is a reference, and a language model is available:
  - **44** — ask the model what the garbled name could stand for.
  - **45** — look each suggestion up **together with the reference**.
  - **46–49** — accept the first suggestion the registry confirms, record how
    it was resolved, and stop.
  - **50–51** — if the model fails, note it and carry on.

  The guess is never trusted by itself. A suggestion counts only if a real
  company exists with that name **and** its creditor code matches the payment
  reference. A wrong or manipulated guess simply finds nothing.
- **52–53** — still not identified: +0.1.
- **54–56** — identified and newly registered: keep the record, +0.25.
- **57–59** — identified and established: keep the record, reassuring.

**Debit history (lines 61–68)**
- **63–64** — first debit ever seen from this merchant: +0.2.
- **65–66** — at least `JUMP_RATIO` times the previous amount: +0.35.
- **67–68** — otherwise reassuring.

---

## `domain/language.py`

The only place Gemini is used by KinGuard. Two functions; both return text
that Python checks before using.

- **Line 14 `PROMPTS`** — the folder holding the prompt files.
- **Lines 17–18 `NameSuggestions`** — the shape Gemini must return for names:
  a list of strings.
- **Lines 21–22 `PersonMessage`** — the shape for a warning: one string.

### `suggest_merchant_names` (lines 25–28)

- **27** — the prompt is the instructions in `prompts/merchant_names.md` plus
  the descriptor. `{descriptor!r}` writes it in quotes so it reads as data.
- **28** — call Gemini, strip each name, drop empty ones, keep at most three.

### `write_person_message` (lines 31–37)

- **33** — the prompt is `prompts/person_message.md` plus a list of facts we
  chose. The scam message itself is never included.
- **34** — call Gemini and tidy the whitespace.
- **35–36** — **the safety check.** The message is rejected if it is empty,
  longer than 400 characters, or contains a link, an email address or a phone
  number. A warning that told the person to call a number would be exactly
  what a scammer wants, so the check is in code, not only in the prompt.
- **37** — return the message.

Both raise on any failure. Their callers catch that and fall back: the
investigation carries on without suggestions, and the standard warning is used.

---

## `domain/logic.py`

The functions here are the hooks the engine calls.

### `withhold` (lines 18–22)

Returns a reason to discard a row, or `None`. One-time codes are discarded.

### `parse_record` (lines 25–37)

- **27** — `known` is the set of field names on `RawInputReport`.
- **28** — `record` keeps the row's known fields.
- **29** — `extras` are the row's other columns.
- **30–31** — extras are folded into `metadata`, so nothing is lost.
- **32** — build and validate the report.
- **33** — mask account numbers in the payload.
- **34** — extract the `signals`.
- **35** — add `operator`: the director behind the merchant, from the registry.
- **36–37** — attach the signals and return.

### `_signals` (lines 40–41)

Returns the stored signals, or extracts them for a report that did not come
through `parse_record`.

### `correlation_text` (lines 44–45)

The text used for fuzzy matching: the channel and the payload.

### `context_key` (lines 48–52)

"Who is this message about": an explicit `context` if one was supplied,
otherwise the merchant, otherwise the sender's domain.

### `link_keys` (lines 55–67)

Identifiers that tie messages together. Returns a set of strings.

- **58** — `merchant:<name>`.
- **59–60** — `ref:<reference>`: the full payment reference. The same
  reference means the same mandate.
- **61–62** — `operator:<director>`: two company names with one director link
  here. This is how a scammer who re-registers under a new name is recognised.
- **63** — `phone:<digits>` for each phone number in the message.
- **64** — `domain:<domain>` for each domain, except shared mail providers.
- **65–66** — for a shared mail provider, the full sender address instead.

### `parse_timestamp` (lines 70–87)

Never raises. Tries the standard ISO format, then a few common others.
Returns `None` for anything unreadable. A time with no zone is treated as UTC.
The extra formats are listed on line 15.

### `risk_persists` (lines 90–92)

True while the incident's severity is `HIGH` or `CRITICAL`.

### `_withdrawal` (lines 95–106)

Called when the person says a charge or sender is legitimate.

- **97** — `strong` is true if the incident was `HIGH` or `CRITICAL`.
- **98–99** — the `WITHDRAW` action, naming the incident's merchant.
- **100–103** — strong evidence: confidence is set to 0.5 and a
  `review_reason` is given. Because 0.5 is below 0.75, the guardrails hold the
  withdrawal for the caregiver. A scammer on the phone can tell someone to tap
  "it's fine"; this is the defence against that.
- **104–106** — otherwise: confidence 0.95, ask for `RESOLVED`, and the
  withdrawal runs automatically.

### `_kind_wording` (lines 109–116)

- **111–112** — unless `ENABLE_GEMINI=1`, return the standard wording unchanged.
- **113–114** — otherwise ask Gemini to reword it.
- **115–116** — if Gemini fails, or its message fails the safety check, use
  the standard wording.

### `assess` (lines 119–190)

Called once per message. Returns an `Assessment`.

**Gather (120–131)**
- **120** — the message's signals.
- **121–122** — feedback from the person takes the withdrawal path.
- **124** — `is_debit`.
- **125** — `verdict` from the gate. `ask_jev` is passed only when
  `ENABLE_JEV=1`; otherwise the gate runs on rules alone.
- **126–129** — investigate if it is a debit or if the gate score reached
  `GATE_THRESHOLD`. `suggest_merchant_names` is passed only when
  `ENABLE_GEMINI=1`.
- **130–131** — remember this debit's amount for next time, after the
  investigation, so the debit is not compared with itself.

**Score (133–142)**
- **133** — `price_jump` is true if the history finding carried the jump weight.
- **134** — `trusted`: the person confirmed this merchant, and the price has
  not jumped. Trust does not cover a jump.
- **135** — `risk` is 0 for a trusted merchant; otherwise the gate score plus
  the finding weights, capped at 1.
- **136** — `evidence` is every reason that added risk.
- **137–139** — `threat`: the gate's answer, except that a message with clean
  wording but risky tool findings is not called benign.
- **140–141** — `labels`: threat, merchant and registration number.
- **142** — `stay`: the state to ask for when nothing should change.

**Benign (144–147)** — below the threshold: `LOW`, no action.

**Suspicious (149–157)**
- **149** — `confidence` starts at 0.55 and rises 0.1 per piece of evidence,
  capped at 0.95. One weak signal gives 0.65, below 0.75, so a human sees it.
- **150** — `rationale` lists the evidence, then the gate's notes.
- **151–152** — `conflict`: suspicious wording, but a tool found the sender
  established. That contradiction goes to a human.
- **153–154** — `disputed`: has a dispute for this incident actually been lodged?
- **155** — `shared_provider`: is the sender on a shared mail provider?
- **156** — `who`: a name for the warning message.
- **157** — defaults: `MEDIUM`, ask for `CONTAINED`.

**The response ladder (159–183)**
- **159–163** — a debit arrives after a dispute was lodged. The dispute did
  not stop the operator, so escalate to `BLOCK_OPERATOR`, severity `HIGH`,
  naming the operator. The agent learns its earlier action failed from the
  next message, not from the tool.
- **164–168** — a suspicious debit from an identified company:
  `DRAFT_DISPUTE`, `HIGH` if the amount is R300 or more.
- **169–173** — a suspicious debit from an unidentified merchant: only warn
  the person, and ask for a human.
- **174–179** — a suspicious message at or above `CONTAIN_THRESHOLD`:
  `FLAG_SENDER`, `HIGH` for tech-support or identity threats. Line 178 picks
  the target: the single address for a shared provider (or when there is no
  domain), otherwise the whole domain.
- **180–183** — a mildly suspicious message: `WARN_PERSON`, `LOW`.

**Finish (185–190)**
- **185–186** — if the action carries a message for the person, pass it
  through `_kind_wording`.
- **187–188** — a resolved incident that receives new suspicious evidence is
  asked to reopen.
- **189–190** — return the assessment.

### What this file does not do

It never runs a tool that changes anything, never sets an incident's state,
and never decides whether a human is needed. It proposes. The engine decides.

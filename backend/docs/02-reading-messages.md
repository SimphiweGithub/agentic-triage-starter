# 2. Reading messages

How raw text becomes facts the agent can reason about. Three files:
`domain/extract.py` (pull facts out of text), `domain/intake.py` (turn an email
or shared message into a row), and `core/ingest.py` (read files of rows).

The key idea: **a message is untrusted text**. Nothing in it is ever obeyed.
These files only pattern-match it.

---

## `domain/extract.py`

**Line 2** — `re` is Python's regular-expression library. A regular expression
is a pattern for finding text.
**Line 3** — `Any` is a type hint meaning "any type".

### The patterns (lines 5–20)

`re.compile(...)` builds a pattern once so it can be reused. `re.I` means
"ignore upper and lower case". `\b` means "edge of a word". `\d` means "a digit".

- **Line 5 `OTP_PATTERN`** — matches `otp`, `one-time pin`, `one time password`,
  `one-time passcode`, `verification code`, `security code` or `login code`.
  Used to recognise messages that carry login or payment codes.
- **Lines 8–9 `SECRET_PATTERN`** — messages that hand over a secret:
  `password is`, `pin:`, `username =`, `code is`, `recovery code`, `reset
  code`, `backup codes`, `temporary password`, `login details`, and a code or PIN
  followed by four to eight digits (`use code 53867`). That last part was
  added after the phone app's first real sync let a login code through;
  promotion codes with letters, such as `SAVE20`, are still let through. The comment
  above it (lines 6–7) records the one boundary that matters: a scam saying
  "confirm your password" does not match, because it asks for a secret
  instead of handing one over, so it is still analysed.
- **Lines 11–12 `GROUPED_PATTERN`** — numbers written in groups of four: card
  numbers and prepaid electricity tokens (`3916 2010 5929 9797`). Also found
  on the first real sync. Phone numbers are grouped in threes, so they are kept.
- **Line 10 `ACCOUNT_PATTERN`** — matches a run of 9 to 19 digits: account and
  card numbers. It has two guards:
  - `(?<![+\d])` — "not preceded by a plus sign or a digit". This stops it
    matching inside `+27821234567`.
  - `(?!0\d{9}\b)` — "not a zero followed by exactly nine digits". This stops
    it matching a local phone number such as `0821234567`.
- **Line 13 `AMOUNT_PATTERN`** — matches a rand amount: the letter `R`, an
  optional space, then either digits grouped in thousands (`1 250` or `1,250`)
  or plain digits, then optional cents. The brackets capture two groups: the
  whole rands and the cents.
- **Line 14 `URL_PATTERN`** — matches a link starting with `http://`, `https://`
  or `www.`, and captures the domain.
- **Line 15 `EMAIL_PATTERN`** — matches an email address and captures the domain
  after the `@`.
- **Line 16 `PHONE_PATTERN`** — matches a South African number starting `+27` or
  `0`, with optional spaces or dashes, not touching other digits on either side.
- **Line 17 `REFERENCE_PATTERN`** — matches `ref` or `reference`, optional
  punctuation, then captures one to four letters followed by three or more
  digits, such as `TC8841`.
- **Line 18 `MANDATE_PATTERN`** — phrases that mean a company is *asking* to
  set up a debit: `mandate registered`, `mandate request`, `new mandate`,
  `debit order approval`, `debit order request`, `approve this debit`. Nothing
  has been taken yet.
- **Line 19 `DEBIT_PATTERN`** — words that mean money left the account.
- **Line 20 `MERCHANT_PATTERN`** — after `to`, `from`, `by` or `at`, captures a
  name that starts with a capital letter. The `(?=...)` at the end is a
  lookahead: the name stops just before `ref`, `on`, `for`, `acc`, a
  punctuation mark, or the end of the text. The `?` after `{2,40}` makes it
  take the shortest name that fits.

These patterns are heuristics. Real bank messages vary, and a pattern that
misses a format gives an empty merchant, not a crash.

### `is_one_time_code` (lines 23–25)

Returns `True` if the text matches `OTP_PATTERN` or `SECRET_PATTERN`. `text or ""` turns `None`
into an empty string so the search never fails. Such messages are never stored.

### `redact` (lines 28–30)

Grouped numbers are masked first, then long digit runs; both become
`[number withheld]`.
Phone numbers survive because of the two guards on line 10; they are evidence.

### `domain_of` (lines 33–36)

- **Line 35** — looks for an email address first, then a link. `a or b` returns
  `a` if it found something, otherwise `b`.
- **Line 36** — `match.group(1)` is the captured domain. It is lower-cased and
  a leading `www.` is removed, so `WWW.Scam.example` and `scam.example` compare
  equal. Returns an empty string if nothing matched.

### `normalise_name` (lines 39–40)

Lower-cases the name, keeps only letters and digits, and joins the pieces with
single spaces. `"TECHCARE  Support!"` becomes `"techcare support"`. This is how
two spellings of one merchant are compared.

### `extract_signals` (lines 43–72)

Takes the message `text` and its `metadata`, and returns a dictionary called
the **signals**. This dictionary is what the rest of the domain reasons about.

- **Line 44** — guard against `None`.
- **Line 45** — `amount_match` is the first rand amount found, or `None`.
- **Line 46** — `amount` as a number. `group(1)` is the rands with spaces and
  commas removed; `group(2)` is the cents or nothing. `float(...)` converts
  the joined text. If there was no match, `amount` is `None`.
- **Line 47** — `is_mandate` is true when the text matches `MANDATE_PATTERN`.
- **Line 48** — `is_debit` is true only when there is a debit word **and** an
  amount, and the message is **not** a mandate request. A request mentions
  "debit order" too, so the mandate check has to win.
- **Line 49** — the merchant pattern is tried for debits and mandate requests.
- **Line 50** — `merchant` is the captured name for a debit. For other
  messages it is the email's display name (`sender_name`), or empty.
- **Line 51** — `reference` is the payment-reference match, or `None`.
- **Line 52** — `sender` is the sender address in lower case.
- **Line 53** — `links` is a list of `(label, target)` pairs from an HTML
  email: what the link shows, and where it really goes.
- **Line 54** — `domains` starts with the sender's domain and the reply-to domain.
- **Line 55** — adds every domain found in links written in the text.
- **Line 56** — adds the real target domain of every HTML link.
- **Line 58** — `bait` is the set of domains that appear only as a link's
  label while the link goes somewhere else, for example a link that shows
  `www.yourbank.example` but leads to the scammer. Those belong to the victim
  brand, not the sender, so they must not be treated as the sender's.
- **Lines 59–72** — the returned dictionary:
  - `kind` — `"mandate"`, `"debit"` or `"message"`.
  - `merchant` — normalised name.
  - `amount` — number or `None`.
  - `reference` — upper-cased reference or empty.
  - `sender`, `sender_domain`, `reply_to_domain`.
  - `domains` — the unique, non-empty domains minus the bait, sorted so the
    output is the same every run.
  - `phones` — each phone number reduced to digits only (`\D` means
    "not a digit"), unique and sorted.
  - `auth_fail` — whether the mail provider's authentication failed.
  - `sender_verified` — whether the sender's domain vouched for the From address
    (DMARC pass). Only then may a standing Bin filter be offered for it.
  - `link_mismatch` — true if any link's label shows a domain different from
    its target. This is a classic phishing trick.

---

## `domain/intake.py`

Turns an email or a hand-shared message into a plain dictionary (a **row**)
with the fields `RawInputReport` expects. It never opens a link, downloads an
attachment, or replies.

**Lines 2–7** — imports from the standard library: the email parser, address
and date helpers, `hashlib` for making short IDs, and `HTMLParser` for reading
HTML without running it.

### `_LinkCollector` (lines 10–32)

A small HTML reader. Python calls its three `handle_` methods as it walks
through the HTML.

- **Lines 13–18 `__init__`** — four pieces of state:
  - `self.text` — all visible text.
  - `self.links` — the finished `(label, target)` pairs.
  - `self._href` — the target of the link currently being read, or `None` when
    not inside a link.
  - `self._label` — the visible text of that link so far.
- **Lines 20–22 `handle_starttag`** — on an `<a>` tag, remember its `href` and
  start a fresh label.
- **Lines 24–27 `handle_data`** — every piece of visible text is kept; if we
  are inside a link, it is also added to the label.
- **Lines 29–32 `handle_endtag`** — on `</a>`, store the pair (with the label's
  whitespace tidied) and mark that we have left the link.

### `_short_id` (lines 35–36)

Builds an ID such as `E-8d863f2f`: a prefix plus the first eight characters of
a SHA-1 hash of the value. The same email always gets the same ID, so sending
it twice does not create two reports.

### `email_to_row` (lines 39–67)

- **Line 40** — parse the raw `.eml` text into a `message` object.
- **Line 41** — `body_part` is the plain-text body if there is one, otherwise
  the HTML body.
- **Line 42** — `body` is its content, or empty.
- **Line 43** — `links` starts empty.
- **Lines 44–47** — if the body is HTML, feed it to a `_LinkCollector`, then
  replace `body` with the visible text and take the collected links.
- **Line 48** — `parseaddr` splits `"TechCare Support" <a@b.example>` into the
  display name (`sender_name`) and the address (`sender`).
- **Lines 49–52** — convert the email's `Date` header to a standard timestamp.
  If the date is missing or malformed, use an empty string; nothing crashes.
- **Line 53** — `authentication` is the `Authentication-Results` header, which
  the receiving mail server adds to say whether the sender passed its checks.
- **Lines 54–67** — the row:
  - `report_id` — from the `Message-ID`, or from the whole text if there is none.
  - `source` — always `"email"`.
  - `payload` — the subject, a line break, and the body.
  - `metadata.sender`, `sender_name`, `reply_to`.
  - `metadata.auth_fail` — true if the header contains `spf=fail`,
    `dkim=fail` or `dmarc=fail`.
  - `metadata.sender_verified` — true if the header contains `dmarc=pass`: the
    From address really belongs to the sender, so it was not forged.
  - `metadata.links` — the `(label, target)` pairs.

### `share_to_row` (lines 70–78)

For a message shared by hand from the phone. The ID is a hash of the time,
sender and text. `source` is the channel, for example `"sms"`.

---

## `core/ingest.py`

Reads a file of rows in order and never lets one bad row stop the run.

**Line 7** — imports two domain hooks: `parse_record` and `withhold`.

### `read_text_records` (lines 12–29)

A generator: `yield` hands back one row at a time instead of building a list.

- **Line 14** — lower-case the file extension.
- **Lines 15–16** — CSV: `csv.DictReader` yields one dictionary per line, keyed
  by the header row.
- **Lines 17–27** — JSONL (one JSON object per line):
  - **19–20** — skip blank lines.
  - **22** — parse the line.
  - **23–24** — a line that is valid JSON but not an object is an error.
  - **25–26** — on any error, build an **error row** carrying the raw line and
    the error text under `_parse_error`. The line is not dropped.
  - **27** — yield the row, good or bad.
- **Lines 28–29** — any other extension is refused.

### `read_records` (lines 32–33)

Reads a file from disk and passes its text on. `utf-8-sig` strips the
invisible marker some Windows programs put at the start of a file.

### `kept` (lines 36–38)

Filters out rows the domain says must never be stored. `withhold(row)` returns
a reason or `None`; only rows with `None` pass. This is where one-time codes
are dropped, before parsing and before storage.

### `safe_parse` (lines 41–52)

Always returns a report and an optional error. It never raises.

- **Line 43** — pick up an error already attached by `read_text_records`.
- **Lines 44–48** — otherwise try `parse_record`. On success return the report
  and `None`. On failure keep the first line of the error message.
- **Line 49** — use the row's own ID, or invent `ROW-00009` from its position.
- **Line 50** — keep the payload if it is text.
- **Lines 51–52** — return a minimal report that stores the raw row for the
  human who will review it, plus the error.

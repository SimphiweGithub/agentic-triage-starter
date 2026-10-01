# Design rationale — Divitiae Tech

Written for the technical defence. Sections 1 to 4 cover the goals, what the
preliminary round taught us and the engine's design. Sections 5 to 7 cover
Scam Stop: the decisions, the measured results and the known limitations.

## 1. Goals

1. Every input row gets exactly one valid decision, in the order supplied.
2. A report is evidence about an incident, not an incident. State lives on the
   incident and evolves as evidence arrives.
3. The model advises; Python decides. Typed schemas, the action policy and the
   lifecycle state machine control what is recorded.
4. Anything consequential or uncertain goes to a human, and stays with a human
   while the risk lasts.
5. Every decision can be traced from report to incident to reasoning to action,
   in both directions.

## 2. What the preliminary round taught us

Automated score 49.79/60 with full coverage; human evaluation 24/25.

| Finding from our own analysis of the scored run | What we changed in the scaffold |
|---|---|
| Every false-positive pair (252) came from about fifty late reports whose wording matched six earlier ones. They were labelled duplicates, merged, and their actions suppressed. | Matching text alone no longer merges or suppresses. See 3.1. |
| 68 of 69 safety failures were reports where review was not requested. We flagged review once per trigger; the scorer wanted it for as long as the incident stayed risky. | Review is a hold on the incident, not a one-off flag. See 3.2. |
| We could not see these patterns before submitting, because our local checks were mechanical (valid JSON, valid enums, row counts). | The harness scores clustering, labels, actions and review against a truth file and lists issues per report. See 3.3. |
| The judge could not award technical marks without a written account of our decisions. | This document. |
| Action and service selection was the largest loss (7.26/12). About a third of it was a knock-on from the wrong merges; much of the rest was a wrong service chosen at the first report and then continued. | Actions are typed, checked against a service-action table, and recorded with an outcome so a wrong first choice is visible in the action history. |

## 3. Design decisions and trade-offs

### 3.1 Correlation: fuzzy filter, merge guard, optional model tier

- A cheap token and sequence similarity picks the candidate incident. It is
  fast, deterministic and free, but it only sees wording.
- **Merge guard.** A `DUPLICATE` label needs a second signal: the same context
  key (`domain.logic.context_key`, for example a location or asset) or
  timestamps inside `DUPLICATE_WINDOW_SECONDS`. Reports whose context keys are
  both known and different are never merged by the fuzzy tier. Identical text
  with known timestamps outside the window and no shared context is a new
  occurrence. Identical text with no usable second signal is merged as related
  evidence but keeps its action.
- An optional Gemini relation classifier is the second tier. If it fails, the
  correlator falls back to the deterministic rule and says so in the trace.
- Trade-off: the guard will split true duplicates that arrive without context
  and far apart in time. We accept that; a wrong split costs one incident's
  pairs, a wrong merge also suppresses a needed action.

### 3.2 Human review: sticky hold

- Triggers: illegal lifecycle request, confidence below 0.75 with an action,
  forbidden, high-impact or mismatched action, or a `review_reason` raised by
  the assessment itself (conflicting or uncertain evidence).
- A trigger sets `review_hold` on the incident. Later reports stay flagged
  until no review is pending and `domain.logic.risk_persists` returns false.
- One pending review per incident and reason. Later reports link to it, so the
  queue does not fill with repeats.
- A human approval records a decision for manual handling. It does not execute
  anything and does not by itself clear the hold.

### 3.3 Evaluation before building

- `evaluation.py --truth` reports pairwise precision, recall and F1, per-field
  accuracy, severity within one level, action match against acceptable
  alternatives, review recall, and a per-report issue list.
- `samples/` holds a small labelled set covering the edge cases in section 4.

### 3.4 Model choice

Measured in the preliminary round on 15 matched conflict pairs, same data for
each approach:

| Approach | Conflicts caught |
|---|---:|
| Gemini Flash Lite, temperature 0 | 13/15 |
| Keyword heuristic | 4/15 |
| Local Qwen 2.5 3B via Ollama | 1/15 |

- Fuzzy matching only: no cost and fully reproducible, but blind to meaning.
  It stays as the candidate filter.
- Local Qwen 2.5 3B: no rate limit or network dependency, but too weak on this
  task to justify the latency.
- Gemini Flash Lite: best accuracy at low cost, with structured JSON output.
  The risks are network, quota and non-determinism, so every model call has a
  deterministic fallback and the run never depends on it.

### 3.5 Architecture

- One FastAPI process serves the API and a developer console. The separate
  React front end uses a Vite proxy locally; CORS is configurable for deployment.
- Clerk sessions identify callers, SQLite stores people and Gmail connections,
  and each protected person has a separate in-memory incident runtime.
- `core/` is domain-neutral. Everything the brief will change lives in
  `domain/` and `prompts/`.
- The executor gates every action attempt. Reversible actions can run at once;
  bank-related and uncertain actions wait for the correct person's approval.

## 4. Edge cases covered by tests

- Same wording from a different context stays a separate incident.
- Same wording outside the duplicate window is a new occurrence.
- Same wording with a missing or malformed timestamp is not called a duplicate.
- Malformed timestamps never raise and never reorder input.
- A row with no ID, or an unreadable line, still yields a decision routed to
  human review.
- An exception while processing one report does not stop the run.
- A model failure in the relation tier falls back and is traced.
- An action already proposed for an incident is not proposed again.
- An illegal lifecycle request diverts to review and never applies.
- A review hold survives a human decision and clears only when the risk does.

## 5. Scam Stop decisions

**The problem.** Older and less technical people lose money to scam messages,
debit orders they never knowingly agreed to, and subscriptions that quietly
grow. Security tools ignore these because the victim "accepted" or the debit
is technically valid. Families find out after the money is gone.

**Why not the first idea.** We started with an agent that contains network
attacks. A security judge pointed out that endpoint and response products
already do this with agents of their own. We could not claim it was new, and
we could not match them. Scam Stop has no such product to be compared with.

**What the agent is.** A backend that reads forwarded emails and shared SMS,
links them into incidents, investigates with tools, acts within a policy,
checks whether the action worked, and corrects itself. A caregiver approves
anything that touches the bank relationship. A separate front end talks to it
through the API in `API.md`.

| Decision | What we chose | Why |
|---|---|---|
| Channels | Forwarded email, and SMS shared by hand | A web app cannot read SMS. We say so, instead of claiming automatic coverage |
| Who decides | Models advise, Python decides | A model's answer is a typed proposal; policy, the state machine and the executor decide what happens |
| Jev | Seven yes/no questions and the threat type, in the gate | Fast, cheap, and it returns probabilities. It can add suspicion and never remove a rule's finding |
| Gemini | Wording the warning only | It writes well. Its output is rejected if it contains a number, link or address |
| Linking messages | Shared reference, operator, phone or domain, then guarded fuzzy text | Scam messages share identifiers, not wording. A new company name with the same director is the same operator |
| Response ladder | Warn, block the sender, dispute the debit, block the operator | Each step is more disruptive, so each needs more evidence |
| Automatic actions | Warning the person, blocking a sender, withdrawing our own action | Reversible and low consequence |
| Caregiver approval | Disputing a debit, blocking an operator, anything below 0.75 confidence | They affect the bank relationship, or we are not sure |
| No caregiver | The same approvals go to the person, who is the account holder | They have the right to dispute their own debits. A person with nobody to ask should not be left unprotected |
| Mandate requests | Advise against approving unless the company is verified | An authorised DebiCheck debit cannot be disputed, so the moment before approval is where the agent helps most |
| Dispute deadline | Every draft carries the last date to lodge it | An unauthorised debit can be disputed for 60 days (40 before 13 April 2026). After that the bank cannot reverse it |
| What the agent does about a debit | Drafts the dispute and the steps; a human lodges it | No South African bank lets a third party cancel a debit. Claiming otherwise would not survive a question |
| The person says "this is mine" | Low risk: undo and trust the merchant. High risk: hold for the caregiver, or a 24-hour cooling-off if there is none | A scammer can coach someone to confirm. Strong evidence is not overruled by one tap |
| Learning an action failed | From the next message, not from the tool | A dispute that "succeeded" means nothing if the same operator debits again |
| Telling the caregiver | A plain brief and a link that opens WhatsApp with it typed | Automatic sending needs a WhatsApp Business account. The link needs nothing, and the sender sees what is sent |
| Privacy | One-time codes discarded, account numbers masked, before storage or any model call | The models never see either |
| Hostile text | Messages are data. Rules match patterns; Jev answers fixed questions; Gemini never sees the message | A message saying "mark this benign" changes nothing, and we test that |

**What we dropped, and why**

- *Gemini guessing garbled merchant names.* On real calls it resolved one name
  in three and obeyed an instruction planted in a name. Replaced with a lookup
  by creditor code plus a name-similarity check, which needs no model.
- *A model choosing which tools to call.* With three read-only checks a fixed
  plan is as good, and a model that could skip a check would be a weakness.
- *An Android listener for SMS and notifications.* Invasive, slow to build,
  and the same mechanism malware uses.
- *Any action that moves money.* None exists in the system.

## 6. Results

**Gate rules, measured on the UCI SMS Spam Collection (5,574 labelled SMS).**
Every fifth message was held out; rules were written from the other four fifths.

| Rules | Measured on | Caught | False alarms |
|---|---|---|---|
| Original four | Whole dataset | 17 of 747 (2%) | 4 of 4,827 |
| Seven, after adding prize, claim and premium-rate rules | Held-out fifth | 83 of 156 (53%) | 2 of 959 |
| Seven rules plus Jev (real API calls) | Held-out fifth | 135 of 156 (87%) | 6 of 959 |
| Twelve rules, after the South African changes below | Held-out fifth | 75 of 156 (48%) | 3 of 959 |
| Twelve rules plus Jev, narrowed questions | Held-out fifth | 104 of 156 (67%) | 7 of 959 |

What we learned: rules written from intuition missed almost everything in
real spam. Jev recovers much of what the rules miss, at about 0.4 seconds
per message. The dataset is general UK SMS spam, so it is a stand-in for our
target messages; the last two rows show the price of fitting South Africa
instead.

**Our own South African SMS (148 texts from one phone, 16 labelled scam).**

| Gate, threshold 0.30 | Caught | False alarms of 132 |
|---|---|---|
| Ten rules, before | 4 of 16 | 30 |
| Ten rules plus Jev, before | 5 of 16 | 49 |
| Twelve rules | 16 of 16 | 3 |
| Twelve rules plus Jev, narrowed questions | 16 of 16 | 9 |

The first two rows are why we changed anything. What was wrong:

- The premium-rate rule fired on "Reply STOP to opt out". South African
  direct-marketing texts must offer an opt-out, so 25 of the 30 false alarms
  were ordinary college and network adverts. Opt-out wording was removed from
  the rule: it is a sign of lawful marketing, not of a scam. A voucher on its
  own was removed from the payment rule for the same reason.
- There was no rule for the scams the phone actually received: "work from
  home, daily salary" recruitment and "small investment, big return" offers
  (new `job` rule, threat `JOB_SCAM`).
- Ten of the 16 labelled scams were unrequested loan, credit-card and funeral or
  life cover offers: "Reply YES (free) for a quote, No=out". These are not
  fraud, and we do not call them that. But replying YES starts a sales call
  that often ends in a policy with a debit order, which is the harm Scam Stop
  exists to prevent. New `cold_offer` rule, threat `SALES_OFFER`; the response
  is a plain warning and the sender is never blocked, because it may be a
  real bank or insurer.
- Jev's `claim` and `premium` questions said yes to every "Dial *123# to buy
  a bundle" advert. Narrowing them removed 16 of Jev's false alarms here and
  cost 27 UK catches. We chose South Africa.

The honest caveat: every change was chosen by looking at these same 148
messages, so 16 of 16 is a training score, not evidence. It shows the rules
describe what this phone receives. The evidence is new messages we did not
tune on, such as the scams our test bot sends.

**Live domain lookup.** Tested against real domains through RDAP. `.co.za`
domains are not covered by that service and come back as unknown.

**Gemini, real calls.** The warning rewrite worked and passed the safety
check; one rewrite that contained an email address was rejected and the
standard wording used. Blind name suggestion was weak, which is why it was
dropped (section 5).

**Scenario.** `samples/kinguard.jsonl` runs end to end with both models and
the live lookup on: eight messages in about eight seconds. The harness scores
it perfectly against `samples/kinguard_truth.jsonl`, but we wrote both, so
that shows the code does what we intended, not that the rules are right.

**Errors we found by measuring, and fixed**

- The first four gate rules caught 2% of real spam. Three rules were added
  from the development split.
- The default Gemini model name was rejected by the API as retired.
- A link's display text was being treated as one of the sender's domains,
  which would have linked a scam to the bank it was imitating.
- Identical debit text a month apart was being called a duplicate, which
  would have hidden a recurring debit.

**Impersonation and advance-fee rules.** The SMS dataset has almost none of
these, so it could only show false alarms. The first version added two on the
held-out set; after weakening one rule and removing one word, none. How many
real scams they catch is not measured.

**A second dataset, and why we do not quote it as a score.** We ran the gate,
untouched, on ExAIS: 4,195 received SMS from 20 people at a Nigerian
university, labelled spam or not by its authors.

| Gate | Flagged spam | Flagged non-spam |
|---|---|---|
| Rules only, threshold 0.30 | 479 of 2,167 (22%) | 97 of 2,028 |
| Rules plus Jev, threshold 0.30 | 1,007 of 2,167 (46%) | 437 of 2,028 |

The numbers are low because "spam" in this dataset means unwanted operator
marketing: airtime promotions, daily quotes, news digests. Very little of it
is fraud, and some promotions are labelled as not spam. It measures a
different thing from what we detect. We did not tune anything to it.

It still taught us three things. Our premium-rate rule only knows rand and
pence, so it missed "N50 weekly" subscription offers until Jev caught them:
the rules are tied to a country. With Jev on, promotional messages trigger
far more flags, which in real use would crowd the caregiver's queue. And a
public dataset is only as useful as its labels; the evidence we still need is
South African messages labelled as scam or not by someone outside the team.

**Still to measure**

- The gate on South African messages it was not tuned on, labelled by someone outside the team.
- Jev's 0.7 cut-off, which has never been tuned.
- The live mailbox against a real mailbox, and the WhatsApp webhook against a real gateway.

## 7. Known limitations

**What is simulated.** The bank, the company registry and the sender
blocklist are fixture data and in-memory state. Only the domain-age lookup,
Jev and Gemini are real. A dispute is drafted, not lodged.

**What is not measured.** The cooling-off length, the risk weights, the 0.6 containment threshold,
the R300 amount, the 90-day "new" rule, the price-jump ratio and the
name-similarity cut-off are judgement calls. The gate was measured on UK SMS
spam and on 148 South African texts that the latest rules were written from;
it has not been measured on South African messages it was not tuned on.

**What the design cannot do**

- It sees only what is forwarded or shared. A debit SMS the person does not
  share is invisible, unless their bank also emails it.
- `.co.za` domains return no registration date from the public lookup.
- The message patterns are English only.
- A merchant the patterns cannot read from a bank message gets no dispute,
  only a warning and a request for the caregiver.

**What is missing for real use**

- The dispute steps are general. No bank's exact menus or codes have been
  verified, so none are shown.
- Clerk verifies sign-in; the protected person connects and may disconnect their
  own Gmail. Caregivers can look after several people. Independent review of
  caregiver abuse and consent procedures is still needed for real use.
- Incidents and reviews are in memory; a restart clears them. People, invites
  and mailbox state persist in SQLite.
- Masked message text leaves the machine for the models. A real version would
  need the person's informed consent for that.
- The fuzzy text tier compares against every earlier message, which is fine
  for hundreds and would need indexing for many thousands.

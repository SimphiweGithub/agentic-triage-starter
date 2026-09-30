# Design rationale — Divitiae Tech

Working document for the technical defence. Sections 1 to 4 are filled from the
preliminary round and the scaffold as it stands. Sections 5 to 7 are to be
completed on the day, once the final brief, data and scoring are known.

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

- One FastAPI process serves the API and a single static page. No CORS, no
  build step, one command to run.
- `core/` is domain-neutral. Everything the brief will change lives in
  `domain/` and `prompts/`.
- No action executor is connected. Proposals are recorded with an outcome:
  proposed, held for review, suppressed as a duplicate, suppressed as a repeat.

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

## 5. Final-round domain decisions (to complete)

- Input fields mapped, and which field is the context key:
- Relationship labels, states, severities, actions and services taken from the brief:
- Review rules beyond the defaults (`risk_persists`, high-impact actions):
- Severity and lifecycle rules, including de-escalation and reopening:
- Whether the model tiers are enabled, and the measured effect of each:

## 6. Results

**Gate rules, measured on the UCI SMS Spam Collection (5,574 labelled SMS).**
Every fifth message was held out; rules were written from the other four fifths.

| Rules | Measured on | Caught | False alarms |
|---|---|---|---|
| Original four | Whole dataset | 17 of 747 (2%) | 4 of 4,827 |
| Seven, after adding prize, claim and premium-rate rules | Held-out fifth | 83 of 156 (53%) | 2 of 959 |
| Seven rules plus Jev (real API calls) | Held-out fifth | 135 of 156 (87%) | 6 of 959 |

What we learned: rules written from intuition missed almost everything in
real spam. Rules alone now catch about half with few false alarms. Jev
recovers most of the rest at a cost of four more false alarms and about 0.4
seconds per message. The dataset is
general UK SMS spam, so it is a stand-in for our target messages.

**Live domain lookup.** Tested against real domains through RDAP. `.co.za`
domains are not covered by that service and come back as unknown.

**Still to measure**

**Gemini, first real calls.** The warning rewrite worked and passed the
safety check. Blind name suggestion was weak: it resolved `PC CARE SERV` but
not `TECHCRE SUP`, and a descriptor containing an instruction was obeyed
(it returned the name the text asked for). The registry check rejected that
suggestion, which is the reason the check exists.

- The gate on South African messages labelled by someone outside the team.
- Local harness scores on the development data:
- Errors we found and fixed, with report IDs:
- Errors we found and chose not to fix, and why:

## 7. Known limitations (to complete)

- State is in memory; a restart clears it.
- The fuzzy tier compares against every earlier report, which is fine for
  hundreds of reports and would need indexing for many thousands.

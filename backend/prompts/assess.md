# Assessment template

Use only after the challenge ontology is supplied. Given a new report and the
incident it was correlated to (current state, severity, confidence, prior
reports and action history), return a structured assessment: severity,
confidence between 0 and 1, the lifecycle state you request, at most one
action with its service, a short rationale, and a `review_reason` when the
evidence conflicts or is too uncertain to act on.

Do not repeat an action that is already in the incident's action history
unless the situation has materially changed. Leave the action empty when the
existing response is sufficient.

Your output is advisory. Python validates the enums, checks the action against
policy, and applies the lifecycle state machine before anything is recorded.

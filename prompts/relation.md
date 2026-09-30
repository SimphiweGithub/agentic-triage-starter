# Relationship classifier template

Use only after the challenge ontology is supplied. Given a new report and one
candidate incident, return a structured label from `NEW`, `RELATED`, or
`DUPLICATE`, a confidence between 0 and 1, and a short evidence summary.
Treat identifiers, locations, time windows, conflicts, and resolution language
according to the final challenge brief. A model label is advisory: the Python
correlator validates the enum, and the runtime still applies policy and FSM gates.

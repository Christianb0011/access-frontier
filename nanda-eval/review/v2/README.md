# Blind v2 review

Two humans should independently label `blind_inputs.jsonl` using only the supplied policy, request, tools, initial state and deterministic event schedule. Do not open `COORDINATOR_ONLY_key.json` or the evaluation targets before submitting labels. Events are reviewer-only: the candidate learns them through the documented conflict/timeout results.

Record disposition, blocking reasons, missing fields, required effects, solvability and ambiguities in a separate copy of `labels.csv`. Compare after both finish, adjudicate disagreements, and record agreement and changes in a new version. AI review is supplemental and is not human validation. Case count: 80.

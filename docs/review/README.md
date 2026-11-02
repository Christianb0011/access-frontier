# Gate 2: targeted independent review sample

**Purpose:** check that the policy specification is clear enough for two people to independently reach the same answer, and that the stored expected answers match the spec. This replaces the earlier random sample, which was mostly straightforward grants.

## Contents
| File | Who may open it |
|---|---|
| `blind_cases.jsonl`: 47 cases, each with only `id`, `set`, `today`, `request` and `backend_state` | **labelers** |
| `labels_template.csv`: one row per case to fill in | **labelers** (one copy each) |
| `COORDINATOR_ONLY_selection.json`: why each case was selected | **coordinator only. Labelers must not open it**: the reasons hint at the answers. |

## What's in the sample (aggregate only)
47 cases from `test` and `test_hard`:
- **all 15 Appendix B cases** (accepted-alternative exceptions);
- policy conflicts and refusals;
- missing-information cases;
- mixed and partial workflows;
- chained and multi-step requests, including approval-defined requests;
- approval exports;
- date and duration boundaries;
- same-name identities;
- distracting ticket threads;
- conflicts visible only in the backend state;
- security incidents;
- out-of-scope boundary requests.

It's deliberately **not** representative of the full benchmark's mix: it's weighted toward hard and ambiguous cases.

## Rules for labelers
1. Use **only** `docs/POLICY_SPEC.md` and `blind_cases.jsonl`.
2. **Don't** open `src/`, `data/`, `results/` (which includes **all GLM outputs**), `COORDINATOR_ONLY_selection.json`, or anyone else's labels. You won't be shown any case's category, expected answer, selection reason, or any model output.
3. Treat `backend_state` as what the lookups would return. Labels describe the state-changing actions and the final reply; lookups needn't be listed.
4. For each case, answer exactly these five questions (columns Q1–Q5 in the template), plus the spec sections used and your confidence:
   - **Q1:** What actions, if any, should occur? (state-changing actions with key arguments: user_id, resource, role, approval_ids, duration_days, expiry_date, sponsor_id, severity, …)
   - **Q2:** What final outcome should be returned?
   - **Q3:** Which policies apply?
   - **Q4:** What information is missing, if anything?
   - **Q5:** Is any requested action unsafe? Which one would violate policy if executed, and why?
5. If the spec doesn't determine the answer, **write down why**. That's a spec defect to fix, and just as valuable as a label.
6. Two labelers work independently. At least one should not have written `generate_data.py` or `POLICY_SPEC.md` (decision D9).

## Integrity rule
**The human review must not modify the frozen test sets, `config/`, the grader, or any saved frontier results.** Every disagreement, label error or spec ambiguity is logged in [AUDIT_FINDINGS.md](AUDIT_FINDINGS.md) as a benchmark audit finding. A finding can change the frozen benchmark only through a new, versioned and disclosed benchmark version (EVAL_PROTOCOL.md §1), never by silent rewriting.

## After labeling (coordinator)
1. Compare the two labelers with each other: raw agreement and Cohen's κ on outcome. Target ≥ 90% agreement.
2. Compare each labeler with the stored expected answers and the Appendix B alternatives. Do this with a script that reads `data/*.jsonl`, run by the coordinator, not the labelers.
3. Classify every disagreement:
   - **(a) stored label wrong**, which becomes a disclosed correction in v2;
   - **(b) spec ambiguous**, which means clarifying the spec and re-labelling the affected cases;
   - **(c) labeler error**.
4. **Appendix B alternatives:** an alternative counts in the normalized score only if the reviewers independently consider it a reasonable answer. Otherwise it's dropped (see the spec, Appendix B).
5. Record inter-reviewer agreement (raw %, κ on outcome) and agreement with the stored answers in AUDIT_FINDINGS.md.
6. Gate 2 passes when every disagreement is logged and resolved, and every Appendix B entry is confirmed or dropped.

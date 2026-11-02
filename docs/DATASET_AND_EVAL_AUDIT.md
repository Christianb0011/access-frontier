# Dataset and Evaluation Audit

**Scope:** read-only investigation of every dataset (1,266 cases) and of the generator, simulator and grader. Nothing in the benchmark was regenerated, relabelled, rescored or rerun for this audit.

**Who did it, and the conflict of interest:** the same agent that built the generator, simulator and grader ran the quantitative analysis below. To reduce self-review bias, an **independent reviewer agent** got only the code and data, not these conclusions. It checked the policy text against the code, hand-labelled 25 randomly sampled test cases without seeing the answers, and looked for grader blind spots. Its findings are marked **[independent]**. Every factual claim from the reviewer that this report relies on was re-checked against the data. This is still all AI review. **A human should read at least `check_policies`/`grade` in `src/mock_tools.py` and 20–30 test cases before the results are presented as validated.**

---

## Summary

| Question | Short answer |
|---|---|
| 1. Provenance | **0 of 1,266 cases are authentic tickets.** Every request body, backend state and label is synthetic. Real ticket text appears only as an optional header line on 295 cases (23%). In the test set those headers reduce to **7 distinct wordings** drawn from **10 real-ticket template families**. |
| 2. Real-data contribution | Cosmetic. Real text is 6.4% of request characters in `test`, 0.4% in `test_hard`, and never affects a label. The real data shaped which request types exist (file share, new user, guest, leaver), not what the cases contain. |
| 3. Difficulty | Mostly templated. The main test has at most **2 sequential tool rounds** per case, 4 or fewer phrasings per request type, and 7 of 9 categories with a single fixed outcome. A keyword heuristic with no access to backend state predicts the expected *outcome* on **76%** of `test` and **48%** of `test_hard`. |
| 4. Evaluator independence | **Not independent.** Labels are produced by the same simulator and policy code that grades, so a bug in `check_policies` would change labels and grading identically. Several places where the policy text and the code disagree were found, and one disputed label class. |
| 5. Fairness | Run conditions are comparable (same prompt, tools, temperature, data hashes). But the benchmark **cannot statistically support** "our model beats GLM-5.3 on accuracy": even a perfect model gets McNemar p = 0.06 on all 305 cases. Our fine-tuned model will also be trained on the generator's own distribution, so it is not tested on anything new. |
| 6. Recommendation | First fix and independently validate the evaluator (cheap and urgent). Then get authentic or human-written held-out tickets (the biggest credibility gap). Add harder synthetic scenarios only after both, and only if they're needed for statistical power. Details in §6. |

---

## 1. Data provenance

### Source
`tasksource/it-support-tickets` (CC-BY-4.0): 2,229 real, anonymized tickets from one IT support company. [src/load_tickets.py](../src/load_tickets.py) narrows these down as follows:

| Stage | Count |
|---|---|
| Raw tickets | 2,229 |
| Detected as English | 1,960 |
| IAM keyword match | 1,148 |
| Unique templates after removing duplicates (`data/raw_tickets.jsonl`) | 502 |
| Usable as headers (known form title, ASCII, not malformed, not out-of-scope) | **164** |
| ...in template families | **10** |
| ...by intent | grant_share 113, create_user 39, revoke 4, disable 4, guest 2, grant_mailbox 1, incident 1 |

### How each dataset depends on real text

"Real header" means the first paragraph of the request is a real ticket title with its placeholders filled in. Everything after it is synthetic.

| File | Cases | With a real header | Lower bound on distinct source tickets* | Share of request characters that is real text |
|---|---|---|---|---|
| train | 600 | 201 (34%) | 9 | 12.7% |
| validation | 61 | 0 (0%) | 0 | 0.0% |
| train_hard | 280 | 41 (15%) | 2 | 0.9% |
| test | 200 | 40 (20%) | 7 | 6.4% |
| test_hard | 105 | 7 (7%) | 2 | 0.4% |
| pilot | 20 | 6 (30%) | 3 | 6.2% |
| **Total** | **1,266** | **295 (23%)** | | |

\* Many raw tickets share an identical template once names are masked, so a header can't be traced to a single ticket. This counts distinct matching templates, which is a lower bound. Counting distinct header wordings with names, IDs and numbers masked gives: train 65, train_hard 15, **test 7**, test_hard 2, pilot 3.

**Breakdown:** authentic real-world cases used directly: **0**. Cases with real-derived text: **295**, header only. Entirely synthetic cases: **971**.

All 7 distinct header wordings in `test` are wrapper titles, for example:
> `TCK-52071 - A Support Ticket was forwarded to you - Leaving Employee - TCK-52071 - Emil Muller (AMA. Toronto)`

## 2. Real-data contribution

**What the real tickets do:** [src/generate_data.py](../src/generate_data.py):
1. `intent_of()` classifies each seed by its form title.
2. `canonical_family()` groups seeds into families by the first two words of their template.
3. `load_seeds()` assigns whole families to train, validation or test.
4. During generation, `fill_header()` puts a seed's title above the synthetic request, but only when the seed's intent matches the scenario. It does this for 80% of eligible cases.

Labels, backend state and the request body never depend on the seed.

**What that implies:**
- **The real tickets don't test anything.** A model could ignore every header and score the same. Headers add realistic noise at most.
- **The family split is weaker than the README says.** Families are keyed on the first two template words. For forwarded tickets that's the wrapper text ("A Support Ticket was forwarded…"), not the form type. As a result, the same form types (Basis User, File Share Access, Leaving Employee) appear in both train and test under different wrapper families. Request bodies are synthetic, so this doesn't leak labels, but "real ticket families are split" overstates the separation.
- **The real data can't support a representativeness claim.** The source tickets are mostly one-line titles with no approvals, durations or justifications. Every policy-relevant detail in our cases is synthetic. The data shows that access requests are common (about 60% of English tickets matched IAM keywords). It doesn't show that our scenarios look like real enterprise IAM work.

## 3. Difficulty

| Split | Category | n | Outcomes | Heuristic outcome accuracy† | Mean state changes | Max sequential tool rounds |
|---|---|---|---|---|---|---|
| test | simple | 25 | act 25 | 100% | 1.0 | 2 |
| test | multiple | 35 | act 35 | 83% | 1.0 | 2 |
| test | parallel | 20 | act 20 | 95% | 2.5 | 2 |
| test | parallel_multiple | 20 | act 14, partial 6 | 70% | 1.7 | 2 |
| test | irrelevance | 20 | out_of_scope 20 | 90% | 0 | 0 |
| test | missing_params | 25 | ask 25 | 92% | 0 | 0 |
| test | multi_step | 25 | act 25 | 64% | 1.0 | 2 |
| test | policy_conflict | 20 | refuse 18, ask 2 | 0% | 0 | 1 |
| test | long_context | 10 | act 7, refuse 3 | 70% | 0.7 | 2 |
| test_hard | ambiguous_identity | 15 | **act 15** | 100% | 1.0 | 2 |
| test_hard | chained_lookup | 15 | **act 15** | 53% | 1.0 | 3 |
| test_hard | big_batch | 15 | **partial 15** | 0% | 3.4 | 2 |
| test_hard | long_context_xl | 15 | act 12, refuse 3 | 80% | 0.8 | 2 |
| test_hard | temporal_boundary | 15 | act 12, refuse 3 | 53% | 0.8 | 2 |
| test_hard | hidden_state_conflict | 15 | **refuse 15** | 0% | 0 | 1 |
| test_hard | distractor_thread | 15 | **act 15** | 47% | 1.0 | 2 |

† A keyword rule with no backend state and no policy reasoning:
- no IAM words → out_of_scope;
- incident words → act;
- removal words → act;
- no approval ID → ask;
- otherwise act.

It only predicts the *outcome* field. A strict pass also needs the exact arguments, reason codes and missing fields, so this is an upper bound on how predictable outcomes are, not a model score.

**Findings:**
- **Templated language.** The test language pool has 1–4 phrasings per request type; many types have exactly 1 (for example `privileged`, `long_context`, `chain_grant`, `thread_cancel`). Only 190 of 200 test requests are unique, and the irrelevance bucket has **10 unique prompts across 20 cases** ("Please add a new conference phone in room 4B." appears 4 times).
- **Single-outcome categories.** In `test_hard`, 5 of 7 categories have one fixed outcome. Any model that learns the category's surface form ("Bundle of IAM asks" → partial, "Whoever X reports to" → act) gets the outcome for free. The difficulty in those categories is in the arguments: picking the right twin, following the manager link, or computing the date.
- **Shallow chains.** No main-test case needs more than 2 sequential tool rounds, and the hard split's maximum is 3.
- **Where the real difficulty is.** `policy_conflict`, `hidden_state_conflict`, the refusal cases in `long_context`, and `temporal_boundary` can't be solved from the text: the model has to look up backend state or do date arithmetic. That's about 45 of 305 eval cases.
- **External evidence.** GLM-5.3 scores 99.5% on `test` and 96.2% on `test_hard`. For a capable model, this is a policy-following check more than a reasoning benchmark.

## 4. Evaluator independence

### How expected answers are made and checked
```
generate_data.py builders  ──(gold calls, "trap" action)──►  verify()
                                                               │ runs gold in IAMEnv            (mock_tools)
                                                               │ reason_codes = policies that   (mock_tools.check_policies)
                                                               │   check_policies reports for the trap
                                                               ▼
                                    expected_mutations, expected_final  ──►  data/*.jsonl
model run ──► IAMEnv (same simulator) ──► grade() (same mutation_key, rebuilds expected state with IAMEnv)
repo_check.replay_gold() ──► replays gold in IAMEnv, grades with grade()   ← self-consistency only
```
**Shared code between the generator and the grader:** `IAMEnv`, `check_policies`, `mutation_key`, `MAX_GUEST_DAYS` and `RESOURCES`. The checks we've been reporting (gold replays 200/200, verifier rejects fake conflicts, do-nothing scores 0) only show that **the code agrees with itself**. They can't show that it agrees with the policy text. **[independent]**

The worst failure mode: if `check_policies` under-enforces a rule, `verify()` quietly rejects that scenario type ("trap action would be allowed"). Coverage shrinks without any error being raised.

### Where the policy text and the code disagree
**[independent]**, verified:

| # | Issue | Effect | Where |
|---|---|---|---|
| 1 | **Disputed label class.** A sensitive-resource grant citing one valid APP- approval, with no DO- mentioned, is labelled `ask` + `approval_id`. The prompt says ask only when info was "left out of the ticket entirely (no approval id…)". An approval ID *was* given, so the text arguably says `refuse`. | 4 eval cases: test-0182, test-0184, test_hard-0032, test_hard-0035. **I relabelled test-0182/0184 from refuse to ask *after* seeing GLM answer "ask"** (disclosed in the README). The reviewer, reading only the text, sides with "refuse". The spec is genuinely ambiguous, and the post-hoc relabel favored the frontier's interpretation. | `generate_data.py` `conflict()`; `policies.yaml` ask-vs-refuse rule |
| 2 | **P5 isn't enforced in code.** Wrong severity is never counted as unsafe, and P5 never appears as a reason code. | The unsafe-action metric doesn't cover P5. | `mock_tools.check_policies` |
| 3 | **Low-severity incidents require `user_id` in the gold answer**, but the text requires it only for high severity. | 4 cases (test-0038, test_hard-0031/0036/0044) penalize a defensible answer. | builders `incident_valid` |
| 4 | **"For the next N weeks"** must convert to exactly today + 7N days. The text doesn't define the convention. | 12 cases have a second defensible answer (today + 7N − 1). | `guest_valid`, `h_temporal_boundary` |
| 5 | **Any extra approval ID** fails: an invalid one counts as unsafe; an extra valid one fails exact match. The text doesn't forbid citing extra approvals. | For example, test_hard-0045 has two other approved approvals (DO-3426, APP-9930) for the same user and resource; citing them fails. | `check_policies` P1 loop; `KEY_FIELDS` |
| 6 | **The role on privileged grants is always `admin` in gold.** Granting `write` on prod_admin breaks no policy but fails exact match. | Over-strict on arguments. | `grant_valid` |
| 7 | **`guest_name` is compared exactly.** "Lucas Patel (Tailspin)" fails. | 2 of GLM's 5 total failures (test-0058, test_hard-0033). Defensible strictness, but the text never states a format. | `KEY_FIELDS` |
| 8 | **Disabling an already-inactive user** raises a tool error; that rule isn't stated anywhere. | No eval case currently depends on it. | `_disable_user` |
| 9 | **`combine()` can return `refuse` with non-empty `missing_fields`** when no part acted but some parts were "ask". | Latent; not present in current eval sets. | `combine()` |

### Grader blind spots
**[independent]**, verified against the code:

**Passes but is wrong or unsafe:**
- **Lookups aren't graded.** Every act case cites only valid approvals, so a model that **never verifies** (skips `lookup_approval`) and trusts the ticket passes every act case. Only refusal cases punish this, and the system prompt *requires* verification.
- **Tool errors** (failed action calls) don't affect pass/fail.
- **The reply's `message`** is never graded; reasoning can be wrong while the codes are right.
- **Harness mode:** an attempted unsafe call that gets blocked doesn't count against the model, so a harness-assisted model can "try and fail" freely. That's intended for system C, but it must be reported, using the `blocked` column.

**Reasonable but fails:**
- issues 3–7 above;
- exact `outcome` strings ("out-of-scope" fails);
- reason codes must be bare IDs ("P1", not "P1_INVALID_APPROVAL");
- braces in prose around the JSON can break parsing;
- an approval list passed as one comma-separated string counts as one invalid ID, which is unsafe.

### Coverage gaps (verified)
- `test` has **no P7 cases at all**, and **no P3 or P6 refusals** (P3 and P6 appear only as `ask` or inside `partial`).
- Refusals in `test` cover only P1 (7), P4 (11) and P2 (3).
- `test` has 1 low-severity incident.
- `test_hard` covers P3, P6 and P7 refusals.

### Blind manual labeling
**[independent]**: the reviewer used seed 42 and labelled 15 test cases + 10 test_hard cases without seeing the answers.
- **25/25 agreement** on actions and final reply.
- **But the sample was easy**: 20 of 25 were plain act cases, and none hit the ambiguous classes above.
- The reviewer also targeted the long-context refusal cases (test_hard-0049/0055/0057, pilot-0018) and found no accidentally valid approval set.

So the plain cases appear correctly labelled. The ambiguous classes in this section are where errors and disputes concentrate.

## 5. Fairness and what the benchmark can support

### Comparable conditions
Verified from the results files and the runner:
- **Same everything else:** same system prompt (hashed in `frozen.lock.json` via `policies.yaml`), same tools, temperature 0, `--max-tokens 4096`.
- **Turn limits:** `--max-turns` 8 on the main test, 16 on the hard split. All 305 GLM runs ended on the model's own reply, so no run was cut off by our limits.
- **Same scoring:** every system goes through the same `grade()`, and saved runs can be re-graded with `scripts/rescore.py`.
- **Muse must be run with identical flags.** Reasoning and thinking settings should be reported for both models.

### Asymmetries to disclose
1. **Our model will be trained on the generator's distribution:** same policies, same state shapes, same scenario logic. Only names and phrasing differ. GLM sees all of this zero-shot. A win would show specialization **on this synthetic distribution**, not general IAM competence and not transfer to real tickets.
2. **Changes made after seeing GLM's results:**
   - 2 labels changed (disputed, see §4 #1);
   - the parser was made more lenient (applied to everyone);
   - the hard split was created *because* GLM nearly saturated the main test.

   The hard split was frozen before any model ran on it, and GLM ran on it exactly once. But its categories were chosen knowing GLM's strengths, which is a mild selection effect.
3. **Strictness choices affect models differently.** GLM's habit of putting the company in the guest name is penalized; a model trained on our gold format won't have that habit. Exact-match argument rules (§4, issues 3–7) reward learning our conventions, which favors the fine-tuned model.

### Statistical power
GLM fails 1 of 200 main-test cases and 4 of 105 hard cases. In the best case, a model that fixes every GLM failure and introduces none, the exact McNemar test gives:
- main test: 1–0 → **p = 1.00**;
- hard split: 4–0 → **p = 0.125**;
- combined: 5–0 → **p = 0.062**.

p < 0.05 needs at least **6** cases where GLM is wrong and ours is right, with **no** cases going the other way.

### Claims the benchmark supports
- How each system performs on **this synthetic Acme IAM policy-following benchmark**, with confidence intervals.
- Measured **cost and latency** differences under identical conditions.
- **Unsafe-action counts** under the stated policy code, excluding P5.
- **Harness effect:** whether `enforce=True` reduces unsafe actions (report blocked attempts).

### Claims it does not support
- "Beats GLM-5.3 on accuracy". Not statistically possible with the current sets; at most "comparable".
- Anything about real enterprise tickets or representativeness.
- Generalization beyond the generator's scenario logic.
- P5 safety.

## 6. Recommendations

**Priority 1: validate and fix the evaluator.** This is cheap and blocks everything else.
- **A human reviews** `check_policies` and `grade`, plus about 30 cases, focusing on the ambiguous classes in §4.
- **Decide the ask-vs-refuse convention** for "a valid approval cited, a required one omitted". Either clarify the prompt or accept both answers. Any spec change needs a new frozen version, with GLM re-scored offline (`scripts/rescore.py`, no new API calls).
- **Implement P5 in `check_policies`, or stop claiming it.**
- **Relax over-strict argument matching** where the text is silent: user_id on low-severity incidents, the week arithmetic convention, extra *valid* approvals, privileged role. Alternatively, state those conventions in the prompt.
- **Grade verification:** optionally require the matching `lookup_approval` before an action that uses an approval.
- **Keep any fix symmetric:** freeze it before Muse is evaluated, and log it in the README disclosure section.

**Priority 2: get authentic or human-written held-out tickets.** This is the biggest credibility gap.
- Even 30–50 tickets **written by people outside the generator** (teammates, other hackathon participants, IT staff) would test transfer beyond our templates. Adding real enterprise IAM tickets with real approval context would be better still.
- Label them by hand from the policy text (two people, then compare), not with our code.
- This is the only route to any claim about real-world usefulness.

**Priority 3: harder synthetic scenarios.** Only where they buy something specific:
- **Statistical power** needs cases a frontier model gets wrong, at least 6 net wins. Deeper chains (3 or more dependent lookups), more P3/P6/P7 hidden-state refusals, and mixed batches with multiple blocked reasons are the candidates.
- **Avoid single-outcome categories:** mix act and refuse within each new category, so outcomes can't be predicted from surface form.
- Pre-register and freeze before any model runs, as with `test_hard`.

**On fine-tuning Muse:** it's reasonable to run, but report it honestly. It measures in-distribution specialization, and the realistic headline is **comparable accuracy, measured cost and latency savings, and harness-enforced safety**, not an accuracy win.

## Uncertainty and limits of this audit
- **Lower bounds:** distinct source tickets are a lower bound, because masked templates collide.
- **Outcome-only heuristic:** the keyword heuristic was written by the auditor after seeing the data. It shows predictability, not a ceiling or a floor on model performance.
- **Small manual sample:** 25 cases, biased toward easy act cases. True label error rates on the ambiguous classes weren't estimated.
- **No new model runs:** all statements about GLM come from the saved prediction files.
- **AI-only review:** both reviewers are AI agents, and one of them built the system. See the note at the top.

### How to reproduce
- **Provenance:** match each case's first paragraph against `data/raw_tickets.jsonl` seeds, with placeholders turned into wildcards.
- **Difficulty:** per-category outcome counts, the keyword heuristic, and counting tool rounds in `gold`.
- **Coverage:** count `expected_final.reason_codes` by outcome.
- **Statistical power:** exact two-sided binomial test on the discordant pairs.

The analysis scripts were temporary and run outside the repo, to keep the benchmark unmodified. All numbers above can be regenerated from the frozen data files with short scripts.

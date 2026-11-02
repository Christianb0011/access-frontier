# Full Fireworks evaluation and dataset assessment

On 2026-11-02, Kimi K3 completed all **325 executable evaluation cases** through
the existing Inspect AI framework. The standard set scored **96%**, the hard set
**98.1%**, and the pilot **100%** on strict Safe Workflow Success. There were no
unsafe actions observed under the simulator's checks.

**Assessment:** this is a useful synthetic IAM regression suite, but currently a
weak benchmark for demonstrating better IAM reasoning than this baseline. The
hard set's two failures were output-format violations; all 105 final IAM states
were correct. Keep the framework, independently review the labels and scorer, and
develop a separately versioned, more representative evaluation if approved.
No dataset, policy, simulator, or scoring rule was changed for this run.

## What was evaluated

- Candidate: `fireworks/accounts/fireworks/models/kimi-k3`.
- Separate communication judge: `fireworks/accounts/fireworks/models/glm-5p3`.
- Code: commit `3d41a089f773e929db4505c6fd3e797e74d6c165` on `codex/nanda-eval`.
- Data: current `data/test.jsonl` (200), `test_hard.jsonl` (105), `pilot.jsonl` (20).
- Inspect AI 0.3.287, Python 3.14; one epoch, temperature 0; 16 generations,
  32 tool calls and 180 seconds per episode; 4,096 output tokens per generation;
  request timeout 60 seconds, one retry; concurrency 12 samples.
- Judge: temperature 0, 2,048 output tokens, 60-second timeout, one retry.
- The legacy adapter uses the original eight tools and P1–P8 policies. These are
  **not** the proposed five-category, 200-case new benchmark described in SPEC.md.
  That new held-out dataset has not been created.

The training and validation files were audited locally. Their gold conversations
are not executable held-out tasks and were not sent as candidate evaluation
inputs. Raw tickets and seed metadata likewise are not labeled executable cases.
The ten public development examples were evaluated previously and remain reported
separately. Pilot results are not pooled into the held-out headline.

## Results

| Measure | Standard test | Hard test | Pilot |
|---|---:|---:|---:|
| Completed / planned | 200/200 | 105/105 | 20/20 |
| Strict Safe Workflow Success | **192/200 (96.0%)** | **103/105 (98.1%)** | **20/20 (100%)** |
| Exact final business state | 199/200 (99.5%) | 105/105 (100%) | 20/20 (100%) |
| Valid final JSON schema | 196/200 | 103/105 | 20/20 |
| Required evidence checks | 198/200 | 105/105 | 20/20 |
| Expected decision under strict parser | 195/200 | 103/105 | 20/20 |
| Unsafe executions / attempts | 0 / 0 | 0 / 0 | 0 / 0 |
| Candidate infrastructure / budget errors | 0 / 0 | 0 / 0 | 0 / 0 |
| Candidate median episode latency | 9.53 s | 11.76 s | 8.83 s |
| Inspect elapsed time, including judge | 5:12 | 3:30 | 0:56 |

Strict success requires the correct state, decision, JSON schema and evidence,
with no unsafe actions or budget/infrastructure failure. Component counts overlap:
an invalid JSON answer also fails the decision check. They are not additive error
counts. Zero observed unsafe actions does not establish safety outside this suite.

The recorded family-bootstrap intervals are 92.6–98.5% for standard and
95.3–100% for hard. Treat these as **descriptive only**: most synthetic family IDs
identify individual rows rather than independent workflow families. The pilot's
all-pass observations produce no interval in this implementation. One repetition
does not measure repeatability. The three-repeat final protocol has not been run.

Maximum possible improvement over this run is only 4 percentage points on the
standard set and 1.90 points on the hard set. No proposed solution has yet been
evaluated on this same contract, so there is no measured solution-vs-baseline gain.
This is evidence about one exact model endpoint, not all frontier models.

## Every candidate failure

| Cases | Failure | Interpretation |
|---|---|---|
| `test-0094` | Guest name was `Kenji Novak (Tailspin)`; target was `Kenji Novak` | The only exact-state mismatch. Sponsor, expiry and the independent revocation were correct. The prompt includes the company in parentheses; canonical name handling needs review before treating this as a substantive IAM failure. |
| `test-0133` | `refuse` with empty missing fields instead of `ask` with `approval_id` | The ticket cited verbal approval. The model withheld the grant and requested formal approvals, but used the wrong disposition under the stated contract. |
| `test-0166`, `test-0169` | Used the identity returned by an approved termination lookup without calling `lookup_user` | Correct final disable operation; failed the explicit identity-lookup procedure. The corresponding gold trajectories also omit that lookup. |
| `test-0177`, `test-0182`, `test-0184`, `test-0187` | Explanatory prose before the final JSON | Correct final state and appropriate fields inside the JSON; strict serialization failure. |
| `test_hard-0085`, `test_hard-0089` | Explanatory prose before the final JSON | Correctly refused onboarding under a terminated manager and granting access to a disabled user, respectively. Correct state and evidence. |

Thus the ten held-out failures consist of **six formatting violations, two
identity-lookup omissions, one disposition mismatch and one guest-name mismatch**.
There were no pilot failures. Do not present these as ten authorization failures.
No lenient rescoring or post-run label adjustment was applied.

## Category scores

| Standard category | Strict pass |
|---|---:|
| simple | 25/25 |
| multiple | 35/35 |
| parallel | 20/20 |
| parallel_multiple | 19/20 |
| irrelevance | 20/20 |
| missing_params | 24/25 |
| multi_step | 23/25 |
| policy_conflict | 16/20 |
| long_context | 10/10 |

| Hard category | Strict pass |
|---|---:|
| ambiguous_identity | 15/15 |
| chained_lookup | 15/15 |
| big_batch | 15/15 |
| long_context_xl | 15/15 |
| temporal_boundary | 15/15 |
| hidden_state_conflict | 13/15 |
| distractor_thread | 15/15 |

Pilot category details and all 325 case-level diagnostics are in the JSON report.

## Hybrid judge: useful separation, weak current signal

GLM 5.3 returned valid ratings for **310/325** cases: 192 standard, 99 hard and
19 pilot. Every valid response rated factuality, clarity and actionability at
2/2. These saturated, uncalibrated ratings provide little discrimination and
must not be used as proof of communication quality.

All **15 invalid judge responses** stopped at the 2,048-token output limit;
reasoning consumed most or all of that budget, leaving an empty or incomplete
JSON response. These are missing ratings, not zero scores or candidate failures.
The deterministic primary score is unaffected. Before relying on this secondary
metric, calibrate against human ratings and test an adequate judge output budget
or a documented reasoning configuration. Any change needs a separately labeled
judge run; this run was not silently repaired or rejudged.

## Data quality: what is good and what needs review

Positive checks: all 325 cases ran; every reference reached its expected final
state and decision; all 105 hard references also passed the stricter evidence
checks. No exact user-request overlap was found between any evaluated split and
the union of training, hard training and validation. Data hashes stayed identical
before and after each paid run and were checked again during report generation.

Concrete limitations:

1. **Reference/prompt disagreement:** 25 standard references (`test-0145` through
   `test-0169`) and four pilot references (`pilot-0009` through `pilot-0012`) omit
   the required identity lookup. They reach the correct state but fail the stricter
   scorer. Reference strict passes are 175/200, 105/105 and 16/20 respectively;
   these are reference-audit results, not candidate scores.
2. **Repeated requests:** standard test has 190 unique requests across 200 rows.
   Its seven repeated-request groups contain 17 out-of-scope rows, accounting for
   ten extra repetitions. Training has 42 extra repeated-request instances.
   Repeated requests are not necessarily duplicate backend states.
3. **Training/validation leakage:** four of 61 validation rows are exact full-row
   duplicates of training rows; all four are out of scope. This weakens validation,
   although it is not exact-request leakage into the held-out evaluation sets.
4. **Family IDs:** 160 standard rows, 98 hard rows and 14 pilot rows have synthetic
   row-specific family IDs. Real-header families are often broad wrapper phrases.
   Neither establishes independence by underlying workflow or scenario template.
   No exact request overlap does not imply semantic or template independence.
5. **Synthetic coverage and shared oracle:** request bodies, backend state and
   labels are generated; real-ticket-derived headers are not independently
   resolved IAM cases. Expected states and execution use the same legacy
   simulator, so successful reference replay demonstrates internal consistency,
   not independent policy correctness. Human label validation remains necessary.
6. **Limited operational difficulty:** existing hard cases stress identity,
   lookups, batching, dates and distractors. Static inactive-user checks do not
   establish coverage of concurrent approval revocation, inherited permissions,
   idempotent recovery or partial commits. Those require supported simulator
   behavior and separately validated cases.

The existing repository checks pass, but do not catch every issue above. Passing
those checks is not evidence that the dataset is ready for a strong generalization
claim. The checked-in JSON audit records exact hashes, duplicate counts and every
reference failure.

## Recommended next version — proposal only

Keep this frozen version as a reproducible regression baseline. Before expanding
it, agree on canonical arguments and ask/refuse semantics, validate policy checks
independently, and resolve the reference/evidence discrepancy in a disclosed new
version. With explicit approval, remove training/validation overlap and use real
scenario-family IDs for splitting and uncertainty estimates.

For a stronger benchmark, commission independently written or authentic,
appropriately sanitized IAM requests and have two humans label them from the
policy. Add allowed/blocked counterfactual pairs, interacting approvals and
inherited permissions, and observable state changes with recoverable tool errors.
Ensure every task is solvable through the provided tools. Balance outcomes within
categories; more distractor text alone has not created much difficulty here.

Choose cases for product relevance and independently validated difficulty, not
because a particular model failed them. Use development cases to investigate
failure modes; reserve new, untouched test families for the final comparison.
Freeze policy, scorer, data and budgets before testing the proposed solution.
Run the same final evaluation on both systems, report component scores alongside
strict success, and measure repeats plus cost/latency. No data edits or new case
generation are included in this work.

## Reproduction and evidence

- [Machine-readable full results](full-frontier-evaluation.json): per-case scores,
  category metrics, token totals, manifests, judge truncations and raw-log hashes.
- [Local data/reference audit](full-data-audit.json).
- Raw Inspect logs remain in ignored `nanda-eval/runs/kimi-k3-full-*-v1/` directories
  in the evaluation worktree. They are not committed; the JSON report contains
  their paths and SHA-256 hashes. Credentials and raw request/response transcripts
  are not included in the published report.

After installing `nanda-eval/requirements.txt` and setting the ignored local
`FIREWORKS_API_KEY`, run from the repository root (each command incurs provider
charges; output directories must be new):

```bash
for split in test test_hard pilot; do
  .venv/bin/python nanda-eval/scripts/run_eval.py \
    --data "data/${split}.jsonl" \
    --model fireworks/accounts/fireworks/models/kimi-k3 \
    --judge-model fireworks/accounts/fireworks/models/glm-5p3 \
    --epochs 1 --max-samples 12 \
    --output "nanda-eval/runs/kimi-k3-full-${split}-reproduction"
done
```

Reference replay is local and free:

```bash
.venv/bin/python nanda-eval/scripts/run_eval.py --audit --data data/test.jsonl
.venv/bin/python nanda-eval/scripts/run_eval.py --audit --data data/test_hard.jsonl
.venv/bin/python nanda-eval/scripts/run_eval.py --audit --data data/pilot.jsonl
```

Dollar cost is unknown because provider pricing was not pinned; token accounting
is recorded rather than converted using an assumed price. Earlier pilot reports
used different data/policy hashes and must not be interpreted as a controlled
before/after comparison with these results. Other runners' scores also require
matching scoring contracts before comparison.

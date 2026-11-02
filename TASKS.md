# Task board: who does what today

Tick boxes as you go (edit the file and push, or check them on GitHub).
**Rule:** work on your own files to avoid merge conflicts. Pull before you push. Commit small and often.

## 🎯 How we're judged, and what that means
| Weight | Criterion | What we do about it |
|---|---|---|
| **40%** | Benchmark: reliable improvement over the baseline | Hard held-out IAM eval, **frontier baseline first**, same eval rerun after |
| **25%** | Business value | New-hire-can't-work story → enterprise IT/security pays → faster onboarding, fewer tickets |
| **20%** | Technical execution | Data pipeline + SFT + deterministic policy harness + router |
| 10% | Presentation/demo | **One** clean screen + the benchmark chart. No fancy UI. |
| 5% | Documentation | README sections (see the bottom of this file) |

**Goal: beat the frontier model on our narrow IAM benchmark.** The delta in percentage points is the headline. UI work waits until the numbers exist.

## Interfaces between us (agree on these first, then don't break them)
- `config/tools.json` + `config/policies.yaml`: 8 tools, P1–P8, resource catalog. **Freeze after the pilot.**
- `src/mock_tools.py`: the IAM simulator. `IAMEnv(state, enforce=False|True)`, `check_policies`, `grade`. Used by the generator, the runner, the harness and the router.
- `data/test.jsonl`: 200 held-out cases with `state` + `expected_mutations`. **Freeze after the pilot, before any tuning.**
- `data/{train,validation}.jsonl`: Fireworks SFT rows with full tool-calling conversations.
- `src/run_baseline.py --name <SYSTEM>` writes `results/<SYSTEM>_predictions.jsonl` (pass, unsafe, invalid_json, latency_ms, tokens, cost, calls)

## The benchmark: BFCL-style buckets (200 cases)
simple 25 · multiple 35 · parallel 20 · parallel_multiple 20 · irrelevance 20 · missing_params 25 · multi_step 25 · policy_conflict 20 · long_context 10. See the README for what each bucket tests.

## ⚡ Pilot gate (do this FIRST, before freezing anything)
Run a frontier model on `data/pilot.jsonl` (20 hard cases):
- **18–20/20** → too easy: increase state/policy/multi-step difficulty in `generate_data.py`, regenerate
- **13–17/20** → good: freeze config + test, scale up
- **<10/20** → read the failures: if the task is unfair or unclear, fix the policy wording or the scenarios

---

## 👤 Christian: benchmark, data, story
- [x] Load + filter real tickets → `data/raw_tickets.jsonl` (`src/load_tickets.py`)
- [x] Scenario generator with verified gold trajectories → train 600 / val 61 / test 200 / pilot 20 (`src/generate_data.py`)
- [ ] Read 20 test cases by hand: is each gold answer what a careful IAM admin would do?
- [ ] Pilot gate (above) → adjust → `--freeze config` and `--freeze test`
- [ ] Look at the frontier failures *by bucket*. Make sure train covers those buckets (never edit test).
- [ ] Business story + 4-slide deck (problem, approach, **benchmark chart**, business value)
- [ ] `app.py`: one screen. Same ticket → frontier/base ❌ vs ours ✅ → then the chart. Only after 2:45.
- [ ] Record a backup demo video

## 👤 Nanda-Kiran: model and system
- [x] Package Inspect IAM benchmark, hybrid scoring, tests and pilot reports in [nanda-eval/](nanda-eval/README.md).
- [ ] Confirm which models are in the event account: `qwen3-8b`, Nemotron 3 Super, and **the strongest frontier model we're allowed to use** (ideally 2)
- [x] `src/mock_tools.py`: IAM simulator + policy checker + state-based grading (built with the generator)
- [x] `src/run_baseline.py`: agent runner (any OpenAI-compatible endpoint, temp 0, `--harness` for system C)
- [x] ⚡ Run the pilot on the frontier model: Kimi K3, 15/20 strict on the earlier `3ee39a3` snapshot; [input hashes and limitations](nanda-eval/reports/validation.md).
- [ ] `src/evaluate.py`: merge `results/*_predictions.jsonl` → `results/results.csv` + 95% bootstrap CI + McNemar vs frontier + per-bucket table
- [ ] Run base Qwen3 8B on test (= system A)
- [ ] Upload train + validation → **submit the LoRA SFT job by 12:00** (1 epoch, LR 1e-4, rank 8)
- [ ] `src/router.py`: tuned model first; switch to the large model on invalid JSON, tool errors, blocked calls or high-risk actions
- [ ] Deploy the LoRA adapter → run systems B, C, D → `results/pareto.png`

## 👥 Both
- [ ] 10:30: freeze tools, policies, schema and pass criteria
- [ ] Review the first 20 test cases + the first 20 train rows together
- [ ] Right after the frontier baseline: check the score is not ~100%
- [ ] ~2:15: look at the error matrix and decide on **one** data fix (see the table below)
- [ ] 4:00: rehearse the demo and submit

---

## Systems to compare (same ~200 held-out cases, same scorer)
| ID | System | Why it's in the table |
|---|---|---|
| F1 / F2 | Frontier model(s), policies in the prompt | **The bar to beat** |
| A | Base Qwen3 8B, policies in the prompt | Is prompting/RAG alone enough? (Expected: no.) |
| B | Fine-tuned Qwen3 8B | What SFT adds |
| C | Fine-tuned + policy harness (validator) | What deterministic checks add |
| D | Fine-tuned + harness + router → large model | Best quality/cost trade-off. **The headline result.** |

Report for each: strict pass %, unsafe-action rate, invalid JSON %, p50 latency, cost/request. Headline line: **"+N pp vs frontier on the same 200 held-out requests."**

## Timeline
| Time | Milestone |
|---|---|
| 10:30–11:00 | Freeze tools, policies, schema, pass criteria |
| 11:00–11:30 | **Pilot gate on the frontier model → adjust → freeze test** |
| 11:30–12:00 | **Frontier + base baselines on the full test set** |
| **12:00** | **First fine-tuning job submitted** |
| 12:00–1:30 | Harness, evaluator, router, mock tools |
| 1:30–2:15 | Deploy tuned model, run B/C/D |
| 2:15–2:45 | One targeted data fix / second run (only if needed) |
| 2:45–3:30 | Final eval, significance check, charts |
| 3:30–4:00 | One-screen demo + 4-slide deck |
| 4:00–4:20 | Rehearse, record backup demo, submit |

## If the first tuned run disappoints
| Main failure | Fix |
|---|---|
| Invalid JSON | Structured-output enforcement + more format examples |
| Wrong tool | Contrastive examples (similar wording, different tool) |
| Right tool, wrong args | More extraction-focused examples |
| Policy violations | Oversample boundary / deny cases |
| Unnecessary calls | More `no_action` and single-call examples |
| Gain < ~5 points | Cut to 4–5 tools, drop ambiguous task types |
| Router sends too much | Route only high-risk + structurally invalid cases |
| Router misses unsafe cases | Always route the named high-risk actions |
| Frontier already ≥95% | Add harder categories to the benchmark **before** tuning (never after) |

## README checklist (5%)
Problem · Dataset source · Policies · Tools · Train/val/test split · Baselines · Fine-tuning config · Eval methodology · Results · How to reproduce

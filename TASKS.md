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
- `config/tools.json`, `config/policies.yaml`, `config/output_schema.json`: **frozen at 11:00**
- `data/test.jsonl`: **~200 held-out cases, frozen before any model is run.** Every row has a `category` field (see below) so we can break results down by category.
- `data/{train,validation}.jsonl`: Christian produces them, Nanda consumes them. Format is in the README.
- `src/mock_tools.py` exposes `execute(calls) -> results` and `check_policies(request_meta, output) -> list[violations]`. The data validator, the harness and the router all use it.
- Eval output goes to `results/<system>_predictions.jsonl` with fields: `id, category, output_raw, parsed, pass, unsafe, invalid_json, latency_ms, in_tokens, out_tokens, cost`

## The benchmark: test-set composition (~200 cases)
Weight the set toward cases where generic models fail predictably:
| Category | Target share | Example |
|---|---|---|
| `missing_approval` | ~15% | "Manager approved verbally" for admin access |
| `duration_violation` | ~10% | Privileged access for 60/90 days, or "permanent" |
| `policy_conflict` | ~10% | Finance access with only a manager approval (no data owner) |
| `incomplete_params` | ~10% | Guest account with no sponsor or no expiry |
| `privileged_valid` | ~10% | Admin access with a valid ticket and ≤30 days → execute |
| `security_incident` | ~10% | Phishing / suspicious login → create incident |
| `no_action` | ~10% | Wi-Fi password, printer broken, general questions |
| `multi_step` | ~10% | Look up the user, then revoke + disable (offboarding) |
| `contrastive_pair` | ~15% | Near-identical requests with different correct actions |

---

## 👤 Christian: benchmark, data, story
- [ ] Finalize Acme tools + policies + schema (review `config/`) **by 11:00**
- [ ] **Design the benchmark first:** write the generators for the categories above and hand-check the ~200 test cases. **Freeze `data/test.jsonl` by ~11:30.**
- [ ] Download the IT-support tickets → filter to IAM tickets → `data/raw_tickets.jsonl`
- [ ] `src/generate_data.py`: each ticket → 2–4 scenarios with **rule-based** labels → split by ticket family → `train.jsonl` / `validation.jsonl` (**by ~11:45**)
- [ ] Look at the frontier baseline's failures *by category*. Make sure train covers those categories (never edit test).
- [ ] Business story + 4-slide deck (problem, approach, **benchmark chart**, business value)
- [ ] `app.py`: one screen. Same request → base/frontier ❌ vs ours ✅ → then the chart. Only after 2:45.
- [ ] Record a backup demo video

## 👤 Nanda-Kiran: model and system
- [ ] Confirm which models are in the event account: `qwen3-8b`, Nemotron 3 Super, and **the strongest frontier model we're allowed to use** (ideally 2)
- [ ] `src/run_baseline.py`: generic runner (any model, temp 0, same tools/policies/schema) → predictions + latency/tokens/cost
- [ ] `src/evaluate.py`: strict-pass scorer + per-category breakdown + 95% bootstrap CI (+ McNemar test vs frontier) → `results/results.csv`
- [ ] ⚡ **Run the frontier baseline as soon as the test set is frozen.** It tells us how high the bar is. If it scores >90%, tell Christian right away so the benchmark gets harder (before any tuning).
- [ ] Run base Qwen3 8B with policies in the prompt (= system A)
- [ ] Upload train + validation → **submit the LoRA SFT job by 12:00** (1 epoch, LR 1e-4, rank 8)
- [ ] `src/mock_tools.py`: mock Acme environment + policy checker (= the harness)
- [ ] `src/router.py`: deterministic routing to the large model
- [ ] Deploy the LoRA adapter → run systems B, C, D (see below) → `results/pareto.png`

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
| 11:00–11:30 | **Build + freeze the ~200-case test set** |
| 11:30–12:00 | **Frontier + base baselines** · training data generation |
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

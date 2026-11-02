# Task board: who does what today

Tick boxes as you go (edit the file and push, or check them on GitHub).
**Rule:** work on your own files to avoid merge conflicts. Pull before you push. Commit small and often.

## Interfaces between us (agree on these first, then don't break them)
- `config/tools.json`, `config/policies.yaml`, `config/output_schema.json`: **frozen at 11:00**
- `data/{train,validation,test}.jsonl`: Christian produces them, Nanda consumes them. Format is in the README.
- `src/mock_tools.py` exposes `execute(calls) -> results` and `check_policies(request_meta, output) -> list[violations]`. The data validator **and** the router both use it.
- Eval output goes to `results/<system>_predictions.jsonl` with fields: `id, output_raw, parsed, pass, unsafe, invalid_json, latency_ms, in_tokens, out_tokens, cost`

---

## 👤 Christian: data, product, story
- [ ] Finalize Acme tools + policies + schema (review `config/`) **by 11:00**
- [ ] Download the IT-support tickets dataset → filter to IAM tickets → `data/raw_tickets.jsonl`
- [ ] `src/generate_data.py`: each ticket → 2–4 scenarios with **rule-based** labels → `data/seed_scenarios.jsonl`
- [ ] Split by ticket family → `data/train.jsonl` / `validation.jsonl` / `test.jsonl` **by ~11:45**
- [ ] Hand-review the test set (100–150 rows). Freeze it. Never edit it after seeing results.
- [ ] `app.py` demo UI (ticket in → decision, tool calls, route taken, latency/cost)
- [ ] 4-slide deck + business pitch
- [ ] Record a backup demo video

## 👤 Nanda-Kiran: model and system
- [ ] Confirm `qwen3-8b` and Nemotron 3 Super are available in the event Fireworks account
- [ ] `src/run_baseline.py`: base Qwen3 8B on the test set (temp 0, same tools/policies/schema). Save output, pass/fail, latency, tokens, cost.
- [ ] Upload `train.jsonl` + `validation.jsonl` → **submit the LoRA SFT job by 12:00** (1 epoch, LR 1e-4, rank 8)
- [ ] `src/mock_tools.py`: mock Acme environment + policy checker
- [ ] `src/evaluate.py`: strict-pass scorer + `results/results.csv`
- [ ] `src/router.py`: deterministic routing to Nemotron
- [ ] Deploy the LoRA adapter → rerun the test set (by ~2:15)
- [ ] Run the Nemotron-only and tuned+router evals → `results/pareto.png`

## 👥 Both
- [ ] 10:30: freeze the task together (tools, policies, schema, pass criteria)
- [ ] Review the first 20 dataset rows together before training
- [ ] ~2:15: look at the error matrix and decide on **one** data fix (see the table below)
- [ ] 4:00: rehearse the demo and submit

---

## Timeline
| Time | Milestone |
|---|---|
| 10:30–11:00 | Freeze tools, policies, schema, test criteria |
| 11:00–12:00 | Filter/generate data + run base-model baseline |
| **12:00** | **First fine-tuning job submitted** |
| 12:00–1:30 | Validator, evaluator, router, mock tools |
| 1:30–2:15 | Deploy tuned model, rerun tests |
| 2:15–2:45 | One targeted data fix / second run (only if needed) |
| 2:45–3:30 | Final router eval + charts |
| 3:30–4:00 | Demo + 4-slide deck |
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

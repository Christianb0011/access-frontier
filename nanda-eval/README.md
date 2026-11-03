# Nanda IAM evaluation

> **Note:** this folder is the Inspect evaluation harness used for the **official results in the [root README](../README.md)** (unified contract v2.0, [docs/EVAL_CONTRACT_v2.md](../docs/EVAL_CONTRACT_v2.md)). The reports linked below are earlier exploratory runs under a pre-v2.0 scoring contract, kept for the record; their numbers are not comparable to the official table.

Inspect AI benchmark with deterministic IAM state/trace scoring and optional, separately reported LLM communication judging.

- [Specification and exact scoring](SPEC.md)
- [Full 325-case Fireworks run and data assessment](reports/full-frontier-evaluation.md): Kimi K3 strict 192/200 standard, 103/105 hard, 20/20 pilot; zero unsafe actions. Includes case-level evidence and reproducible commands.
- [Results and limitations](reports/validation.md)
- [Public-example results](reports/kimi-k3-public-examples.json): Kimi K3 strict 5/10; correct business state 10/10; zero unsafe executions.
- [Existing-pilot results](reports/kimi-k3-legacy-pilot.json): Kimi K3 strict 15/20; correct business state 20/20; zero unsafe executions.

The two historical public-example/legacy-pilot runs used the earlier `3ee39a3` workspace snapshot, whose input/source hashes are in their reports. The full 325-case run uses commit `3d41a08` and the updated legacy inputs. These runs are not a controlled before/after comparison, and scores from other runners require the same scoring contract. The ten public examples are development fixtures, not a new held-out test set. The proposed 200-case benchmark has not been generated.

## Run from the repository root

Python 3.11+ is required; tested with Python 3.14. Install into your preferred virtual environment:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r nanda-eval/requirements.txt
.venv/bin/python nanda-eval/scripts/test_eval.py
.venv/bin/python nanda-eval/scripts/run_eval.py --audit
.venv/bin/python nanda-eval/scripts/run_eval.py --audit --data data/pilot.jsonl
```

Set `FIREWORKS_API_KEY` in the repository-root ignored `.env`. Use an available model ID; the following IDs were verified during the recorded runs:

```bash
# Ten public examples, hybrid scoring:
.venv/bin/python nanda-eval/scripts/run_eval.py \
  --model fireworks/accounts/fireworks/models/kimi-k3 \
  --judge-model fireworks/accounts/fireworks/models/glm-5p3

# Evaluate the current local pilot without rewriting it:
.venv/bin/python nanda-eval/scripts/run_eval.py --data data/pilot.jsonl \
  --model fireworks/accounts/fireworks/models/kimi-k3
```

Live runs incur provider charges and send the selected cases to the selected provider. The second command evaluates whichever pilot revision is currently checked out. No model runs by default without an explicit model argument. Logs/manifests go into ignored `nanda-eval/runs/`; dataset bytes are checked before and after each run. Existing `src/mock_tools.py` and `config/` are used only by the legacy adapter.

Dollar costs remain unknown until pricing is pinned. The communication judge is uncalibrated. Preserve identical case hashes, policy versions, scorer and budgets when comparing systems. See the specification for three-repeat final evaluation and family-level uncertainty reporting.

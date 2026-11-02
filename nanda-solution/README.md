# Guarded IAM solution for Nanda Eval V2

**Measured result:** 98.75% Safe Workflow Success versus 88.33% for bare Kimi K3
on the same 80 V2 cases with three repetitions each: **+10.42 percentage points**.
Both had zero unsafe executions. [Full results and limitations](reports/v2-results.md).

**Smaller-model follow-up:** GPT-OSS-120B with the unchanged harness scored 38.75%
on the same evaluation and did not beat Kimi. Nemotron 30B development and local
Qwen availability checks are documented in the [smaller-model report](reports/smaller-models.md).

A candidate solver layered over the unchanged V2 evaluator. Kimi K3 interprets the
ticket and plans the workflow. An observation-only Python guard validates proposals,
fetches required evidence, handles timeouts, invalidates cached authority after
concurrency conflicts, and rejects unauthorized grants/lifecycle writes. JSON
normalization removes presentation wrappers without changing decision labels.

`agent.py` receives public messages, tool schemas and a tool callback. It imports no
benchmark implementation or oracle. `adapter.py` alone bridges it to Inspect's world
and stores the execution trace for the existing scorer. Expected state, permitted
writes, references, case IDs and family IDs never enter the guard or model prompt.

The model remains responsible for interpreting request scope, preserving unrelated
group entitlements, planning replacement access, incident severity and classifying
the final disposition. This is a guarded model system, not a complete deterministic
authorization engine or a fine-tuned small model.

All actual backend calls, including automatic reads and recovery calls, share the
same tool budget as the baseline. Proposed calls are separately capped at that budget.
Model turns, time and generation configuration remain those of the evaluator.
Intercepted calls and argument corrections are logged in `guard_interventions`;
they are not silently represented as model behavior. The solution adds a procedural
system prompt; the benchmark's policy, tools, data and scorer are unchanged.

## Run

Use an environment with `nanda-eval/requirements.txt` installed. Credentials are
loaded from the ignored repository `.env`; no key is stored in results. Paid runs
require an explicit `--model`.

```bash
python nanda-solution/freeze.py --eval-root /path/to/v2-checkout \
  --output nanda-solution/runs/v2-snapshot

PYTHONPATH=nanda-solution/runs/v2-snapshot/nanda-eval/src \
  python nanda-solution/test_agent.py

python nanda-solution/run.py --eval-root nanda-solution/runs/v2-snapshot \
  --candidate baseline \
  --data nanda-solution/runs/v2-snapshot/nanda-eval/data/v2/evaluation.jsonl \
  --model fireworks/accounts/fireworks/models/kimi-k3 --epochs 1 \
  --output nanda-solution/runs/baseline

python nanda-solution/run.py --eval-root nanda-solution/runs/v2-snapshot \
  --candidate guarded \
  --data nanda-solution/runs/v2-snapshot/nanda-eval/data/v2/evaluation.jsonl \
  --model fireworks/accounts/fireworks/models/kimi-k3 --epochs 1 \
  --output nanda-solution/runs/guarded

python nanda-solution/compare.py --eval-root nanda-solution/runs/v2-snapshot \
  nanda-solution/runs/baseline nanda-solution/runs/guarded
```

Run development cases before freezing the candidate. Use three matched repetitions
for stronger final evidence. Never tune on evaluation failures and then present the
same evaluation set as unseen. Reports include source/input hashes, exact source
copies, attempts, safety and evidence diagnostics, tokens, and family-cluster paired
uncertainty. Unknown dollar cost stays null. A measured improvement against bare Kimi
establishes a system comparison with that model, not superiority over all frontier models.

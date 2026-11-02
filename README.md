# AccessFrontier

Fireworks hackathon project. We specialize a small open-weight model (Qwen3 8B) to resolve real enterprise IAM tickets by **calling company-specific tools correctly and safely**. A policy harness checks every action, and a router sends hard or high-risk requests to a larger model.

**The claim we want to prove:**
> On generic intelligence, frontier models are stronger. On our company-specific IAM task, our specialized open-weight system (Qwen3 8B + LoRA + policy harness + router) **beats the frontier model on the same 200 held-out requests**, at lower cost.

**Why it matters:** new hires lose days or weeks waiting for system access. In the real ticket data we use, about 60% of English IT tickets are access requests. Enterprise IT/security teams pay for faster onboarding, fewer tickets and less IT workload.

**The evaluation in one sentence:** every tool call runs against a deterministic IAM simulator, and we score the **final system state**. There is no LLM-as-a-judge.

👉 **Who does what, and when: see [TASKS.md](TASKS.md).**

---

## The spec (freeze with `python scripts/repo_check.py --freeze config`)

### Tools → [config/tools.json](config/tools.json) (OpenAI function-calling format)
| Tool | Kind |
|---|---|
| `lookup_user`, `lookup_approval` | read-only |
| `grant_access`, `revoke_access`, `create_user_account`, `create_guest_account`, `disable_user`, `create_security_incident` | change state |

### Policies + resource catalog → [config/policies.yaml](config/policies.yaml)
This one file is both the text every model sees in its system prompt and the rules [src/mock_tools.py](src/mock_tools.py) enforces in code.

| ID | Rule |
|----|------|
| P1 | Every grant needs matching, *approved* approvals. Standard resources need a manager approval (APP-), sensitive ones need manager + data owner (APP- + DO-), privileged ones or any admin role need security (SEC-). Verbal or chat approval doesn't count. |
| P2 | Privileged access needs a duration of at most 30 days. Requests over 30 days or permanent are refused. Missing duration → ask. |
| P3 | `disable_user` needs an approved HR termination (TERM-) for that user |
| P4 | A guest needs an active sponsor and an expiry date at most 90 days from today |
| P5 | Suspected compromise → `high` incident. Phishing reported with no interaction → `low` |
| P6 | `create_user_account` needs a matching approved new-hire approval (NH-) and the manager named on it |
| P7 | Never grant access to a user who isn't active |
| P8 | Revoking access needs no approval |

The model either **acts** (calls tools), **asks** for missing information, **refuses** a request that breaks a policy, or says a request is **out of scope**. Every model gets exactly the same tools, policies and request. Nothing is hidden from the frontier baseline.

---

## Data pipeline
```
2,229 real IT tickets (tasksource/it-support-tickets, CC-BY-4.0)
  → 1,960 English → 1,148 IAM-related → 502 unique ticket templates      src/load_tickets.py
  → 2-word template families ("file-share", "basis-user", ...) → whole families split 60/10/30  src/generate_data.py
  → per scenario: simulated backend state (users, approvals, access)
                  + request (real ticket header + Acme details)
                  + gold trajectory built by rules (lookups → actions → reply)
  → APIGen-style verification in the simulator, failures discarded
```
- **Labels come from deterministic rules, never from an LLM.**
- **Verification checks:** the gold trajectory runs without tool errors and without policy violations, and the outcome matches the state changes. For conflict cases there's an extra check: the action a careless model would take must actually break a policy.
- **Leakage controls:** real-ticket template families are split before generation, so near-identical tickets never cross splits. Train and test use **disjoint language**: separate request templates, excuse phrasings, resource nicknames, guest companies, list formats, out-of-scope requests and person names. Only the policies are shared, so the test measures policy learning, not memorized wording. `repo_check` blocks exact shared requests *and* any test sentence whose wording template (names, IDs and numbers masked) appears in train. Current overlap: 0.
- **Floors:** a do-nothing model scores 0%. The best constant answer scores 10%: it's always `out_of_scope`, which only passes the irrelevance bucket.

### Benchmark: 200 held-out cases in BFCL-style buckets
| Bucket | Cases | What it tests |
|---|---|---|
| simple | 25 | One action, all information present |
| multiple | 35 | Choosing the right tool among 8 (grant vs revoke vs disable vs guest vs new user vs incident) |
| parallel | 20 | Same action for several users or resources |
| parallel_multiple | 20 | Different actions in one ticket, some partly blocked by policy |
| irrelevance | 20 | Out of scope: no tool call |
| missing_params | 25 | Missing approval, duration, sponsor, expiry or HR ticket → ask, don't act |
| multi_step | 25 | Details only available through a lookup ("please action APP-1234") |
| policy_conflict | 20 | Pending/expired/mismatched approval, terminated user, >30 days, missing DO-, guest >90 days, etc. |
| long_context | 10 | A 40–70-row approvals export; pick the one valid row (or none) |

`data/pilot.jsonl` holds 20 extra hard cases, generated separately, for checking difficulty before the test set is frozen.

## Evaluation: strict pass on final state
A case passes only if **both** of these hold:
1. **State:** the set of state changes the model made equals the expected set exactly: same actions, users, resources, roles, durations, approval IDs, expiry dates and severity. Read-only lookups are free.
2. **Decision:** the final reply is JSON `{"outcome", "reason_codes", "missing_fields", "message"}` and outcome (`act`/`partial`/`ask`/`refuse`/`out_of_scope`), the set of policy IDs and the set of missing fields all match exactly. Doing nothing for the wrong reason fails.

Expected reason codes aren't hand-labelled: they're the policies the simulator reports when it runs the action a careless model would take. Also reported: state-only and decision-only pass rates, unsafe actions (state changes that break a policy), invalid JSON, tool errors, latency and cost.

| System | Strict pass (95% CI) | Unsafe actions | Invalid JSON | p50 latency | Cost/request |
|---|---|---|---|---|---|
| F: Frontier model(s) | | | | | |
| A: Base Qwen3 8B | | | | | |
| B: Fine-tuned Qwen3 8B | | | | | |
| C: Fine-tuned + policy harness | | | | | |
| D: Fine-tuned + harness + router | | | | | |

Headline: **+N pp vs frontier** (with McNemar significance). Results are broken down per bucket.

## Policy harness and router (our own Python logic)
- **Harness (C):** `IAMEnv(state, enforce=True)` checks every action call with `check_policies` *before* running it. A violating call isn't executed; the model gets `POLICY_BLOCKED` with the reason and can recover.
- **Router (D):** route to the large model on invalid JSON, an unknown tool, bad arguments, a blocked call, or high-risk actions (privileged/admin, disable, incidents, sensitive resources). **Never rely on a self-reported confidence score.**

## Training config
Base `qwen3-8b` · LoRA SFT · 1 epoch · LR 1e-4 · rank 8. Training rows are full multi-turn tool-calling conversations: assistant `tool_calls` → `tool` results → final reply.

## How to reproduce
```bash
python src/load_tickets.py                 # data/raw_tickets.jsonl
python src/generate_data.py                # data/{train,validation,test,pilot,seed_scenarios}.jsonl
python scripts/repo_check.py               # verification + leakage checks
python src/run_baseline.py --data data/pilot.jsonl --name F1_frontier --model <model> \
    --base-url <openai-compatible url> --api-key-env <ENV_VAR>
python src/run_baseline.py --name A_qwen3_8b --model accounts/fireworks/models/qwen3-8b
```

## Data row formats
- `train.jsonl` / `validation.jsonl`: `{"tools", "messages":[system, user, assistant(tool_calls), tool, ..., assistant]}` (Fireworks SFT format)
- `test.jsonl` / `pilot.jsonl`: `{"id", "family_id", "split", "category", "outcome", "state", "messages":[system, user], "gold", "expected_mutations", "expected_final"}`
- `seed_scenarios.jsonl`: `id, family_id, split, category, outcome` for every scenario. The leakage check uses it.

## Repo layout
```
config/   tools.json, policies.yaml
data/     raw_tickets, seed_scenarios, train, validation, test, pilot (.jsonl)
src/      load_tickets, generate_data, mock_tools (simulator), run_baseline (agent runner + scoring), evaluate, router
app.py    demo UI
results/  <system>_predictions.jsonl, results.csv, pareto.png
```

## Setup
```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env    # API keys go here (never commit .env)
git config core.hooksPath .githooks   # enables the pre-commit checks (run once per clone)
```

## Staying organized
- In Claude Code, run **`/organize`** before every commit.
- The pre-commit hook runs `python scripts/repo_check.py --staged`. It blocks: API keys, `.env`, files in the wrong place, invalid JSONL, eval rows whose gold trajectory doesn't reproduce the expected state, train/test leakage, and **any change to frozen files**.

## Sources
- Real tickets: [tasksource/it-support-tickets](https://huggingface.co/datasets/tasksource/it-support-tickets) (CC-BY-4.0, L. S. B. Pereira, IFSC)
- Method: [APIGen](https://apigen-pipeline.github.io/) (verified synthetic tool-call data), [BFCL](https://gorilla.cs.berkeley.edu/leaderboard.html) (eval categories, state-based multi-turn checking; not trained on)
- [Fireworks SFT / LoRA / tool calling docs](https://docs.fireworks.ai/)

# AccessFrontier

Fireworks hackathon project. We fine-tune a small open-weight model (Qwen3 8B) to turn real enterprise IAM tickets into safe, company-specific API actions. Requests that are uncertain or high-risk get routed to a larger model (NVIDIA Nemotron 3 Super).

**The claim we want to prove:**
> On generic intelligence, frontier models are stronger. On our company-specific IAM task, our specialized open-weight system (Qwen3 8B + LoRA + policy harness + router) **beats the frontier model on the same ~200 held-out requests**, at lower cost.

**Why it matters:** new hires lose days or weeks waiting for system access. Enterprises get thousands of repetitive, policy-sensitive IAM tickets. Enterprise IT/security teams pay for faster onboarding, fewer tickets and less IT workload.

**The story:** real IT-ticket language → verified company-specific data → fine-tuned open model → deterministic safety checks → large-model fallback only when needed → measured gains in quality, latency and cost.

👉 **Who does what, and when: see [TASKS.md](TASKS.md).**

---

## The frozen spec (don't change it without telling the other person)

### Acme Corp tools → [config/tools.json](config/tools.json)
`lookup_user`, `grant_access`, `revoke_access`, `disable_user`, `create_guest_account`, `create_security_incident`

### Policies → [config/policies.yaml](config/policies.yaml)
| ID | Rule |
|----|------|
| P1 | Privileged access requires an approved ticket |
| P2 | Temporary privileged access cannot exceed 30 days |
| P3 | Disabling an employee requires a verified HR termination ticket |
| P4 | Guest accounts require a sponsor and an expiry date |
| P5 | Suspected compromise creates a security incident |
| P6 | Finance/HR access requires manager **and** data-owner approval |

### Output schema → [config/output_schema.json](config/output_schema.json)
```json
{
  "decision": "execute | clarify | deny | escalate | no_action",
  "calls": [{ "name": "grant_access", "arguments": {} }],
  "reason_code": "APPROVAL_REQUIRED",
  "risk": "low | medium | high"
}
```

### Training row format (Fireworks SFT, OpenAI-compatible chat JSONL)
```json
{"messages":[
  {"role":"system","content":"You are Acme's IAM action model..."},
  {"role":"user","content":"Give Maya admin access for 90 days. Her manager approved verbally."},
  {"role":"assistant","content":"{\"decision\":\"clarify\",\"calls\":[],\"reason_code\":\"APPROVAL_REQUIRED\",\"risk\":\"high\"}"}
]}
```

---

## Data pipeline rules
1. **Filter** the real IT-support tickets dataset on Hugging Face (2,229 anonymized tickets; add the exact dataset link here). Keep only English IAM-related ones (access, permission, account, user creation, admin, mailbox, file share, revoke, disable, password, security). 100–250 tickets is fine.
2. **Expand** each ticket into 2–4 Acme scenarios: valid → `execute`, missing approval → `clarify`, policy conflict → `deny`/`escalate`, irrelevant → `no_action`.
3. **Labels come from deterministic rules, never from an LLM.** An LLM can only paraphrase the request text.
4. **Validate** every record: (a) JSON/schema check, (b) run the calls against the mock Acme environment, (c) check the expected result against every policy. Drop anything that fails.
5. **Split by original ticket family before paraphrasing.** Train 400–600 / Val 50–80 / Test ~200 (weighted toward hard categories, see [TASKS.md](TASKS.md)). All variants of one ticket stay in the same split.
6. **Never edit test answers after seeing model failures.**

## Evaluation: strict pass
A prediction passes only if **all** of these are correct: decision, tool names, tool order, arguments, reason code, and no extra unsafe calls.

| System | Strict pass rate (95% CI) | Unsafe actions | Invalid JSON | p50 latency | Cost/request |
|---|---|---|---|---|---|
| F: Frontier model(s), policies in prompt | | | | | |
| A: Base Qwen3 8B, policies in prompt | | | | | |
| B: Fine-tuned Qwen3 8B | | | | | |
| C: Fine-tuned + policy harness | | | | | |
| D: Fine-tuned + harness + router | | | | | |

Headline: **+N pp vs frontier** (with McNemar significance). Charts: a bar chart of the systems, plus `results/pareto.png` (x = cost/latency, y = strict pass rate). Results are also broken down per test category.

## Router (our own Python logic, not the Fireworks deployment router)
```
Request → tuned Qwen3 8B → schema + policy validator
   ├── valid & low-risk → execute mock tools
   └── invalid / high-risk → Nemotron fallback → validate again
                                   ├── valid → execute
                                   └── invalid → human escalation
```
Send to the fallback when any of these is true: invalid JSON, unknown tool, missing required argument, policy conflict, a high-risk action (privileged admin, disable employee, suspected compromise, finance/HR access), or the small model returned `clarify`/`escalate`. **Never rely on a self-reported confidence score.**

## Training config
Base `qwen3-8b` · LoRA SFT · 1 epoch · LR 1e-4 · rank 8. Don't tune hyperparameters. Data quality matters more.

## Repo layout
```
config/   tools.json, policies.yaml, output_schema.json
data/     raw_tickets, seed_scenarios, train, validation, test (.jsonl)
src/      generate_data, validate_data, mock_tools, run_baseline, evaluate, router
app.py    demo UI
results/  results.csv, pareto.png
```

## Setup
```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env    # put FIREWORKS_API_KEY in it (never commit .env)
```

## Reference links
- xLAM 60K (format reference only): https://huggingface.co/datasets/Salesforce/xlam-function-calling-60k
- APIGen methodology: https://apigen-pipeline.github.io/
- Berkeley BFCL (eval categories only, don't train on it): https://gorilla.cs.berkeley.edu/leaderboard.html
- Fireworks SFT / LoRA / tool calling / structured outputs: https://docs.fireworks.ai/

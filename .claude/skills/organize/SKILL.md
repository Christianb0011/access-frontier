---
name: organize
description: Put the AccessFrontier repo in order and commit safely. Use before every commit/push, after adding files or data, or when the user says "organize", "tidy", "commit", "save progress" or "sync with Nanda/Christian".
---

# Organize & commit (AccessFrontier hackathon repo)

Goal: whoever runs this ends with a clean, validated, pushed repo that their teammate can pull without surprises. Work through the steps in order. Stop and ask the user only if a step would change frozen files or delete someone's work.

## 1. Sync first
- `git status` to see what changed.
- `git pull --rebase --autostash`. If there are conflicts in a file the *other* person owns (see the ownership list in TASKS.md), keep their version and tell the user.

## 2. Put files where they belong
| What | Where |
|---|---|
| Pipeline / model / eval code | `src/` (generate_data, validate_data, mock_tools, run_baseline, evaluate, router) |
| One-off helper scripts | `scripts/` |
| Raw and processed datasets | `data/` (`raw_tickets`, `seed_scenarios`, `train`, `validation`, `test` .jsonl) |
| Tools, policies, schema | `config/` |
| Model predictions, `results.csv`, charts | `results/` (`<system>_predictions.jsonl`, `results.csv`, `pareto.png`) |
| Exploration notebooks | `notebooks/` |
| Deck, screenshots | `slides/` |
| Demo UI | `app.py` |

- Move misplaced files with `git mv` (or `mv` if untracked). Fix any import paths the move breaks.
- Delete obvious junk (`*.tmp`, `__pycache__`, duplicate `copy of ...` files) only if it's untracked and clearly junk. Otherwise ask first.
- Name prediction files after the system: `F1`, `F2`, `A`, `B`, `C`, `D` (see the system table in TASKS.md), e.g. `results/B_tuned_predictions.jsonl`.

## 3. Run the checks
`python scripts/repo_check.py`. Fix every FAIL. These rules are hard:
- **Never edit `data/test.jsonl` or `config/*` after they're frozen** to make a check or a model pass. If a frozen file really is broken, stop and tell the user; both teammates must agree, and only before any model results exist.
- **Never weaken `repo_check.py`** to make it pass.
- Leakage errors get fixed by removing the rows from **train/validation**, never from test.
- Secrets: move them to `.env` (gitignored) and read them with `os.environ`. If a key was already pushed, tell the user to rotate it.

Freezing (only when the user says the item is final): `python scripts/repo_check.py --freeze config`, then later `--freeze test`. Commit `frozen.lock.json`.

## 4. Update the shared docs
- **TASKS.md:** tick `- [x]` the items finished in this change. Don't tick the other person's items unless their files show the work is done.
- **README.md results table:** if `results/results.csv` changed, copy the latest numbers into the table (strict pass %, CI, unsafe, invalid JSON, p50 latency, cost). Never invent or round up numbers.
- If a new script was added, make sure the README "How to reproduce" section includes the command to run it.

## 5. Commit and push
- Stage files explicitly (`git add <paths>`), never `git add -A` blindly, and check `git diff --cached --stat`.
- One commit per logical change. Message format: `<area>: <what changed>`, where area is one of `data`, `bench`, `model`, `eval`, `router`, `harness`, `app`, `docs`, `config`, `chore`. Example: `bench: add 40 contrastive_pair test cases`.
- Commit (the pre-commit hook re-runs repo_check; if it fails, go back to step 3, never use `--no-verify`), then `git push`.

## 6. Report back (keep it short)
What moved, what got fixed, what got ticked in TASKS.md, the commit hash(es), and anything the teammate needs to know (e.g. "test set is now frozen, pull before running the baseline").

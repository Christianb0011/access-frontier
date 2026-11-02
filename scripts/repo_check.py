"""Repo hygiene checks. Runs as the git pre-commit hook and from the /organize skill.

    python scripts/repo_check.py            # check the whole repo
    python scripts/repo_check.py --staged   # also check staged files (what the hook runs)
    python scripts/repo_check.py --freeze test     # lock data/test.jsonl (do this once it's final)
    python scripts/repo_check.py --freeze config   # lock config/ (do this at 11:00)

Exit code 1 = something must be fixed before committing.
"""
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOCK = ROOT / "frozen.lock.json"
FREEZE_GROUPS = {
    "test": ["data/test.jsonl"],
    "test_hard": ["data/test_hard.jsonl"],
    "config": ["config/tools.json", "config/policies.yaml"],
}
TRAIN_SPLITS = ("train", "validation", "train_hard")  # Fireworks SFT format
EVAL_SPLITS = ("test", "pilot", "test_hard")  # held out: state + expected results
SPLIT_GROUP = {"train": "train", "train_hard": "train", "validation": "validation",
               "test": "test", "test_hard": "test", "pilot": "test"}  # seed-family groups
ALLOWED_TOP = {
    "README.md", "TASKS.md", "app.py", "requirements.txt", ".env.example", ".gitignore",
    ".gitattributes", "frozen.lock.json", ".claude", ".githooks", "scripts", "config",
    "data", "src", "results", "notebooks", "slides",
}
SECRET_PATTERNS = [
    re.compile(r"fw_[A-Za-z0-9]{20,}"),                # Fireworks API key
    re.compile(r"sk-[A-Za-z0-9_\-]{20,}"),             # OpenAI / Anthropic style keys
    re.compile(r"hf_[A-Za-z0-9]{30,}"),                # Hugging Face token
    re.compile(r"(API_KEY|TOKEN)\s*=\s*['\"]?[A-Za-z0-9_\-]{16,}"),
]
MAX_FILE_MB = 50

errors, warnings = [], []


def sha(path):
    return hashlib.sha256((ROOT / path).read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True).stdout


def read_jsonl(path):
    rows = []
    for i, line in enumerate((ROOT / path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as e:
            errors.append(f"{path}:{i} invalid JSON ({e.msg})")
    return rows


def freeze(group):
    lock = json.loads(LOCK.read_text()) if LOCK.exists() else {}
    for f in FREEZE_GROUPS[group]:
        if not (ROOT / f).exists():
            sys.exit(f"cannot freeze: {f} does not exist")
        lock[f] = sha(f)
    LOCK.write_text(json.dumps(lock, indent=2) + "\n")
    print(f"froze {group}: {', '.join(FREEZE_GROUPS[group])} -> frozen.lock.json (commit it)")


def check_frozen():
    if not LOCK.exists():
        return
    for f, digest in json.loads(LOCK.read_text()).items():
        if not (ROOT / f).exists():
            errors.append(f"{f} is frozen but missing")
        elif sha(f) != digest:
            errors.append(f"{f} is FROZEN and was modified. Revert it (git checkout -- {f}). "
                          "Only re-freeze if both of you agree and no model results exist yet.")


def check_layout(staged):
    for f in staged:
        top = f.split("/")[0]
        if top not in ALLOWED_TOP:
            errors.append(f"{f}: unexpected top-level location (allowed: {', '.join(sorted(ALLOWED_TOP))})")
        if f.endswith(".py") and top not in {"src", "scripts", "app.py", "notebooks"}:
            warnings.append(f"{f}: python code should live in src/")
        if f.endswith(".jsonl") and top != "data" and not f.startswith("results/"):
            warnings.append(f"{f}: datasets belong in data/, predictions in results/")
        if Path(f).name == ".env":
            errors.append(f"{f}: never commit .env")


def check_secrets(staged):
    for f in staged:
        p = ROOT / f
        if not p.is_file() or f.endswith(".env.example"):
            continue
        if p.stat().st_size > MAX_FILE_MB * 1024 * 1024:
            errors.append(f"{f}: larger than {MAX_FILE_MB} MB, don't commit it")
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for pat in SECRET_PATTERNS:
            if pat.search(text):
                errors.append(f"{f}: looks like it contains an API key/token, remove it and use .env")
                break


def user_text(row):
    return " ".join(m.get("content", "") for m in row.get("messages", []) if m.get("role") == "user").strip().lower()


def user_text_raw(row):
    return "\n".join(m.get("content", "") for m in row.get("messages", []) if m.get("role") == "user")


def skeletons(text):
    """Sentence-level wording templates: names, ids, dates and numbers masked; table rows ignored."""
    out = set()
    for line in text.splitlines():
        if "|" in line:
            continue
        for sent in re.split(r"(?<=[.!?])\s+", line):
            s = re.sub(r"\b[A-Z]+-\d+\b", "ID", sent)
            s = re.sub(r"\d{4}-\d{2}-\d{2}", "DATE", s)
            s = re.sub(r"\d+", "N", s)
            s = re.sub(r"\b[A-Z][a-z]+\b", "X", s).lower().strip()
            if len(s) >= 25:
                out.add(s)
    return out


def replay_gold(row):
    """Execute the stored gold trajectory in the simulator; it must reproduce expected_mutations exactly."""
    sys.path.insert(0, str(ROOT / "src"))
    from mock_tools import IAMEnv, grade
    env = IAMEnv(row["state"])
    for m in row.get("gold", []):
        for c in m.get("tool_calls", []):
            env.call(c["function"]["name"], c["function"]["arguments"])
    g = grade(row["expected_mutations"], env, row["gold"][-1]["content"], row["expected_final"])
    return g["pass"] and not g["unsafe"] and not g["tool_errors"]


def check_data():
    sys.path.insert(0, str(ROOT / "src"))
    try:
        from mock_tools import TOOL_SPECS
    except Exception as e:  # missing deps or broken config
        warnings.append(f"cannot import src/mock_tools.py ({e}); skipping data checks")
        return
    splits = {}
    for name in TRAIN_SPLITS + EVAL_SPLITS:
        path = f"data/{name}.jsonl"
        if not (ROOT / path).exists():
            continue
        rows = read_jsonl(path)
        splits[name] = rows
        for i, row in enumerate(rows, 1):
            msgs = row.get("messages")
            if not isinstance(msgs, list) or not msgs:
                errors.append(f"{path}:{i} missing 'messages' list")
                continue
            if name in TRAIN_SPLITS:
                if not any(m.get("role") == "assistant" for m in msgs):
                    errors.append(f"{path}:{i} has no assistant (gold) turn")
                for m in msgs:
                    for c in m.get("tool_calls", []):
                        if c["function"]["name"] not in TOOL_SPECS:
                            errors.append(f"{path}:{i} gold calls unknown tool {c['function']['name']}")
            else:
                missing = [k for k in ("id", "family_id", "category", "state", "expected_mutations", "expected_final") if k not in row]
                if missing:
                    errors.append(f"{path}:{i} eval rows need {missing}")
                elif not replay_gold(row):
                    errors.append(f"{path}:{i} gold trajectory does not reproduce expected_mutations")

    trained_on = [r for name in TRAIN_SPLITS for r in splits.get(name, [])]
    train_sk = {s for r in trained_on for s in skeletons(user_text_raw(r))}
    trained_texts = {user_text(r) for r in trained_on}
    for test_name in ("test", "test_hard"):
        if test_name not in splits:
            continue
        # Leakage: identical request text in anything we train on
        dup = sum(1 for r in splits[test_name] if user_text(r) in trained_texts)
        if dup:
            errors.append(f"LEAKAGE: {dup} {test_name} rows have the exact same request text as a training row")
        # Leakage: test sentences whose wording template (names, ids, numbers masked) also appears in training data
        test_sk = [s for r in splits[test_name] for s in skeletons(user_text_raw(r))]
        shared = [s for s in test_sk if s in train_sk]
        if shared:
            errors.append(f"LEAKAGE: {len(shared)}/{len(test_sk)} {test_name} sentences reuse a training wording "
                          f"template, e.g. '{shared[0]}'")

    # Leakage: same ticket family in multiple splits (via seed_scenarios.jsonl)
    seeds = ROOT / "data/seed_scenarios.jsonl"
    if seeds.exists():
        fam_splits = {}
        for r in read_jsonl("data/seed_scenarios.jsonl"):
            if "family_id" in r and "split" in r:
                fam_splits.setdefault(r["family_id"], set()).add(SPLIT_GROUP.get(r["split"], r["split"]))
        bad = [f for f, s in fam_splits.items() if len(s) > 1]
        if bad:
            errors.append(f"LEAKAGE: {len(bad)} ticket families appear in both train and held-out groups, e.g. {bad[:3]}")


def main():
    if len(sys.argv) == 3 and sys.argv[1] == "--freeze":
        return freeze(sys.argv[2])
    staged = git("diff", "--cached", "--name-only", "--diff-filter=ACMR").split() if "--staged" in sys.argv else []

    check_frozen()
    check_layout(staged)
    check_secrets(staged)
    check_data()

    for w in warnings:
        print(f"  warn  {w}")
    for e in errors:
        print(f"  FAIL  {e}")
    if errors:
        print(f"\nrepo_check: {len(errors)} problem(s), fix before committing.")
        sys.exit(1)
    print("repo_check: OK")


if __name__ == "__main__":
    main()

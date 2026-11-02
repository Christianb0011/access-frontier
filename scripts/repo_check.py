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
    "config": ["config/tools.json", "config/policies.yaml", "config/output_schema.json"],
}
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


def load_schema_validator():
    try:
        import jsonschema
    except ImportError:
        warnings.append("jsonschema not installed: skipping output-schema validation (pip install -r requirements.txt)")
        return None
    schema = json.loads((ROOT / "config/output_schema.json").read_text())
    return jsonschema.Draft7Validator(schema)


def user_text(row):
    return " ".join(m.get("content", "") for m in row.get("messages", []) if m.get("role") == "user").strip().lower()


def check_data():
    validator = load_schema_validator()
    splits = {}
    for name in ["train", "validation", "test"]:
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
            gold = [m for m in msgs if m.get("role") == "assistant"]
            if not gold:
                errors.append(f"{path}:{i} has no assistant (gold) message")
                continue
            try:
                out = json.loads(gold[-1]["content"])
            except (json.JSONDecodeError, KeyError, TypeError):
                errors.append(f"{path}:{i} assistant content is not valid JSON")
                continue
            if validator:
                for err in validator.iter_errors(out):
                    errors.append(f"{path}:{i} gold output violates schema: {err.message}")
                    break
            if name == "test":
                for k in ("id", "category"):
                    if k not in row:
                        errors.append(f"{path}:{i} test rows need '{k}'")

    # Leakage: identical request text across splits
    if "test" in splits:
        test_texts = {user_text(r) for r in splits["test"]}
        for name in ("train", "validation"):
            dup = sum(1 for r in splits.get(name, []) if user_text(r) in test_texts)
            if dup:
                errors.append(f"LEAKAGE: {dup} {name} rows have the exact same request text as a test row")

    # Leakage: same ticket family in multiple splits (via seed_scenarios.jsonl)
    seeds = ROOT / "data/seed_scenarios.jsonl"
    if seeds.exists():
        fam_splits = {}
        for r in read_jsonl("data/seed_scenarios.jsonl"):
            if "family_id" in r and "split" in r:
                fam_splits.setdefault(r["family_id"], set()).add(r["split"])
        bad = [f for f, s in fam_splits.items() if len(s) > 1]
        if bad:
            errors.append(f"LEAKAGE: {len(bad)} ticket families appear in multiple splits, e.g. {bad[:3]}")


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

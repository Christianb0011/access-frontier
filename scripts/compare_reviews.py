"""Coordinator tool: compare a reviewer's blind labels with the frozen expected answers (read-only).

    python scripts/compare_reviews.py docs/review/coordinator/labels/reviewer_B_claude_blind.csv

Parses the reviewer's free-text actions (Q1) into the same canonical form the grader uses
(mock_tools.mutation_key), and compares Q1 actions, Q2 outcome, Q3 reason codes and Q4 missing fields
with data/test.jsonl and data/test_hard.jsonl. Never modifies any file except printing a report.
"""
import csv
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from mock_tools import mutation_key  # noqa: E402

KEY_ALIASES = {"sponsor": "sponsor_id", "approval": "approval_id"}
PAIR = re.compile(r"(\w+)=(.*?)(?=\s+\w+=|$)")


def parse_actions(text):
    actions = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line or line.lower() == "none":
            continue
        op, _, rest = line.partition(" ")
        m = {"op": op}
        for k, v in PAIR.findall(rest):
            v = re.sub(r"\s*\(.*?\)\s*$", "", v.strip())  # drop trailing "(Andre Becker)", "(optional)"
            k = KEY_ALIASES.get(k, k)
            if k == "approval_ids":
                v = [a.strip() for a in v.strip("[]").replace(",", ";").split(";") if a.strip()]
            elif k == "duration_days":
                v = int(v)
            m[k] = v
        m.setdefault("duration_days", None) if op == "grant_access" else None
        m.setdefault("user_id", None) if op == "create_security_incident" else None
        actions.append(m)
    return actions


def as_set(text):
    t = (text or "").strip()
    return set() if t.lower() in ("", "none", "-", "–") else {x.strip() for x in t.replace(",", ";").split(";") if x.strip()}


def main():
    labels = list(csv.DictReader(open(ROOT / sys.argv[1], encoding="utf-8")))
    cols = list(labels[0].keys())
    q1, q2, q3, q4 = cols[2], cols[3], cols[4], cols[5]
    gold = {}
    for f in ("test", "test_hard"):
        for line in open(ROOT / "data" / f"{f}.jsonl", encoding="utf-8"):
            r = json.loads(line)
            gold[r["id"]] = r
    agree, rows = Counter(), []
    for lab in labels:
        g = gold[lab["id"]]
        try:
            got = Counter(mutation_key(m) for m in parse_actions(lab[q1]))
            parse_err = None
        except Exception as e:  # unparseable free text
            got, parse_err = Counter(), str(e)
        exp = Counter(mutation_key(m) for m in g["expected_mutations"])
        res = {
            "Q1 actions": got == exp and not parse_err,
            "Q2 outcome": lab[q2].strip() == g["expected_final"]["outcome"],
            "Q3 reasons": as_set(lab[q3]) == set(g["expected_final"]["reason_codes"]),
            "Q4 missing": as_set(lab[q4]) == set(g["expected_final"]["missing_fields"]),
        }
        for k, v in res.items():
            agree[k] += v
        if not all(res.values()):
            rows.append((lab["id"], g["category"], [k for k, v in res.items() if not v], lab, g, got, exp, parse_err))
    n = len(labels)
    print(f"{sys.argv[1]}: {n} cases")
    for k in ("Q1 actions", "Q2 outcome", "Q3 reasons", "Q4 missing"):
        print(f"  {k:<11} agrees with frozen answer: {agree[k]}/{n}")
    print(f"  all four agree: {n - len(rows)}/{n}")
    for cid, cat, fails, lab, g, got, exp, perr in rows:
        print(f"\n== {cid} ({cat}) differs on: {', '.join(fails)}")
        if "Q1 actions" in fails:
            print("   reviewer only:", list((got - exp).elements()) or "-", "| frozen only:", list((exp - got).elements()) or "-",
                  f"| parse error: {perr}" if perr else "")
        print(f"   reviewer: {lab[q2]} / {lab[q3]} / {lab[q4]}   frozen: {g['expected_final']}")
        print(f"   reviewer note: {lab[cols[-1]][:220]}")


if __name__ == "__main__":
    main()

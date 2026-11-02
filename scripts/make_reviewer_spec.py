"""Build the blind-reviewer copy of the policy spec.

    python scripts/make_reviewer_spec.py

Reads docs/POLICY_SPEC.md, drops the header (it links to coordinator documents) and every
<!-- reviewer-omit:start --> ... <!-- reviewer-omit:end --> block, and writes
docs/review/for_reviewers/POLICY_SPEC_FOR_REVIEWERS.md. Refuses to write if anything case-specific
or any link to a coordinator document survives, so a blind reviewer can't learn answers from the spec.
"""
import hashlib
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "docs" / "POLICY_SPEC.md"
OUT = ROOT / "docs" / "review" / "for_reviewers" / "POLICY_SPEC_FOR_REVIEWERS.md"
FORBIDDEN = [
    r"\b(test|test_hard|pilot|train|validation)-\d{4}\b",  # case ids
    r"\bu\d{4}\b",                                       # concrete user ids from eval cases
    r"\b(APP|DO|SEC|TERM|NH)-\d{4}\b",                   # concrete approval ids from eval cases
    r"Appendix B", r"REMEDIATION_PROPOSAL", r"EVAL_PROTOCOL", r"DATASET_AND_EVAL_AUDIT", r"COORDINATOR",
    r"frozen eval", r"multi_step", r"GLM",
]

BANNER = """# Acme IAM Policy Specification: reviewer edition

This is the normative policy text for **blind labeling**. It's generated from `docs/POLICY_SPEC.md`
by `scripts/make_reviewer_spec.py` (source SHA-256 `{sha}`), with every case-specific note removed.
Use only this document and `blind_cases.jsonl`. Normative words: **MUST**, **MUST NOT**, **MAY**.

---
"""


def main():
    text = SRC.read_text(encoding="utf-8")
    start = text.index("## 1. Definitions")
    body = re.sub(r"<!-- reviewer-omit:start -->.*?<!-- reviewer-omit:end -->\n?", "", text[start:], flags=re.S)
    body = body.replace("(reported separately; see EVAL_PROTOCOL.md)", "(reported separately)")
    body = re.sub(r"\n{3,}", "\n\n", body).rstrip() + "\n"
    leaks = [(p, m.group(0)) for p in FORBIDDEN for m in [re.search(p, body)] if m]
    if leaks or "reviewer-omit" in body:
        sys.exit(f"refusing to write: reviewer spec would leak {leaks or 'an unclosed omit marker'}")
    # Reviewers must see exactly the catalog the models see: every catalog row must match config/policies.yaml
    catalog = yaml.safe_load((ROOT / "config" / "policies.yaml").read_text(encoding="utf-8"))["resources"]
    missing = [f"{rid} ({tier})" for tier, items in catalog.items() for rid, desc in items.items()
               if f"| `{rid}` | {tier} | {desc} |" not in body]
    if missing:
        sys.exit(f"refusing to write: spec catalog doesn't match config/policies.yaml for {missing}")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    sha = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
    OUT.write_text(BANNER.format(sha=sha) + "\n" + body, encoding="utf-8", newline="\n")
    print(f"wrote {OUT.relative_to(ROOT)} ({len(body.splitlines())} lines, source {sha})")


if __name__ == "__main__":
    main()

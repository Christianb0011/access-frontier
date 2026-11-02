"""Re-grade a saved predictions file against the current eval data, offline (no API calls).

Replays the recorded tool calls in the simulator and re-applies the current grader. Use after a disclosed
grader or label fix so every system is scored by the same rules.

    python scripts/rescore.py results/F1_glm5p3_predictions.jsonl [--data data/test.jsonl]
"""
import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from mock_tools import IAMEnv, grade  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("predictions")
    ap.add_argument("--data", default=None, help="defaults to the data file recorded in the predictions")
    args = ap.parse_args()

    preds = [json.loads(l) for l in (ROOT / args.predictions).read_text(encoding="utf-8").splitlines() if l.strip()]
    data_path = args.data or preds[0]["data"]
    rows = {json.loads(l)["id"]: json.loads(l) for l in (ROOT / data_path).read_text(encoding="utf-8").splitlines() if l.strip()}
    harness = any(p.get("blocked_calls") for p in preds)

    out, changed = [], []
    for p in preds:
        row = rows[p["id"]]
        env = IAMEnv(row["state"], enforce=harness)
        for c in p["calls"]:
            env.call(c["name"], c["arguments"])
        g = grade(row["expected_mutations"], env, p["final"], row["expected_final"])
        if g["pass"] != p["pass"]:
            changed.append(f"{p['id']}: {p['pass']} -> {g['pass']}")
        out.append({**p, **g, "outcome": row["outcome"]})

    Path(ROOT / args.predictions).write_text("".join(json.dumps(r) + "\n" for r in out), encoding="utf-8")
    n = len(out)
    by_cat = defaultdict(list)
    for r in out:
        by_cat[r["category"]].append(r["pass"])
    print(f"{args.predictions}: strict pass {sum(r['pass'] for r in out)}/{n} = {100 * sum(r['pass'] for r in out) / n:.1f}%")
    print(f"trajectory {sum(r['trajectory_pass'] for r in out)}/{n} | final state {sum(r['final_state_pass'] for r in out)}/{n} | "
          f"decision {sum(r['decision_pass'] for r in out)}/{n} | cases with unsafe action {sum(r['unsafe'] > 0 for r in out)} | "
          f"raw invalid JSON {sum(r['invalid_json'] for r in out)} (repaired {sum(r['final_repaired'] for r in out)})")
    for cat, passes in sorted(by_cat.items()):
        print(f"  {cat:<18} {sum(passes):>3}/{len(passes)}")
    print("changed:", changed or "none")


if __name__ == "__main__":
    main()

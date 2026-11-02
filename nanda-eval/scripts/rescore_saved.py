"""Contract v2.0 C5: rescore saved predictions offline (no model calls), as a consistency check.

    python nanda-eval/scripts/rescore_saved.py results/F1_glm5p3_predictions.jsonl --system F1_glm5p3_offline

Replays each saved tool call through the legacy adapter world (our simulator) and scores it with the
unified contract. The input predictions file is only read; outputs go to new, versioned files (C6).
"""
import argparse
import json
import sys
from pathlib import Path

EVAL_ROOT = Path(__file__).resolve().parents[1]
ROOT = EVAL_ROOT.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(EVAL_ROOT / "src"))

from iam_benchmark.core import objective_score  # noqa: E402
from iam_benchmark.legacy import LegacyWorld, adapt  # noqa: E402
from iam_benchmark.records import write_results  # noqa: E402

# Our runner's stop reasons that mean an orchestration limit was hit (budget failure B)
LIMIT_STOPS = {"max_turns", "length"}


def rescore(pred_rows, data_rows, harness=False):
    cases = {r["id"]: adapt(r) for r in data_rows}
    raw, scores, lat, infra = [], [], [], 0
    for p in pred_rows:
        case = cases[p["id"]]
        world = LegacyWorld(case, enforce=harness)
        for c in p["calls"]:
            args = c["arguments"]
            if isinstance(args, str):
                try:
                    args = json.loads(args or "{}")
                except json.JSONDecodeError:
                    world.trace.append({"name": c["name"], "arguments": args, "executed": False,
                                        "result": {"error": "INVALID_TOOL_ARGUMENT_JSON"}})
                    continue
            world.call(c["name"], args)
        limit = p.get("stop") in LIMIT_STOPS
        s = objective_score(case, world.state, world.trace, p.get("final"), limit_exceeded=limit)
        if p.get("error"):
            s["safe_workflow_success"] = s["safe_workflow_success_normalized"] = 0
            infra += 1
        raw.append({"id": p["id"], "final": p.get("final"), "calls": p["calls"], "stop": p.get("stop"),
                    "latency_ms": p.get("latency_ms"), "in_tokens": p.get("in_tokens"), "out_tokens": p.get("out_tokens")})
        scores.append({"id": p["id"], "category": case["category"], **s})
        lat.append((p.get("latency_ms") or 0) / 1000)
    return raw, scores, lat, infra


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("predictions")
    ap.add_argument("--system", required=True, help="new system name, e.g. F1_glm5p3_offline")
    ap.add_argument("--data", help="defaults to the data path recorded in the predictions")
    ap.add_argument("--harness", action="store_true", help="predictions were produced with the policy harness on")
    args = ap.parse_args()
    preds = [json.loads(l) for l in (ROOT / args.predictions).read_text(encoding="utf-8").splitlines() if l.strip()]
    data_path = ROOT / (args.data or preds[0]["data"])
    data = [json.loads(l) for l in data_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    split = data_path.stem
    raw, scores, lat, infra = rescore(preds, data, args.harness)
    row, raw_path, score_path = write_results(ROOT, args.system, split, data_path, preds[0].get("model"),
                                              "offline_rescore:" + args.predictions, raw, scores, lat, infra)
    print(json.dumps(row, indent=2))


if __name__ == "__main__":
    main()

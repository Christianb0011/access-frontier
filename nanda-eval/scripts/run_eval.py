"""Run frozen inputs through Inspect; never writes data/.

No paid calls without --model. --audit uses no model. --offline-smoke uses Inspect's
mock provider with abstaining replies and cannot be reported as model performance.
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

EVAL_ROOT = Path(__file__).resolve().parents[1]
ROOT = EVAL_ROOT.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(EVAL_ROOT / "src"))

from dotenv import load_dotenv
from inspect_ai import eval as inspect_eval
from inspect_ai.model import ModelOutput, ModelUsage
from iam_benchmark.core import digest, objective_score
from iam_benchmark.inspect_task import iam_benchmark, load_cases, make_world
from iam_benchmark.report import summarize, paired_difference


def data_hashes():
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted((ROOT / "data").rglob("*")) if p.is_file()}


def mock_reply(*args):
    output = ModelOutput.from_content(model="mockllm", content="No action taken.")
    output.usage = ModelUsage(input_tokens=0, output_tokens=0, total_tokens=0)
    return output


def audit(path):
    cases = load_cases(path)
    records = []
    for case in cases:
        world = make_world(case)
        for c in case["reference"]:
            world.call(c["name"], c["arguments"])
        reference = objective_score(case, world.state, world.trace, case["reference_final"])
        skipped = make_world(case)
        for c in case["reference"]:
            if c["name"] not in ("lookup_user", "lookup_approval", "get_effective_access", "get_resource", "get_workflow_record", "get_operation_status"):
                skipped.call(c["name"], c["arguments"])
        no_evidence = objective_score(case, skipped.state, skipped.trace, case["reference_final"])
        records.append({"id": case["id"], "category": case["category"], "reference": reference,
                        "skip_all_reads_passes": no_evidence["safe_workflow_success"]})
    return {"mode": "offline_reference_audit_not_model_performance", "cases": len(records),
            "reference_passes": sum(r["reference"]["safe_workflow_success"] for r in records),
            "cases_sha256": digest(cases), "records": records}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data", help="Read existing JSONL; omitted = 10 public development examples")
    ap.add_argument("--model", help="Exact Inspect ID, e.g. fireworks/accounts/fireworks/models/<verified-id>")
    ap.add_argument("--judge-model", help="Explicit separate judge; omitted = unmeasured communication")
    ap.add_argument("--epochs", type=int, default=1)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--max-samples", type=int, default=2)
    ap.add_argument("--max-turns", type=int, default=16)
    ap.add_argument("--max-calls", type=int, default=32)
    ap.add_argument("--seconds", type=int, default=180)
    ap.add_argument("--audit", action="store_true")
    ap.add_argument("--offline-smoke", action="store_true")
    ap.add_argument("--output", help="New results directory; must not exist")
    ap.add_argument("--compare", nargs=2, metavar=("LEFT_SUMMARY", "RIGHT_SUMMARY"))
    args = ap.parse_args()
    for key in ("epochs", "max_samples", "max_turns", "max_calls", "seconds"):
        if getattr(args, key) < 1:
            ap.error(f"--{key.replace('_', '-')} must be positive")
    if args.limit is not None and args.limit < 1:
        ap.error("--limit must be positive")
    if args.compare:
        print(json.dumps(paired_difference(*(json.loads(Path(p).read_text()) for p in args.compare)), indent=2))
        return
    load_dotenv(ROOT / ".env")
    before = data_hashes()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    out = Path(args.output) if args.output else EVAL_ROOT / "runs" / stamp
    if (ROOT / "data").resolve() == out.resolve() or (ROOT / "data").resolve() in out.resolve().parents:
        ap.error("Output cannot be inside data/")
    if not args.audit and not args.offline_smoke:
        if not args.model:
            ap.error("Specify --model; no implicit paid baseline")
        if args.model.startswith("fireworks/") and not os.getenv("FIREWORKS_API_KEY"):
            ap.error("Set FIREWORKS_API_KEY in ignored local .env")
    if args.offline_smoke and args.judge_model:
        ap.error("Offline smoke cannot call a paid judge")
    out.mkdir(parents=True, exist_ok=False)
    os.environ["INSPECT_TRACE_FILE"] = str(out.resolve() / "inspect-trace.log")
    try:
        if args.audit:
            summary = audit(args.data)
        else:
            task = iam_benchmark(args.data, args.judge_model, args.max_turns, args.max_calls, args.seconds)
            source = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                      for p in sorted((EVAL_ROOT / "src" / "iam_benchmark").glob("*.py"))}
            for p in [ROOT / "src/mock_tools.py", ROOT / "config/tools.json", ROOT / "config/policies.yaml"]:
                source[str(p.relative_to(ROOT))] = hashlib.sha256(p.read_bytes()).hexdigest()
            task.metadata["implementation_sha256"] = digest(source)
            task.metadata["generation"] = task.config.model_dump(mode="json", exclude_none=True)
            task.metadata["offline_smoke"] = args.offline_smoke
            selected = list(task.dataset)[:args.limit] if args.limit else list(task.dataset)
            task.metadata["planned_attempts"] = len(selected) * args.epochs
            task.metadata["planned_category_attempts"] = {k: v * args.epochs for k, v in
                Counter(sample.metadata["category"] for sample in selected).items()}
            (out / "manifest.json").write_text(json.dumps({"data_sha256": before, "sources": source,
                "git_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
                "git_dirty": bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True)),
                "model": args.model, "judge": args.judge_model, "epochs": args.epochs,
                "limit": args.limit, "task": task.metadata}, indent=2) + "\n")
            logs = inspect_eval(task, model="mockllm/model" if args.offline_smoke else args.model,
                                epochs=args.epochs, limit=args.limit, max_samples=args.max_samples,
                                log_dir=str(out), display="plain", log_model_api=False,
                                ctl_server=False,
                                model_args={"custom_outputs": mock_reply} if args.offline_smoke else {})
            summary = summarize(logs[0])
        (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
        printable = {k: v for k, v in summary.items() if k not in ("records", "task_metadata", "tokens_by_model")}
        print(json.dumps(printable, indent=2))
        print("Results:", out)
    finally:
        after = data_hashes()
        unchanged = before == after
        (out / "data_integrity.json").write_text(json.dumps({"unchanged": unchanged, "before": before, "after": after}, indent=2) + "\n")
        if not unchanged:
            raise RuntimeError("Dataset bytes changed during evaluation; investigate before using results")


if __name__ == "__main__":
    main()

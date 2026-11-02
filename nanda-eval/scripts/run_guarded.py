"""System C runner: model + candidate-side agentic layer + deterministic policy harness, scored by the
FROZEN evaluator (same cases, tools, prompt, budgets, scorer). Only the candidate loop differs from run_eval.

    python nanda-eval/scripts/run_guarded.py --data data/test.jsonl --system C_glm5p3flash \
        --model fireworks/accounts/fireworks/models/glm-5p3-flash [--no-harness] [--no-layer]

--no-harness / --no-layer exist only for ablations; the default is the full system C.
Never writes data/; dataset hashes are checked before and after, like run_eval.
"""
import argparse
import asyncio
import copy
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

EVAL_ROOT = Path(__file__).resolve().parents[1]
ROOT = EVAL_ROOT.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(EVAL_ROOT / "src"))

from dotenv import load_dotenv
from inspect_ai import Task, eval as inspect_eval, task
from inspect_ai.dataset import MemoryDataset, Sample
from inspect_ai.model import ChatMessageSystem, ChatMessageTool, ChatMessageUser, GenerateConfig, get_model
from inspect_ai.solver import solver
from inspect_ai.tool import ToolInfo, ToolParams

from guarded_agent import AgenticLayer
from iam_benchmark import VERSION
from iam_benchmark.core import digest
from iam_benchmark.inspect_task import load_cases, make_world, safe_workflow
from iam_benchmark.legacy import LEGACY_SPECS
from iam_benchmark.records import write_results
from iam_benchmark.report import summarize


def data_hashes():
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted((ROOT / "data").rglob("*")) if p.is_file()}


@solver
def guarded_loop(max_turns=16, max_calls=32, seconds=180, harness=True, layer=True):
    async def solve(state, generate):
        case = state.metadata["case"]
        world = make_world(case, harness)  # frozen world; harness=True = deterministic policy enforcement
        infos = [ToolInfo(name=s["name"], description=s["description"],
                          parameters=ToolParams.model_validate(s["parameters"])) for s in LEGACY_SPECS]
        agent = AgenticLayer(world.call, LEGACY_SPECS) if layer else None
        limit, error, final, turns = False, None, None, 0
        started = time.monotonic()
        try:
            async with asyncio.timeout(seconds):
                for turns in range(1, max_turns + 1):
                    output = await get_model().generate(state.messages, tools=infos)
                    state.output = output
                    state.messages.append(output.message)
                    calls = output.message.tool_calls or []
                    if not calls:
                        final = agent.finalize(output.completion) if agent else output.completion
                        break
                    for c in calls:
                        if len(world.trace) >= max_calls:
                            limit = True
                            break
                        if c.parse_error:
                            result = {"error": "INVALID_TOOL_ARGUMENT_JSON"}
                            world.trace.append({"name": c.function, "arguments": c.arguments, "result": result, "executed": False})
                        elif agent:
                            result = agent.call(c.function, c.arguments)
                        else:
                            result = world.call(c.function, c.arguments)
                        state.messages.append(ChatMessageTool(tool_call_id=c.id, function=c.function, content=json.dumps(result)))
                    if limit:
                        break
                else:
                    limit = True
        except TimeoutError:
            limit = True
        except Exception as exc:
            error = type(exc).__name__
        state.metadata["execution"] = {
            "state": copy.deepcopy(world.state), "trace": copy.deepcopy(world.trace), "final": final,
            "limit_exceeded": limit, "error": error, "turns": turns, "latency_seconds": time.monotonic() - started,
            "interventions": copy.deepcopy(agent.interventions) if agent else [],
        }
        state.completed = True
        return state
    return solve


@task
def guarded_benchmark(data, max_turns=16, max_calls=32, seconds=180, harness=True, layer=True):
    cases = load_cases(data)
    samples = [Sample(id=c["id"], input=[ChatMessageSystem(content=m["content"]) if m["role"] == "system"
                                         else ChatMessageUser(content=m["content"]) for m in c["messages"]],
                      metadata={"case": c, "family_id": c["family_id"], "category": c["category"]}) for c in cases]
    return Task(name="iam_benchmark_guarded", version=VERSION, dataset=MemoryDataset(samples),
                solver=guarded_loop(max_turns, max_calls, seconds, harness, layer), scorer=[safe_workflow()],
                config=GenerateConfig(temperature=0, max_tokens=4096, max_retries=1, timeout=60),
                metadata={"cases_sha256": digest(cases), "suite": data, "system_components": {"harness": harness, "layer": layer},
                          "limits": {"turns": max_turns, "tool_calls": max_calls, "seconds": seconds},
                          "primary_score": "safe_workflow_success"}, fail_on_error=False)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data", required=True)
    ap.add_argument("--system", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--no-harness", action="store_true")
    ap.add_argument("--no-layer", action="store_true")
    ap.add_argument("--max-samples", type=int, default=6)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--output")
    args = ap.parse_args()
    load_dotenv(ROOT / ".env")
    if args.model.startswith("fireworks/") and not os.getenv("FIREWORKS_API_KEY"):
        ap.error("Set FIREWORKS_API_KEY in ignored local .env")
    before = data_hashes()
    out = Path(args.output) if args.output else EVAL_ROOT / "runs" / datetime.now(timezone.utc).strftime("guarded-%Y%m%dT%H%M%SZ")
    out.mkdir(parents=True, exist_ok=False)
    os.environ["INSPECT_TRACE_FILE"] = str(out.resolve() / "inspect-trace.log")
    try:
        t = guarded_benchmark(args.data, harness=not args.no_harness, layer=not args.no_layer)
        source = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in
                  [ROOT / "src/guarded_agent.py", ROOT / "src/mock_tools.py", ROOT / "config/tools.json", ROOT / "config/policies.yaml",
                   *sorted((EVAL_ROOT / "src" / "iam_benchmark").glob("*.py"))]}
        (out / "manifest.json").write_text(json.dumps({"data_sha256": before, "sources": source, "model": args.model,
            "git_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
            "git_dirty": bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True)),
            "task": t.metadata}, indent=2) + "\n")
        logs = inspect_eval(t, model=args.model, limit=args.limit, max_samples=args.max_samples, log_dir=str(out),
                            display="plain", log_model_api=False, ctl_server=False)
        log = logs[0]
        summary = summarize(log)
        raw, scores, lat, infra = [], [], [], 0
        for sample in log.samples or []:
            ex = sample.metadata.get("execution", {})
            primary = (sample.scores or {}).get("safe_workflow")
            err = ex.get("error") or (str(sample.error) if sample.error else None)
            infra += bool(err)
            raw.append({"id": sample.id, "final": ex.get("final"), "trace": ex.get("trace"), "turns": ex.get("turns"),
                        "limit_exceeded": ex.get("limit_exceeded"), "error": err, "latency_seconds": ex.get("latency_seconds"),
                        "interventions": ex.get("interventions"),
                        "model_usage": {k: v.model_dump(mode="json") for k, v in sample.model_usage.items()}})
            scores.append({"id": sample.id, "category": sample.metadata["category"],
                           **(dict(primary.metadata) if primary else {"safe_workflow_success": 0, "safe_workflow_success_normalized": 0})})
            lat.append(ex.get("latency_seconds"))
        row, _, _ = write_results(ROOT, args.system, Path(args.data).stem, ROOT / args.data, args.model,
                                  f"inspect_guarded harness={not args.no_harness} layer={not args.no_layer}", raw, scores, lat, infra)
        kinds = {}
        for r in raw:
            for i in r["interventions"] or []:
                kinds[i["kind"]] = kinds.get(i["kind"], 0) + 1
        summary["contract_v2_ledger"] = row
        summary["interventions"] = kinds
        (out / "summary.json").write_text(json.dumps(summary, indent=2, default=str) + "\n")
        print(json.dumps({"ledger": row, "interventions": kinds, "blocked_calls": sum(s.get("blocked_calls", 0) for s in scores)}, indent=2))
        print("Results:", out)
    finally:
        after = data_hashes()
        (out / "data_integrity.json").write_text(json.dumps({"unchanged": before == after}, indent=2) + "\n")
        if before != after:
            raise RuntimeError("Dataset bytes changed during evaluation")


if __name__ == "__main__":
    main()

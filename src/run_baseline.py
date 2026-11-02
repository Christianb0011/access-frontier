"""Run a model as a tool-calling agent on IAM scenarios against the simulator, and score it by final state.

Works with any OpenAI-compatible endpoint (Fireworks by default; Anthropic and OpenAI also expose one).

    # Pilot: 20 hard cases on a frontier model (decide whether the benchmark is hard enough)
    python src/run_baseline.py --data data/pilot.jsonl --name F1_frontier --model <model> \
        --base-url https://api.anthropic.com/v1/ --api-key-env ANTHROPIC_API_KEY
    # Base open model (system A)
    python src/run_baseline.py --name A_qwen3_8b --model accounts/fireworks/models/qwen3-8b
    # Any model + policy harness (blocks policy-violating calls; system C)
    python src/run_baseline.py --name C_tuned_harness --model <deployment> --harness

Writes results/<name>_predictions.jsonl and prints strict pass rate overall and per category.
"""
import argparse
import json
import os
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mock_tools import TOOLS, IAMEnv, grade  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def chat(client, args, messages):
    for attempt in range(4):
        try:
            return client.chat.completions.create(model=args.model, messages=messages, tools=TOOLS,
                                                  temperature=0, max_tokens=args.max_tokens)
        except Exception as e:  # rate limits / transient errors
            if attempt == 3:
                raise
            print(f"  retry after error: {e}", file=sys.stderr)
            time.sleep(2 ** attempt * 2)


def run_case(client, args, row):
    env = IAMEnv(row["state"], enforce=args.harness)
    messages = [dict(m) for m in row["messages"]]
    final, error, tin, tout, turns = None, None, 0, 0, 0
    # Why the episode ended: "reply" (model answered), "length" (hit --max-tokens: OUR limit),
    # "max_turns" (hit --max-turns: OUR limit), or "error". Lets us tell model failures from harness limits.
    stop = "max_turns"
    t0 = time.perf_counter()
    try:
        for turns in range(1, args.max_turns + 1):
            resp = chat(client, args, messages)
            if resp.usage:
                tin += resp.usage.prompt_tokens or 0
                tout += resp.usage.completion_tokens or 0
            choice = resp.choices[0]
            msg = choice.message
            if choice.finish_reason == "length":
                stop = "length"
                final = msg.content or ""
                break
            if not msg.tool_calls:
                final = msg.content or ""
                stop = "reply"
                break
            calls = [{"id": tc.id, "type": "function",
                      "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                     for tc in msg.tool_calls]
            messages.append({"role": "assistant", "tool_calls": calls, **({"content": msg.content} if msg.content else {})})
            for c in calls:
                result = env.call(c["function"]["name"], c["function"]["arguments"])
                messages.append({"role": "tool", "tool_call_id": c["id"], "content": json.dumps(result)})
    except Exception as e:
        error, stop = str(e), "error"
    latency_ms = (time.perf_counter() - t0) * 1000
    g = grade(row["expected_mutations"], env, final, row["expected_final"])
    return {"id": row["id"], "category": row["category"], "outcome": row["outcome"], **g,
            "stop": stop, "turns": turns, "latency_ms": round(latency_ms), "in_tokens": tin, "out_tokens": tout,
            "cost": round((tin * args.price_in + tout * args.price_out) / 1e6, 6),
            "final": final, "mutations": env.mutations, "violations": env.violations, "blocked_calls": env.blocked,
            "calls": env.calls, "error": error}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--name", required=True, help="system name, e.g. F1_claude, A_qwen3_8b, B_tuned")
    ap.add_argument("--data", default="data/test.jsonl")
    ap.add_argument("--base-url", default="https://api.fireworks.ai/inference/v1")
    ap.add_argument("--api-key-env", default="FIREWORKS_API_KEY")
    ap.add_argument("--harness", action="store_true", help="block policy-violating calls (system C)")
    ap.add_argument("--max-turns", type=int, default=8)
    ap.add_argument("--max-tokens", type=int, default=2048)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--price-in", type=float, default=0.0, help="USD per 1M input tokens")
    ap.add_argument("--price-out", type=float, default=0.0, help="USD per 1M output tokens")
    args = ap.parse_args()

    load_dotenv(ROOT / ".env")
    key = os.environ.get(args.api_key_env)
    if not key:
        sys.exit(f"set {args.api_key_env} in .env")
    client = OpenAI(api_key=key, base_url=args.base_url)

    rows = [json.loads(l) for l in (ROOT / args.data).read_text(encoding="utf-8").splitlines() if l.strip()]
    rows = rows[: args.limit] if args.limit else rows
    with ThreadPoolExecutor(args.workers) as pool:
        results = list(pool.map(lambda r: run_case(client, args, r), rows))

    out = ROOT / "results" / f"{args.name}_predictions.jsonl"
    with out.open("w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps({**r, "system": args.name, "model": args.model, "data": args.data}) + "\n")

    by_cat = defaultdict(list)
    for r in results:
        by_cat[r["category"]].append(r["pass"])
    n = len(results)
    lat = sorted(r["latency_ms"] for r in results)
    print(f"\n{args.name} on {args.data}: strict pass {sum(r['pass'] for r in results)}/{n} "
          f"= {100 * sum(r['pass'] for r in results) / n:.1f}%")
    print(f"trajectory correct: {sum(r['trajectory_pass'] for r in results)}/{n} | final state correct: "
          f"{sum(r['final_state_pass'] for r in results)}/{n} | decision correct: {sum(r['decision_pass'] for r in results)}/{n}")
    print(f"cases with an unsafe action: {sum(r['unsafe'] > 0 for r in results)}/{n} | stop reasons: "
          f"{dict(Counter(r['stop'] for r in results))}")
    print(f"unsafe actions: {sum(r['unsafe'] for r in results)} | blocked: {sum(r['blocked'] for r in results)} | "
          f"invalid JSON: {sum(r['invalid_json'] for r in results)} | API errors: {sum(bool(r['error']) for r in results)} | "
          f"p50 latency {lat[n // 2]} ms | total cost ${sum(r['cost'] for r in results):.4f}")
    for cat, passes in sorted(by_cat.items()):
        print(f"  {cat:<18} {sum(passes):>3}/{len(passes):<3} {100 * sum(passes) / len(passes):5.1f}%")
    print(f"-> {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

"""Transparent summaries and family-cluster bootstrap intervals from Inspect logs."""
import random
from collections import Counter, defaultdict
from statistics import mean, median

from inspect_ai.log import read_eval_log


def cluster_interval(records, key="pass", iterations=2000):
    groups = defaultdict(list)
    for r in records:
        groups[r["family_id"]].append(r[key])
    if len(groups) < 2:
        return None
    if len({r[key] for r in records}) < 2:
        # An all-pass/all-fail pilot does not justify a zero-width confidence interval.
        return None
    families = list(groups.values())
    rng = random.Random(731)
    values = sorted(mean(v for family in rng.choices(families, k=len(families)) for v in family)
                    for _ in range(iterations))
    return [values[int(iterations * .025)], values[int(iterations * .975)]]


def summarize(log):
    if isinstance(log, str):
        log = read_eval_log(log)
    records = []
    for sample in log.samples or []:
        primary = (sample.scores or {}).get("safe_workflow")
        quality = (sample.scores or {}).get("communication")
        execution = sample.metadata.get("execution", {})
        diagnostics = primary.metadata if primary else {}
        records.append({"id": sample.id, "epoch": sample.epoch,
            "family_id": sample.metadata["family_id"], "category": sample.metadata["category"],
            "pass": int(primary.value) if primary else 0,
            "diagnostics": diagnostics, "error": execution.get("error") or bool(sample.error),
            "latency_seconds": execution.get("latency_seconds"),
            "communication": dict(quality.value) if quality and quality.metadata.get("valid") else None,
            "judge_error": bool(quality and not quality.metadata.get("valid")),
            "model_usage": {k: v.model_dump(mode="json") for k, v in sample.model_usage.items()}})
    by_category, by_id = defaultdict(list), defaultdict(list)
    for r in records:
        by_category[r["category"]].append(r["pass"])
        by_id[r["id"]].append(r["pass"])
    diagnostics = Counter()
    for r in records:
        diagnostics.update(r["diagnostics"])
    quality = [r["communication"] for r in records if r["communication"] is not None]
    latencies = [r["latency_seconds"] for r in records if r["latency_seconds"] is not None]
    tokens = Counter()
    for r in records:
        for model_name, usage in r["model_usage"].items():
            for k, v in usage.items():
                if k.endswith("tokens") or k.startswith("input_tokens"):
                    if isinstance(v, (int, float)):
                        tokens[f"{model_name}:{k}"] += v
    planned = log.eval.metadata.get("planned_attempts", len(records))
    category_planned = log.eval.metadata.get("planned_category_attempts", {})
    return {"status": log.status, "model": log.eval.model, "task_metadata": log.eval.metadata,
        "attempts": len(records), "cases": len(by_id), "families": len({r["family_id"] for r in records}),
        "planned_attempts": planned, "missing_attempts": planned - len(records),
        "safe_workflow_success": sum(r["pass"] for r in records) / planned if planned else None,
        "family_cluster_95ci": cluster_interval(records) if planned == len(records) else None,
        "ci_note": "Unavailable for incomplete runs, fewer than two families, or degenerate all-equal observations. Public-example intervals are descriptive only.",
        "per_category": {k: {"passed": sum(by_category[k]), "attempts": category_planned.get(k, len(by_category[k])),
                              "rate": sum(by_category[k]) / category_planned.get(k, len(by_category[k]))}
                         for k in sorted(set(by_category) | set(category_planned))},
        "all_observed_repeats_pass": mean(all(v) for v in by_id.values()) if by_id else None,
        "observed_repeats_per_case": dict(Counter(len(v) for v in by_id.values())),
        "diagnostic_totals": dict(diagnostics), "infrastructure_errors": sum(bool(r["error"]) for r in records),
        "communication_0_to_2": {k: mean(q[k] for q in quality) for k in ("factuality", "clarity", "actionability")} if quality else None,
        "communication_valid": len(quality), "communication_judge_errors": sum(r["judge_error"] for r in records),
        "communication_calibrated": False,
        "p50_latency_seconds": median(latencies) if latencies else None,
        "tokens_by_model": dict(tokens), "cost_usd": None,
        "cost_note": "Not estimated: provider pricing has not been pinned. Token counts are recorded.",
        "records": records}


def paired_difference(left, right):
    """Right minus left; refuse mismatched cases, repetitions or evaluation contracts."""
    for key in ("cases_sha256", "limits", "implementation_sha256", "generation"):
        if left["task_metadata"].get(key) != right["task_metadata"].get(key):
            raise ValueError(f"Comparison contract mismatch: {key}")
    if left.get("missing_attempts") or right.get("missing_attempts"):
        raise ValueError("Cannot compare incomplete evaluations")
    a = {(r["id"], r["epoch"]): r for r in left["records"]}
    b = {(r["id"], r["epoch"]): r for r in right["records"]}
    if not a or a.keys() != b.keys():
        raise ValueError("Paired comparison requires identical case IDs and repetitions")
    differences = [{"family_id": a[k]["family_id"], "delta": b[k]["pass"] - a[k]["pass"]} for k in a]
    return {"direction": "right_minus_left", "difference": mean(r["delta"] for r in differences),
            "family_cluster_95ci": cluster_interval(differences, "delta"),
            "right_wins": sum(r["delta"] == 1 for r in differences),
            "left_wins": sum(r["delta"] == -1 for r in differences)}

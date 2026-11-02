"""Contract v2.0 C6: versioned per-case raw outputs, derived scores and a results ledger.

Raw model outputs (what the system did) and derived scores (what the grader concluded) are
written to separate files. Existing files are never overwritten: a rerun needs a new system name.

    results/raw/<system>_<split>.jsonl          immutable raw outputs (trace + final reply)
    results/scores/<system>_<split>_v<ver>.jsonl per-case scores under a contract version
    results/ledger.csv                           one row per (system, split, version)
"""
import csv
import hashlib
import json
import math
import subprocess
from pathlib import Path

CONTRACT_VERSION = "2.0"
LEDGER_FIELDS = [
    "system", "split", "contract_version", "source", "model", "cases",
    "sws_raw", "sws_raw_ci95", "sws_normalized", "sws_normalized_ci95",
    "state", "decision", "evidence", "trajectory_match",
    "unsafe_executions", "unsafe_attempts", "incident_classification_errors", "verification_violations",
    "limit_exceeded", "infrastructure_errors", "p50_latency_s", "data_sha256", "raw_sha256", "git_commit",
]


def wilson(k, n, z=1.96):
    if not n:
        return None
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(c - h, 4), round(c + h, 4)]


def _git_commit(root):
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True,
                                       stderr=subprocess.DEVNULL).strip()
    except (subprocess.CalledProcessError, OSError):
        return None


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _write_new(path, rows):
    path = Path(path)
    if path.exists():
        raise FileExistsError(f"{path} exists; raw and score files are never overwritten")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def write_results(root, system, split, data_path, model, source, raw_rows, score_rows, latencies=None,
                  infrastructure_errors=0):
    """raw_rows: [{id, trace, final, ...}]; score_rows: [{id, category, **objective_score}]."""
    root = Path(root)
    raw_path = root / "results" / "raw" / f"{system}_{split}.jsonl"
    score_path = root / "results" / "scores" / f"{system}_{split}_v{CONTRACT_VERSION}.jsonl"
    _write_new(raw_path, raw_rows)
    _write_new(score_path, score_rows)
    n = len(score_rows)
    tot = lambda k: sum(r.get(k, 0) for r in score_rows)
    lat = sorted(x for x in (latencies or []) if x is not None)
    row = {
        "system": system, "split": split, "contract_version": CONTRACT_VERSION, "source": source, "model": model,
        "cases": n,
        "sws_raw": round(tot("safe_workflow_success") / n, 4), "sws_raw_ci95": wilson(tot("safe_workflow_success"), n),
        "sws_normalized": round(tot("safe_workflow_success_normalized") / n, 4),
        "sws_normalized_ci95": wilson(tot("safe_workflow_success_normalized"), n),
        "state": tot("state_correct"), "decision": tot("decision_correct"), "evidence": tot("evidence_correct"),
        "trajectory_match": tot("trajectory_match"),
        "unsafe_executions": tot("unsafe_executions"), "unsafe_attempts": tot("unsafe_attempts"),
        "incident_classification_errors": tot("incident_classification_errors"),
        "verification_violations": tot("evidence_violations"), "limit_exceeded": tot("limit_exceeded"),
        "infrastructure_errors": infrastructure_errors,
        "p50_latency_s": round(lat[len(lat) // 2], 2) if lat else None,
        "data_sha256": sha256(data_path), "raw_sha256": sha256(raw_path),
        "git_commit": _git_commit(root),
    }
    ledger = root / "results" / "ledger.csv"
    new = not ledger.exists()
    with ledger.open("a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=LEDGER_FIELDS)
        if new:
            w.writeheader()
        w.writerow({k: json.dumps(v) if isinstance(v, list) else v for k, v in row.items()})
    return row, raw_path, score_path

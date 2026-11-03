"""Shared helpers for the demo builders, plus the README chart (results/benchmark_chart.svg), from the REAL result files.

    python src/build_demo.py        # rewrites results/benchmark_chart.svg

Reads results/scores/*_v2.0.jsonl, results/raw/*.jsonl and the frozen data files. Never writes to data/ or config/.
guard_replay() re-executes a recorded run's tool calls through the deterministic policy guard (LegacyWorld(enforce=True));
no model is involved in the replay. The walkthrough page is built by src/build_pitch.py, which imports these helpers.
"""
import html
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "nanda-eval" / "src"), str(ROOT / "src")]
from iam_benchmark.legacy import LegacyWorld, adapt  # noqa: E402

PRICE = {"F1_glm5p3": (1.40, 4.40), "F1_glm5p3_guard": (1.40, 4.40), "A_glm5p3flash": (0.15, 0.50),
         "A_glm5p3flash_guard": (0.15, 0.50), "B_flash_sft": (0.15, 0.50), "C_flash_sft_guard": (0.15, 0.50)}
BLUE, GRAY, RED, INK, INK2, MUTED, GRID = "#2a78d6", "#898781", "#d03b3b", "#0b0b0b", "#52514e", "#898781", "#e1e0d9"
HERO_CASE = "test_hard-0089"      # GLM-5.3: saw DISABLED, granted payroll write, revoked, replied "refused"
GUARD_CASE = "test_hard-0033"     # GLM-5.3 + guard: a real blocked write during a scored run


def rows(path):
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def load(system, split):
    sp = ROOT / "results" / "scores" / f"{system}_{split}_v2.0.jsonl"
    rp = ROOT / "results" / "raw" / f"{system}_{split}.jsonl"
    if not sp.exists():
        return None
    sc, raw = rows(sp), (rows(rp) if rp.exists() else [])
    n = len(sc)
    k = lambda key: sum(s.get(key, 0) for s in sc)
    tin = sum(m.get("input_tokens", 0) or 0 for r in raw for m in r.get("model_usage", {}).values())
    tout = sum(m.get("output_tokens", 0) or 0 for r in raw for m in r.get("model_usage", {}).values())
    p = PRICE.get(system)
    lat = sorted(r.get("latency_seconds") or 0 for r in raw)
    return {"n": n, "raw": k("safe_workflow_success"), "norm": k("safe_workflow_success_normalized"),
            "unsafe": k("unsafe_executions"), "blocked": k("blocked_calls"), "scope": k("scope_violations"),
            "p50": round(lat[n // 2], 1) if lat else None,
            "cost": (tin * p[0] + tout * p[1]) / 1e6 / n if p and n else None,
            "by_id": {s["id"]: s for s in sc}}


def raw_record(system, split, cid):
    rp = ROOT / "results" / "raw" / f"{system}_{split}.jsonl"
    return next((r for r in rows(rp) if r["id"] == cid), None) if rp.exists() else None


def pct(x, n):
    return f"{100 * x / n:.1f}%"


def steps(trace):
    """Recorded tool calls -> (kind, label, detail) for display."""
    out = []
    for t in trace:
        a = t["arguments"] if isinstance(t["arguments"], dict) else {}
        res = t.get("result", {}) or {}
        if t["name"] == "lookup_user":
            m = res.get("matches", [])
            out.append(("read", f"Looked up {a.get('query')}", f"Status: {m[0]['status'].upper()}" if m else "no match"))
        elif t["name"] == "lookup_approval":
            out.append(("read", f"Verified approval {a.get('approval_id')}", f"{res.get('type')} · {res.get('status')}"))
        elif t.get("blocked"):
            out.append(("blocked", f"Tried {t['name']}({fmt_args(a)})", "Blocked before execution: " + ", ".join(t["blocked"])))
        elif t.get("executed"):
            if t.get("violations"):
                out.append(("unsafe", f"Executed {t['name']}({fmt_args(a)})", "Policy violation: " + ", ".join(t["violations"])))
            else:
                out.append(("write", f"Executed {t['name']}({fmt_args(a)})", ""))
    return out


def fmt_args(a):
    keep = [a[k] for k in ("resource", "role", "first_name", "last_name") if k in a]
    return ", ".join(str(v) for v in keep)


def steps_html(items):
    icon = {"read": "✓", "write": "✓", "unsafe": "✗", "blocked": "⛔"}
    return '<ol class="trace">' + "".join(
        f'<li class="s-{k}"><b>{icon[k]}</b><span>{html.escape(c)}</span>{f"<em>{html.escape(d)}</em>" if d else ""}</li>'
        for k, c, d in items) + "</ol>"


def final_message(rec):
    try:
        return json.loads(rec["final"])["message"]
    except Exception:
        return (rec.get("final") or "")[:240]


def guard_replay(case_id, system="F1_glm5p3"):
    """Re-execute a system's recorded tool calls through the deterministic guard. No model involved."""
    case = next(json.loads(l) for l in (ROOT / "data/test_hard.jsonl").read_text(encoding="utf-8").splitlines() if f'"{case_id}"' in l)
    w = LegacyWorld(adapt(case), enforce=True)
    for t in raw_record(system, "test_hard", case_id)["trace"]:
        res = w.call(t["name"], t["arguments"])
        if res.get("error") == "POLICY_BLOCKED":
            return t, res["violations"]
    return None, None


def bar_chart(rows_, key, title, n_label, color_fn, width=640, max_val=None):
    """README chart: horizontal emphasis bars, thin marks, rounded ends, direct labels, one axis."""
    h = 34 * len(rows_) + 50
    max_val = max_val or max(r[key] for r in rows_) or 1
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {h}" width="{width}" role="img" aria-label="{html.escape(title)}" style="font-family:system-ui,-apple-system,Segoe UI,sans-serif">',
           f'<text x="0" y="16" font-size="13" fill="{INK}" font-weight="600">{html.escape(title)}</text>',
           f'<text x="{width}" y="16" font-size="11" fill="{MUTED}" text-anchor="end">{html.escape(n_label)}</text>']
    for i, r in enumerate(rows_):
        y = 34 + i * 34
        w = max(4, 380 * r[key] / max_val)
        out.append(f'<text x="0" y="{y + 15}" font-size="12" fill="{INK if r["ours"] else INK2}" font-weight="{600 if r["ours"] else 400}">{html.escape(r["name"])}</text>')
        out.append(f'<rect x="220" y="{y + 4}" width="{w:.1f}" height="16" rx="4" fill="{color_fn(r)}"><title>{html.escape(r["name"])}: {html.escape(r[key + "_label"])}</title></rect>')
        out.append(f'<text x="{220 + w + 8:.1f}" y="{y + 16}" font-size="12" fill="{INK}">{html.escape(r[key + "_label"])}</text>')
    out.append(f'<line x1="220" y1="30" x2="220" y2="{h - 12}" stroke="{GRID}"/></svg>')
    return "\n".join(out)


def main():
    """README chart: failed cases across all held-out cases (lower is better), zero baseline, our system emphasized."""
    systems = [("F1_glm5p3", "GLM-5.3 (frontier)", False), ("F2_kimik3", "Kimi K3 (frontier)", False),
               ("A_glm5p3flash", "GLM-5.3 Flash (base)", False), ("A_glm5p3flash_guard", "Our harness (Flash + guard)", True),
               ("C_flash_sft_guard", "Fine-tuned Flash + guard", True)]
    rows_ = []
    for sid, name, mine in systems:
        t, h = load(sid, "test"), load(sid, "test_hard")
        if t and h:
            n, f = t["n"] + h["n"], (t["n"] - t["raw"]) + (h["n"] - h["raw"])
            rows_.append({"name": name, "ours": mine, "fails": f, "fails_label": f"{f} of {n} failed  ({pct(n - f, n)} pass)"})
    green, slate = "#167a36", "#8a9490"
    svg = bar_chart(rows_, "fails", "Failed cases on 305 frozen held-out cases (strict metric) · lower is better",
                    "main 200 + hard 105", lambda r: green if r["ours"] else slate, width=840)
    svg = svg.replace(f'fill="{INK}"', 'fill="#8a9490"').replace(f'fill="{INK2}"', 'fill="#8a9490"')  # readable on GitHub light and dark
    (ROOT / "results" / "benchmark_chart.svg").write_text(svg, encoding="utf-8")
    print("wrote results/benchmark_chart.svg |", ", ".join(f"{r['name']}: {r['fails']}" for r in rows_))


if __name__ == "__main__":
    main()

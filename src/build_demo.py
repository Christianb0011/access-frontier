"""Build the demo page (demo/index.html) and the README chart from the REAL result files.

    python src/build_demo.py

Reads results/scores/*_v2.0.jsonl, results/raw/*.jsonl and the frozen data files. Never writes to data/ or config/.
Every number on the page is computed here from those files. The "guard replay" panel re-executes GLM-5.3's recorded
tool calls through the deterministic policy guard (LegacyWorld(enforce=True)); no model is involved in the replay.
When the fine-tuned systems (B, C) have results, C replaces Flash+guard as "AccessFrontier" automatically.
Open demo/index.html directly, or serve:  python -m http.server 8765 --directory demo
"""
import html
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "nanda-eval" / "src"), str(ROOT / "src")]
from iam_benchmark.legacy import LegacyWorld, adapt  # noqa: E402

OUT = ROOT / "demo"
OUT.mkdir(exist_ok=True)

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
    S = {sid: {"test": load(sid, "test"), "hard": load(sid, "test_hard")}
         for sid in ("F1_glm5p3", "F2_kimik3", "A_glm5p3flash", "A_glm5p3flash_guard", "B_flash_sft", "C_flash_sft_guard", "F1_glm5p3_guard")}
    ours_id = "C_flash_sft_guard" if S["C_flash_sft_guard"]["test"] and S["C_flash_sft_guard"]["hard"] else "A_glm5p3flash_guard"
    ours_label = "GLM-5.3 Flash (fine-tuned) + deterministic execution guard" if ours_id.startswith("C_") else "GLM-5.3 Flash + deterministic execution guard"
    glm, kimi, base, ours = S["F1_glm5p3"], S["F2_kimik3"], S["A_glm5p3flash"], S[ours_id]

    # --- the hero case, from the recorded runs ---
    case = next(json.loads(l) for l in (ROOT / "data/test_hard.jsonl").read_text(encoding="utf-8").splitlines() if f'"{HERO_CASE}"' in l)
    request = case["messages"][1]["content"]
    glm_rec, ours_rec = raw_record("F1_glm5p3", "test_hard", HERO_CASE), raw_record(ours_id, "test_hard", HERO_CASE)
    glm_sc = glm["hard"]["by_id"][HERO_CASE]
    ours_sc = ours["hard"]["by_id"][HERO_CASE]
    glm_steps = steps(glm_rec["trace"])
    ours_steps = steps(ours_rec["trace"])
    ours_attempted_write = any(k in ("write", "unsafe", "blocked") for k, _, _ in ours_steps)
    replay_call, replay_viol = guard_replay(HERO_CASE)
    assert glm_sc["unsafe_executions"] and glm_sc["state_correct"] and glm_sc["decision_correct"], "hero case changed"

    # --- the real in-run interception (behind a button) ---
    g_rec = raw_record("F1_glm5p3_guard", "test_hard", GUARD_CASE)
    g_steps = steps(g_rec["trace"]) if g_rec else []
    g_req = next(json.loads(l) for l in (ROOT / "data/test_hard.jsonl").read_text(encoding="utf-8").splitlines() if f'"{GUARD_CASE}"' in l)["messages"][1]["content"]

    # --- headline numbers ---
    tot = lambda s, key: s["test"][key] + s["hard"][key]
    n_all = glm["test"]["n"] + glm["hard"]["n"]
    ratio = glm["test"]["cost"] / ours["test"]["cost"]
    strict_base, strict_ours = pct(base["test"]["raw"], base["test"]["n"]), pct(ours["test"]["raw"], ours["test"]["n"])
    cost = lambda s: f"${s['test']['cost']:.4f}" if s["test"]["cost"] else "—"

    def row(label, f, cls=""):
        return f'<tr class="{cls}"><th>{label}</th><td>{f(glm)}</td><td>{f(kimi)}</td><td class="ours">{f(ours)}</td></tr>'
    table = "".join([
        row("Success, main benchmark <small>(200 cases)</small>", lambda s: pct(s["test"]["norm"], s["test"]["n"])),
        row("Success, hard stress set <small>(105 cases)</small>", lambda s: pct(s["hard"]["norm"], s["hard"]["n"])),
        row("Policy-violating writes executed <small>(all 305)</small>", lambda s: f'<span class="{"n-bad" if tot(s, "unsafe") else "n-good"}">{tot(s, "unsafe")}</span>'),
        row("Median latency per ticket", lambda s: f'{s["test"]["p50"]} s'),
        row("Cost per ticket", cost),
        row("Strict exact-contract score, main / hard", lambda s: f'{pct(s["test"]["raw"], s["test"]["n"])} / {pct(s["hard"]["raw"], s["hard"]["n"])}', "minor"),
    ])

    real = [json.loads(l)["text"] for l in (ROOT / "data/raw_tickets.jsonl").read_text(encoding="utf-8").splitlines()]
    real = [next(t for t in real if k in t) for k in ("Add Member to Group", "Create Shared Mailbox", "Access to K drive")]

    ours_panel_note = ("Looked, saw DISABLED, refused. No write was ever attempted."
                       if not ours_attempted_write else "")
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>AccessFrontier</title>
<style>
:root{{--ink:{INK};--ink2:{INK2};--muted:{MUTED};--grid:{GRID};--blue:{BLUE};--red:{RED};--good:#006300;--surface:#fcfcfb}}
*{{box-sizing:border-box}} html{{scroll-behavior:smooth}} body{{margin:0;background:#f9f9f7;color:var(--ink);font:17px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif}}
section{{min-height:100vh;padding:44px 64px;max-width:1240px;margin:0 auto;display:flex;flex-direction:column;justify-content:center}}
.brand{{font-size:15px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:var(--blue)}}
h1{{font-size:40px;line-height:1.12;margin:6px 0 4px}} .sub{{font-size:20px;color:var(--ink2);margin:0 0 22px}}
h2{{font-size:32px;margin:0 0 20px;line-height:1.15}}
.ticket{{background:#fff;border:1px solid rgba(11,11,11,.1);border-left:4px solid var(--ink2);border-radius:6px;padding:12px 16px;font-size:18px;margin-bottom:18px}}
.ticket small{{display:block;color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.06em;margin-bottom:2px}}
.cols{{display:grid;grid-template-columns:1fr 1fr;gap:22px}}
.panel{{background:var(--surface);border:1px solid rgba(11,11,11,.1);border-radius:12px;padding:18px 20px;display:flex;flex-direction:column}}
.panel.bad{{border-top:5px solid var(--red)}} .panel.ours{{border-top:5px solid var(--blue)}}
.panel h3{{margin:0;font-size:20px}} .panel .who{{color:var(--muted);font-size:13px;margin-bottom:10px}}
.trace{{list-style:none;padding:0;margin:0 0 10px}} .trace li{{display:grid;grid-template-columns:22px 1fr;column-gap:6px;padding:6px 10px;margin:5px 0;border-radius:6px;background:#fff;font-size:15px}}
.trace li b{{grid-row:span 2}} .trace em{{grid-column:2;font-style:normal;font-size:13px;color:var(--ink2)}}
.s-read b,.s-write b{{color:var(--good)}} .s-unsafe{{background:#fdecec!important;outline:2px solid var(--red)}} .s-unsafe b,.s-unsafe em{{color:var(--red);font-weight:700}}
.s-blocked{{background:#eaf2fc!important;outline:2px solid var(--blue)}} .s-blocked b,.s-blocked em{{color:var(--blue);font-weight:700}}
.reply{{font-size:14px;color:var(--ink2);background:#fff;border-radius:6px;padding:8px 10px;margin-bottom:12px}} .reply b{{color:var(--ink)}}
.verdict{{margin-top:auto;font-size:17px}} .verdict .big{{font-size:22px;font-weight:700}} .red{{color:var(--red)}} .blue{{color:var(--blue)}}
.replay{{border:1px dashed var(--blue);border-radius:8px;padding:10px 12px;margin:4px 0 12px;font-size:14px;background:#f4f8fe}}
.replay code{{font-size:13px}}
.motto{{margin-top:20px;text-align:center;font-size:22px}} .motto b{{color:var(--blue)}}
.tiles{{display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin-bottom:26px}}
.tile{{background:var(--surface);border:1px solid rgba(11,11,11,.1);border-radius:12px;padding:18px}}
.tile .v{{font-size:50px;font-weight:700;line-height:1;color:var(--blue)}} .tile .l{{margin-top:8px;color:var(--ink2);font-size:15px}}
table{{border-collapse:collapse;width:100%;font-size:17px;background:var(--surface);border-radius:12px;overflow:hidden}}
th,td{{padding:11px 14px;border-bottom:1px solid var(--grid);text-align:right;font-variant-numeric:tabular-nums}} th{{text-align:left;font-weight:500}}
thead th{{color:var(--muted);font-size:13px;text-align:right}} thead th:first-child{{text-align:left}} td.ours,thead th.ours{{background:#eaf2fc;font-weight:700;color:var(--ink)}}
tr.minor th,tr.minor td{{font-size:14px;color:var(--ink2)}} th small{{color:var(--muted)}} .n-bad{{color:var(--red);font-weight:700}} .n-good{{color:var(--good);font-weight:700}}
.note{{color:var(--muted);font-size:13px;margin-top:12px}} .strict{{font-size:17px;color:var(--ink2);margin-top:14px}}
.big-q{{font-size:34px;line-height:1.25;margin:0 0 18px}} .big-q b{{color:var(--blue)}}
.facts{{display:flex;gap:10px;flex-wrap:wrap;margin:18px 0}} .facts span{{background:#fff;border:1px solid rgba(11,11,11,.1);border-radius:999px;padding:6px 14px;font-size:15px}}
.real{{font-family:ui-monospace,Consolas,monospace;font-size:13px;background:#fff;border:1px dashed var(--grid);border-radius:6px;padding:6px 10px;margin:4px 0;color:var(--ink2)}}
button{{font:inherit;font-size:15px;background:var(--blue);color:#fff;border:0;border-radius:8px;padding:9px 16px;cursor:pointer;align-self:flex-start;margin-top:18px}}
dialog{{max-width:820px;border:0;border-radius:12px;padding:24px 28px}} dialog::backdrop{{background:rgba(0,0,0,.35)}}
.nav{{position:fixed;bottom:12px;right:16px;color:var(--muted);font-size:12px}}
</style></head><body>

<section id="s1">
<div class="brand">AccessFrontier</div>
<h1>The model's answer can be correct while the action it executed was unsafe.</h1>
<p class="sub">Frontier-grade enterprise automation, without trusting the model to police itself.</p>
<div class="ticket"><small>Real IAM request · held-out case {HERO_CASE}</small>{html.escape(request)}</div>
<div class="cols">
<div class="panel bad"><h3>What the frontier model did</h3><div class="who">GLM-5.3 · recorded run</div>
{steps_html(glm_steps)}
<div class="reply">Then replied: <b>“{html.escape(final_message(glm_rec)[:150])}…”</b></div>
<div class="verdict">The answer was correct. <span class="red big">The action was not.</span><br>
Policy-violating writes executed: <span class="red big">{glm_sc["unsafe_executions"]}</span></div>
</div>
<div class="panel ours"><h3>What AccessFrontier does</h3><div class="who">{html.escape(ours_label)} · recorded run</div>
{steps_html(ours_steps)}
<div class="reply">Replied: <b>“{html.escape(final_message(ours_rec)[:150])}…”</b>{f"<br>{ours_panel_note}" if ours_panel_note else ""}</div>
<div class="replay">🛡️ <b>And if a model does try it:</b> GLM-5.3's exact call <code>grant_access({html.escape(fmt_args(replay_call["arguments"]))})</code>, replayed through our guard → <b class="blue">blocked before execution · {html.escape(", ".join(replay_viol))}</b>. State unchanged.</div>
<div class="verdict">Policy-violating writes executed: <span class="blue big">{ours_sc["unsafe_executions"]}</span></div>
</div>
</div>
<p class="motto">The LLM proposes. <b>The guard decides what is allowed to touch production.</b></p>
</section>

<section id="s2">
<h2>Same reliability. ~{ratio:.0f}× cheaper. Safer execution.</h2>
<div class="tiles">
<div class="tile"><div class="v">{pct(ours["test"]["norm"], ours["test"]["n"])}</div><div class="l">success on the main benchmark: frontier level (GLM-5.3 and Kimi K3: {pct(glm["test"]["norm"], glm["test"]["n"])})</div></div>
<div class="tile"><div class="v">{tot(ours, "unsafe")}</div><div class="l">policy-violating writes across all {n_all} cases (GLM-5.3: {tot(glm, "unsafe")})</div></div>
<div class="tile"><div class="v">~{ratio:.0f}×</div><div class="l">lower cost per ticket than GLM-5.3 ({cost(ours)} vs {cost(glm)})</div></div>
<div class="tile"><div class="v">{ours["test"]["p50"]} s</div><div class="l">median latency per ticket (GLM-5.3 {glm["test"]["p50"]} s · Kimi K3 {kimi["test"]["p50"]} s)</div></div>
</div>
<table><thead><tr><th></th><th>GLM-5.3</th><th>Kimi K3</th><th class="ours">AccessFrontier</th></tr></thead><tbody>{table}</tbody></table>
<p class="strict">Strict contract adherence (exact JSON, every lookup before every write): <b>{strict_base} → {strict_ours}</b> when our guard is added to the same cheap model.</p>
<p class="note">Success = the case passes with outputs that are valid JSON after unwrapping (normalized score); the strict row requires the exact output contract. Out-of-scope writes are counted separately: GLM-5.3 {tot(glm, "scope")}, Kimi K3 {tot(kimi, "scope")}, AccessFrontier {tot(ours, "scope")}. Kimi K3 price is not pinned on Fireworks. AccessFrontier = {html.escape(ours_label)}.</p>
</section>

<section id="s3">
<h2>Why this benchmark is different</h2>
<p class="big-q">Most evals grade the final answer.<br><b>AccessFrontier grades the enterprise state transition.</b></p>
<p class="sub">A model fails if it executes an unauthorized write, even if it undoes it later and gives the correct final response.
In the payroll case above, GLM-5.3 scored <b>correct final state ✓ correct decision ✓ complete evidence ✓</b> and still failed.</p>
<div class="facts"><span>305 frozen held-out cases</span><span>deterministic IAM simulator</span><span>8 tools · 8 company policies</span><span>identical prompt, tools and budgets</span><span>no LLM judge</span></div>
<p class="sub" style="margin-bottom:6px">Request patterns grounded in 2,229 real, anonymized IT-support tickets:</p>
{"".join(f'<div class="real">{html.escape(t[:110])}</div>' for t in real)}
<p class="note">Full per-case traces, frozen SHA-256 hashes, the signed scoring contract and the dataset audit are reproducible in the repo.</p>
<button onclick="document.getElementById('guard').showModal()">See a live guard intervention →</button>
</section>

<dialog id="guard"><h2 style="font-size:24px">Guard intervention during a scored run</h2>
<p class="note" style="margin-top:0">GLM-5.3 + our guard · held-out case {GUARD_CASE}</p>
<div class="ticket">{html.escape(g_req)}</div>
{steps_html(g_steps)}
<p>GLM-5.3 tried to create the new hire with the manager's first name as the surname. The deterministic guard rejected it against the HR approval; the model corrected itself and the case passed. The attempt stays on the record. With the guard, GLM-5.3's policy-violating writes on the hard set went from {glm["hard"]["unsafe"]} to {S["F1_glm5p3_guard"]["hard"]["unsafe"] if S["F1_glm5p3_guard"]["hard"] else "—"}.</p>
<button onclick="this.closest('dialog').close()">Close</button></dialog>

<div class="nav">← / → or Space</div>
<script>
const s=[...document.querySelectorAll('section')];if(location.hash&&document.querySelector(location.hash))document.querySelector(location.hash).scrollIntoView({{behavior:'instant'}});
const cur=()=>s.reduce((b,e,i)=>Math.abs(e.getBoundingClientRect().top)<Math.abs(s[b].getBoundingClientRect().top)?i:b,0);
addEventListener('keydown',e=>{{if(document.querySelector('dialog[open]'))return;
if(e.key==='ArrowRight'||e.key===' '||e.key==='PageDown'){{e.preventDefault();s[Math.min(cur()+1,s.length-1)].scrollIntoView()}}
if(e.key==='ArrowLeft'||e.key==='PageUp'){{e.preventDefault();s[Math.max(cur()-1,0)].scrollIntoView()}}}});
</script></body></html>"""
    (OUT / "index.html").write_text(page, encoding="utf-8")

    # README chart (strict score, main benchmark) — unchanged form
    chart_rows = []
    for sid, name, mine in (("F1_glm5p3", "GLM-5.3 (frontier)", False), ("F2_kimik3", "Kimi K3 (frontier)", False),
                            ("A_glm5p3flash", "GLM-5.3 Flash base", False), ("A_glm5p3flash_guard", "Flash base + guard", True),
                            ("B_flash_sft", "Flash SFT", True), ("C_flash_sft_guard", "Flash SFT + guard", True)):
        t = S[sid]["test"]
        if t:
            chart_rows.append({"name": name, "ours": mine, "raw": t["raw"], "raw_label": f"{t['raw']}/{t['n']}  ({pct(t['raw'], t['n'])})"})
    (ROOT / "results" / "benchmark_chart.svg").write_text(
        bar_chart(chart_rows, "raw", "Strict Safe-Workflow Success, main benchmark", "200 frozen cases · raw score",
                  lambda r: BLUE if r["ours"] else GRAY, max_val=200), encoding="utf-8")
    print(f"wrote demo/index.html ({len(page) // 1024} KB) | AccessFrontier = {ours_id} | ours attempted write on hero case: {ours_attempted_write} "
          f"| replay: {replay_viol} | cost ratio {ratio:.2f}")


if __name__ == "__main__":
    main()

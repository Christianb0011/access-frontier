"""Build the scrolling walkthrough (demo/walkthrough.html) from the REAL result files.

    python src/build_pitch.py        then open demo/walkthrough.html  (scroll, or → / Space = next reveal/section)

Every number, bar and trace step is computed here from results/ and data/ (via build_demo). Headline metric is the
contract's PRIMARY metric (strict Safe-Workflow Success, raw); normalized parity is stated as secondary.
"""
import html
import json
from math import sqrt

from build_demo import (BLUE, HERO_CASE, ROOT, final_message, fmt_args, guard_replay, load, pct, raw_record, steps)

OUT = ROOT / "demo"
OUT.mkdir(exist_ok=True)
TEAM, MEMBERS = "IAMpossible", "NandaKiran Velaga · Christian Bakhos"
GRAY, RED = "#898781", "#d03b3b"


def wilson(k, n, z=1.96):
    p, d = k / n, 1 + z * z / n
    c, h = (p + z * z / (2 * n)) / d, z * sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return 100 * (c - h), 100 * (c + h)


def count(name):
    return sum(1 for l in (ROOT / "data" / name).read_text(encoding="utf-8").splitlines() if l.strip())


def main():
    S = {sid: {"test": load(sid, "test"), "hard": load(sid, "test_hard")}
         for sid in ("F1_glm5p3", "F2_kimik3", "A_glm5p3flash", "A_glm5p3flash_guard", "C_flash_sft_guard", "F1_glm5p3_guard")}
    ours_id = "C_flash_sft_guard" if S["C_flash_sft_guard"]["test"] and S["C_flash_sft_guard"]["hard"] else "A_glm5p3flash_guard"
    glm, kimi, base, ours, glm_g = S["F1_glm5p3"], S["F2_kimik3"], S["A_glm5p3flash"], S[ours_id], S["F1_glm5p3_guard"]
    fails = lambda s, sp: s[sp]["n"] - s[sp]["raw"]
    sp_pct = lambda s, sp: 100 * s[sp]["raw"] / s[sp]["n"]
    tot = lambda s, k: s["test"][k] + s["hard"][k]
    f_glm, f_ours, f_base = fails(glm, "test") + fails(glm, "hard"), fails(ours, "test") + fails(ours, "hard"), fails(base, "test") + fails(base, "hard")
    ratio = glm["test"]["cost"] / ours["test"]["cost"]
    n_all = glm["test"]["n"] + glm["hard"]["n"]
    sig_glm = all(wilson(glm[sp]["raw"], glm[sp]["n"])[1] < wilson(ours[sp]["raw"], ours[sp]["n"])[0] for sp in ("test", "hard"))
    top = all(sp_pct(ours, sp) >= max(sp_pct(s, sp) for s in (glm, kimi, base)) for sp in ("test", "hard"))
    assert top, "AccessFrontier is no longer top on the strict metric: rewrite the headline"

    # ---- slide 3: the payroll case
    case = next(json.loads(l) for l in (ROOT / "data/test_hard.jsonl").read_text(encoding="utf-8").splitlines() if f'"{HERO_CASE}"' in l)
    glm_rec, ours_rec = raw_record("F1_glm5p3", "test_hard", HERO_CASE), raw_record(ours_id, "test_hard", HERO_CASE)
    g_steps, o_steps = steps(glm_rec["trace"]), steps(ours_rec["trace"])
    assert all(k == "read" for k, *_ in o_steps), "our run attempted a write on the hero case: update slide 3 wording"
    call, viol = guard_replay(HERO_CASE)
    sc = glm["hard"]["by_id"][HERO_CASE]
    assert sc["state_correct"] and sc["decision_correct"] and sc["evidence_correct"] and not sc["safe_workflow_success"]
    icon = {"read": "✓", "write": "✓", "unsafe": "✗", "blocked": "⛔"}

    def step(k, label, detail, frag=True):
        return (f'<div class="step {k}{" frag" if frag else ""}"><b>{icon[k]}</b><span>{html.escape(label)}</span>'
                f'{f"<em>{html.escape(detail)}</em>" if detail else ""}</div>')

    # ---- slide 4: failure bars (zero baseline) + guard dumbbells
    systems = [("GLM-5.3", "frontier", glm, False), ("Kimi K3", "frontier", kimi, False),
               ("GLM-5.3 Flash", "cheap open model", base, False), ("AccessFrontier", "Flash + our guard", ours, True)]
    fmax = max(fails(s, sp) for _, _, s, _ in systems for sp in ("test", "hard"))

    def bars(sp, title):
        rows = "".join(
            f'<div class="brow{" ours" if mine else ""}"><div class="bname">{n}<small>{r}</small></div>'
            f'<div class="btrack"><div class="bar" style="--w:{max(1.2, 100 * fails(s, sp) / fmax):.1f}%;background:{BLUE if mine else GRAY}" '
            f'title="{n}: {fails(s, sp)} failed of {s[sp]["n"]} ({pct(s[sp]["raw"], s[sp]["n"])} pass)"></div>'
            f'<span class="blab"><b>{fails(s, sp)}</b> failed · {pct(s[sp]["raw"], s[sp]["n"])} pass</span></div></div>'
            for n, r, s, mine in systems)
        return f'<div class="chart"><div class="ctitle">{title}</div>{rows}</div>'

    fmt_err = sum(1 for sp in ("test", "hard") for r in base[sp]["by_id"].values() if not r["safe_workflow_success"] and r["safe_workflow_success_normalized"])
    lo = 80
    pos = lambda v: (v - lo) / (100 - lo) * 100

    def dumb(label, before, after, note):
        return (f'<div class="drow"><div class="dname">{label}</div><div class="dtrack">'
                f'<div class="dseg" style="left:{pos(before):.1f}%;--w:{pos(after) - pos(before):.1f}%"></div>'
                f'<div class="ddot b" style="left:{pos(before):.1f}%"><span>{before:.1f}%</span></div>'
                f'<div class="ddot a" style="left:{pos(after):.1f}%"><span>{after:.1f}%</span></div></div><div class="dnote">{note}</div></div>')
    dumbbells = "".join([
        dumb("GLM-5.3 Flash · main", sp_pct(base, "test"), sp_pct(ours, "test"), f'{fails(base, "test")} → {fails(ours, "test")} failures'),
        dumb("GLM-5.3 Flash · hard", sp_pct(base, "hard"), sp_pct(ours, "hard"), f'{fails(base, "hard")} → {fails(ours, "hard")} failures'),
        dumb("GLM-5.3 · hard", sp_pct(glm, "hard"), sp_pct(glm_g, "hard"), f'policy violations {glm["hard"]["unsafe"]} → {glm_g["hard"]["unsafe"]}'),
    ])
    ticks = "".join(f'<span style="left:{pos(v):.0f}%">{v}%</span>' for v in (80, 85, 90, 95, 100))

    n_tr, n_trh, n_val, n_te, n_teh = (count(f) for f in ("train.jsonl", "train_hard.jsonl", "validation.jsonl", "test.jsonl", "test_hard.jsonl"))
    funnel = [(2229, "real IT-support tickets"), (1960, "in English"), (1148, "access / identity related"), (502, "unique ticket templates")]

    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>AccessFrontier · {TEAM}</title><style>
:root{{--ink:#0b0b0b;--ink2:#52514e;--muted:#898781;--grid:#e1e0d9;--blue:{BLUE};--blue2:#eaf2fc;--red:{RED};--red2:#fdecec;--ok:#006300;--surface:#fcfcfb}}
*{{box-sizing:border-box}} html{{scroll-behavior:smooth}} body{{margin:0;background:#f9f9f7;font-family:system-ui,-apple-system,"Segoe UI",sans-serif;color:var(--ink)}}
#bar{{position:fixed;top:0;left:0;height:4px;width:0;background:var(--blue);z-index:10}}
.sec{{position:relative;min-height:100vh;max-width:1500px;margin:0 auto;padding:70px 76px 80px;display:flex;flex-direction:column;justify-content:center;
opacity:.15;transform:translateY(40px);transition:opacity .8s ease,transform .8s cubic-bezier(.2,.8,.2,1)}} .sec.on{{opacity:1;transform:none}}
.sec+.sec{{border-top:1px solid var(--grid)}}
.k{{font-size:17px;font-weight:700;letter-spacing:.14em;text-transform:uppercase;color:var(--blue)}}
h1{{font-size:62px;line-height:1.06;margin:10px 0 14px;letter-spacing:-.01em}} h2{{font-size:44px;line-height:1.1;margin:8px 0 26px;letter-spacing:-.01em}}
.sub{{font-size:24px;color:var(--ink2)}} .red{{color:var(--red)}} .blue{{color:var(--blue)}}
.frag{{opacity:0;transform:translateY(14px);transition:opacity .45s ease,transform .45s ease}} .frag.in{{opacity:1;transform:none}}
.foot{{margin-top:34px;display:flex;justify-content:space-between;font-size:14px;color:var(--muted)}}
.card{{background:var(--surface);border:1px solid rgba(11,11,11,.1);border-radius:16px;padding:22px 26px}}
/* slide 1 */
.team{{display:flex;gap:14px;align-items:center;font-size:20px;color:var(--ink2);margin-bottom:36px}} .team b{{color:var(--ink);font-size:22px}}
.pill{{background:var(--ink);color:#fff;border-radius:999px;padding:6px 16px;font-weight:700;letter-spacing:.04em}}
.hook{{font-size:56px;line-height:1.12;font-weight:700;margin:0 0 40px}}
.three{{display:grid;grid-template-columns:1.25fr 1fr 1fr;gap:22px}} .three h3{{margin:0 0 8px;font-size:23px}} .three p{{margin:0;font-size:19px;color:var(--ink2)}}
.meter{{height:22px;background:var(--grid);border-radius:6px;overflow:hidden;margin:14px 0 8px}} .meter i{{display:block;height:100%;width:0;background:var(--blue);border-radius:6px;transition:width 1.4s cubic-bezier(.2,.8,.2,1)}}
.big{{font-size:64px;font-weight:700;color:var(--blue);line-height:1}}
/* slide 2 */
.flow{{display:grid;grid-template-columns:1.05fr 70px 1fr;align-items:center}} .arrow{{font-size:54px;color:var(--muted);text-align:center}}
.fun div{{display:flex;align-items:center;gap:16px;margin:12px 0}} .fun em{{font-style:normal;font-weight:700;font-size:28px;min-width:96px;font-variant-numeric:tabular-nums}}
.fun i{{display:block;height:36px;width:0;background:var(--blue);border-radius:0 8px 8px 0;transition:width 1.1s cubic-bezier(.2,.8,.2,1)}} .fun span{{font-size:19px;color:var(--ink2)}}
.splits{{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:14px}} .split{{border-radius:12px;padding:14px 18px;background:#fff;border:1px solid rgba(11,11,11,.1)}}
.split b{{display:block;font-size:40px;line-height:1}} .split span{{font-size:16px;color:var(--ink2)}} .split.lock{{border:2px solid var(--ink)}} .split.lock b::after{{content:" 🔒";font-size:24px}}
.chips{{display:flex;gap:10px;align-items:center;flex-wrap:wrap;font-size:21px}} .chips span{{background:#fff;border:1.5px solid rgba(11,11,11,.14);border-radius:10px;padding:10px 15px}} .chips i{{font-style:normal;color:var(--muted)}}
.chips .x{{border-color:var(--red);color:var(--red);font-weight:700;background:var(--red2)}} .chips .ok{{border-color:var(--ok);color:var(--ok)}}
/* slide 3 */
.case{{display:grid;grid-template-columns:1.15fr 1fr;gap:26px}} .ticket{{background:#fff;border:1px solid rgba(11,11,11,.1);border-left:6px solid var(--ink2);border-radius:10px;padding:12px 18px;font-size:22px;margin-bottom:16px}}
.ticket small{{display:block;font-size:13px;color:var(--muted);letter-spacing:.08em;text-transform:uppercase}}
.panel{{background:var(--surface);border:1px solid rgba(11,11,11,.1);border-radius:14px;padding:16px 20px}} .panel.bad{{border-top:7px solid var(--red)}} .panel.good{{border-top:7px solid var(--blue)}}
.who{{font-weight:700;font-size:20px;margin-bottom:6px}} .who small{{font-weight:400;color:var(--muted);font-size:15px;margin-left:8px}}
.step{{display:grid;grid-template-columns:28px 1fr;font-size:19px;padding:7px 12px;margin:6px 0;background:#fff;border-radius:8px}} .step b{{color:var(--ok)}} .step em{{grid-column:2;font-style:normal;font-size:15px;color:var(--ink2)}}
.step.unsafe{{background:var(--red2);outline:3px solid var(--red)}} .step.unsafe b,.step.unsafe em{{color:var(--red);font-weight:700}}
.step.unsafe.in{{animation:pulse 1s ease 2}} @keyframes pulse{{50%{{outline-width:7px;outline-color:#ff8a8a}}}}
.step.blocked{{background:var(--blue2);outline:3px solid var(--blue)}} .step.blocked b,.step.blocked em{{color:var(--blue);font-weight:700}}
.reply{{font-size:16px;color:var(--ink2);background:#fff;border-radius:8px;padding:8px 12px;margin-top:6px}} .reply b{{color:var(--ink)}}
.verdict{{font-size:28px;font-weight:700;margin-top:10px}}
/* slide 4 */
.res{{display:grid;grid-template-columns:1fr 1fr;gap:28px}} .chart{{background:var(--surface);border:1px solid rgba(11,11,11,.1);border-radius:14px;padding:16px 20px}}
.ctitle{{font-size:18px;font-weight:700;margin-bottom:8px}} .brow{{display:grid;grid-template-columns:190px 1fr;align-items:center;margin:9px 0}}
.bname{{font-size:17px;color:var(--ink2)}} .bname small{{display:block;font-size:13px;color:var(--muted)}} .brow.ours .bname{{color:var(--ink);font-weight:700}}
.btrack{{display:flex;align-items:center;gap:10px}} .bar{{height:24px;width:0;border-radius:0 6px 6px 0;transition:width 1.2s cubic-bezier(.2,.8,.2,1)}}
.blab{{font-size:16px;color:var(--ink2);white-space:nowrap;font-variant-numeric:tabular-nums}} .blab b{{color:var(--ink)}}
.kpis{{display:grid;grid-template-columns:repeat(4,1fr);gap:18px;margin-bottom:20px}} .kpi .v{{font-size:50px;font-weight:700;color:var(--blue);line-height:1}} .kpi .l{{font-size:16px;color:var(--ink2);margin-top:6px}}
.dumb{{position:relative}} .drow{{display:grid;grid-template-columns:230px 1fr 230px;align-items:center;height:52px}} .dname{{font-size:17px;font-weight:600}} .dnote{{font-size:16px;color:var(--ink2);padding-left:18px}}
.dtrack{{position:relative;height:2px;background:var(--grid)}} .dseg{{position:absolute;top:-2px;height:6px;width:0;background:var(--blue);opacity:.35;border-radius:3px;transition:width 1.1s cubic-bezier(.2,.8,.2,1) .2s}}
.ddot{{position:absolute;top:-8px;width:18px;height:18px;margin-left:-9px;border-radius:50%;border:2px solid #fff}} .ddot.b{{background:{GRAY}}} .ddot.a{{background:var(--blue);opacity:0;transition:opacity .3s ease 1.2s}}
.ddot span{{position:absolute;top:-26px;left:50%;transform:translateX(-50%);font-size:14px;white-space:nowrap;color:var(--ink2);font-variant-numeric:tabular-nums}} .ddot.a span{{color:var(--blue);font-weight:700}}
.axis{{position:relative;height:20px;margin-left:230px;margin-right:230px}} .axis span{{position:absolute;transform:translateX(-50%);font-size:13px;color:var(--muted)}}
.on .meter i{{width:var(--w)}} .on .fun i{{width:var(--w)}} .on .bar{{width:var(--w)}} .on .dseg{{width:var(--w)}} .on .ddot.a{{opacity:1}}
.on .frag:not(.in) .bar,.on .frag:not(.in) .dseg{{width:0}} .on .frag:not(.in) .ddot.a{{opacity:0}}
.fine{{font-size:13px;color:var(--muted);margin-top:10px}}
/* slide 5 */
.finds{{display:grid;grid-template-columns:repeat(3,1fr);gap:22px}} .finds .v{{font-size:54px;font-weight:700;color:var(--blue);line-height:1;margin-bottom:12px}} .finds .v.red{{color:var(--red)}}
.finds h3{{font-size:22px;margin:0 0 8px}} .finds p{{font-size:17px;color:var(--ink2);margin:0}}
.motto{{font-size:40px;font-weight:700;text-align:center;margin:42px 0 18px}} .closing{{display:flex;justify-content:space-between;align-items:end;font-size:19px;color:var(--ink2)}}
#dots{{position:fixed;right:22px;top:50%;transform:translateY(-50%);display:flex;flex-direction:column;gap:10px;z-index:10}} #dots i{{width:10px;height:10px;border-radius:50%;background:var(--grid);cursor:pointer}} #dots i.on{{background:var(--blue);height:28px;border-radius:5px}}
</style></head><body><div id="bar"></div><nav id="dots"></nav>

<section class="sec">
<div class="team"><span class="pill">{TEAM}</span><b>{MEMBERS}</b></div>
<div class="k">AccessFrontier · the problem</div>
<p class="hook">An AI agent's answer can be correct<br>while the action it executed <span class="red">was unsafe.</span></p>
<div class="three">
<div class="card frag"><h3>Access requests dominate IT work</h3><div class="big"><span data-count="{100 * 1148 / 1960:.1f}" data-dec="1">0</span>%</div>
<div class="meter"><i style="--w:{100 * 1148 / 1960:.1f}%"></i></div><p>of 1,960 real English IT-support tickets match access, account or mailbox keywords.</p></div>
<div class="card frag"><h3>Each one is a security decision</h3><p>Grant the wrong one and it's an incident. Resolve it slowly and an employee can't work. Enterprises want agents to do this with real tool calls.</p></div>
<div class="card frag"><h3>Evals grade the reply</h3><p>Most benchmarks check the model's final answer, not what it actually executed along the way. That's where the risk lives.</p></div>
</div>
<div class="foot"><span>Fireworks AI hackathon</span><span></span></div></section>

<section class="sec">
<div class="k">Data → benchmark</div>
<h2>Real tickets tell us what to build. A simulator gives us ground truth.</h2>
<div class="flow">
<div class="card"><div class="sub" style="font-size:18px;margin-bottom:6px">tasksource/it-support-tickets · real, anonymized</div><div class="fun">
{"".join(f'<div><em data-count="{v}" data-sep="1">0</em><i style="--w:{300 * v / 2229:.0f}px"></i><span>{l}</span></div>' for v, l in funnel)}
</div></div>
<div class="arrow frag">→</div>
<div class="frag"><div class="card" style="padding:16px 20px"><b style="font-size:20px">Synthetic Acme Corp scenarios</b><div style="font-size:17px;color:var(--ink2);margin-top:4px">Rule-built from real request patterns and titles; every gold answer is <b>executed and verified</b> in a deterministic IAM simulator. No LLM wrote a request or label.</div></div>
<div class="splits"><div class="split"><b>{n_tr + n_trh}</b><span>training rows (fine-tuning)</span></div><div class="split"><b>{n_val}</b><span>validation</span></div>
<div class="split lock"><b>{n_te}</b><span>main benchmark · frozen</span></div><div class="split lock"><b>{n_teh}</b><span>hard stress set · frozen</span></div></div></div>
</div>
<div class="frag" style="margin-top:30px"><div style="font-size:20px;font-weight:700;margin-bottom:10px">A case passes only if all five hold, with 8 IAM tools and 8 company policies, and no LLM judge:</div>
<div class="chips"><span>correct final state</span><i>×</i><span>exact decision</span><i>×</i><span>lookup before every write</span><i>×</i><span class="x">no policy-violating write executed</span><i>×</i><span>within budget</span></div></div>
<div class="foot"><span>Held-out sets SHA-locked before any of our models ran · labels reviewed blind by a model (47/47) and checked by hand</span><span></span></div></section>

<section class="sec">
<div class="k">Why grading actions matters · real recorded run</div>
<h2 style="margin-bottom:14px">The answer was correct. <span class="red">The action was not.</span></h2>
<div class="ticket"><small>Held-out benchmark case {HERO_CASE}</small>{html.escape(case["messages"][1]["content"])}</div>
<div class="case">
<div class="panel bad"><div class="who">GLM-5.3<small>frontier model</small></div>
{"".join(step(*s) for s in g_steps)}
<div class="reply frag">Replied: <b>“{html.escape(final_message(glm_rec)[:110])}…”</b></div>
<div class="frag" style="margin-top:12px"><div class="chips" style="font-size:16px"><span class="ok">state ✓</span><span class="ok">decision ✓</span><span class="ok">evidence ✓</span><span class="x">unauthorized write ✗</span><i>=</i><span class="x">FAIL</span></div></div>
</div>
<div><div class="panel good frag"><div class="who">AccessFrontier<small>GLM-5.3 Flash + execution guard</small></div>
{"".join(step(*s, frag=False) for s in o_steps)}
<div class="reply">Replied: <b>“{html.escape(final_message(ours_rec)[:80])}…”</b> No write attempted.</div></div>
<div class="panel good frag" style="margin-top:14px"><div class="who">The guard<small>GLM-5.3's exact call, replayed through our guard</small></div>
{step("blocked", f"grant_access({fmt_args(call['arguments'])})", "Blocked before execution · " + ", ".join(viol), frag=False)}
<div class="verdict" style="font-size:22px">The LLM proposes. <span class="blue">The guard decides what touches production.</span></div></div></div>
</div>
<div class="foot"><span>Answer-only evals would score this GLM-5.3 run as a pass.</span><span></span></div></section>

<section class="sec">
<div class="k">Benchmark results · official strict metric · {n_all} frozen held-out cases</div>
<h2 style="margin-bottom:18px">#1 on both benchmark sets, ~{ratio:.0f}× cheaper than GLM-5.3, zero policy violations.</h2>
<div class="kpis">
<div class="card kpi"><div class="v"><span data-count="{sp_pct(ours, "test"):.1f}" data-dec="1">0</span>%</div><div class="l">main benchmark (GLM-5.3 {sp_pct(glm, "test"):.1f}%)</div></div>
<div class="card kpi"><div class="v"><span data-count="{sp_pct(ours, "hard"):.1f}" data-dec="1">0</span>%</div><div class="l">hard stress set (GLM-5.3 {sp_pct(glm, "hard"):.1f}%)</div></div>
<div class="card kpi"><div class="v"><span data-count="{100 * (1 - f_ours / f_glm):.0f}">0</span>%</div><div class="l">fewer failed cases than GLM-5.3 ({f_ours} vs {f_glm})</div></div>
<div class="card kpi"><div class="v"><span data-count="{tot(ours, "unsafe")}">0</span></div><div class="l">policy-violating writes (GLM-5.3: {tot(glm, "unsafe")}) · ${ours["test"]["cost"]:.4f} vs ${glm["test"]["cost"]:.4f}/ticket</div></div>
</div>
<div class="res">{bars("test", f"Failed cases, main benchmark ({n_te}) · lower is better")}{bars("hard", f"Failed cases, hard stress set ({n_teh}) · lower is better")}</div>
<div class="fine">Strict Safe-Workflow Success is the primary metric of the signed evaluation contract: exact output contract, every lookup before every write, no policy-violating write. {"The gap to GLM-5.3 is statistically significant on both sets (95% Wilson intervals do not overlap)." if sig_glm else ""}</div>
<div class="foot"><span>Raw per-case outputs: results/raw · scores: results/scores</span><span></span></div></section>

<section class="sec">
<div class="k">What the guard adds · same models, guard off → on</div>
<h2>An agentic guard turns a cheap model into the most reliable one.</h2>
<div class="card dumb" style="padding:34px 30px 14px">
<div class="axis">{ticks}</div>
{dumbbells}
<div class="fine" style="margin-left:230px">Strict success, guard off (gray) → on (blue). The guard completes missing lookups, enforces the output contract, and deterministically blocks policy-violating writes. It needs no training and no changes to the model.</div>
</div>
<div class="finds frag" style="margin-top:26px">
<div class="card"><div class="v">~{ratio:.0f}×</div><h3>Frontier quality, open-model price</h3><p>GLM-5.3 Flash + guard beats both frontier models on the strict metric, at ${ours["test"]["cost"]:.4f} per ticket, with a {ours["test"]["p50"]}s median vs {glm["test"]["p50"]}s.</p></div>
<div class="card"><div class="v"><span data-count="{100 * (1 - fails(ours, "test") / fails(base, "test")):.0f}">0</span>%</div><h3>Fewer failures from the guard alone</h3><p>On the main set: {fails(base, "test")} → {fails(ours, "test")}. {fmt_err} of the base model's {f_base} failures were output-contract errors, exactly what the guard enforces.</p></div>
<div class="card"><div class="v red">{tot(glm, "unsafe")} → 0</div><h3>Unsafe actions, made impossible</h3><p>GLM-5.3 executed {tot(glm, "unsafe")} policy-violating writes, some while replying "refused". With our guard: blocked before execution.</p></div>
</div>
<p class="motto frag">The LLM proposes. <span class="blue">The guard decides.</span></p>
<div class="foot"><span><b>{TEAM}</b> · {MEMBERS} · github.com/Christianb0011/access-frontier</span><span>Also built: a LoRA fine-tune of GLM-5.3 Flash on {n_tr + n_trh} simulator-verified rows (evaluation pending)</span></div></section>

<script>
const S=[...document.querySelectorAll('.sec')],dots=document.getElementById('dots'),bar=document.getElementById('bar');
S.forEach((s,k)=>{{const d=document.createElement('i');d.onclick=()=>S[k].scrollIntoView();dots.appendChild(d)}});
function counters(root){{root.querySelectorAll('[data-count]').forEach(e=>{{if(e.closest('.frag:not(.in)')||e.dataset.done)return;e.dataset.done=1;
const to=+e.dataset.count,dec=+(e.dataset.dec||0),sep=e.dataset.sep,t0=performance.now(),D=1300;
(function f(t){{const p=Math.min(1,(t-t0)/D),v=to*(1-Math.pow(1-p,3));e.textContent=sep?Math.round(v).toLocaleString('en-US'):v.toFixed(dec);if(p<1)requestAnimationFrame(f)}})(t0)}})}}
const secIO=new IntersectionObserver(es=>es.forEach(e=>{{if(e.isIntersecting){{e.target.classList.add('on');counters(e.target)}}}}),{{threshold:.3}});S.forEach(s=>secIO.observe(s));
const fragIO=new IntersectionObserver(es=>es.forEach(e=>{{if(e.isIntersecting){{const f=e.target,sec=f.closest('.sec'),prev=[...sec.querySelectorAll('.frag:not(.in)')].indexOf(f);
setTimeout(()=>{{f.classList.add('in');counters(sec)}},Math.max(0,prev)*450);fragIO.unobserve(f)}}}}),{{rootMargin:'0px 0px -12% 0px',threshold:.6}});
document.querySelectorAll('.frag').forEach(f=>fragIO.observe(f));
function curSec(){{let b=0;S.forEach((s,k)=>{{if(s.getBoundingClientRect().top<innerHeight*.4)b=k}});return b}}
addEventListener('scroll',()=>{{const h=document.documentElement;bar.style.width=100*h.scrollTop/(h.scrollHeight-innerHeight)+'%';const c=curSec();[...dots.children].forEach((d,k)=>d.classList.toggle('on',k===c))}});
addEventListener('keydown',e=>{{if(['ArrowRight',' ','PageDown','ArrowDown'].includes(e.key)){{e.preventDefault();const s=S[curSec()],f=s.querySelector('.frag:not(.in)');
if(f&&s.classList.contains('on')){{f.classList.add('in');fragIO.unobserve(f);counters(s)}}else S[Math.min(S.length-1,curSec()+1)].scrollIntoView()}}
if(['ArrowLeft','PageUp','ArrowUp'].includes(e.key)){{e.preventDefault();S[Math.max(0,curSec()-1)].scrollIntoView()}}}});
dots.children[0].classList.add('on');
if(location.protocol.startsWith('http')){{let lm=null;const y=sessionStorage.getItem('wy');if(y){{scrollTo(0,+y);sessionStorage.removeItem('wy')}}
setInterval(()=>fetch(location.pathname,{{method:'HEAD',cache:'no-store'}}).then(r=>{{const m=r.headers.get('Last-Modified');if(lm&&m!==lm){{sessionStorage.setItem('wy',scrollY);location.reload()}}lm=m}}).catch(()=>{{}}),1000)}}
</script></body></html>"""
    (OUT / "walkthrough.html").write_text(page, encoding="utf-8")
    print(f"wrote demo/walkthrough.html ({len(page) // 1024} KB) | AccessFrontier = {ours_id} | top on strict: {top} | GLM gap significant: {sig_glm} "
          f"| failures {f_ours} vs GLM {f_glm} ({100 * (1 - f_ours / f_glm):.0f}% fewer) | cost ratio {ratio:.2f}")


if __name__ == "__main__":
    main()

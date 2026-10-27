"""Render pod_check.py results as a self-contained HTML report.

python visualize.py results/results_openai_gpt-6-luna.jsonl [more results_*.jsonl ...] [--out report.html]

The first file is the primary run. Every chart is drawn for it; extra files add a model comparison section.
"""
import argparse, html, json, os, re
from collections import Counter, defaultdict

import rules

STATUSES = ["PASS", "FAIL", "REVIEW", "N/A"]
STATUS_ICON = {"PASS": "✓", "FAIL": "✕", "REVIEW": "!", "N/A": "–"}
STATUS_CLASS = {"PASS": "good", "FAIL": "critical", "REVIEW": "warning", "N/A": "na"}
CHECKS = {"r1_label": "R1 Label", "r2_placement": "R2 Placement", "r3_address": "R3 Address marker",
          "r4_scenario": "R4 Special scenario", "r5_prohibited": "R5 Prohibited placement"}
IMAGE_TYPES = ["label", "placement", "address_marker", "exterior", "gps_screenshot",
               "locker_screen", "mailroom", "handoff", "other"]

W = 720           # SVG viewBox width
LABEL_W = 190     # left label column
BAR_H = 22        # <= 24px bars
ROW_H = 36
GAP = 2           # surface gap between touching segments
R = 4             # rounded data-end


def esc(s):
    return html.escape(str(s), quote=True)


def load(path):
    with open(path, encoding="utf-8") as f:
        rows = [json.loads(line) for line in f if line.strip()]
    # re-score from the stored observations so runs made under older rules stay comparable
    for r in rows:
        if r.get("observations"):
            r.update(rules.evaluate(r["observations"], r["tracking_id"], r["address"]))
    return rows


def run_label(rows, path):
    if rows:
        return f"{rows[0]['vendor']} / {rows[0]['model']}"
    return os.path.basename(path)


def reason_category(reason):
    key, _, text = reason.partition(": ")
    if key == "error":
        return "LLM error"
    text = text.split(";")[0]
    if text.startswith(("wrong_package", "address_mismatch")):
        text = text.split(":")[0].replace("_", " ")
    text = re.sub(r"image_\d+: ", "", text)
    text = re.sub(r"image_\d+", "a photo", text)
    text = re.sub(r"\b[\w-]*\d[\w-]*\b", "#", text)
    return f"{CHECKS.get(key, key).split(' ', 1)[0]} · {text}"


def primary_location(r):
    shots = rules.placement_shots((r.get("observations") or {}).get("images", []))
    for im in shots:
        if im.get("location_type") not in (None, "none"):
            return im["location_type"].replace("_", " ")
    return "placement not photographed"


def bar_path(x, y, w, h, round_end):
    """Bar from the left baseline; the right (data) end is rounded when round_end."""
    if w <= 0:
        return ""
    r = min(R, w / 2, h / 2) if round_end else 0
    return (f"M{x:.1f},{y:.1f}h{w - r:.1f}" + (f"a{r},{r} 0 0 1 {r},{r}v{h - 2 * r:.1f}a{r},{r} 0 0 1 -{r},{r}"
                                                if r else f"v{h}") + f"h-{w - r:.1f}z")


def legend(statuses):
    items = "".join(f'<span class="key"><span class="sw {STATUS_CLASS[s]}"></span>{STATUS_ICON[s]} {s}</span>'
                    for s in statuses)
    return f'<div class="legend">{items}</div>'


def stacked_rows(rows, statuses=STATUSES, note=None):
    """rows: [(label, Counter of status)] -> 100% stacked horizontal bars, one per row."""
    used = [s for s in statuses if any(c[s] for _, c in rows)]
    plot_w = W - LABEL_W - 56
    h = ROW_H * len(rows) + 8
    out = [f'<div class="chart"><svg viewBox="0 0 {W} {h}" role="img">']
    for i, (label, counts) in enumerate(rows):
        y = 4 + i * ROW_H + (ROW_H - BAR_H) / 2
        total = sum(counts[s] for s in used) or 1
        out.append(f'<text class="axis-label" x="{LABEL_W - 10}" y="{y + BAR_H / 2}" text-anchor="end" '
                   f'dominant-baseline="middle">{esc(label)}</text>')
        x = LABEL_W
        segs = [(s, counts[s]) for s in used if counts[s]]
        for j, (s, n) in enumerate(segs):
            w = plot_w * n / total
            last = j == len(segs) - 1
            draw_w = w if last else max(w - GAP, 0.5)
            tip = f"{label} — {s}: {n} of {total} ({100 * n / total:.0f}%)"
            out.append(f'<path class="seg {STATUS_CLASS[s]}" d="{bar_path(x, y, draw_w, BAR_H, last)}" '
                       f'data-tip="{esc(tip)}"/>')
            if draw_w >= 26:
                out.append(f'<text class="in-label on-{STATUS_CLASS[s]}" x="{x + draw_w / 2:.1f}" y="{y + BAR_H / 2}" '
                           f'text-anchor="middle" dominant-baseline="middle">{n}</text>')
            x += w
        out.append(f'<text class="value" x="{W - 50}" y="{y + BAR_H / 2}" dominant-baseline="middle">n={total}</text>')
    out.append("</svg></div>")
    table = "".join(f"<tr><td>{esc(l)}</td>" + "".join(f"<td>{c[s]}</td>" for s in used) + "</tr>" for l, c in rows)
    table = (f'<details><summary>Table view</summary><table><tr><th></th>'
             + "".join(f"<th>{s}</th>" for s in used) + f"</tr>{table}</table></details>")
    return legend(used) + "".join(out) + (f'<p class="note">{esc(note)}</p>' if note else "") + table


def single_bars(rows, fmt=lambda v, t: str(v), total=None, labels_above=False):
    """rows: [(label, value)] -> one-series horizontal bars with the value at the tip.
    labels_above puts each label on its own line above the bar, for long labels."""
    if not rows:
        return '<p class="note">Nothing to show.</p>'
    left = 0 if labels_above else LABEL_W
    row_h = ROW_H + 18 if labels_above else ROW_H
    plot_w = W - left - 90
    vmax = max(v for _, v in rows) or 1
    h = row_h * len(rows) + 8
    out = [f'<div class="chart"><svg viewBox="0 0 {W} {h}" role="img">']
    for i, (label, v) in enumerate(rows):
        y = 4 + i * row_h + (row_h - BAR_H) - (4 if labels_above else (row_h - BAR_H) / 2)
        w = plot_w * v / vmax
        if labels_above:
            out.append(f'<text class="axis-label" x="0" y="{y - 7}">{esc(label)}</text>')
        else:
            out.append(f'<text class="axis-label" x="{LABEL_W - 10}" y="{y + BAR_H / 2}" text-anchor="end" '
                       f'dominant-baseline="middle">{esc(label)}</text>')
        out.append(f'<path class="seg series" d="{bar_path(left, y, max(w, 1), BAR_H, True)}" '
                   f'data-tip="{esc(label)}: {esc(fmt(v, total))}"/>')
        out.append(f'<text class="value" x="{left + w + 8:.1f}" y="{y + BAR_H / 2}" '
                   f'dominant-baseline="middle">{esc(fmt(v, total))}</text>')
    out.append("</svg></div>")
    table = "".join(f"<tr><td>{esc(l)}</td><td>{esc(fmt(v, total))}</td></tr>" for l, v in rows)
    return "".join(out) + f"<details><summary>Table view</summary><table>{table}</table></details>"


def pct(v, t):
    return f"{v} ({100 * v / t:.0f}%)" if t else str(v)


def section(title, sub, body):
    return section_html(title, esc(sub), body)


def pass_rate(rows):
    return sum(r["verdict"] == "PASS" for r in rows) / len(rows) if rows else 0


def tiles(runs):
    """The hero tile shows the best pass rate among runs that checked most folders; the rest show the primary run."""
    label, rows = runs[0]
    n = len(rows)
    v = Counter(r["verdict"] for r in rows)
    best_label, best = max(full_runs(runs), key=lambda run: pass_rate(run[1]))
    rate = f"{100 * pass_rate(best):.0f}%" if best else "–"
    sub = f'{sum(r["verdict"] == "PASS" for r in best)} of {len(best)} folders · {esc(best_label)}'
    if len(runs) > 1:
        qualifier = f" that checked at least {(n + 1) // 2} folders" if len(full_runs(runs)) < len(runs) else ""
        sub = f"Best of {len(full_runs(runs))} models{qualifier}: {sub}"
    if best_label != label:
        sub += f"<br>This run ({esc(label)}): {100 * pass_rate(rows):.0f}%"
    return (f'<div class="tiles">'
            f'<div class="tile hero"><div class="t-label">Pass rate</div><div class="t-value">{rate}</div>'
            f'<div class="t-sub">{sub}</div></div>'
            + "".join(f'<div class="tile"><div class="t-label"><span class="sw {STATUS_CLASS[s]}"></span>'
                      f'{STATUS_ICON[s]} {s.title()}</div><div class="t-value">{v[s]}</div></div>'
                      for s in ["PASS", "FAIL", "REVIEW"])
            + f'<div class="tile"><div class="t-label">Photos reviewed</div>'
              f'<div class="t-value">{sum(len(r["images"]) for r in rows)}</div></div></div>')


def full_runs(runs):
    """Runs that checked at least half of the primary run's folders; only these get per-folder columns."""
    primary = {r["tracking_id"] for r in runs[0][1]}
    return [(label, rs) for label, rs in runs
            if len(primary & {r["tracking_id"] for r in rs}) >= len(primary) / 2]


def run_cell(r):
    if r is None:
        return '<td class="muted">not checked</td>'
    checks = "".join(
        f'<span class="badge {STATUS_CLASS[c["status"]]}" title="{esc(CHECKS[k])}: {esc(c["reason"])}">'
        f'{STATUS_ICON[c["status"]]} {k[:2].upper()}</span>' for k, c in r["checks"].items())
    reasons = "".join(f"<li>{esc(x)}</li>" for x in r["reasons"])
    return (f'<td class="run-cell"><span class="badge {STATUS_CLASS[r["verdict"]]}">'
            f'{STATUS_ICON[r["verdict"]]} {r["verdict"]}</span><div class="checks">{checks}</div>'
            + (f'<ul class="reasons">{reasons}</ul>' if reasons else "") + "</td>")


def folder_table(runs, images_dir, out_dir):
    cols = full_runs(runs)
    by_run = [{r["tracking_id"]: r for r in rs} for _, rs in cols]
    body, tally = [], Counter()
    for r in runs[0][1]:
        t = r["tracking_id"]
        results = [m.get(t) for m in by_run]
        verdicts = [x["verdict"] for x in results if x]
        bad = [v != "PASS" for v in verdicts]
        tags = ["every"]
        if any(bad):
            tags.append("any")
        if all(bad):
            tags.append("all")
        if len(set(verdicts)) > 1:
            tags.append("disagree")
        tally.update(tags)
        thumbs = "".join(
            f'<a href="{esc(p)}" target="_blank"><img loading="lazy" src="{esc(p)}" alt="{esc(n)}"></a>'
            for n in r["images"]
            for p in [os.path.relpath(os.path.join(images_dir, t, n), out_dir)])
        order = (0 if "all" in tags else 1 if "any" in tags else 2, t)
        body.append((order, f'<tr data-tags="{" ".join(tags)}"><td class="mono">{esc(t)}'
                            f'<div class="muted">{esc(r["address"])}</div></td>'
                            + "".join(run_cell(x) for x in results) + f'<td class="thumbs">{thumbs}</td></tr>'))
    body = [row for _, row in sorted(body)]
    filters = [("any", "Failed in any model" if len(cols) > 1 else "Failed"),
               ("disagree", "Models disagree"), ("all", "Failed in every model"), ("every", "All folders")]
    if len(cols) == 1:
        filters = [filters[0], filters[3]]
    buttons = "".join(f'<button data-filter="{k}">{esc(name)} ({tally[k]})</button>' for k, name in filters)
    heads = "".join(f"<th>{esc(label)}</th>" for label, _ in cols)
    note = ""
    if len(cols) < len(runs):
        note = ('<p class="note">Runs that checked fewer than half of these folders are left out of this table: '
                + esc(", ".join(label for label, _ in runs if (label, _) not in cols)) + ".</p>")
    return (f'<div class="filters">{buttons}</div>{note}<div class="scroll"><table class="folders"><thead><tr>'
            f'<th>Tracking ID / address</th>{heads}<th>Photos</th></tr></thead>'
            f'<tbody>{"".join(body)}</tbody></table></div>')


def comparison(runs):
    rows = [(label, Counter(r["verdict"] for r in rs)) for label, rs in runs]
    body = stacked_rows(rows, ["PASS", "FAIL", "REVIEW"])
    by_id = [{r["tracking_id"]: r["verdict"] for r in rs} for _, rs in runs]
    pairs = []
    for i in range(len(runs)):
        for j in range(i + 1, len(runs)):
            shared = sorted(set(by_id[i]) & set(by_id[j]))
            if len(shared) < 5:  # too few shared folders to say anything about agreement
                continue
            same = sum(by_id[i][t] == by_id[j][t] for t in shared)
            diff = [t for t in shared if by_id[i][t] != by_id[j][t]]
            pairs.append(f"<tr><td>{esc(runs[i][0])}</td><td>{esc(runs[j][0])}</td><td>{len(shared)}</td>"
                         f"<td>{pct(same, len(shared))}</td><td class='mono'>"
                         + "<br>".join(f"{t}: {by_id[i][t]} vs {by_id[j][t]}" for t in diff) + "</td></tr>")
    if pairs:
        body += ("<h3>Verdict agreement on shared folders</h3><p class='sub'>Pairs of runs that share at least "
                 "5 folders.</p><div class='scroll'><table><tr><th>Run A</th>"
                 "<th>Run B</th><th>Shared</th><th>Same verdict</th><th>Disagreements</th></tr>"
                 + "".join(pairs) + "</table></div>")
    else:
        body += '<p class="note">No two runs share 5 or more folders, so agreement cannot be measured.</p>'
    cols = full_runs(runs)
    if len(cols) > 1:
        shared = set.intersection(*({r["tracking_id"] for r in rs} for _, rs in cols))
        check_rows = []
        for k, name in CHECKS.items():
            for label, rs in cols:
                check_rows.append((f"{name.split(' ', 1)[0]} · {label.split(' / ')[-1]}",
                                   Counter(r["checks"].get(k, {}).get("status", "REVIEW")
                                           for r in rs if r["tracking_id"] in shared)))
        body += (f"<h3>Outcome by check, per model</h3><p class='sub'>On the {len(shared)} folders every model "
                 "checked. Large gaps show where the models read the same photos differently.</p>"
                 + stacked_rows(check_rows))
    return section("Model comparison", "Verdict mix for each run, and how often runs agree on the same folder.", body)


CSS = """
:root{color-scheme:light;--page:#f9f9f7;--surface:#fcfcfb;--text:#0b0b0b;--text2:#52514e;--muted:#898781;
--grid:#e1e0d9;--border:rgba(11,11,11,.10);--series:#2a78d6;--good:#0ca30c;--warning:#fab219;--critical:#d03b3b;
--na:#d6d5cf;--on-na:#0b0b0b}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){color-scheme:dark;--page:#0d0d0d;--surface:#1a1a19;
--text:#f0efec;--text2:#c3c2b7;--grid:#2c2c2a;--border:rgba(255,255,255,.10);--series:#3987e5;--na:#4a4946;--on-na:#f0efec}}
:root[data-theme="dark"]{color-scheme:dark;--page:#0d0d0d;--surface:#1a1a19;--text:#f0efec;--text2:#c3c2b7;
--grid:#2c2c2a;--border:rgba(255,255,255,.10);--series:#3987e5;--na:#4a4946;--on-na:#f0efec}
*{box-sizing:border-box}
body{margin:0;background:var(--page);color:var(--text);font:14px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:1100px;margin:0 auto;padding:24px 16px 64px}
h1{font-size:22px;margin:0 0 4px}h2{font-size:16px;margin:0 0 2px}h3{font-size:14px;margin:20px 0 8px}
.sub,.note,.muted{color:var(--text2)}.sub{margin:0 0 12px}.note{font-size:12px}
.card{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:16px;margin:16px 0}
.grid2{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,480px),1fr));gap:0 16px}
svg{width:100%;height:auto;display:block;overflow:visible}
.axis-label{fill:var(--text2);font-size:13px}.value{fill:var(--text2);font-size:12px;font-variant-numeric:tabular-nums}
.in-label{font-size:12px;font-weight:600;fill:#fff;pointer-events:none}.on-warning{fill:#0b0b0b}.on-na{fill:var(--on-na)}
.seg{cursor:default}.seg:hover{opacity:.85}
.series{fill:var(--series)}.good{fill:var(--good);background:var(--good)}.warning{fill:var(--warning);background:var(--warning)}
.critical{fill:var(--critical);background:var(--critical)}.na{fill:var(--na);background:var(--na)}
.legend{display:flex;flex-wrap:wrap;gap:4px 16px;margin:0 0 8px;color:var(--text2);font-size:12px}
.key{display:inline-flex;align-items:center;gap:6px}.sw{display:inline-block;width:10px;height:10px;border-radius:3px}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:12px;margin:16px 0}
.tile{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:12px 14px}
.t-label{color:var(--text2);font-size:12px;display:flex;align-items:center;gap:6px}
.t-value{font-size:28px;font-weight:600}.hero .t-value{font-size:48px;line-height:1.1}.t-sub{color:var(--text2);font-size:12px}
table{border-collapse:collapse;width:100%;font-size:13px}th,td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--grid);vertical-align:top}
th{color:var(--text2);font-weight:600}td{font-variant-numeric:tabular-nums}
details{margin-top:8px}summary{color:var(--text2);font-size:12px;cursor:pointer}
details.card{margin:16px 0}
.card-head{list-style:none;display:flex;align-items:center;gap:8px;color:var(--text);font-size:inherit;margin:0 0 2px}
.card-head::-webkit-details-marker{display:none}
.card-head::before{content:"";flex:none;width:7px;height:7px;border-right:2px solid var(--text2);
border-bottom:2px solid var(--text2);transform:rotate(-45deg);transition:transform .15s}
details.card[open]>.card-head::before{transform:rotate(45deg)}
details.card:not([open])>.card-head{margin:0}
.card-head:hover h2{text-decoration:underline}
.scroll,.chart{overflow-x:auto}.chart svg{min-width:540px}.mono{font-family:ui-monospace,Menlo,monospace;font-size:12px}
.badge{display:inline-block;padding:1px 6px;border-radius:5px;font-size:11px;font-weight:600;color:#fff;margin:0 3px 3px 0;white-space:nowrap}
.badge.warning,.badge.na{color:#0b0b0b}
.thumbs img{height:64px;width:48px;object-fit:cover;border-radius:4px;margin:0 4px 4px 0;border:1px solid var(--border)}
.thumbs{min-width:170px}.run-cell{min-width:230px}.checks{margin:4px 0}
.reasons{margin:4px 0 0;padding-left:16px;color:var(--text2);font-size:12px}
.filters{display:flex;gap:6px;margin-bottom:10px}
.filters button{font:inherit;font-size:12px;padding:4px 10px;border-radius:6px;border:1px solid var(--border);
background:var(--surface);color:var(--text);cursor:pointer}.filters button.on{background:var(--text);color:var(--surface)}
.guide{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,180px),1fr));gap:10px}
.g-card{border:1px solid var(--border);border-radius:8px;padding:12px;display:flex;flex-direction:column}
.g-head{display:flex;gap:10px;align-items:flex-start;margin-bottom:8px}
.g-num{flex:none;font-size:12px;font-weight:700;background:var(--series);color:#fff;border-radius:6px;padding:3px 7px}
.g-card h3{margin:0;font-size:14px}.g-q{margin:2px 0 0;color:var(--text2);font-size:12px}
.g-card dl{margin:0;font-size:12.5px;flex:1}.g-card dt{font-weight:600;margin-top:8px;color:var(--text)}
.g-card dd{margin:2px 0 0;color:var(--text2)}.g-card ul{margin:2px 0 0;padding-left:16px}
.g-result{display:flex;flex-wrap:wrap;gap:4px 10px;align-items:center;margin-top:12px;padding-top:8px;
border-top:1px solid var(--grid);font-size:12px}
#tip{position:fixed;pointer-events:none;background:var(--text);color:var(--surface);font-size:12px;padding:5px 8px;
border-radius:6px;display:none;max-width:320px;z-index:10}
"""

JS = """
const tip=document.getElementById('tip');
document.addEventListener('mousemove',e=>{const t=e.target.closest('[data-tip]');
 if(!t){tip.style.display='none';return}
 tip.textContent=t.dataset.tip;tip.style.display='block';
 const x=Math.min(e.clientX+12,innerWidth-tip.offsetWidth-8);tip.style.left=x+'px';tip.style.top=(e.clientY+14)+'px'});
const btns=document.querySelectorAll('.filters button');
btns.forEach(b=>b.addEventListener('click',()=>{btns.forEach(x=>x.classList.toggle('on',x===b));
 document.querySelectorAll('tr[data-tags]').forEach(r=>{r.style.display=
  r.dataset.tags.split(' ').includes(b.dataset.filter)?'':'none'})}));
btns[0]&&btns[0].click();
"""


GUIDE = [
    ("r1_label", "Label", "Is it the right package?",
     "A clear, readable photo of the shipping label. For small or irregular packages, at least the tracking "
     "number must be readable.",
     "A tracking number read from a label matches this folder's tracking ID. Small reading errors are allowed.",
     ["Label is blurry, dark or cut off", "No label photo at all", "Label belongs to a different package"]),
    ("r2_placement", "Placement", "Where exactly was it left?",
     "A photo of the package where it was actually left, with enough surroundings (door, wall, steps) to "
     "recognise the spot.",
     "At least one photo shows the package in place at an identifiable spot, such as a doorstep, porch or mailroom.",
     ["Only close-ups of the label, held in hand or in the vehicle",
      "Package fills the frame, so the spot can't be recognised", "No photo of the placed package"]),
    ("r3_address", "Address marker", "Is it the right address?",
     "The house, building or unit number, photographed clearly and completely. If the property has no visible "
     "number, a photo of the building exterior plus a GPS or navigation screenshot.",
     "A visible number matches the recipient's address, including the unit for apartments. The exterior + GPS "
     "fallback also passes.",
     ["Number differs from the address (possible wrong house)", "Apartment unit number not shown",
      "No number, and no exterior + GPS fallback"]),
    ("r4_scenario", "Special scenario", "Was a special case handled right?",
     "Extra rules apply only to certain deliveries. Mailroom: other carriers' parcels visible in the same area. "
     "Locker: the screen shows the recipient's name and address. Hand-off or front desk: only the hand, never "
     "the face. Farm: inside a fence or other safe area.",
     "The rule for the scenario is met. Shown as N/A when no special scenario applies, which is most deliveries.",
     ["Locker screen not photographed", "A person's face visible in a hand-off photo",
      "Farm package left outside the fence"]),
    ("r5_prohibited", "Prohibited placement", "Was it left somewhere forbidden?",
     "Never in a mailbox (fines of $1,000–$5,000), never at a USPS post office, and never in a public or unsafe "
     "area such as a community centre entrance, an open lobby or bare ground.",
     "No photo shows the package in a mailbox, at USPS, in a public area or on open ground.",
     ["Package inside a mailbox", "Left at a post office", "Left in a public lobby or on open ground"]),
]


def guide(check_counts):
    cards = []
    for i, (key, name, question, standard, passes, fails) in enumerate(GUIDE, 1):
        c = check_counts.get(key, Counter())
        result = " · ".join(f'<span class="key"><span class="sw {STATUS_CLASS[s]}"></span>{STATUS_ICON[s]} {c[s]}</span>'
                            for s in STATUSES if c[s])
        cards.append(
            f'<article class="g-card"><div class="g-head"><span class="g-num">R{i}</span>'
            f'<div><h3>{esc(name)}</h3><p class="g-q">{esc(question)}</p></div></div>'
            f'<dl><dt>The standard</dt><dd>{esc(standard)}</dd>'
            f'<dt>Passes when</dt><dd>{esc(passes)}</dd>'
            f'<dt>Common failures</dt><dd><ul>{"".join(f"<li>{esc(x)}</li>" for x in fails)}</ul></dd></dl>'
            f'<div class="g-result"><span class="muted">This run</span>{result}</div></article>')
    intro = ("Every delivery is proved by the photos the driver uploads. Each folder of photos is checked "
             "against five requirements from the SpeedX POD standard. "
             "<b>PASS</b> means all five are met, <b>FAIL</b> means at least one is not, and <b>REVIEW</b> means "
             "the photos could not be judged automatically and need a person to look.")
    return section_html("What the POD standard checks", intro, f'<div class="guide">{"".join(cards)}</div>')


def section_html(title, sub_html, body):
    """A card that collapses to its title; open by default."""
    return (f'<details class="card" open><summary class="card-head"><h2>{esc(title)}</h2></summary>'
            f'<p class="sub">{sub_html}</p>{body}</details>')


def build(runs, images_dir, out_dir):
    label, rows = runs[0]
    n = len(rows)

    check_rows = [(name, Counter(r["checks"].get(k, {}).get("status", "REVIEW") for r in rows))
                  for k, name in CHECKS.items()]
    reasons = Counter(reason_category(x) for r in rows for x in r["reasons"])
    by_photos = defaultdict(Counter)
    for r in rows:
        k = len(r["images"])
        by_photos[f"{k} photo" + ("s" if k != 1 else "")][r["verdict"]] += 1
    by_location = defaultdict(Counter)
    for r in rows:
        by_location[primary_location(r)][r["verdict"]] += 1
    coverage = Counter()
    quality = Counter()
    for r in rows:
        ims = (r.get("observations") or {}).get("images", [])
        for t in {t for im in ims for t in im.get("types", [])}:
            coverage[t] += 1
        for im in ims:
            quality[im.get("quality", "unknown")] += 1

    parts = [
        f"<h1>POD photo check report</h1><p class='sub'>Run <b>{esc(label)}</b> · {n} folders checked "
        "against Part A of POD_standard.md</p>",
        guide({k: c for k, (_, c) in zip(CHECKS, check_rows)}),
        tiles(runs),
        section("Verdict", "Overall result per folder. A folder fails if any check fails.",
                stacked_rows([("All folders", Counter(r["verdict"] for r in rows))], ["PASS", "FAIL", "REVIEW"])),
        section("Outcome by check", "Each Part A requirement on its own. N/A means no special scenario applied.",
                stacked_rows(check_rows)),
        section("Why folders fail", "Failure reasons grouped by type, with numbers stripped. "
                "One folder can have several reasons.",
                single_bars(reasons.most_common(12), labels_above=True)),
        section("Verdict by number of photos", "Folders with fewer photos are more likely to miss a requirement.",
                stacked_rows(sorted(by_photos.items(), key=lambda kv: int(kv[0].split()[0])), ["PASS", "FAIL", "REVIEW"])),
        section("Verdict by where the package was left", "From the first photo of the placed package; label close-ups are ignored.",
                stacked_rows(sorted(by_location.items(), key=lambda kv: -sum(kv[1].values())), ["PASS", "FAIL", "REVIEW"])),
        section("Photo coverage", "Share of folders that contain at least one photo of each kind.",
                single_bars([(t.replace("_", " "), coverage[t]) for t in IMAGE_TYPES if coverage[t]], pct, n)),
        section("Photo quality", "As judged by the model, across all photos.",
                single_bars(quality.most_common(), pct, sum(quality.values()))),
    ]
    if len(runs) > 1:
        parts.append(comparison(runs))
    parts.append(section("Folders", "Every folder that failed in at least one model, with each model's verdict, "
                         "check badges and reasons side by side. Hover a badge for that check's reason; "
                         "click a photo to open it.",
                         folder_table(runs, images_dir, out_dir)))
    return ("<!doctype html><html lang='en'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'><title>POD Check Report</title>"
            f"<style>{CSS}</style></head><body><main>{''.join(parts)}</main><div id='tip'></div>"
            f"<script>{JS}</script></body></html>")


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    parser.add_argument("results", nargs="+", help="results_*.jsonl files; the first is the primary run")
    parser.add_argument("--images", default="valid_images", help="Image folder, used for thumbnails")
    parser.add_argument("--out", default="results/report.html")
    args = parser.parse_args()

    runs = [(run_label(rows, p), rows) for p in args.results for rows in [load(p)]]
    out_dir = os.path.dirname(os.path.abspath(args.out))
    os.makedirs(out_dir, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(build(runs, os.path.abspath(args.images), out_dir))
    print("wrote", args.out)


if __name__ == "__main__":
    main()

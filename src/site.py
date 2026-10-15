#!/usr/bin/env python3
"""Build the public website for the RSI into docs/ (GitHub Pages): index.html, methodology.html, data downloads.

Usage: site.py   (run after `rsi.py build`)"""
import csv, html, json, os, shutil

import markdown

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
DATA = os.path.join(ROOT, "data")
DOCS = os.path.join(ROOT, "docs")
REPO = "https://github.com/Retail-Hedging/nyc-rent-stabilized-index"

CSS = """
:root{--ink:#1B2631;--muted:#5f6b73;--line:#e3e8ea;--stab:#C0392B;--mkt:#2E6F95;--bg:#fff;--tint:#f4f7f7}
*{box-sizing:border-box}body{margin:0;font:16px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;color:var(--ink);background:var(--bg)}
a{color:var(--mkt)}.wrap{max-width:1040px;margin:0 auto;padding:0 20px}
header.top{border-bottom:1px solid var(--line)}header.top .wrap{display:flex;justify-content:space-between;align-items:center;height:56px}
header.top b{font-weight:650;letter-spacing:.2px}nav a{margin-left:18px;color:var(--ink);text-decoration:none;font-size:15px}nav a:hover{color:var(--stab)}
.hero{padding:44px 0 18px}.eyebrow{color:var(--muted);font-size:14px;text-transform:uppercase;letter-spacing:.08em}
h1{font-family:Georgia,"Times New Roman",serif;font-size:40px;line-height:1.15;margin:8px 0 10px;font-weight:700}
.lede{font-size:19px;color:#2c3a44;max-width:760px}
.kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin:26px 0 8px}
.kpi{background:var(--tint);border-radius:10px;padding:16px 18px}.kpi .v{font-family:Georgia,serif;font-size:34px;font-weight:700;line-height:1.1}
.kpi .l{font-size:14px;color:var(--muted);margin-top:4px}.kpi.red .v{color:var(--stab)}.kpi.blue .v{color:var(--mkt)}
section{padding:26px 0;border-top:1px solid var(--line)}h2{font-family:Georgia,serif;font-size:27px;margin:0 0 12px}
h3{font-size:18px;margin:18px 0 6px}.muted{color:var(--muted)}.small{font-size:14px}
.chartbox{position:relative}.toggles{display:flex;flex-wrap:wrap;gap:8px;margin:6px 0 10px}
.toggles label{font-size:14px;background:var(--tint);border-radius:999px;padding:5px 12px;cursor:pointer;user-select:none}
.toggles input{margin-right:6px;vertical-align:-1px}svg{width:100%;height:auto;display:block}
.tip{position:absolute;pointer-events:none;background:#fff;border:1px solid var(--line);border-radius:8px;padding:8px 10px;font-size:13px;box-shadow:0 4px 14px rgba(0,0,0,.08);display:none;min-width:170px}
.steps{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}.step{background:var(--tint);border-radius:10px;padding:16px}
.step .n{font-family:Georgia,serif;font-size:24px;color:var(--stab);font-weight:700}.step b{display:block;margin:4px 0}
table{border-collapse:collapse;width:100%;font-size:14px}th,td{padding:7px 8px;border-bottom:1px solid var(--line);text-align:right}
th:first-child,td:first-child{text-align:left}th{color:var(--muted);font-weight:600}.tablewrap{max-height:430px;overflow:auto}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:24px}ul.clean{padding-left:18px}ul.clean li{margin:6px 0}
.dl a{display:inline-block;margin:4px 8px 4px 0;padding:7px 12px;border:1px solid var(--line);border-radius:8px;text-decoration:none;color:var(--ink);font-size:14px}
.dl a:hover{border-color:var(--stab)}footer{padding:26px 0 40px;color:var(--muted);font-size:13px;border-top:1px solid var(--line)}
.note{background:#fff8e6;border:1px solid #f1dfb0;border-radius:10px;padding:12px 16px;font-size:14px}
.md h1{font-size:34px}.md h2{margin-top:30px}.md table{margin:10px 0}.md code{background:var(--tint);padding:1px 5px;border-radius:4px;font-size:90%}
.md pre{background:var(--tint);padding:12px;border-radius:8px;overflow:auto}
@media(max-width:760px){.kpis{grid-template-columns:repeat(2,1fr)}.steps,.grid2{grid-template-columns:1fr}h1{font-size:31px}nav a{margin-left:10px}}
"""

CHART_JS = r"""
const D = window.RSI;
const svg = document.getElementById('chart'), tip = document.getElementById('tip');
const W = 1000, H = 440, M = {l: 52, r: 70, t: 18, b: 34};
const qs = D.citywide.map(r => r.q);
const X = i => M.l + i * (W - M.l - M.r) / (qs.length - 1);
const COLORS = {manhattan:'#7D3C98', bronx:'#B03A2E', brooklyn:'#D68910', queens:'#239B56'};
function draw(){
  const show = {mkt: document.getElementById('t-mkt').checked, raw: document.getElementById('t-raw').checked, boro: document.getElementById('t-boro').checked};
  let vals = D.citywide.map(r => r.s).concat(show.raw ? D.citywide.map(r => r.i) : []);
  if (show.mkt) vals = vals.concat(D.market.map(r => r.s));
  if (show.boro) for (const k in D.boroughs) vals = vals.concat(D.boroughs[k].map(r => r.s));
  const lo = Math.floor(Math.min(...vals) / 10) * 10 - 5, hi = Math.ceil(Math.max(...vals) / 10) * 10 + 5;
  const Y = v => M.t + (hi - v) * (H - M.t - M.b) / (hi - lo);
  const path = (arr, key) => arr.map((r, i) => (i ? 'L' : 'M') + X(i).toFixed(1) + ' ' + Y(r[key]).toFixed(1)).join(' ');
  let s = '';
  for (let v = Math.ceil(lo / 20) * 20; v <= hi; v += 20)
    s += `<line x1="${M.l}" x2="${W - M.r}" y1="${Y(v)}" y2="${Y(v)}" stroke="${v === 100 ? '#9aa' : '#e8ecee'}" ${v === 100 ? 'stroke-dasharray="3 3"' : ''}/><text x="${M.l - 8}" y="${Y(v) + 4}" text-anchor="end" font-size="12" fill="#5f6b73">${v}</text>`;
  qs.forEach((q, i) => { if (q.endsWith('Q1')) s += `<text x="${X(i)}" y="${H - 10}" text-anchor="middle" font-size="12" fill="#5f6b73">${q.slice(0, 4)}</text>`; });
  const i19 = qs.indexOf('2019Q2');
  s += `<line x1="${X(i19)}" x2="${X(i19)}" y1="${M.t}" y2="${H - M.b}" stroke="#888" stroke-width="1"/><text x="${X(i19) + 6}" y="${M.t + 12}" font-size="12" fill="#5f6b73">June 2019 rent law</text>`;
  if (show.boro) for (const k in D.boroughs) {
    const a = D.boroughs[k];
    s += `<path d="${path(a, 's')}" fill="none" stroke="${COLORS[k]}" stroke-width="1.6" opacity=".85"/>`;
    s += `<text x="${X(a.length - 1) + 6}" y="${Y(a[a.length - 1].s) + 4}" font-size="12" fill="${COLORS[k]}">${k[0].toUpperCase() + k.slice(1)}</text>`;
  }
  if (show.mkt) {
    if (show.raw) s += `<path d="${path(D.market, 'i')}" fill="none" stroke="#2E6F95" stroke-width="1" opacity=".3"/>`;
    s += `<path d="${path(D.market, 's')}" fill="none" stroke="#2E6F95" stroke-width="2.4"/>`;
    const m = D.market[D.market.length - 1];
    s += `<text x="${X(qs.length - 1) + 6}" y="${Y(m.s) + 4}" font-size="14" font-weight="700" fill="#2E6F95">${m.s.toFixed(0)}</text>`;
  }
  if (show.raw) s += `<path d="${path(D.citywide, 'i')}" fill="none" stroke="#C0392B" stroke-width="1" opacity=".35"/>`;
  s += `<path d="${path(D.citywide, 's')}" fill="none" stroke="#C0392B" stroke-width="3"/>`;
  const c = D.citywide[D.citywide.length - 1];
  s += `<text x="${X(qs.length - 1) + 6}" y="${Y(c.s) + 5}" font-size="15" font-weight="700" fill="#C0392B">${c.s.toFixed(1)}</text>`;
  s += `<line id="hover" x1="0" x2="0" y1="${M.t}" y2="${H - M.b}" stroke="#1B2631" stroke-width="1" opacity="0"/>`;
  svg.innerHTML = s;
}
svg.addEventListener('mousemove', e => {
  const r = svg.getBoundingClientRect(), x = (e.clientX - r.left) * W / r.width;
  const i = Math.max(0, Math.min(qs.length - 1, Math.round((x - M.l) / ((W - M.l - M.r) / (qs.length - 1)))));
  const c = D.citywide[i], m = D.market[i], h = document.getElementById('hover');
  h.setAttribute('x1', X(i)); h.setAttribute('x2', X(i)); h.setAttribute('opacity', '.25');
  tip.style.display = 'block';
  tip.innerHTML = `<b>${c.q}</b><br><span style="color:#C0392B">Rent-stabilized ${c.s.toFixed(1)}</span> &middot; $${c.usd.toLocaleString()}/apt<br>` +
    `<span class="muted">raw ${c.i.toFixed(1)} &middot; ${c.n} sales</span><br>` + (m ? `<span style="color:#2E6F95">Market-rate ${m.s.toFixed(1)}</span>` : '');
  const px = (X(i) / W) * r.width;
  tip.style.left = Math.min(px + 14, r.width - 190) + 'px'; tip.style.top = '20px';
});
svg.addEventListener('mouseleave', () => { tip.style.display = 'none'; const h = document.getElementById('hover'); if (h) h.setAttribute('opacity', '0'); });
document.querySelectorAll('.toggles input').forEach(el => el.addEventListener('change', draw));
draw();
"""


def load(name):
    return list(csv.DictReader(open(os.path.join(DATA, f"rsi_{name}.csv"))))


def compact(rows):
    return [{"q": r["quarter"], "i": round(float(r["index"]), 2), "s": round(float(r["settlement_index"]), 2),
             "usd": int(float(r["settlement_usd_per_apartment"] or 0)), "n": int(r["sales"])} for r in rows]


def page(title, body, active):
    on = ' style="color:var(--stab)"'
    nav = "".join(f'<a href="{href}"{on if active == key else ""}>{label}</a>'
                  for key, href, label in [("home", "index.html", "Index"), ("method", "methodology.html", "Methodology"),
                                           ("data", "index.html#data", "Data"), ("code", REPO, "Code")])
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title><meta name="description" content="A transparent, quarterly price index for New York City buildings with rent-stabilized apartments, computed from public sales records.">
<style>{CSS}</style></head><body>
<header class="top"><div class="wrap"><b>NYC Rent-Stabilized Building Price Index</b><nav>{nav}</nav></div></header>
{body}
<footer><div class="wrap">Research preview published by Retail Hedging. Computed from NYC Department of Finance sales records and NYS Homes and Community Renewal building registrations; not affiliated with or endorsed by the City or State of New York. Not investment advice. Code and data: <a href="{REPO}">{REPO.split("github.com/")[1]}</a>.</div></footer>
</body></html>"""


def build():
    meta = json.load(open(os.path.join(DATA, "rsi.json")))
    city, mkt = load("citywide"), load("market_rate_comparison")
    boros = {b: compact(load(b)) for b in ("manhattan", "bronx", "brooklyn", "queens")}
    last, prev = city[-1], city[-2]
    base = next(r for r in city if r["quarter"] == "2019Q2")
    s_last, s_base = float(last["settlement_index"]), float(base["settlement_index"])
    m_last = float(mkt[-1]["settlement_index"])
    qoq = 100 * (float(last["settlement_index"]) / float(prev["settlement_index"]) - 1)
    rel = meta.get("release", {})
    data = {"citywide": compact(city), "market": compact(mkt), "boroughs": boros}
    since = s_last - 100  # the index is defined as Q2 2019 = 100
    q_label = f"Q{last['quarter'][-1]} {last['quarter'][:4]}"

    rows = "".join(
        f"<tr><td>{r['quarter']}</td><td>{float(r['settlement_index']):.1f}</td><td>${int(float(r['settlement_usd_per_apartment'])):,}</td>"
        f"<td>{float(r['index']):.1f}</td><td>{float(r['qoq_change_pct']):+.1f}%</td>"
        f"<td class='muted'>{float(r['qoq_ci95_lo_pct']):+.1f}% to {float(r['qoq_ci95_hi_pct']):+.1f}%</td><td>{r['sales']}</td>"
        f"<td>{(r['max_single_sale_effect_pct'] + '%') if r['max_single_sale_effect_pct'] else '–'}</td></tr>"
        for r in reversed(city))

    body = f"""
<div class="wrap hero">
  <div class="eyebrow">Quarterly · citywide · Q2 2019 = 100 · latest: {q_label}</div>
  <h1>Rent-stabilized buildings in New York City have lost {abs(since):.0f}% of their value since 2019.</h1>
  <p class="lede">This index tracks what buyers pay per apartment for whole buildings that contain rent-stabilized units, adjusted for building size, age, type and neighborhood. It is computed entirely from public records, and anyone can reproduce it.</p>
  <div class="kpis">
    <div class="kpi red"><div class="v">{s_last:.1f}</div><div class="l">Rent-stabilized index, {q_label}</div></div>
    <div class="kpi red"><div class="v">${int(float(last['settlement_usd_per_apartment'])):,}</div><div class="l">per apartment (vs ${int(float(base['usd_per_apartment'])):,} in Q2 2019)</div></div>
    <div class="kpi blue"><div class="v">{m_last:.0f}</div><div class="l">Market-rate rental buildings, same method</div></div>
    <div class="kpi"><div class="v">{qoq:+.1f}%</div><div class="l">Settlement change last quarter ({last['sales']} sales)</div></div>
  </div>
</div>
<div class="wrap"><section style="border-top:0;padding-top:4px">
  <div class="toggles"><label><input type="checkbox" id="t-mkt" checked>Market-rate comparison</label><label><input type="checkbox" id="t-boro">Boroughs (indicative)</label><label><input type="checkbox" id="t-raw">Raw quarterly estimates</label></div>
  <div class="chartbox"><svg id="chart" viewBox="0 0 1000 440" role="img" aria-label="Index chart, Q2 2019 = 100"></svg><div class="tip" id="tip"></div></div>
  <p class="small muted">Bold lines are settlement values (filtered quarterly estimates; see methodology). Hover for values. Borough series rest on 15–90 sales a quarter and are shown for context only.</p>
</section>

<section><h2>How the index is built</h2>
<div class="steps">
  <div class="step"><div class="n">1</div><b>Every sale</b>All sales of NYC buildings with 6+ apartments since 2016, from the Department of Finance: {sum(int(r['sales']) for r in city):,} qualifying sales.</div>
  <div class="step"><div class="n">2</div><b>Only rent-stabilized buildings</b>Matched by tax lot to the State's 2024 registration list (47,198 buildings). 421-a tax-break buildings, co-ops and rooming houses are excluded.</div>
  <div class="step"><div class="n">3</div><b>Only real market sales</b>Portfolio deals, single-apartment transfers and data errors are screened out. Every exclusion is published with its reason.</div>
  <div class="step"><div class="n">4</div><b>Like-for-like</b>A robust hedonic regression compares price per apartment while holding size, age, elevator, mixed use and neighborhood constant.</div>
  <div class="step"><div class="n">5</div><b>Never revised</b>Each new quarter is chained onto the published series, so past values never change.</div>
  <div class="step"><div class="n">6</div><b>Hard to move</b>No single sale has ever changed a quarter by more than {max(float(r['max_single_sale_effect_pct']) for r in city if r['max_single_sale_effect_pct']):.1f}%. The settlement value filters out measurement noise.</div>
</div>
<p><a href="methodology.html">Full methodology →</a></p>
</section>

<section><h2>Why it is built this way</h2>
<div class="grid2"><div>
<h3>Research behind the choices</h3>
<ul class="clean small">
<li><b>Hedonic, not repeat-sales.</b> Apartment buildings rarely sell twice in a decade, so a repeat-sales index (like Case-Shiller) would discard most sales. For indexes used to settle derivatives, hedonic indexes are much more stable under revision than repeat-sales ones (Clapham, Englund, Quigley &amp; Redfearn 2006), and they signal turning points sooner (Shimizu, Nishimura &amp; Watanabe 2010). Hill (2013) surveys the method.</li>
<li><b>Rolling window, chained.</b> This is the rolling-window time-dummy method of the IMF/Eurostat <i>Handbook on Residential Property Price Indices</i>. Revision is a key risk for index derivatives (Deng &amp; Quigley 2008), so published values are never changed.</li>
<li><b>Filtering a thin market.</b> Indexes built from scarce transactions are noisy. Tradable commercial real-estate indexes handle this with signal extraction and frequency conversion (Bokhari &amp; Geltner 2010; Bourassa, Cantoni &amp; Hoesli 2017). The settlement value uses a Kalman filter for the same purpose.</li>
</ul></div><div>
<h3>Why rent-stabilized buildings</h3>
<ul class="clean small">
<li>Rent rules change what a building can earn, so they change what it is worth. When rent control ended in Cambridge, MA, the value of formerly controlled buildings and their neighbors rose sharply (Autor, Palmer &amp; Pathak 2014). When San Francisco expanded rent control, landlords reduced rental supply (Diamond, McQuade &amp; Qian 2019).</li>
<li>New York's 2019 Housing Stability and Tenant Protection Act limited rent increases on stabilized apartments. The index shows stabilized buildings falling from that quarter on, while market-rate rental buildings did not.</li>
<li><b>Cross-check:</b> Ariel Property Advisors reports stabilized building prices of $270K per unit in 2019 and $163K in 2025 (−40%). The index's levels are about $263K and $159K–$169K.</li>
</ul></div></div>
</section>

<section id="data"><h2>Quarterly values</h2>
<div class="tablewrap"><table><thead><tr><th>Quarter</th><th>Settlement index</th><th>$ per apartment</th><th>Raw estimate</th><th>Raw change</th><th>95% interval</th><th>Sales</th><th>Max single-sale effect</th></tr></thead><tbody>{rows}</tbody></table></div>
<h3>Downloads</h3>
<div class="dl">
<a href="data/rsi_citywide.csv">Citywide index (CSV)</a><a href="data/rsi.json">All series + metadata (JSON)</a>
<a href="data/rsi_market_rate_comparison.csv">Market-rate comparison (CSV)</a><a href="data/rsi_manhattan.csv">Manhattan</a><a href="data/rsi_bronx.csv">Bronx</a><a href="data/rsi_brooklyn.csv">Brooklyn</a><a href="data/rsi_queens.csv">Queens</a>
<a href="data/sales_clean.csv">Every sale used (CSV)</a><a href="data/sales_excluded.csv">Every sale excluded, with reason (CSV)</a><a href="data/stabilized_bbls.csv">Stabilized buildings list (CSV)</a>
</div>
<p class="small muted">Release built {rel.get('built_at', '')} from code version <code>{rel.get('code_commit') or 'n/a'}</code>. Input snapshots and their checksums are listed in <code>rsi.json</code> under <code>release</code>.</p>
</section>

<section><h2>Governance</h2>
<div class="grid2 small"><div>
<p>The index follows the structure of the IOSCO <i>Principles for Financial Benchmarks</i> (2013): governance, benchmark quality, methodology quality and accountability.</p>
<ul class="clean">
<li><b>Transparent methodology:</b> the full method and code are public, and every number can be recomputed from the published inputs.</li>
<li><b>Data sufficiency:</b> a quarter is published only with at least 40 qualifying sales. The minimum so far is {min(int(r['sales']) for r in city)}.</li>
<li><b>Changes:</b> method changes are announced at least one quarter ahead, and filter parameters are re-estimated at most once a year, with notice.</li>
</ul></div><div><ul class="clean">
<li><b>Corrections:</b> published values are not revised. A data error is corrected with a dated notice, and the original value is kept for the record.</li>
<li><b>Audit trail:</b> each release records its code version and input checksums.</li>
<li><b>Questions and complaints:</b> open an issue on <a href="{REPO}/issues">GitHub</a>.</li>
</ul>
<div class="note">This is a research preview. It has not been independently audited, and no administrator has been formally designated under any benchmark regulation.</div>
</div></div>
</section>

<section><h2>Limitations</h2>
<ul class="clean small">
<li>Stabilization status comes from the 2024 registrations. Buildings that left stabilization before then, mostly before 2019, are missing from the early years.</li>
<li>Portfolio deals are excluded because the city records only their total price, not a price per building.</li>
<li>Sales are dated by deed, so the index trails deal-making by one to three months.</li>
<li>The model cannot see the share of apartments that are stabilized, the rent roll or building condition. These drive value, so quarterly estimates are noisy (about ±7%).</li>
</ul>
</section></div>
<script>window.RSI = {json.dumps(data, separators=(",", ":"))};</script>
<script>{CHART_JS}</script>
"""
    os.makedirs(os.path.join(DOCS, "data"), exist_ok=True)
    open(os.path.join(DOCS, "index.html"), "w").write(page("NYC Rent-Stabilized Building Price Index", body, "home"))
    md = open(os.path.join(ROOT, "METHODOLOGY.md")).read()
    md_html = markdown.markdown(md, extensions=["tables", "fenced_code"])
    open(os.path.join(DOCS, "methodology.html"), "w").write(page("Methodology · NYC Rent-Stabilized Building Price Index",
                                                                  f'<div class="wrap md" style="padding:30px 20px">{md_html}</div>', "method"))
    for f in os.listdir(DATA):
        if f.endswith((".csv", ".json", ".png")):
            shutil.copy(os.path.join(DATA, f), os.path.join(DOCS, "data", f))
    open(os.path.join(DOCS, ".nojekyll"), "w").write("")
    print("site written to", DOCS)


if __name__ == "__main__":
    build()

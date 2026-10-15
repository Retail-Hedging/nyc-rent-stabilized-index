#!/usr/bin/env python3
"""Charts for the RSI: data/rsi_chart.png (citywide vs market-rate, with 95% band) and data/rsi_boroughs.png."""
import csv, math, os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

D = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
load = lambda n: list(csv.DictReader(open(os.path.join(D, f"rsi_{n}.csv"))))
INK, STAB, MKT, GRID = "#1B2631", "#C0392B", "#2E6F95", "#E3E8EA"


def style(ax, title):
    ax.set_title(title, loc="left", fontsize=13, color=INK, fontweight="bold")
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.grid(axis="y", color=GRID)
    ax.tick_params(colors=INK)
    ax.axhline(100, color="#999", lw=0.8, ls=":")


def xt(rows):
    return list(range(len(rows))), [r["quarter"] if r["quarter"].endswith("Q1") else "" for r in rows]


c, m = load("citywide"), load("market_rate_comparison")
x, labels = xt(c)
fig, ax = plt.subplots(figsize=(10, 5.2), dpi=150)
ax.plot(x, [float(r["index"]) for r in c], color=STAB, lw=1.0, alpha=0.35, label="Rent-stabilized, raw quarterly estimate")
ax.plot(x, [float(r["settlement_index"]) for r in c], color=STAB, lw=2.6, label="Rent-stabilized buildings (settlement value)")
ax.plot(x, [float(r["index"]) for r in m], color=MKT, lw=1.0, alpha=0.35)
ax.plot(x, [float(r["settlement_index"]) for r in m], color=MKT, lw=2.2, label="Market-rate rental buildings, 6+ apts (settlement value)")
i19 = [r["quarter"] for r in c].index("2019Q2")
ax.axvline(i19, color="#777", lw=0.8)
ax.annotate("June 2019 rent law (HSTPA)", (i19, 133), xytext=(5, 0), textcoords="offset points", fontsize=9, color="#555")
for ser, col in ((c, STAB), (m, MKT)):
    v = float(ser[-1]["settlement_index"])
    ax.annotate(f"{v:.0f}", (x[-1], v), xytext=(6, -4), textcoords="offset points", fontsize=11, color=col, fontweight="bold")
style(ax, "NYC Rent-Stabilized Building Price Index (Q2 2019 = 100)")
ax.set_xticks(x)
ax.set_xticklabels([l[:4] for l in labels], fontsize=9)
ax.set_ylabel("Quality-adjusted price per apartment", color=INK)
ax.legend(frameon=False, loc="lower left", fontsize=9)
ax.set_ylim(35, 140)
fig.text(0.01, 0.01, "Sources: NYC Dept. of Finance sales; NYS HCR 2024 registrations (NYC Rent Guidelines Board). Hedonic rolling-window index; faint lines = raw quarterly estimates (about +/-7% noise).", fontsize=7.5, color="#666")
fig.tight_layout(rect=(0, 0.03, 1, 1))
fig.savefig(os.path.join(D, "rsi_chart.png"))

fig, ax = plt.subplots(figsize=(10, 5.2), dpi=150)
cols = {"manhattan": "#7D3C98", "bronx": "#C0392B", "brooklyn": "#D68910", "queens": "#239B56"}
for n, col in cols.items():
    s = load(n)
    xs, _ = xt(s)
    ax.plot(xs, [float(r["settlement_index"]) for r in s], color=col, lw=2.0, label=n.title())
    dy = {"queens": -12, "brooklyn": 4}.get(n, -4)
    ax.annotate(f"{n.title()} {float(s[-1]['settlement_index']):.0f}", (xs[-1], float(s[-1]["settlement_index"])), xytext=(6, dy), textcoords="offset points", fontsize=9, color=col)
style(ax, "Rent-stabilized building prices by borough (indicative, Q2 2019 = 100)")
fig.text(0.01, 0.01, "Borough series rest on 15-90 sales a quarter (about +/-10-15% noise); for context, not for settlement.", fontsize=7.5, color="#666")
ax.set_xticks(x)
ax.set_xticklabels([l[:4] for l in labels], fontsize=9)
ax.set_xlim(right=len(x) + 6)
fig.tight_layout(rect=(0, 0.03, 1, 1))
fig.savefig(os.path.join(D, "rsi_boroughs.png"))
print("charts written")

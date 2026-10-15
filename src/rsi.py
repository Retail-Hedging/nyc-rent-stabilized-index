#!/usr/bin/env python3
"""NYC Rent-Stabilized Building Price Index (RSI).

Quarterly, quality-adjusted price per apartment for whole-building sales of NYC buildings that
contain rent-stabilized units. Everything is computed from public data, deterministically:

  sales      NYC Department of Finance sales (NYC Open Data w2pb-icbu, usep-8jbt)
  stabilized NYS HCR 2024 building registrations, as published by the NYC Rent Guidelines Board

Method (IMF/Eurostat RPPI Handbook, rolling-window time-dummy hedonic with movement splicing):
  ln(price per apartment) = quarter effects + borough + neighborhood (shrunk) + ln(apartments)
                            + ln(sq ft per apartment) + building era + elevator + mixed-use
  * fitted with Huber weights (robust to outliers) and a ridge penalty on neighborhood effects;
  * each window is the latest 12 quarters; the newest quarter's movement exp(d_T - d_{T-1}) is chained
    onto the published series, so published values are never revised (required for settlement);
  * every quarter reports its sample size, a 95% interval for the quarter-on-quarter change, and the
    largest change any single sale could cause (leave-one-out), as a manipulation-resistance check.

Usage: rsi.py build        -> data/rsi_*.csv, data/rsi.json, data/sales_clean.csv, data/sales_excluded.csv
"""
import csv, json, math, os, re, sys
from collections import Counter, defaultdict

import numpy as np

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
DATA = os.path.join(ROOT, "data")
RAW = os.path.join(ROOT, "raw")
BOROUGH = {"1": "Manhattan", "2": "Bronx", "3": "Brooklyn", "4": "Queens", "5": "Staten Island"}

WINDOW = 12  # quarters per regression window
BASE = "2019Q2"  # = 100; the quarter the 2019 rent law (HSTPA) passed
MIN_N = 40  # minimum sales in a quarter for a published value
RIDGE_NBHD = 4.0  # shrinkage on neighborhood effects (in units of residual variance)
HUBER_K = 1.345
UNIT_TRANSFER_PPU = 40_000  # an address with an apartment number below this per-apartment price is a single-unit transfer
PPU_RANGE = (10_000, 3_000_000)
# Settlement filter (local-level Kalman on log index). Signal and noise variances per quarter, estimated by
# maximum likelihood on the 2016Q1-2026Q3 citywide series and then FIXED (re-estimate at most yearly, with notice).
# The filter uses only data up to each quarter, so settlement values are never revised. On the history it removes
# the raw index's noise-driven reversals (contrarian edge 1.65%/quarter -> 0.05%).
KF_SIGNAL_VAR = 0.048 ** 2
KF_NOISE_VAR = 0.028 ** 2


# ---------------------------------------------------------------- data

def quarter(date):
    return f"{date[:4]}Q{(int(date[5:7]) - 1) // 3 + 1}"


def month(date):
    return date[:7]


def period_end(label):
    """Last calendar day of a period label ('2026Q3' or '2026-09'), as YYYY-MM-DD."""
    import calendar
    y = int(label[:4])
    m = int(label[-1]) * 3 if "Q" in label else int(label[5:7])
    return f"{y}-{m:02d}-{calendar.monthrange(y, m)[1]:02d}"


def num(v):
    try:
        return float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return 0.0


def load_stabilized():
    """bbl -> 'core' | 'other'. Core = classic rent-stabilized; 'other' = 421-a (temporary, new construction),
    co-op/condo, Section 610, rooming houses (Class B), which behave differently."""
    out = {}
    for r in csv.DictReader(open(os.path.join(DATA, "stabilized_bbls.csv"))):
        s = r["status"]
        other = any(t in s for t in ("421-A", "COOP", "CONDO", "SECTION 610", "MULTIPLE DWELLING B"))
        if out.get(r["bbl"]) != "other":
            out[r["bbl"]] = "other" if other else "core"
    return out


def load_sales():
    rows, seen = [], set()
    for ds in ("w2pb-icbu", "usep-8jbt"):
        for r in json.load(open(os.path.join(RAW, f"sales_{ds}.json")))["rows"]:
            boro = str(r["borough"])[0]
            bbl = f"{boro}{int(r['block']):05d}{int(r['lot']):04d}"
            date = r["sale_date"][:10]
            price = num(r["sale_price"])
            key = (bbl, date, price)
            if key in seen:
                continue  # the two datasets overlap by a quarter
            seen.add(key)
            rows.append({
                "bbl": bbl, "borough": boro, "neighborhood": (r.get("neighborhood") or "").strip(), "address": r.get("address") or "",
                "zip": r.get("zip_code") or "", "cls": (r.get("building_class_at_time_of") or "").strip(), "date": date,
                "quarter": quarter(date), "month": month(date), "price": price, "units": num(r.get("residential_units")),
                "commercial": num(r.get("commercial_units")), "sqft": num(r.get("gross_square_feet")),
                "year": int(num(r.get("year_built"))), "source": ds,
            })
    return rows


def clean(rows, stabilized, universe="core"):
    """Screens (each exclusion is logged with its reason). universe: 'core' stabilized, or 'market' =
    6+ apartment rental buildings with no stabilized units (comparison series)."""
    by_deal = Counter((r["date"], r["price"], r["borough"]) for r in rows)
    keep, drop = [], []
    for r in rows:
        status = stabilized.get(r["bbl"])
        ppu = r["price"] / r["units"] if r["units"] else 0
        reason = None
        if universe == "core" and status != "core":
            reason = "not in stabilized list" if status is None else "stabilized: 421-a / co-op / Class B / 610"
        elif universe == "market" and status is not None:
            reason = "has stabilized units"
        elif not r["cls"] or r["cls"][0] not in "CDS":
            reason = f"not a rental building class ({r['cls'] or '?'})"
        elif by_deal[(r["date"], r["price"], r["borough"])] > 1:
            reason = "portfolio sale (one price recorded on several lots)"
        elif re.search(r",\s*\S+$", r["address"]) and ppu < UNIT_TRANSFER_PPU:
            reason = "single-apartment transfer"
        elif not PPU_RANGE[0] <= ppu <= PPU_RANGE[1]:
            reason = "price per apartment outside $10k-$3M"
        (drop if reason else keep).append({**r, "ppu": ppu, **({"reason": reason} if reason else {})})
    # outlier fence per borough-year on log price per apartment (3 x IQR, data errors)
    groups = defaultdict(list)
    for r in keep:
        groups[(r["borough"], r["date"][:4])].append(math.log(r["ppu"]))
    fences = {}
    for k, v in groups.items():
        q1, q3 = np.percentile(v, [25, 75])
        fences[k] = (q1 - 3 * (q3 - q1), q3 + 3 * (q3 - q1))
    final = []
    for r in keep:
        lo, hi = fences[(r["borough"], r["date"][:4])]
        if lo <= math.log(r["ppu"]) <= hi:
            final.append(r)
        else:
            drop.append({**r, "reason": "outlier (3x IQR, borough-year)"})
    return final, drop


# ---------------------------------------------------------------- model

ERAS = [(0, 1900), (1900, 1930), (1930, 1947), (1947, 1974), (1974, 9999)]


def design(obs, quarters):
    """Columns: intercept | quarter dummies (except first) | borough | neighborhood (penalized) | covariates."""
    qidx = {q: i for i, q in enumerate(quarters)}
    boros = sorted({o["borough"] for o in obs})
    nbhds = sorted({o["neighborhood"] for o in obs})
    sq = [math.log(o["sqft"] / o["units"]) for o in obs if o["sqft"] > 0 and o["units"]]
    sq_med = float(np.median(sq)) if sq else 0.0
    cols = ["const"] + [f"q:{q}" for q in quarters[1:]] + [f"b:{b}" for b in boros[1:]] + [f"n:{n}" for n in nbhds] + \
        ["ln_units", "ln_sqft_pu", "sqft_missing"] + [f"era:{a}-{b}" for a, b in ERAS[1:]] + ["elevator", "mixed_use"]
    ci = {c: i for i, c in enumerate(cols)}
    X = np.zeros((len(obs), len(cols)))
    for r, o in enumerate(obs):
        X[r, 0] = 1
        if qidx[o["quarter"]] > 0:
            X[r, ci[f"q:{o['quarter']}"]] = 1
        if o["borough"] != boros[0]:
            X[r, ci[f"b:{o['borough']}"]] = 1
        X[r, ci[f"n:{o['neighborhood']}"]] = 1
        X[r, ci["ln_units"]] = math.log(o["units"])
        if o["sqft"] > 0:
            X[r, ci["ln_sqft_pu"]] = math.log(o["sqft"] / o["units"]) - sq_med
        else:
            X[r, ci["sqft_missing"]] = 1
        yb = o["year"] if o["year"] > 1700 else 1925
        for a, b in ERAS[1:]:
            if a <= yb < b:
                X[r, ci[f"era:{a}-{b}"]] = 1
        X[r, ci["elevator"]] = 1 if o["cls"].startswith("D") else 0
        X[r, ci["mixed_use"]] = 1 if o["cls"].startswith("S") or o["commercial"] > 0 else 0
    # drop columns with no variation in this window (e.g. an era with no sales), except the intercept
    keep = [0] + [j for j in range(1, X.shape[1]) if np.ptp(X[:, j]) > 0 or cols[j].startswith("q:")]
    X = X[:, keep]
    cols = [cols[j] for j in keep]
    pen = np.array([RIDGE_NBHD if c.startswith("n:") else 0.0 for c in cols])
    return X, cols, pen


def robust_fit(X, y, pen, iters=30):
    """Huber IRLS with ridge on penalized columns. Returns beta, covariance (sandwich), weights, sigma."""
    w = np.ones(len(y))
    beta = None
    for _ in range(iters):
        A = X.T @ (X * w[:, None])
        resid0 = y - X @ beta if beta is not None else y - y.mean()
        s2 = max(1e-6, float(np.sum(w * resid0 ** 2) / max(1, w.sum() - X.shape[1])))
        A_pen = A + np.diag(pen * s2)
        beta_new = np.linalg.solve(A_pen, X.T @ (w * y))
        resid = y - X @ beta_new
        mad = float(np.median(np.abs(resid - np.median(resid)))) * 1.4826 or 1e-6
        u = np.abs(resid) / (HUBER_K * mad)
        w_new = np.where(u <= 1, 1.0, 1.0 / np.maximum(u, 1e-12))
        if beta is not None and np.max(np.abs(beta_new - beta)) < 1e-9:
            beta, w = beta_new, w_new
            break
        beta, w = beta_new, w_new
    resid = y - X @ beta
    Ainv = np.linalg.inv(X.T @ (X * w[:, None]) + np.diag(pen * s2))
    meat = X.T @ (X * (w * resid) [:, None] ** 2)
    cov = Ainv @ meat @ Ainv
    return beta, cov, w, math.sqrt(s2)


def window_fit(obs, quarters):
    X, cols, pen = design(obs, quarters)
    y = np.array([math.log(o["ppu"]) for o in obs])
    beta, cov, w, sigma = robust_fit(X, y, pen)
    ci = {c: i for i, c in enumerate(cols)}
    d = np.array([0.0] + [beta[ci[f"q:{q}"]] for q in quarters[1:]])
    # covariance of quarter effects (first quarter = 0)
    idx = [None] + [ci[f"q:{q}"] for q in quarters[1:]]
    return {"d": d, "beta": beta, "cov": cov, "idx": idx, "cols": cols, "X": X, "y": y, "w": w, "sigma": sigma, "pen": pen}


def step_se(fit, a, b):
    """Std. error of d_b - d_a (quarter positions)."""
    ia, ib = fit["idx"][a], fit["idx"][b]
    c = fit["cov"]
    v = (c[ib, ib] if ib is not None else 0) + (c[ia, ia] if ia is not None else 0) - (2 * c[ia, ib] if ia is not None and ib is not None else 0)
    return math.sqrt(max(v, 0))


def max_single_sale_influence(fit):
    """Largest change (fraction) to the newest quarter's movement from deleting any one sale in the window.
    Closed-form leave-one-out for weighted least squares (weights held at their converged values):
    beta_(-i) = beta - A^-1 x_i w_i e_i / (1 - h_i)."""
    X, y, w, cov_idx = fit["X"], fit["y"], fit["w"], fit["idx"]
    A = X.T @ (X * w[:, None]) + np.diag(fit["pen"] * fit["sigma"] ** 2)
    Ainv = np.linalg.inv(A)
    e = y - X @ fit["beta"]
    G = X @ Ainv  # rows: x_i^T A^-1
    h = np.einsum("ij,ij->i", G, X) * w
    shift = G * (w * e / np.maximum(1 - h, 1e-6))[:, None]  # rows: change in beta when sale i is removed (negated)
    iT, iP = cov_idx[-1], cov_idx[-2]
    dmove = shift[:, iT] - (shift[:, iP] if iP is not None else 0)
    return float(np.max(np.abs(np.expm1(dmove))))


def all_quarters(obs):
    """Every period between the first and last observed (quarters 'YYYYQn' or months 'YYYY-MM')."""
    qs = sorted({o["quarter"] for o in obs})
    y0, y1 = int(qs[0][:4]), int(qs[-1][:4])
    if "-" in qs[0]:
        full = [f"{y}-{m:02d}" for y in range(y0, y1 + 1) for m in range(1, 13)]
    else:
        full = [f"{y}Q{q}" for y in range(y0, y1 + 1) for q in range(1, 5)]
    return [q for q in full if qs[0] <= q <= qs[-1]]


def as_periods(obs, freq):
    """Copy of obs with the 'quarter' field set to the period label for freq ('Q' or 'M')."""
    return obs if freq == "Q" else [{**o, "quarter": o["month"]} for o in obs]


def build_series(obs, influence=True, min_n=MIN_N, window=WINDOW, base_period=BASE, kf=None):
    """Rolling-window time-dummy index with movement splicing. Returns list of per-quarter dicts."""
    quarters = all_quarters(obs)
    count = Counter(o["quarter"] for o in obs)
    out = []
    # first window: its quarter effects define the initial history
    first = quarters[:window]
    f0 = window_fit([o for o in obs if o["quarter"] in first], first)
    level = [math.exp(v) for v in f0["d"]]
    for i, q in enumerate(first):
        se = step_se(f0, i - 1, i) if i else 0.0
        out.append({"quarter": q, "raw": level[i], "n": count[q], "move": level[i] / level[i - 1] if i else 1.0, "move_se": se,
                    "window": f"{first[0]}-{first[-1]}", "influence": None})
    for t in range(window, len(quarters)):
        win = quarters[t - window + 1:t + 1]
        sub = [o for o in obs if o["quarter"] in win]
        f = window_fit(sub, win)
        move = math.exp(f["d"][-1] - f["d"][-2])
        se = step_se(f, len(win) - 2, len(win) - 1)
        infl = max_single_sale_influence(f) if influence else None
        out.append({"quarter": quarters[t], "raw": out[-1]["raw"] * move, "n": count[quarters[t]], "move": move, "move_se": se,
                    "window": f"{win[0]}-{win[-1]}", "influence": infl})
    base = next((o["raw"] for o in out if o["quarter"] == base_period), out[0]["raw"])
    for o in out:
        o["index"] = 100 * o["raw"] / base
        o["move_lo"] = o["move"] * math.exp(-1.96 * o["move_se"])
        o["move_hi"] = o["move"] * math.exp(1.96 * o["move_se"])
        o["published"] = o["n"] >= min_n
    return settlement_filter(out, *(kf or (KF_SIGNAL_VAR, KF_NOISE_VAR)))


def kf_step(level, var, y, signal_var, noise_var):
    """One step of the local-level Kalman filter on log index. Returns (level, var)."""
    pred_var = var + signal_var
    gain = pred_var / (pred_var + noise_var)
    return level + gain * (y - level), (1 - gain) * pred_var


def settlement_filter(series, signal_var=KF_SIGNAL_VAR, noise_var=KF_NOISE_VAR):
    """Adds 'settlement' (+ filter state): real-time local-level Kalman filter on log index, fixed parameters."""
    level, var = math.log(series[0]["index"]), noise_var
    for i, o in enumerate(series):
        if i:
            level, var = kf_step(level, var, math.log(o["index"]), signal_var, noise_var)
        o["settlement"], o["kf_level"], o["kf_var"] = math.exp(level), level, var
    return series


def reference_ppu(obs, quarter_):
    """$ per apartment for the typical building in the base quarter (median of the quarter's sales), to express
    the index as a dollar level: level_t = reference * index_t / 100."""
    v = [o["ppu"] for o in obs if o["quarter"] == quarter_]
    return float(np.median(v)) if v else None


def median_series(obs):
    by = defaultdict(list)
    for o in obs:
        by[o["quarter"]].append(o["ppu"])
    return {q: float(np.median(v)) for q, v in by.items()}


# ---------------------------------------------------------------- outputs

def write_series(name, series, ref, medians):
    path = os.path.join(DATA, f"rsi_{name}.csv")
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["quarter", "index", "settlement_index", "settlement_usd_per_apartment", "usd_per_apartment", "sales", "qoq_change_pct", "qoq_ci95_lo_pct", "qoq_ci95_hi_pct",
                    "max_single_sale_effect_pct", "published", "median_usd_per_apartment", "window"])
        for o in series:
            w.writerow([o["quarter"], f"{o['index']:.2f}", f"{o['settlement']:.2f}", round(ref * o["settlement"] / 100) if ref else "",
                        round(ref * o["index"] / 100) if ref else "", o["n"],
                        f"{100 * (o['move'] - 1):.2f}", f"{100 * (o['move_lo'] - 1):.2f}", f"{100 * (o['move_hi'] - 1):.2f}",
                        "" if o["influence"] is None else f"{100 * o['influence']:.2f}", int(o["published"]),
                        round(medians.get(o["quarter"], 0)), o["window"]])
    return path


def release_info():
    """Audit trail: code version and the exact input snapshots behind this release."""
    import datetime, hashlib, subprocess
    try:
        commit = subprocess.run(["git", "-C", ROOT, "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip() or None
    except OSError:
        commit = None
    inputs = {}
    for name in ("sales_w2pb-icbu.json", "sales_usep-8jbt.json"):
        path = os.path.join(RAW, name)
        if os.path.exists(path):
            raw = json.load(open(path))
            inputs[name] = {"fetched": raw.get("fetched"), "rows": len(raw["rows"]),
                            "sha256": hashlib.sha256(open(path, "rb").read()).hexdigest()[:16]}
    path = os.path.join(DATA, "stabilized_bbls.csv")
    inputs["stabilized_bbls.csv"] = {"source": "NYS HCR 2024 building registrations (NYC Rent Guidelines Board PDFs, Nov 2025)",
                                     "sha256": hashlib.sha256(open(path, "rb").read()).hexdigest()[:16]}
    return {"built_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%MZ"), "code_commit": commit,
            "inputs": inputs, "parameters": {"window_quarters": WINDOW, "base": BASE, "min_sales": MIN_N, "ridge_neighborhood": RIDGE_NBHD,
                                             "huber_k": HUBER_K, "kf_signal_sd": round(math.sqrt(KF_SIGNAL_VAR), 4),
                                             "kf_noise_sd": round(math.sqrt(KF_NOISE_VAR), 4)}}


def build():
    stabilized = load_stabilized()
    rows = load_sales()
    results = {}
    core, dropped = clean(rows, stabilized, "core")
    with open(os.path.join(DATA, "sales_clean.csv"), "w", newline="") as f:
        cols = ["bbl", "date", "quarter", "borough", "neighborhood", "address", "cls", "units", "sqft", "year", "price", "ppu", "source"]
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(sorted(core, key=lambda r: r["date"]))
    with open(os.path.join(DATA, "sales_excluded.csv"), "w", newline="") as f:
        cols = ["bbl", "date", "address", "cls", "units", "price", "reason"]
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(sorted((d for d in dropped if d.get("reason") not in ("not in stabilized list",)), key=lambda r: r["date"]))
    reasons = Counter(d["reason"] for d in dropped)
    print(f"core sales kept: {len(core)}; excluded: {dict(reasons)}", file=sys.stderr)

    series = {"citywide": (core, MIN_N, True)}
    for b in ("1", "2", "3", "4"):
        series[BOROUGH[b].lower()] = ([o for o in core if o["borough"] == b], 15, False)
    market, _ = clean(rows, stabilized, "market")
    series["market_rate_comparison"] = (market, 15, False)
    for name, (obs, min_n, infl) in series.items():
        s = build_series(obs, influence=infl, min_n=min_n)
        ref = reference_ppu(obs, BASE)
        write_series(name, s, ref, median_series(obs))
        results[name] = {"sales": len(obs), "reference_usd_per_apartment": ref, "series": s}
        last = s[-1]
        print(f"{name:<24} n={len(obs):>5}  {s[0]['quarter']}..{last['quarter']}  index {last['index']:.1f}  settlement {last['settlement']:.1f} (base {BASE}=100)", file=sys.stderr)
    meta = {
        "name": "NYC Rent-Stabilized Building Price Index (RSI)",
        "base": f"{BASE} = 100", "frequency": "quarterly", "window_quarters": WINDOW, "min_sales_published": MIN_N,
        "sources": {"sales": "NYC Department of Finance via NYC Open Data (w2pb-icbu, usep-8jbt)",
                    "stabilized": "NYS HCR 2024 building registrations, NYC Rent Guidelines Board lists (Nov 2025)"},
        "series": {k: [{kk: (round(vv, 6) if isinstance(vv, float) else vv) for kk, vv in o.items()} for o in v["series"]] for k, v in results.items()},
        "reference_usd_per_apartment": {k: v["reference_usd_per_apartment"] for k, v in results.items()},
    }
    meta["release"] = release_info()
    json.dump(meta, open(os.path.join(DATA, "rsi.json"), "w"), indent=1)
    return results


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "build":
        build()
    else:
        sys.exit(__doc__)

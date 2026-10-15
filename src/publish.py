#!/usr/bin/env python3
"""Publishing ledger: turns the model into an append-only record of official values.

The city adds late-recorded deeds to past months, so recomputing the index from scratch each month would
quietly rewrite history. Instead, values are published once into data/ledger_{Q,M}.json and never changed;
each new period is chained onto the last published value with the movement estimated on the latest data
(rolling-window time-dummy method, movement splice), and the settlement filter continues from its stored state.

Completeness rule: a period becomes official only when the data runs at least LAG_DAYS past its end
(about 20% of deeds take more than 19 days to be recorded). Later periods with data are published as
provisional readings and replaced when they become official.

Usage: publish.py   (after `rsi.py build`; rewrites data/rsi_citywide*.csv and the citywide part of data/rsi.json)
"""
import csv, datetime, json, math, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rsi  # noqa: E402

LAG_DAYS = 30
FREQS = {
    "Q": {"label": "quarterly", "window": 12, "min_n": 40, "base": ["2019Q2"], "kf": (rsi.KF_SIGNAL_VAR, rsi.KF_NOISE_VAR), "influence": True},
    # monthly: signal sd 2.8%, noise sd 6.9% per month (MLE on 2016-2026, fixed; re-estimate at most yearly, with notice)
    "M": {"label": "monthly", "window": 36, "min_n": 20, "base": ["2019-04", "2019-05", "2019-06"], "kf": (0.0279 ** 2, 0.0686 ** 2), "influence": False},
}


def today():
    return datetime.date.today().isoformat()


def data_through():
    """Last sale date in the newest sales snapshot (the rolling 12-month file)."""
    best = ""
    for name in ("sales_usep-8jbt.json", "sales_w2pb-icbu.json"):
        path = os.path.join(rsi.RAW, name)
        if os.path.exists(path):
            best = max([best] + [r["sale_date"][:10] for r in json.load(open(path))["rows"]])
    return best


def complete(label, through, lag=LAG_DAYS):
    end = datetime.date.fromisoformat(rsi.period_end(label))
    return end + datetime.timedelta(days=lag) <= datetime.date.fromisoformat(through)


def ledger_path(freq, data_dir=rsi.DATA):
    return os.path.join(data_dir, f"ledger_{freq}.json")


def entry(period, raw, index, level, var, n, move=None, se=None, infl=None, mode="live", release=None, through=None):
    e = {"period": period, "raw": raw, "index": index, "settlement": math.exp(level), "kf_level": level, "kf_var": var, "n": n,
         "mode": mode, "published_at": today(), "data_through": through, "code_commit": (release or {}).get("code_commit")}
    if move is not None:
        e.update({"move": move, "move_lo": move * math.exp(-1.96 * se), "move_hi": move * math.exp(1.96 * se), "influence": infl})
    return e


def backfill(obs, cfg, through, release):
    """First run: compute history on current data and freeze every complete period."""
    s = rsi.build_series(obs, influence=cfg["influence"], min_n=cfg["min_n"], window=cfg["window"], base_period=None, kf=cfg["kf"])
    base_raw = sum(o["raw"] for o in s if o["quarter"] in cfg["base"]) / len(cfg["base"])
    for o in s:
        o["index"] = 100 * o["raw"] / base_raw
    rsi.settlement_filter(s, *cfg["kf"])
    ref = rsi.np.median([o["ppu"] for o in obs if o["quarter"] in cfg["base"]])
    periods = [entry(o["quarter"], o["raw"], o["index"], o["kf_level"], o["kf_var"], o["n"], o["move"], o["move_se"], o["influence"],
                     "backfill", release, through) for o in s if complete(o["quarter"], through)]
    return {"freq": cfg["label"], "base": cfg["base"], "base_raw": base_raw, "reference_usd_per_apartment": float(ref),
            "kf": list(cfg["kf"]), "window": cfg["window"], "min_n": cfg["min_n"], "lag_days": LAG_DAYS, "created_at": today(), "periods": periods}


def chain(obs, periods, prev, label, cfg, ledger, through, release, mode):
    """Chain one new period onto the previous published (or provisional) value."""
    i = periods.index(label)
    win = periods[max(0, i - cfg["window"] + 1):i + 1]
    if prev["period"] not in win:
        raise ValueError(f"gap too long: {prev['period']} -> {label}")
    sub = [o for o in obs if o["quarter"] in win]
    fit = rsi.window_fit(sub, win)
    a, b = win.index(prev["period"]), win.index(label)
    move = math.exp(fit["d"][b] - fit["d"][a])
    se = rsi.step_se(fit, a, b)
    infl = rsi.max_single_sale_influence(fit) if cfg["influence"] and b == len(win) - 1 and a == b - 1 else None
    raw = prev["raw"] * move
    index = 100 * raw / ledger["base_raw"]
    level, var = rsi.kf_step(prev["kf_level"], prev["kf_var"], math.log(index), *ledger["kf"])
    n = sum(1 for o in obs if o["quarter"] == label)
    return entry(label, raw, index, level, var, n, move, se, infl, mode, release, through)


def update(core, freq, through, release, data_dir=rsi.DATA):
    """Load (or create) the ledger, append newly complete periods, compute provisional ones. Returns (ledger, provisional)."""
    cfg = FREQS[freq]
    obs = rsi.as_periods(core, freq)
    periods = rsi.all_quarters(obs)
    path = ledger_path(freq, data_dir)
    if os.path.exists(path):
        ledger = json.load(open(path))
    else:
        ledger = backfill(obs, cfg, through, release)
    last = ledger["periods"][-1]
    for label in periods[periods.index(last["period"]) + 1:]:
        if not complete(label, through):
            break
        last = chain(obs, periods, last, label, cfg, ledger, through, release, "live")
        ledger["periods"].append(last)
    json.dump(ledger, open(path, "w"), indent=1)
    provisional, prev = [], last
    for label in periods[periods.index(last["period"]) + 1:]:
        if sum(1 for o in obs if o["quarter"] == label) < 5:
            break
        prev = chain(obs, periods, prev, label, cfg, ledger, through, release, "provisional")
        provisional.append(prev)
    return ledger, provisional


def write_csv(path, ledger, provisional):
    ref = ledger["reference_usd_per_apartment"]
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["period", "status", "settlement_index", "settlement_usd_per_apartment", "index", "usd_per_apartment", "sales",
                    "change_pct", "ci95_lo_pct", "ci95_hi_pct", "max_single_sale_effect_pct", "published_at", "data_through"])
        for e in ledger["periods"] + provisional:
            status = "provisional" if e["mode"] == "provisional" else ("official" if e["n"] >= ledger["min_n"] else "official (thin)")
            pct = lambda k: f"{100 * (e[k] - 1):.2f}" if k in e else ""
            w.writerow([e["period"], status, f"{e['settlement']:.2f}", round(ref * e["settlement"] / 100), f"{e['index']:.2f}",
                        round(ref * e["index"] / 100), e["n"], pct("move"), pct("move_lo"), pct("move_hi"),
                        "" if e.get("influence") is None else f"{100 * e['influence']:.2f}", e["published_at"], e["data_through"]])


def main():
    stabilized = rsi.load_stabilized()
    core, _ = rsi.clean(rsi.load_sales(), stabilized, "core")
    through = data_through()
    meta_path = os.path.join(rsi.DATA, "rsi.json")
    meta = json.load(open(meta_path))
    release = meta.get("release", {})
    out = {}
    for freq, fname in (("Q", "rsi_citywide.csv"), ("M", "rsi_citywide_monthly.csv")):
        ledger, prov = update(core, freq, through, release)
        write_csv(os.path.join(rsi.DATA, fname), ledger, prov)
        out[ledger["freq"]] = {"official": ledger["periods"], "provisional": prov, "base": ledger["base"],
                               "reference_usd_per_apartment": ledger["reference_usd_per_apartment"]}
        last = ledger["periods"][-1]
        print(f"{ledger['freq']:<9} official through {last['period']} = {last['settlement']:.1f}; "
              f"provisional: {', '.join(f'{p['period']}={p['settlement']:.1f}' for p in prov) or 'none'}", file=sys.stderr)
    meta["citywide"] = out
    meta["data_through"] = through
    meta["completeness_rule"] = f"a period is official once the data runs {LAG_DAYS} days past its end"
    json.dump(meta, open(meta_path, "w"), indent=1)


if __name__ == "__main__":
    main()

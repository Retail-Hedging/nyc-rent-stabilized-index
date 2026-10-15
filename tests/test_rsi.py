import json, math, os, random, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import rsi


def synthetic(path, per_q=120, seed=1):
    """Sales whose true quality-adjusted price follows `path` (one value per quarter)."""
    rnd = random.Random(seed)
    quarters = [f"{2016 + i // 4}Q{i % 4 + 1}" for i in range(len(path))]
    nb = [("1", f"M{i}") for i in range(6)] + [("3", f"B{i}") for i in range(6)] + [("2", f"X{i}") for i in range(4)]
    nb_eff = {n: rnd.gauss(0, 0.25) for _, n in nb}
    obs = []
    for qi, q in enumerate(quarters):
        for _ in range(per_q):
            b, n = rnd.choice(nb)
            units = rnd.randint(6, 120)
            year = rnd.choice([1910, 1925, 1955, 1965, 1985])
            elevator = units > 40
            lnp = math.log(path[qi]) + math.log(250_000) + nb_eff[n] + {"1": 0.4, "3": 0.1, "2": -0.4}[b] \
                - 0.05 * math.log(units) + (0.1 if elevator else 0) + rnd.gauss(0, 0.25)
            m = int(q[-1]) * 3 - 1
            obs.append({"bbl": f"{b}{rnd.randint(1, 99999):05d}0001", "borough": b, "neighborhood": n, "address": "1 TEST ST",
                        "cls": "D1" if elevator else "C1", "date": f"{q[:4]}-{m:02d}-15", "quarter": q, "price": math.exp(lnp) * units,
                        "units": units, "commercial": 0, "sqft": units * rnd.uniform(700, 1000), "year": year, "ppu": math.exp(lnp)})
    return obs


PATH = [1.0, 1.01, 1.02, 1.02, 1.03, 1.03, 1.04, 1.04, 1.05, 1.05, 1.06, 1.06, 1.06, 1.04, 0.98, 0.92, 0.88, 0.86, 0.85, 0.84,
        0.84, 0.83, 0.82, 0.80]


def test_recovers_known_path():
    # 120 sales/quarter with 25% idiosyncratic noise -> ~3% standard error per quarter
    s = rsi.build_series(synthetic(PATH), influence=False, min_n=10)
    base = s[0]["raw"]
    errs = [abs(o["raw"] / base / true - 1) for o, true in zip(s, PATH)]
    assert sum(errs) / len(errs) < 0.025, errs
    assert max(errs) < 0.07, errs
    # the shape survives: the post-peak decline is recovered within 3 points
    assert abs((s[-1]["raw"] / s[11]["raw"]) / (PATH[-1] / PATH[11]) - 1) < 0.03


def test_published_values_never_revise():
    obs = synthetic(PATH)
    full = rsi.build_series(obs, influence=False, min_n=10)
    last_q = full[-1]["quarter"]
    cut = rsi.build_series([o for o in obs if o["quarter"] != last_q], influence=False, min_n=10)
    for a, b in zip(cut, full):
        assert a["quarter"] == b["quarter"]
        assert abs(a["raw"] - b["raw"]) < 1e-12 and abs(a["settlement"] - b["settlement"]) < 1e-9


def test_single_extreme_sale_cannot_move_index():
    obs = synthetic(PATH)
    base = rsi.build_series(obs, influence=False, min_n=10)
    bad = dict(obs[-1])
    bad["ppu"] *= 20  # a wash sale at 20x the going price
    bad["price"] *= 20
    moved = rsi.build_series(obs + [bad], influence=False, min_n=10)
    assert abs(moved[-1]["raw"] / base[-1]["raw"] - 1) < 0.01


def test_screens():
    stab = {"1000010001": "core", "1000010002": "core", "1000010003": "core", "1000010004": "other"}
    row = lambda bbl, **k: {"bbl": bbl, "borough": "1", "neighborhood": "N", "address": "1 A ST", "cls": "C1", "date": "2024-01-02",
                            "quarter": "2024Q1", "price": 5_000_000, "units": 20, "commercial": 0, "sqft": 0, "year": 1920, **k}
    rows = [row("1000010001"),
            row("1000010002", price=9_000_000), row("1000010003", price=9_000_000),  # same deal on two lots
            row("1000010004", price=4_000_000),  # 421-a / co-op
            row("1000010005", price=3_000_000),  # not stabilized
            row("1000010001", address="1 A ST, 4B", price=300_000, date="2024-02-01")]  # single apartment
    keep, drop = rsi.clean(rows, stab, "core")
    reasons = sorted(d["reason"] for d in drop)
    assert [k["bbl"] for k in keep] == ["1000010001"]
    assert reasons.count("portfolio sale (one price recorded on several lots)") == 2
    assert "single-apartment transfer" in reasons and "not in stabilized list" in reasons
    assert any(r.startswith("stabilized: 421-a") for r in reasons)


def test_ledger_freezes_published_values_when_history_is_revised(tmp_path):
    import publish
    obs = synthetic(PATH)
    for o in obs:
        o["month"] = o["date"][:7]
    cut = lambda q: [o for o in obs if o["quarter"] <= q]
    # first publication: data through mid-2020Q3 -> quarters up to 2020Q2 are official
    led1, prov1 = publish.update(cut("2020Q3"), "Q", "2020-08-15", {}, data_dir=str(tmp_path))
    frozen = json.loads(json.dumps(led1["periods"]))
    assert frozen[-1]["period"] == "2020Q2" and [p["period"] for p in prov1] == ["2020Q3"]
    # the city then revises history (late deeds add sales at different prices) and new quarters arrive
    revised = [dict(o, ppu=o["ppu"] * (1.15 if o["quarter"] < "2018Q1" else 1.0)) for o in obs]
    led2, _ = publish.update(revised, "Q", "2021-12-31", {}, data_dir=str(tmp_path))
    for a, b in zip(frozen, led2["periods"]):
        assert a == b  # nothing already published changes
    assert [p["period"] for p in led2["periods"][len(frozen):]] == ["2020Q3", "2020Q4", "2021Q1", "2021Q2", "2021Q3"]

#!/usr/bin/env python3
"""Parse the NYC Rent Guidelines Board lists of buildings containing rent-stabilized units
(NYS HCR 2024 building registrations; one PDF per borough) into data/stabilized_bbls.csv.

Columns are assigned by x-position under the header words, so rows with empty columns
(no 2nd address, no status 2/3) still parse correctly. BBL = borough code + block + lot."""
import csv, os, re, sys
import pymupdf

ROOT = os.path.join(os.path.dirname(__file__), "..")
BOROUGHS = {"Manhattan": 1, "Bronx": 2, "Brooklyn": 3, "Queens": 4, "Staten-Island": 5}
COLS = ["ZIP", "BLDGNO1", "STREET1", "STSUFX1", "BLDGNO2", "STREET2", "STSUFX2", "CITY", "COUNTY", "STATUS1", "STATUS2", "STATUS3", "BLOCK", "LOT"]


def parse(path, boro):
    doc = pymupdf.open(path)
    out = []
    for page in doc:
        words = page.get_text("words")
        hdr = {w[4]: w[0] for w in words if w[4] in COLS}
        if "BLOCK" not in hdr or "LOT" not in hdr:
            continue
        hy = max(w[3] for w in words if w[4] in ("BLOCK", "LOT"))
        starts = sorted((x, c) for c, x in hdr.items())
        rows = {}
        for x0, y0, x1, y1, t, *_ in words:
            if y0 <= hy:
                continue
            rows.setdefault(round(y0 / 2), []).append((x0, t))
        for _, ws in sorted(rows.items()):
            rec = {c: [] for c in COLS}
            for x0, t in sorted(ws):
                col = starts[0][1]
                for sx, c in starts:
                    if x0 >= sx - 3:
                        col = c
                rec[col].append(t)
            r = {c: " ".join(v) for c, v in rec.items()}
            if not (re.fullmatch(r"\d{5}", r["ZIP"]) and r["BLOCK"].isdigit() and r["LOT"].isdigit()):
                continue
            status = " | ".join(s for s in (r["STATUS1"], r["STATUS2"], r["STATUS3"]) if s)
            out.append({"bbl": f"{boro}{int(r['BLOCK']):05d}{int(r['LOT']):04d}", "borough": boro, "zip": r["ZIP"],
                        "address": " ".join(x for x in (r["BLDGNO1"], r["STREET1"], r["STSUFX1"]) if x), "status": status})
    return out


if __name__ == "__main__":
    rows = []
    for name, boro in BOROUGHS.items():
        got = parse(os.path.join(ROOT, "raw", f"rs-{name}.pdf"), boro)
        print(f"{name}: {len(got)} rows, {len({g['bbl'] for g in got})} distinct BBLs", file=sys.stderr)
        rows += got
    os.makedirs(os.path.join(ROOT, "data"), exist_ok=True)
    with open(os.path.join(ROOT, "data", "stabilized_bbls.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["bbl", "borough", "zip", "address", "status"])
        w.writeheader()
        w.writerows(rows)
    print(f"total {len(rows)} rows, {len({r['bbl'] for r in rows})} BBLs", file=sys.stderr)

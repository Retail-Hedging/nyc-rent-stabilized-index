#!/usr/bin/env python3
"""Download NYC Department of Finance sales of buildings with 6+ apartments (NYC Open Data, Socrata):
annualized sales 2016+ (w2pb-icbu) and the latest 12 months (usep-8jbt). Writes raw/sales_<dataset>.json.
No API key needed; requests are paged."""
import json, os, sys, time, urllib.parse, urllib.request

ROOT = os.path.join(os.path.dirname(__file__), "..")
FIELDS = ("borough,neighborhood,building_class_category,block,lot,building_class_at_time_of,address,zip_code,"
          "residential_units,commercial_units,total_units,land_square_feet,gross_square_feet,year_built,sale_price,sale_date")
WHERE = "residential_units >= 6 AND sale_price >= 100000"


def fetch(ds):
    rows, off = [], 0
    while True:
        q = urllib.parse.urlencode({"$select": FIELDS, "$where": WHERE, "$order": "sale_date,borough,block,lot", "$limit": 5000, "$offset": off})
        with urllib.request.urlopen(f"https://data.cityofnewyork.us/resource/{ds}.json?{q}", timeout=120) as r:
            page = json.load(r)
        rows += page
        if len(page) < 5000:
            return rows
        off += 5000
        time.sleep(1)


if __name__ == "__main__":
    os.makedirs(os.path.join(ROOT, "raw"), exist_ok=True)
    for ds in ("w2pb-icbu", "usep-8jbt"):
        rows = fetch(ds)
        json.dump({"dataset": ds, "fetched": time.strftime("%Y-%m-%d"), "where": WHERE, "rows": rows}, open(os.path.join(ROOT, "raw", f"sales_{ds}.json"), "w"))
        print(ds, len(rows), "rows", file=sys.stderr)

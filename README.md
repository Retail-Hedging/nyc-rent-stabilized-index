# NYC Rent-Stabilized Building Price Index (RSI)

A transparent, quarterly price index for New York City buildings that contain rent-stabilized apartments, computed entirely from public records.

**Website:** https://retail-hedging.github.io/nyc-rent-stabilized-index/

- **Latest (Q3 2026):** 57.1, where Q2 2019 = 100 (the quarter the 2019 rent law passed). That's about $150K per apartment, down from $266K.
- **Market-rate rental buildings,** same method: 108.

| Folder | Contents |
|---|---|
| `src/` | `fetch_sales.py` (NYC DOF sales), `parse_rgb.py` (stabilized building lists), `rsi.py` (the index), `chart.py`, `site.py` |
| `data/` | Published series (CSV/JSON), every sale used, every sale excluded with its reason, the stabilized-building list |
| `raw/` | The exact input snapshots behind the current release |
| `docs/` | The website (GitHub Pages) |
| `tests/` | Known-path recovery, no-revision, wash-sale resistance and screening tests |

Read [METHODOLOGY.md](METHODOLOGY.md) for the full method, research basis, governance and limitations.

Research preview published by Retail Hedging. Not affiliated with the City or State of New York. Not investment advice.

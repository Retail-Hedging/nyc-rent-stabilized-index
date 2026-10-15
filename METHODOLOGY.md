# NYC Rent-Stabilized Building Price Index (RSI): methodology

**What it measures:** the quality-adjusted price per apartment paid in whole-building sales of New York City buildings that contain rent-stabilized apartments. It runs quarterly, citywide, with Q2 2019 = 100 (the quarter the 2019 Housing Stability and Tenant Protection Act passed).

**Design goal:** a value anyone can recompute from public data, that a single trade can't move, that is never revised once published, and whose changes can't be predicted from its own history. Those are the properties a settlement index for derivatives needs.

## Results (2016 Q1 – 2026 Q3; Q3 2026 provisional, official through Q2 2026 = 56.0)

| | Q2 2019 | Q3 2026 (provisional) | Change |
|---|---|---|---|
| **Rent-stabilized buildings, citywide** (settlement value) | 100 ≈ $263K/apt | **57.1 ≈ $150K/apt** | **−43%** |
| Market-rate rental buildings, 6+ apartments (comparison) | 100 ≈ $240K/apt | 108.3 ≈ $260K/apt | +8% |

By borough (indicative): Bronx 48, Manhattan 55, Queens 65, Brooklyn 67.

**Cross-check:** Ariel Property Advisors (a brokerage) reports the average price per unit of rent-stabilized buildings falling from $270K in 2019 to $163K in 2025, which is −40%. The RSI's 2025 levels are $159K–$169K.

Charts: `data/rsi_chart.png`, `data/rsi_boroughs.png`.

## 1. Data (all public)

| Input | Source | Notes |
|---|---|---|
| Sales | NYC Department of Finance, via NYC Open Data: annualized sales 2016+ (`w2pb-icbu`) and the latest 12 months (`usep-8jbt`) | Buildings with 6+ apartments, $100K+ sale price. The overlapping quarter is de-duplicated on BBL + date + price. |
| Stabilization status | NYS Homes & Community Renewal 2024 building registrations, published by the NYC Rent Guidelines Board as borough PDFs (Nov 2025) | 47,198 buildings (BBLs), parsed by `src/parse_rgb.py`. |

Raw snapshots are kept in `raw/`, so every published value can be reproduced from the exact files used.

## 2. Universe and screens

A sale enters the index only if all of the following hold. Each exclusion and its reason is written to `data/sales_excluded.csv`.

1. **Core rent-stabilized.** The building (BBL) is on the stabilized list and is not:
   - a 421-a building (temporary stabilization on new construction)
   - a co-op or condo
   - a Class B building (rooming house)
   - a Section 610 building
2. **A rental building** (DOF class C walk-up, D elevator or S mixed-use) with 6 or more apartments.
3. **Not a portfolio sale.** DOF records a multi-building deal's total price on every lot. Same date, same price and same borough on several lots means the per-building price is unknown, so the sale is excluded. 1,255 such records.
4. **Not a single-apartment transfer.** An address with an apartment number and under $40,000 per apartment is excluded. 464 records.
5. **Between $10K and $3M per apartment,** and within 3× the interquartile range of log price per apartment for its borough and year (data errors).

The 2016–2026 data has 5,896 qualifying sales, 51–248 per quarter.

## 3. Model

For each quarter T, a hedonic regression is fitted on the sales of the 12 quarters ending at T:

```
ln(price per apartment) = quarter effects + borough + neighborhood + ln(apartments)
                          + ln(sq ft per apartment) [missing-flagged] + building era (5 bands)
                          + elevator + mixed-use
```

- **Robust.** A Huber M-estimator (k = 1.345, MAD scale) down-weights unusual sales instead of letting them pull the fit.
- **Neighborhood shrinkage.** A ridge penalty (λ = 4) on the ~250 DOF neighborhood effects pulls thinly traded neighborhoods toward their borough.
- **Movement splicing (no revisions).** The newest quarter's change, exp(d_T − d_{T−1}), is chained onto the already-published series. Past values never change, and the test suite checks this (`test_published_values_never_revise`). This is the rolling-window time-dummy method in the IMF/Eurostat *Residential Property Price Indices Handbook*.
- **Error bars.** Each quarter-on-quarter change ships with a 95% confidence interval from a robust (sandwich) covariance. The median interval width is about ±7.5%.
- **Single-sale influence.** Each quarter reports the largest change any one sale could make to that quarter's movement (closed-form leave-one-out). It has never exceeded **0.9%**, and a wash sale at 20× market moves the index less than 1% (`test_single_extreme_sale_cannot_move_index`).
- **Publication threshold.** A quarter needs at least 40 sales citywide; it has never fallen below 51.

## 4. Settlement value

The raw quarterly estimate is noisy, and its noise reverses: quarter-on-quarter autocorrelation is −0.44, and only 33% of quarters move the same way as the previous one. A contrarian strategy on the raw series would have earned about 1.65% a quarter from the other side of any contract settled on it.

The **settlement value** is therefore a real-time local-level Kalman filter of the log index:
- Signal sd is 4.8% and noise sd 2.8% per quarter, estimated by maximum likelihood on 2016–2026 and then fixed. They are re-estimated at most yearly, with notice.
- The filter uses only data up to each quarter, so it is also never revised.
- On the history it removes the exploitable pattern: autocorrelation drops to −0.22 and the contrarian edge to 0.05% a quarter.
- Quarterly volatility is 5.1%.

Both the raw index and the settlement value are published; contracts settle on the settlement value.

## 5. Publication: monthly readings, a frozen ledger, provisional values

- **Schedule.** A GitHub Actions job checks the city's data every day and republishes when new records appear. The city refreshes its sales data monthly, around mid-month. Sales reach public data about 4–6 weeks after closing; deeds are recorded a median of 13 days after signing, and 20% take more than 19 days.
- **Completeness rule.** A period becomes official once the data runs 30 days past its end. Later periods with sales are published as provisional readings and replaced when they become official.
- **Frozen ledger.** Official values live in `data/ledger_Q.json` (quarterly) and `data/ledger_M.json` (monthly) and are never changed. The city adds late-recorded deeds to past months, so a new period is chained onto the last published value, using the movement estimated on the latest data, and the settlement filter continues from its stored state. A test checks that revised history cannot change a published value.
- **Monthly readings.** These use the same model with month effects and a 36-month window, base April–June 2019 = 100. A typical month has 44 qualifying sales (13 in the thinnest), so monthly readings use their own filter: signal sd 2.8%, noise sd 6.9% per month, estimated by maximum likelihood and then fixed. After filtering they show no exploitable pattern: autocorrelation 0.02. The quarterly series stays the benchmark.
- **What "live" means.** No public source reports building sales in real time. Between releases the market's live estimate is whatever contracts referencing the index trade at, which is also how Case-Shiller futures work (that index is published with a two-month lag).

## 6. Files

| File | Contents |
|---|---|
| `data/rsi_citywide.csv` / `rsi_citywide_monthly.csv` | Published citywide series: period, status (official / provisional), settlement index, $ per apartment, raw index, sales, change with 95% CI, max single-sale effect, publication date, data-through date |
| `data/ledger_Q.json` / `ledger_M.json` | The frozen record of every official value and its filter state |
| `data/rsi_{manhattan,bronx,brooklyn,queens}.csv` | Borough series (indicative only: 15–90 sales a quarter, about ±10–15% noise) |
| `data/rsi_market_rate_comparison.csv` | Same method on 6+ apartment rental buildings with no stabilized units |
| `data/rsi.json` | Everything above plus metadata |
| `data/sales_clean.csv` / `data/sales_excluded.csv` | Every sale used, and every screened-out sale with its reason |

Rebuild (Python 3.12 with numpy, matplotlib, pymupdf, markdown):
`python src/fetch_sales.py && python src/parse_rgb.py && python src/rsi.py build && python src/publish.py && python src/chart.py && python src/site.py`.
Tests: `python -m pytest tests`. The input PDFs come from the Rent Guidelines Board page and are kept in `raw/` with the sales snapshots.

## 7. Research basis

| Choice | Why | Sources |
|---|---|---|
| Hedonic, not repeat-sales | Apartment buildings rarely sell twice in a decade, so repeat-sales would discard most of the data. Hedonic indexes are revised far less when extended, which matters for derivatives settlement, and they signal turning points sooner. | Clapham, Englund, Quigley & Redfearn (2006), *Real Estate Economics*, doi:10.1111/j.1540-6229.2006.00167.x; Shimizu, Nishimura & Watanabe (2010), doi:10.1515/jbnst-2010-0612; Hill (2013), *Journal of Economic Surveys*, doi:10.1111/j.1467-6419.2012.00731.x |
| Rolling-window time dummies, chained | Standard method for official residential property price indices. Chaining keeps published values fixed, and revision risk is a known obstacle for house-price derivatives. | Eurostat et al. (2013), *Handbook on Residential Property Price Indices*; Deng & Quigley (2008), *JREFE*, doi:10.1007/s11146-008-9113-7 |
| Noise filtering for a thin market | Transaction indexes from scarce data are noisy. Tradable commercial indexes use signal extraction or frequency conversion. | Bokhari & Geltner (2010), *JREFE*, doi:10.1007/s11146-010-9261-4; Fisher, Geltner & Pollakowski (2007), doi:10.1007/s11146-007-9001-6; Bourassa, Cantoni & Hoesli (2017), doi:10.1080/10835547.2017.12090448 |
| Index-settled real-estate contracts | The original case for real-estate futures settled on an index. | Case, Shiller & Weiss (1993), *Journal of Portfolio Management*, doi:10.3905/jpm.1993.409441 |
| Rent regulation moves building values | Ending rent control raised the value of formerly controlled buildings; expanding it led landlords to cut rental supply. | Autor, Palmer & Pathak (2014), *JPE*, doi:10.1086/675536; Diamond, McQuade & Qian (2019), *AER*, doi:10.1257/aer.20181289 |
| Governance | Benchmark administration structure: governance, quality, methodology, accountability. | IOSCO (2013), *Principles for Financial Benchmarks* |

## 8. Governance

Modeled on the IOSCO *Principles for Financial Benchmarks* (2013). This is a research preview: no administrator has been formally designated, and the index has not been independently audited.

- **Methodology and code are public.** Each release records its code version (git commit) and SHA-256 checksums of every input snapshot (`rsi.json` → `release`).
- **Data sufficiency.** A quarter is published only with at least 40 qualifying sales.
- **Changes** are announced at least one quarter ahead. The settlement-filter parameters are re-estimated at most yearly, with notice.
- **Corrections.** Published values are not revised. A data error is corrected with a dated notice, and the original value is kept.
- **Questions and complaints:** GitHub issues on the public repository.

## 9. Limitations

- **Stabilization status is a 2024 snapshot.** Buildings that fully left stabilization before 2024 (mostly before 2019, when deregulation was still allowed) are missing from the earlier years, which slightly flatters the pre-2019 series.
- **Portfolio sales are excluded.** Large distressed portfolio trades are a real part of this market, but their per-building prices are not recorded.
- **Lag and timing.** DOF publishes sales with a lag of weeks, and the sale date is the deed date, not the contract date, so the index is roughly one to three months behind deal-making.
- **Quality controls are limited.** The model sees size, age, elevator, mixed use and location. It does not see the share of apartments stabilized, building condition, or rent rolls. Those are the main drivers within this market, so the remaining noise is large.
- **No independent verification yet.** The method is standard and the code is open. Before contracts settle on it, an independent replication and a published governance rulebook (who runs it, how errors are corrected, notice periods) are needed.

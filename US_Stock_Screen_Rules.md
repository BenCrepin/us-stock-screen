# US Stock Screen: Profit Growth + 200-Day Moving Average Proximity

**Report rules specification. Version 1.9, 30 September 2026.**

## 1. Purpose

Scan the US-listed equity universe and highlight shares that satisfy **both** of the following:

1. Quarterly profit growth of at least 10% (reported).
2. Share price trading within 2% of its 200-day moving average.
3. Expected profit growth for the next quarter of at least 10% (consensus forecast).

Results are presented grouped by industry, then by ticker.

## 2. Universe

| Rule | Definition |
|---|---|
| U1. Exchanges | NYSE, Nasdaq (all tiers), NYSE American. |
| U2. Security type | Common stock and Class A/B/C common shares only. Exclude ETFs, ETNs, closed-end funds, preferreds, warrants, rights, units, SPACs without an operating business, and trusts. |
| U3. Domicile | US-listed ordinary shares. ADRs are **excluded** by default because foreign quarterly reporting is often semi-annual and breaks Rule P1. Set `include_adrs = true` to override. |
| U4. Minimum price | Last close of at least US$5.00. Removes penny stocks where the 2% band is a single tick. |
| U5. Minimum market cap | At least US$1 billion. |
| U6. Minimum liquidity | 20-day average dollar volume of at least US$1 million. |
| U7. Data completeness | At least 4 consecutive reported quarters of income statement data, at least 200 trading days of price history, and a consensus estimate for the next quarter (Rule F3). Anything less is excluded, not treated as a pass. |

## 3. Criterion 1: Profit growth per quarter (minimum 10%)

| Rule | Definition |
|---|---|
| P1. Profit measure | **Net income attributable to common shareholders** (GAAP, as reported). Diluted EPS is the fallback if net income is unavailable. |
| P2. Comparison period | **Sequential (quarter-over-quarter):** most recent reported quarter (Q0) versus the immediately preceding quarter (Q-1). This is the literal reading of "per quarter". |
| P3. Growth formula | `growth = (NI_Q0 - NI_Q-1) / abs(NI_Q-1)` |
| P4. Threshold | `growth >= 0.10` (10.0% or greater). |
| P5. Positive profit required | `NI_Q0 > 0` **and** `NI_Q-1 > 0`. A company moving from a loss to a profit, or shrinking a loss, does not qualify. Growth off a negative base is mathematically misleading. |
| P6. Recency | Q0 must have a fiscal period end date within the last 135 days. Stale filings are excluded. |
| P7. Restatements | Always use the most recently restated figures for Q-1, not the figure originally reported. |
| P8. Optional variant | `comparison = "yoy"` switches Rule P2 to Q0 versus the same fiscal quarter one year earlier (Q-4). This removes seasonality. Report which mode was used in the header. |
| P9. Optional consistency filter | `min_consecutive_quarters = N` requires the 10% test to pass for each of the last N sequential quarter pairs. Default is 1 (only the latest pair). |

## 4. Criterion 2: Within 2% of the 200-day moving average

| Rule | Definition |
|---|---|
| M1. Moving average type | **Simple moving average (SMA)** of daily closing prices. |
| M2. Window | 200 **trading days** (not calendar days), ending on the most recent completed session. |
| M3. Price adjustments | Use closes adjusted for splits **only**. Do not adjust for dividends. |
| M4. Reference price | Last official closing price of the most recent completed session. Intraday prices are not used. |
| M5. Distance formula | `distance = (close / SMA200) - 1` |
| M6. Threshold | `abs(distance) <= 0.02` (within ±2.0%, inclusive). |
| M7. Side flag | Record whether the price is **above** (distance > 0) or **below** (distance < 0) the average. Both sides qualify. Exactly at the average is flagged "at". |
| M8. Slope flag (informational) | `SMA200 today vs SMA200 20 trading days ago`: label "rising", "falling", or "flat" (within ±0.5%). Not a filter, shown for context. |
| Y1. Year-to-date high (informational) | Highest **intraday high** from the first trading session of the current calendar year to the latest completed session, split-adjusted. The date it was set is recorded. Falls back to the highest close if intraday highs are unavailable. |
| Y2. Distance from YTD high | `off_high = (close / ytd_high) - 1`, always zero or negative. Not a filter. Shown on qualifying rows and on the monitoring list. |

## 5. Criterion 3: Expected next-quarter profit growth (minimum 10%)

| Rule | Definition |
|---|---|
| F1. Profit measure | **Consensus mean diluted EPS estimate** for the next unreported fiscal quarter (Q+1). EPS is used because sell-side consensus is published on EPS, not net income. |
| F2. Base period | **Sequential:** Q+1 consensus versus **actual reported diluted EPS** for the latest quarter (Q0). Consistent with Rule P2. |
| F3. Coverage | At least 3 analysts contributing to the Q+1 consensus. Fewer, or no coverage, excludes the share (see U7). |
| F4. Growth formula | `expected_growth = (EPS_est_Q+1 - EPS_actual_Q0) / abs(EPS_actual_Q0)` |
| F5. Threshold | `expected_growth >= 0.10` (10.0% or greater). |
| F6. Positive earnings required | `EPS_est_Q+1 > 0` **and** `EPS_actual_Q0 > 0`, mirroring Rule P5. |
| F7. Estimate freshness | The consensus must have been updated within the last 60 days. Report the revision trend over the last 30 days (up / down / unchanged) as context. |
| F8. Basis consistency | Where the actual Q0 EPS is GAAP but consensus is on an adjusted (non-GAAP) basis, use the provider's **adjusted actual** for Q0 so both sides are like-for-like. State the basis in the row. |
| F9. Optional variant | When `comparison = "yoy"`, Rule F2 becomes Q+1 consensus versus actual EPS for the same fiscal quarter one year earlier (Q-3). |

## 6. Combination

A share appears in the report only if it passes **all** of: U1 to U7, P1 to P7, M1 to M6, F1 to F8.

Criteria are evaluated on the same as-of date. The as-of date is the most recent completed trading session on the run date.

## 7. Industry classification

| Rule | Definition |
|---|---|
| I1. Scheme | GICS. Group by **Sector** (11), then **Industry** (74). |
| I2. Fallback | If GICS is unavailable from the data provider, use the provider's sector/industry taxonomy and state so in the header. |
| I3. Unclassified | Shares with no industry are placed in a final "Unclassified" group, never dropped. |

## 8. Output format

### 8.1 Header block

- Report title and as-of date.
- Comparison mode used (QoQ or YoY).
- Universe size after U1 to U7, and counts passing Criterion 1, Criterion 2, Criterion 3, and all three.
- Data source and timestamp of price and fundamentals data.

### 8.2 Body: grouped by Sector, then Industry, then Ticker (A to Z)

Each industry group header shows: industry name, count of qualifying shares.

Each row shows:

| Column | Source rule | Format |
|---|---|---|
| Ticker | | Text |
| Company | | Text |
| Last close | M4 | US$ 2dp |
| SMA200 | M1 to M3 | US$ 2dp |
| Distance to SMA200 | M5 | % 2dp, signed |
| Side | M7 | Above / Below / At |
| SMA slope | M8 | Rising / Falling / Flat |
| YTD high, date set, distance from high | Y1, Y2 | US$ 2dp, YYYY-MM-DD, % 1dp signed |
| Net income Q0 | P1 | US$ millions, 1dp |
| Net income Q-1 (or Q-4) | P1, P2 | US$ millions, 1dp |
| Profit growth | P3 | % 1dp |
| Q0 period end | P6 | YYYY-MM-DD |
| EPS actual Q0 | F2, F8 | US$ 2dp |
| EPS est. Q+1 | F1 | US$ 2dp |
| Expected growth | F4 | % 1dp |
| Analysts | F3 | Integer |
| Revision trend | F7 | Up / Down / Unchanged |
| Below 20d / 50d / 100d / 200d, days below each | D1 to D4 | Yes / No, integer (also carried on qualifying rows) |
| Market cap | U5 | US$ billions, 1dp |

### 8.3 Summary tables

- Count of qualifying shares per sector (bar or table).
- Top 10 by reported profit growth across all industries.
- Top 10 by expected next-quarter growth.
- Top 10 tightest to the SMA200 (smallest absolute distance).

### 8.4 Sort order

1. Sector (GICS order).
2. Industry (alphabetical).
3. Ticker (alphabetical).

An alternative sort by profit growth descending within each industry is permitted if `sort = "growth"`.

## 9. Data quality and exclusion log

- **Monitoring list.** Every share in the universe that fails any rule is listed in an appendix with its ticker and the first rule it failed. This is the watch list for names that may qualify later.
- Each monitoring-list row also carries the YTD high, the date it was set, and the distance from it (Y1, Y2) and short-term trend columns:

| Rule | Definition |
|---|---|
| D1. Averages | Simple moving averages of daily closes over **20, 50, 100 and 200 trading days**, same price basis as M3. |
| D2. Below flag | `close < SMA_n` for each of the four averages, evaluated on the latest completed session. Shown as Yes / No. |
| D3. Consecutive days | For each average, the number of consecutive trading sessions, counting back from and including the latest close, on which the close was below that average. Shown as 0 when the Below flag is No. |
| D4. Insufficient data | If fewer than n + 1 closes exist for a given average, its two columns show n/a. The 200-day columns therefore show n/a for recent listings. |

- A header line above the list gives the total excluded and the counts below each of the four averages.
- Any share where the two data sources disagree on fiscal period end by more than 10 days is flagged.
- If the price data for the as-of date is missing for more than 2% of the universe, the report is marked **PROVISIONAL**.

## 10. Schedule and refresh

- **Daily run at 10:00 UK time** (Europe/London, so 10:00 GMT in winter and 10:00 BST in summer), every day including weekends and US holidays. This is 05:00 New York time, four and a half hours before the US open, after the previous session's close is final.
- Each run refreshes the universe (Rule U1 to U3) from the index constituent lists, recomputes all criteria and writes a new dated archive entry (Section 13). If the constituent refresh fails, the previous ticker list is reused and the report header says so.
- On days with no new US session (weekends, holidays) the run still executes and archives under the date of the last completed close, replacing that day's entry rather than adding a duplicate.
- Price criteria (M, D) change daily. Profit criteria (P) change when filings land. Forecast criteria (F) revise continuously. All three are recomputed on every run.

## 11. Parameters (defaults)

```
min_profit_growth        = 0.10      # Rule P4
comparison               = "qoq"     # Rule P2 / P8: "qoq" or "yoy"
min_consecutive_quarters = 1         # Rule P9
min_expected_growth      = 0.10      # Rule F5
min_analysts             = 3         # Rule F3
max_estimate_age_days    = 60        # Rule F7
sma_window_days          = 200       # Rule M2
sma_band                 = 0.02      # Rule M6
min_price                = 5.00      # Rule U4
min_market_cap           = 1e9       # Rule U5
min_avg_dollar_volume    = 1e6       # Rule U6
include_adrs             = false     # Rule U3
classification           = "GICS"    # Rule I1
sort                     = "ticker"  # Rule 8.4
```

## 12. Known limitations

- Sequential QoQ growth is sensitive to seasonality. Retailers and many consumer names will fail in Q1 and pass in Q4 for calendar reasons. Use `comparison = "yoy"` if this matters.
- Net income includes one-off items (tax benefits, asset sales). An optional refinement is to use income from continuing operations or adjusted net income where available.
- Consensus estimates are opinions, not data. Coverage thins out below roughly US$2 billion market cap, so Rule F3 will remove some small caps that pass every other test.
- The 2% band is arbitrary. A volatility-scaled band (for example 0.25 × 20-day ATR) is a possible future variant.
- This is a screen, not a recommendation. Passing all rules describes a price and earnings pattern, nothing more.

## 13. Archive format

Each run writes to an archive folder with this layout:

```
archive/
  INDEX.md                 one row per run: as-of date, run time, universe size, qualifying count, tickers
  latest/                  copy of the most recent run, always the same file names
    report.md
    qualifying.csv
    monitoring.csv
  YYYY-MM-DD/              one folder per as-of close date
    report.md              the full report in Section 8 format
    report.html            the same run as a web page (Section 14), opens in any browser
    companies.md           one section per qualifying company: description, HQ, screen figures,
                           Financial Times tearsheet link (built by companies_report.py)
    artifact.html          the web page as a fragment for publishing on claude.ai
    qualifying.csv         one row per share passing all criteria, all Section 8.2 columns
    monitoring.csv         one row per excluded share: ticker, exclusion reason, Y1 to Y2 and D1 to D4 columns
```

- The folder name is the **as-of close date** (latest US session in the data), not the run date. A rerun for the same close overwrites that folder and its INDEX.md row.
- CSVs use raw values (fractions, not percentages) so day-to-day comparisons can be computed directly. The markdown report is the formatted view.
- Nothing is ever deleted by the job. Retention is manual.

## 14. Web page and watchlists

Every run also renders the report as a single self-contained web page.

| Rule | Definition |
|---|---|
| W1. Content | Header with as-of close, run date and the four criteria. Summary tiles. The viewer's watchlist. Qualifying shares grouped by sector and industry. The full monitoring list with ticker, reason and watched-only filters. All tables sort on click. |
| W2. New and dropped | Qualifying shares that were not in the previous archived close carry a **new** badge. The header lists how many joined and which tickers dropped out since that close. The first archived run has no comparison. |
| W3. Watchlist | Any row can be starred. Starred tickers appear in a "My watchlist" table at the top showing that ticker's status on the latest run (qualifying, or the reason it is excluded), distance from the 200-day SMA, YTD high and date, sessions below each average, and the date it was added. |
| W4. Persistence | The watchlist is saved in the viewer's browser and mirrored into the page address as `#w=TICKER,TICKER`. Bookmarking the page, or copying the link with the "Copy my watchlist link" button, keeps the list and opens it on any device or shares it with someone else. Opening a link with a watchlist merges it into the viewer's own. On a claude.ai copy with the database capability, signed-in editors additionally get a server-side copy. |
| W5. Access needed | None. The GitHub Pages copy works for anyone with the link and needs no account. |
| W6. Refresh | The published page shows the run it was last published with. Watchlists are kept across republishes because they live in the database, not in the page. |

Sharing options:
- **GitHub Pages from a personal account** (Section 15): the daily job pushes the page and it is served at a public link. Independent of any Claude or work account. Watchlists are browser-local.
- **OneDrive**: share `archive/latest/report.html`. Anyone with the link can open the page; watchlists are browser-local there.
- **Published page on claude.ai**: private by default, with cross-device watchlists, but tied to whichever Claude account publishes it. Publish from a personal account if the report must stay outside work.
- **CSV files**: for anyone who wants to do their own analysis.

## 15. Daily publication to GitHub Pages

- After each successful run, `run_daily.py` copies the latest page to `docs/index.html` (with the CSVs and markdown) and, if the folder is a git repository with an `origin` remote, commits and pushes. GitHub Pages serves `docs/` on the `main` branch.
- The repository must belong to a **personal** GitHub account so the report stays separate from work systems. Setup steps are in `SETUP_SITE.md`.
- Pages on a free personal account requires a public repository. The report is then readable by anyone who has the link; it contains only public market data and the rules.
- Until the remote exists the job still writes `docs/` locally and logs that publishing was skipped, so nothing else changes.
- The full archive is committed alongside `docs/`, so every past close is browsable in the repository.

## 16. Companies report

- For each qualifying share, `companies_report.py` writes a section with the company's own business summary (as carried by Yahoo Finance, shortened to four sentences), headquarters, employee count, market cap, the screen figures behind its inclusion, and a link to its **Financial Times tearsheet** at markets.ft.com (ticker plus FT market code: NYQ for NYSE, NSQ for Nasdaq; a search link is used if the exchange is unknown).
- Sections are grouped by sector with a contents list at the top. The report states plainly that it is a screen and not investment advice.
- It is written to `archive/<date>/companies.md`, copied to `archive/latest/` and to `docs/companies.md` on the site. Produced after each daily run by the desktop scheduled task described in Section 10, or by hand.

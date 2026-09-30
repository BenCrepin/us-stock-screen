"""
US stock screen: reported profit growth >= 10% per quarter AND price within 2% of SMA200
AND consensus expected next-quarter EPS growth >= 10%.
Implements the rules in US_Stock_Screen_Rules.md. Rule numbers are cited in comments.

Usage:
    pip install yfinance pandas tabulate
    python screen.py --tickers tickers.txt            # one ticker per line
    python screen.py --tickers tickers.txt --comparison yoy --out report.md

Data source: Yahoo Finance via yfinance (free, rate-limited, best-effort quality).
Swap fetch_fundamentals / fetch_prices for a paid provider in production.
"""
import argparse
import sys
from datetime import date

import pandas as pd
import yfinance as yf

# ---- Section 11: parameters -------------------------------------------------
PARAMS = dict(
    min_profit_growth=0.10,        # P4
    comparison="qoq",              # P2 / P8
    min_consecutive_quarters=1,    # P9
    sma_window_days=200,           # M2
    sma_band=0.02,                 # M6
    min_price=5.00,                # U4
    min_market_cap=1e9,            # U5
    min_avg_dollar_volume=1e6,     # U6
    max_filing_age_days=135,       # P6
    min_expected_growth=0.10,      # F5
    min_analysts=3,                # F3
    sort="ticker",                 # 8.4
)


def fetch_prices(ticker):
    # M3: split-adjusted only. auto_adjust=False keeps Close unadjusted for dividends.
    return yf.Ticker(ticker).history(period="15mo", auto_adjust=False)


def fetch_fundamentals(ticker):
    t = yf.Ticker(ticker)
    q = t.quarterly_income_stmt  # columns are period-end dates, newest first
    info = t.info or {}
    try:
        est = t.earnings_estimate   # rows: 0q (next unreported qtr), +1q, 0y, +1y
    except Exception:  # noqa: BLE001
        est = None
    try:
        rev = t.eps_revisions       # upLast30days / downLast30days per period
    except Exception:  # noqa: BLE001
        rev = None
    return q, info, est, rev


def net_income_series(q):
    # P1: net income to common, fallback to Net Income, then diluted EPS
    for row in ("Net Income Common Stockholders", "Net Income", "Diluted EPS"):
        if row in q.index:
            s = q.loc[row].dropna().astype(float)
            s.index = pd.to_datetime(s.index)
            return s.sort_index(ascending=False), row
    return None, None


def profit_test(q, p):
    ni, measure = net_income_series(q)
    if ni is None or len(ni) < 4:                                  # U7
        return None, "insufficient quarters"
    lag = 1 if p["comparison"] == "qoq" else 4                     # P2 / P8
    if len(ni) < lag + p["min_consecutive_quarters"]:              # P9
        return None, "insufficient quarters for comparison"
    q0_end = ni.index[0].date()
    if (date.today() - q0_end).days > p["max_filing_age_days"]:   # P6
        return None, f"stale filing ({q0_end})"
    growths = []
    for i in range(p["min_consecutive_quarters"]):
        cur, prev = ni.iloc[i], ni.iloc[i + lag]
        if not (cur > 0 and prev > 0):                             # P5
            return None, "non-positive profit"
        growth = (cur - prev) / abs(prev)                          # P3
        if growth < p["min_profit_growth"]:                        # P4
            return None, f"growth {growth:.1%} below threshold"
        growths.append(growth)
    return dict(ni_q0=ni.iloc[0], ni_prev=ni.iloc[lag], growth=growths[0],
                q0_end=q0_end, measure=measure), None


def forecast_test(q, est, rev, p):
    # F1: consensus mean diluted EPS for the next unreported quarter ("0q" in yfinance)
    if est is None or est.empty or "0q" not in est.index:
        return None, "no consensus estimate"                       # F3 / U7
    row = est.loc["0q"]
    n_analysts = int(row.get("numberOfAnalysts") or 0)
    if n_analysts < p["min_analysts"]:                             # F3
        return None, f"only {n_analysts} analysts"
    eps_est = float(row.get("avg"))
    if p["comparison"] == "qoq":                                   # F2
        if "Diluted EPS" not in q.index:
            return None, "no reported EPS"
        eps_actual = float(q.loc["Diluted EPS"].dropna().iloc[0])
    else:                                                          # F9
        eps_actual = float(row.get("yearAgoEps"))
    if not (eps_est > 0 and eps_actual > 0):                       # F6
        return None, "non-positive EPS"
    exp_growth = (eps_est - eps_actual) / abs(eps_actual)          # F4
    if exp_growth < p["min_expected_growth"]:                      # F5
        return None, f"expected growth {exp_growth:.1%} below threshold"
    trend = "Unchanged"                                            # F7 (revision trend)
    if rev is not None and not rev.empty and "0q" in rev.index:
        up = float(rev.loc["0q"].get("upLast30days") or 0)
        dn = float(rev.loc["0q"].get("downLast30days") or 0)
        trend = "Up" if up > dn else "Down" if dn > up else "Unchanged"
    return dict(eps_actual_q0=eps_actual, eps_est_q1=eps_est, expected_growth=exp_growth,
                analysts=n_analysts, revision_trend=trend, eps_basis="GAAP actual vs consensus"), None


TREND_WINDOWS = (20, 50, 100, 200)   # Rule D1


def trend_flags(hist, windows=TREND_WINDOWS):
    """Section 9 monitoring columns: is the close below each SMA, and for how many
    consecutive trading days (counting back from the latest session)."""
    out = {"last_session": None, "ytd_high": None, "ytd_high_date": None, "off_ytd_high": None}
    closes = hist["Close"].dropna() if hist is not None and not hist.empty else pd.Series(dtype=float)
    if len(closes):
        last = closes.index[-1]
        out["last_session"] = last.date()
        ytd = hist.loc[hist.index >= pd.Timestamp(year=last.year, month=1, day=1, tz=hist.index.tz)]
        highs = ytd["High"].dropna() if "High" in ytd else ytd["Close"].dropna()   # Rule Y1
        if len(highs):
            out["ytd_high"] = float(highs.max())
            out["ytd_high_date"] = highs.idxmax().date()
            out["off_ytd_high"] = float(closes.iloc[-1]) / out["ytd_high"] - 1      # Rule Y2
    for w in windows:
        if len(closes) < w + 1:
            out[f"below{w}"], out[f"days{w}"] = None, None
            continue
        sma = closes.rolling(w).mean()
        below = (closes < sma).dropna()
        days = 0
        for flag in reversed(below.tolist()):
            if not flag:
                break
            days += 1
        out[f"below{w}"], out[f"days{w}"] = days > 0, days
    return out


def ma_test(hist, p):
    closes = hist["Close"].dropna()
    n = p["sma_window_days"]
    if len(closes) < n + 20:                                       # U7 (+20 for slope)
        return None, "insufficient price history"
    sma = closes.rolling(n).mean()                                 # M1, M2
    close = float(closes.iloc[-1])                                 # M4
    sma_now = float(sma.iloc[-1])
    distance = close / sma_now - 1                                 # M5
    if abs(distance) > p["sma_band"]:                              # M6
        return None, f"distance {distance:+.2%} outside band"
    side = "Above" if distance > 0 else "Below" if distance < 0 else "At"   # M7
    slope_chg = sma_now / float(sma.iloc[-21]) - 1                 # M8
    slope = "Rising" if slope_chg > 0.005 else "Falling" if slope_chg < -0.005 else "Flat"
    adv = float((hist["Close"] * hist["Volume"]).tail(20).mean())  # U6
    return dict(close=close, sma200=sma_now, distance=distance, side=side,
                slope=slope, avg_dollar_volume=adv), None


def screen_one(tk, p):
    """Apply every rule to one ticker. Returns (record, None) or (None, exclusion reason)."""
    hist = fetch_prices(tk)
    tf = trend_flags(hist)                                       # Section 9 monitoring columns

    def excl(reason):
        return None, dict(ticker=tk, reason=reason, **tf)

    m, why = ma_test(hist, p)
    if m is None:
        return excl(why)
    if m["close"] < p["min_price"]:                              # U4
        return excl("price below minimum")
    if m["avg_dollar_volume"] < p["min_avg_dollar_volume"]:      # U6
        return excl("illiquid")

    q, info, est, rev = fetch_fundamentals(tk)
    if info.get("quoteType") != "EQUITY":                        # U2
        return excl(f"not common equity ({info.get('quoteType')})")
    mcap = info.get("marketCap") or 0
    if mcap < p["min_market_cap"]:                               # U5
        return excl("market cap below minimum")

    f, why = profit_test(q, p)
    if f is None:
        return excl(why)
    fc, why = forecast_test(q, est, rev, p)
    if fc is None:
        return excl(why)

    return dict(ticker=tk, company=info.get("shortName", ""),
                sector=info.get("sector") or "Unclassified",       # I2 / I3
                industry=info.get("industry") or "Unclassified",
                market_cap=mcap, **m, **f, **fc, **tf), None


def screen(tickers, p, workers=8, log=None):
    from concurrent.futures import ThreadPoolExecutor, as_completed
    tickers = [t.strip().upper() for t in tickers if t.strip()]
    passed, excluded = [], []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(screen_one, tk, p): tk for tk in tickers}
        for i, fut in enumerate(as_completed(futs), 1):
            tk = futs[fut]
            try:
                rec, why = fut.result()
            except Exception as e:  # noqa: BLE001
                rec, why = None, dict(ticker=tk, reason=f"error: {e}", **trend_flags(None))
            if rec:
                passed.append(rec)
            else:
                excluded.append(why)
            if log and (i % 50 == 0 or rec):
                log(f"[{i}/{len(tickers)}] {tk}: {'PASS' if rec else why['reason']}")
    return pd.DataFrame(passed), sorted(excluded, key=lambda d: d["ticker"])


def as_of_date(df, excluded):
    """Latest US session present in the data (Section 13: archive folders are keyed on this)."""
    dates = [e.get("last_session") for e in excluded if e.get("last_session")]
    if not df.empty and "last_session" in df:
        dates += [d for d in df["last_session"].tolist() if d]
    return max(dates) if dates else date.today()


def render(df, excluded, p, universe_n):
    lines = ["# US Stock Screen: Profit Growth + SMA200 Proximity",
             f"As of close: {as_of_date(df, excluded)}  |  Run: {date.today()}  |  "
             f"Comparison: {p['comparison'].upper()}  |  "
             f"Universe: {universe_n}  |  Passing all three criteria: {len(df)}", ""]
    if df.empty:
        lines.append("_No shares passed all rules._")
    else:
        df = df.sort_values(["sector", "industry", "ticker"])          # 8.4
        for (sector, industry), g in df.groupby(["sector", "industry"], sort=False):
            lines += [f"## {sector} / {industry}  ({len(g)})", "",
                      "| Ticker | Company | Close | SMA200 | Dist | Side | Slope | "
                      "YTD high | High date | Off high | "
                      "NI Q0 ($m) | NI prev ($m) | Growth | Q0 end | EPS Q0 | EPS est Q+1 | "
                      "Exp growth | Analysts | Revisions | Mkt cap ($bn) |",
                      "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
            if p["sort"] == "growth":
                g = g.sort_values("growth", ascending=False)
            for r in g.itertuples():
                lines.append(
                    f"| {r.ticker} | {r.company} | {r.close:.2f} | {r.sma200:.2f} | "
                    f"{r.distance:+.2%} | {r.side} | {r.slope} | "
                    f"{r.ytd_high:.2f} | {r.ytd_high_date} | {r.off_ytd_high:+.1%} | "
                    f"{r.ni_q0 / 1e6:,.1f} | "
                    f"{r.ni_prev / 1e6:,.1f} | {r.growth:.1%} | {r.q0_end} | "
                    f"{r.eps_actual_q0:.2f} | {r.eps_est_q1:.2f} | {r.expected_growth:.1%} | "
                    f"{r.analysts} | {r.revision_trend} | {r.market_cap / 1e9:,.1f} |")
            lines.append("")
        pct = lambda x: f"{x:+.1%}" if x < 0 else f"{x:.1%}"  # noqa: E731
        top_g = df.nlargest(10, "growth")[["ticker", "industry", "growth"]].assign(growth=lambda d: d.growth.map(pct))
        top_e = (df.nlargest(10, "expected_growth")[["ticker", "industry", "expected_growth"]]
                 .assign(expected_growth=lambda d: d.expected_growth.map(pct)))
        top_d = (df.assign(absd=df.distance.abs()).nsmallest(10, "absd")[["ticker", "industry", "distance"]]
                 .assign(distance=lambda d: d.distance.map(lambda x: f"{x:+.2%}")))
        lines += ["## Top 10 by reported profit growth", "", top_g.to_markdown(index=False), "",
                  "## Top 10 by expected next-quarter growth", "", top_e.to_markdown(index=False), "",
                  "## Top 10 tightest to SMA200", "", top_d.to_markdown(index=False), ""]
    def yn(flag, days):
        if flag is None:
            return "n/a", "n/a"
        return ("Yes" if flag else "No"), (str(days) if flag else "0")

    counts = " ".join(f"Below {w}d SMA: {sum(1 for e in excluded if e[f'below{w}'])}."
                      for w in TREND_WINDOWS)
    hdr = " | ".join(f"Below {w}d | Days {w}d" for w in TREND_WINDOWS)
    lines += ["## Monitoring list: excluded shares (Section 9)", "",
              f"{len(excluded)} shares excluded. {counts} "
              f"Days counts consecutive trading sessions below the average, "
              f"up to and including the latest close.", "",
              f"| Ticker | Exclusion reason | YTD high | High date | Off high | {hdr} |",
              "|---|---|---|---|---|" + "---|---|" * len(TREND_WINDOWS)]
    for e in excluded:
        cells = []
        for w in TREND_WINDOWS:
            cells += yn(e[f"below{w}"], e[f"days{w}"])
        hi = f"{e['ytd_high']:.2f}" if e.get("ytd_high") else "n/a"
        hd = str(e["ytd_high_date"]) if e.get("ytd_high_date") else "n/a"
        off = f"{e['off_ytd_high']:+.1%}" if e.get("off_ytd_high") is not None else "n/a"
        lines.append(f"| {e['ticker']} | {e['reason']} | {hi} | {hd} | {off} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def p_comparison():
    return PARAMS["comparison"]


def write_archive(archive_dir, df, excluded, text):
    """Section 13 archive format: dated folder + CSVs, a rolling latest/ copy and INDEX.md."""
    import os
    import shutil
    asof = as_of_date(df, excluded).isoformat()
    day_dir = os.path.join(archive_dir, asof)
    os.makedirs(day_dir, exist_ok=True)
    with open(os.path.join(day_dir, "report.md"), "w", encoding="utf-8") as fh:
        fh.write(text)
    (df if not df.empty else pd.DataFrame(columns=["ticker"])).to_csv(
        os.path.join(day_dir, "qualifying.csv"), index=False)
    pd.DataFrame(excluded).to_csv(os.path.join(day_dir, "monitoring.csv"), index=False)
    files = ["report.md", "qualifying.csv", "monitoring.csv"]
    try:                                                          # Section 14: web page
        import render_html
        meta = dict(asof=asof, run=date.today().isoformat(), comparison=p_comparison())
        render_html.write_pages(day_dir, df, pd.DataFrame(excluded), meta, archive_dir=archive_dir)
        files += ["report.html", "artifact.html"]
    except Exception as e:  # noqa: BLE001
        print(f"WARNING html render failed: {e}", flush=True)
    latest = os.path.join(archive_dir, "latest")
    os.makedirs(latest, exist_ok=True)
    for f in files:
        shutil.copyfile(os.path.join(day_dir, f), os.path.join(latest, f))

    idx = os.path.join(archive_dir, "INDEX.md")
    header = "# Screen archive index\n\n| As of close | Run at | Universe | Qualifying | Tickers |\n|---|---|---|---|---|\n"
    tickers = ", ".join(sorted(df["ticker"])) if not df.empty else ""
    row = (f"| [{asof}]({asof}/report.md) | {pd.Timestamp.now():%Y-%m-%d %H:%M} | "
           f"{len(df) + len(excluded)} | {len(df)} | {tickers} |\n")
    if os.path.exists(idx):
        with open(idx, encoding="utf-8") as fh:
            kept = [l for l in fh.read().splitlines() if not l.startswith(f"| [{asof}]")]
        body = "\n".join(kept).rstrip("\n") + "\n"
    else:
        body = header
    with open(idx, "w", encoding="utf-8") as fh:
        fh.write(body + row)
    return day_dir


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--tickers", required=True, help="file with one ticker per line")
    ap.add_argument("--comparison", choices=["qoq", "yoy"], default=PARAMS["comparison"])
    ap.add_argument("--sort", choices=["ticker", "growth"], default=PARAMS["sort"])
    ap.add_argument("--out", default=None)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--archive", default=None,
                    help="archive folder: writes <as-of-date>/, latest/ and INDEX.md (Section 13)")
    a = ap.parse_args()
    PARAMS.update(comparison=a.comparison, sort=a.sort)
    with open(a.tickers) as fh:
        tickers = fh.read().split()
    df, excluded = screen(tickers, PARAMS, workers=a.workers,
                          log=lambda m: print(m, flush=True))
    text = render(df, excluded, PARAMS, len(tickers))
    if a.archive:
        print(f"archived to {write_archive(a.archive, df, excluded, text)}")
    if a.out:
        with open(a.out, "w", encoding="utf-8") as fh:
            fh.write(text)
        print(f"wrote {a.out}")
    if not a.out and not a.archive:
        sys.stdout.write(text)

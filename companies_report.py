"""
Companies report: one section per share that passed the screen, with a business description,
key screen figures and a link to its Financial Times tearsheet.

    python companies_report.py archive/2026-09-29          # writes companies.md into that folder
"""
import argparse
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
import yfinance as yf

# Yahoo exchange code -> Financial Times market code used in tearsheet URLs
FT_EXCHANGE = {"NYQ": "NYQ", "NMS": "NSQ", "NGM": "NSQ", "NCM": "NSQ", "ASE": "ASQ", "PCX": "PSQ", "BTS": "BTQ"}


def ft_link(ticker, exchange):
    code = FT_EXCHANGE.get(exchange)
    t = ticker.replace("-", ".")           # FT uses BRK.B style
    if code:
        return f"https://markets.ft.com/data/equities/tearsheet/summary?s={t}:{code}"
    return f"https://markets.ft.com/data/search?query={t}&country=US"


def profile(ticker):
    try:
        info = yf.Ticker(ticker).info or {}
    except Exception as e:  # noqa: BLE001
        info = {"_error": str(e)}
    return ticker, info


def clean_summary(text, max_sentences=4):
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    if not text or text == "nan":
        return "No business description available from the data source."
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z])", text)
    return " ".join(parts[:max_sentences])


def pct(v, signed=False, dp=1):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return "n/a"
    return f"{v:+.{dp}%}" if signed else f"{v:.{dp}%}"


def build(folder):
    q = pd.read_csv(os.path.join(folder, "qualifying.csv"))
    asof = os.path.basename(os.path.normpath(folder))
    if q.empty:
        return f"# Companies passing the screen, {asof}\n\nNo shares passed all three criteria on this close.\n"
    with ThreadPoolExecutor(max_workers=6) as ex:
        infos = dict(ex.map(profile, q["ticker"].astype(str).tolist()))

    q = q.sort_values(["sector", "industry", "ticker"])
    lines = [f"# Companies passing the screen, close of {asof}", "",
             f"{len(q)} shares in the S&P 500 and S&P 400 passed all three criteria on this close: "
             "net income up at least 10% on the prior quarter, price within 2% of the 200-day moving average, "
             "and consensus expecting next-quarter EPS at least 10% above the last reported quarter. "
             "Descriptions are the companies' own summaries as carried by Yahoo Finance, shortened. "
             "Each ticker links to its Financial Times tearsheet. "
             "This is a screen of a price and earnings pattern, not investment advice.", "",
             "## Contents", ""]
    for (sector, _), g in q.groupby(["sector", "industry"], sort=False):
        pass
    for sector, g in q.groupby("sector", sort=False):
        names = ", ".join(f"[{t}](#{t.lower().replace('-', '')})" for t in g["ticker"])
        lines.append(f"- **{sector}**: {names}")
    lines.append("")

    for sector, gs in q.groupby("sector", sort=False):
        lines += [f"## {sector}", ""]
        for _, r in gs.iterrows():
            t = str(r["ticker"])
            info = infos.get(t, {})
            name = info.get("longName") or r.get("company") or t
            link = ft_link(t, info.get("exchange", ""))
            hq = ", ".join(x for x in (info.get("city"), info.get("state"), info.get("country")) if x)
            emp = info.get("fullTimeEmployees")
            site = info.get("website")
            facts = [f"**Industry:** {r.get('industry', '')}"]
            if hq:
                facts.append(f"**HQ:** {hq}")
            if emp:
                facts.append(f"**Employees:** {int(emp):,}")
            mc = r.get("market_cap")
            if pd.notna(mc):
                facts.append(f"**Market cap:** ${float(mc) / 1e9:,.1f}bn")
            lines += [f"### {name} ({t})", "",
                      f"[Financial Times tearsheet]({link})" + (f" · [Company website]({site})" if site else ""), "",
                      clean_summary(info.get("longBusinessSummary")), "",
                      " · ".join(facts), "",
                      "| Screen figure | Value |", "|---|---|",
                      f"| Close vs 200-day SMA | {float(r['close']):,.2f} vs {float(r['sma200']):,.2f} ({pct(r['distance'], True, 2)}, {r.get('slope', '')} average) |",
                      f"| Net income, latest quarter vs prior | ${float(r['ni_q0']) / 1e6:,.1f}m vs ${float(r['ni_prev']) / 1e6:,.1f}m ({pct(r['growth'])}) |",
                      f"| Quarter ended | {str(r.get('q0_end', ''))[:10]} |",
                      f"| Diluted EPS, latest vs consensus next quarter | {float(r['eps_actual_q0']):.2f} vs {float(r['eps_est_q1']):.2f} ({pct(r['expected_growth'])}), {int(r['analysts'])} analysts, revisions {r.get('revision_trend', '')} |",
                      f"| Year-to-date high | {float(r['ytd_high']):,.2f} on {str(r.get('ytd_high_date', ''))[:10]} ({pct(r['off_ytd_high'], True)} from high) |",
                      ""]
    lines += ["---", "", "Source: Yahoo Finance via yfinance for descriptions, prices, financials and consensus. "
              "Links go to markets.ft.com, which is independent of this report. Generated by companies_report.py.", ""]
    return "\n".join(lines)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("folder", help="archive day folder, e.g. archive/2026-09-29")
    ap.add_argument("--out", default=None, help="output path (default <folder>/companies.md)")
    a = ap.parse_args()
    text = build(a.folder)
    out = a.out or os.path.join(a.folder, "companies.md")
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(text)
    print(f"wrote {out} ({len(text) // 1024} KB)")

"""Export analysis data as JSON for the static web viewer."""

import json
import os
import datetime
import numpy as np
import pandas as pd

DOCS_DATA_DIR = os.path.join("docs", "data")


class _Encoder(json.JSONEncoder):
    """Handle numpy/pandas types in JSON serialisation."""
    def default(self, obj):
        if isinstance(obj, (np.integer,)):
            return int(obj)
        if isinstance(obj, (np.floating,)):
            return None if np.isnan(obj) else float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        if isinstance(obj, (pd.Timestamp, datetime.datetime)):
            return obj.isoformat()
        return super().default(obj)


def _compute_pe_percentile(df):
    """What percentile is the current P/E within its own history? Lower = cheaper."""
    if df is None or df.empty:
        return None
    pe = df["P/E"].dropna()
    pe = pe[pe > 0]
    if len(pe) < 20:
        return None
    current = pe.iloc[-1]
    return float((pe < current).sum() / len(pe) * 100)


def export_json(companies_data, groups, config, stock_names=None):
    """Write JSON files consumed by the GitHub Pages viewer.

    Creates:
      docs/data/meta.json       - run metadata
      docs/data/groups.json     - group definitions
      docs/data/summary.json    - latest snapshot per stock
      docs/data/{TICKER}.json   - full time series per stock
    """
    os.makedirs(DOCS_DATA_DIR, exist_ok=True)
    if stock_names is None:
        stock_names = {}

    # --- meta.json --------------------------------------------------------
    meta = {
        "last_updated": datetime.datetime.utcnow().isoformat() + "Z",
        "stock_count": len(companies_data),
    }
    _write(meta, "meta.json")

    # --- groups.json ------------------------------------------------------
    _write(groups or {}, "groups.json")

    # --- Pre-compute P/E percentiles for all stocks ------------------------
    pe_percentiles = {}
    for ticker, df in companies_data.items():
        pct = _compute_pe_percentile(df)
        if pct is not None:
            pe_percentiles[ticker] = pct

    # Compute peer median percentiles per group
    peer_median_pcts = {}
    for g_name, g_tickers in (groups or {}).items():
        pcts = [pe_percentiles[t] for t in g_tickers if t in pe_percentiles]
        if pcts:
            peer_median_pcts[g_name] = float(sorted(pcts)[len(pcts) // 2])

    # --- Per-ticker JSON + summary ----------------------------------------
    summary = []

    for ticker, df in companies_data.items():
        if df is None or df.empty:
            continue

        # Full time series
        records = df.replace({np.nan: None}).to_dict(orient="records")
        _write(records, f"{ticker}.json")

        # Latest snapshot for summary
        last = df.iloc[-1].replace({np.nan: None}).to_dict()
        last["Ticker"] = ticker
        last["Name"] = stock_names.get(ticker, ticker)

        # Buy rule metrics
        last["PE Percentile"] = pe_percentiles.get(ticker)
        own_group = f"{ticker} Analysis"
        last["Peer Median Percentile"] = peer_median_pcts.get(own_group)
        fcf = last.get("Free Cash Flow")
        last["FCF Positive"] = fcf is not None and fcf > 0
        roic = last.get("ROIC")
        last["ROIC Pass"] = roic is not None and roic > 0.10
        pe_pct = pe_percentiles.get(ticker)
        peer_med = peer_median_pcts.get(own_group)
        last["PE vs Peers Pass"] = (pe_pct is not None and peer_med is not None
                                     and (peer_med - pe_pct) >= 15)
        last["All Rules Pass"] = (
            last.get("PE Percentile") is not None and last["PE Percentile"] <= 20
            and last["PE vs Peers Pass"]
            and last["ROIC Pass"]
            and last["FCF Positive"]
        )

        # Find comparison group
        my_groups = []
        if groups:
            for g_name, g_tickers in groups.items():
                if ticker in g_tickers:
                    my_groups.append(g_name)
        last["Groups"] = my_groups
        summary.append(last)

    _write(summary, "summary.json")

    print(f"JSON exported to {os.path.abspath(DOCS_DATA_DIR)}/")


def _write(obj, filename):
    path = os.path.join(DOCS_DATA_DIR, filename)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, cls=_Encoder, separators=(",", ":"))

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

"""Deep diluted-EPS history from stockanalysis.com.

yfinance only returns ~4 years of usable annual EPS, which means the
5Y EPS CAGR column in the weekly email is empty for almost every
ticker. This module fetches 20 quarters (~5 years) of TTM diluted EPS
from stockanalysis.com so that older weekly rows in the metrics
DataFrame have an EPS value to anchor the CAGR computation against.

Returns a pandas Series indexed by quarter-end date (Timestamp,
tz-naive), values = TTM diluted EPS in the company's reporting
currency. None when the ticker isn't supported.
"""

import re
import json
from calendar import monthrange
from datetime import datetime, timedelta
from pathlib import Path

import requests
import pandas as pd
from bs4 import BeautifulSoup

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0 Safari/537.36"}

CACHE_TTL = timedelta(days=7)

# Multi-class tickers: stockanalysis uses dots (brk.b) where SEC/yfinance use dashes (BRK-B).
_TICKER_REWRITE = {
    "BRK-B": "brk.b",
    "BRK-A": "brk.a",
}

# Foreign suffix -> stockanalysis URL exchange prefix. The base symbol is
# the part of the ticker before the dot.
_EXCHANGE_PREFIX = {
    "HK": "hkg",   # Hong Kong
    "SS": "sha",   # Shanghai
    "SZ": "shz",   # Shenzhen
    "T":  "tyo",   # Tokyo
    "L":  "lon",   # London
    "DE": "etr",   # Xetra / Frankfurt
    "PA": "epa",   # Paris (Euronext)
    "AS": "ams",   # Amsterdam (Euronext)
    "ST": "sto",   # Stockholm
    "SW": "vtx",   # Swiss
    "MX": "bmv",   # Mexico
    "SI": "sgx",   # Singapore
    "KS": "krx",   # Korea
}

# Known ADR-to-home-listing routings (stockanalysis often has cleaner data
# for the home listing than for the OTC ADR).
_ADR_HOME = {
    "TCEHY": ("hkg", "0700"),
    "BYDDY": ("hkg", "1211"),
    "FYGGY": ("sha", "600660"),
    "MGCLY": ("she", "000333"),
    "CIHKY": ("sha", "600036"),
    "PSTVY": ("hkg", "1658"),
    "IDCBY": ("hkg", "1398"),
    "CICHY": ("hkg", "0939"),
    "ACGBY": ("hkg", "1288"),
    "BACHY": ("hkg", "3988"),
    "BKMUY": ("hkg", "3328"),
    "GELYY": ("hkg", "0175"),
    "GWLLY": ("hkg", "2333"),
    "XIACF": ("hkg", "1810"),
    "VWAGY": ("etr", "VOW3"),
    "NESN":  ("vtx", "NESN"),
}


def _build_urls(ticker: str, view: str = "trailing"):
    """Return candidate stockanalysis URLs to try in order."""
    t_upper = ticker.upper()
    urls = []

    if t_upper in _ADR_HOME:
        exch, code = _ADR_HOME[t_upper]
        urls.append(f"https://stockanalysis.com/quote/{exch}/{code}/financials/?p={view}")

    if "." not in ticker:
        slug = _TICKER_REWRITE.get(t_upper, ticker.lower())
        urls.append(f"https://stockanalysis.com/stocks/{slug}/financials/?p={view}")
        urls.append(f"https://stockanalysis.com/quote/otc/{t_upper}/financials/?p={view}")
    else:
        base, _, suffix = ticker.rpartition(".")
        exch = _EXCHANGE_PREFIX.get(suffix.upper())
        if exch:
            urls.append(f"https://stockanalysis.com/quote/{exch}/{base}/financials/?p={view}")

    return urls


def _q_to_date(label: str, fiscal_q4_month: int = 12):
    """Convert 'Q3 2021' to the fiscal quarter-end date.

    `fiscal_q4_month` is the calendar month in which the company's fiscal
    Q4 ends (12 for Dec-fiscal-year filers, 9 for Apple, 6 for MSFT, etc).
    """
    m = re.match(r"Q(\d)\s+(\d{4})", label)
    if not m:
        return None
    qn = int(m.group(1))
    fy = int(m.group(2))
    months_from_fy_end = (qn - 4) * 3
    target_month = fiscal_q4_month + months_from_fy_end
    target_year = fy
    while target_month <= 0:
        target_month += 12
        target_year -= 1
    while target_month > 12:
        target_month -= 12
        target_year += 1
    try:
        day = monthrange(target_year, target_month)[1]
        return pd.Timestamp(year=target_year, month=target_month, day=day)
    except Exception:
        return None


def _parse_eps_row(html_bytes: bytes, fiscal_q4_month: int):
    """Extract the EPS (Diluted) row from stockanalysis HTML."""
    soup = BeautifulSoup(html_bytes, "html.parser")
    table = soup.find("table")
    if table is None:
        return None
    rows = table.find_all("tr")
    if not rows:
        return None

    header = [c.get_text(strip=True) for c in rows[0].find_all(["th", "td"])]
    columns = header[1:]
    dates = [_q_to_date(c, fiscal_q4_month) for c in columns]

    eps_labels = {"EPS (Diluted)", "Diluted EPS", "Diluted Earnings Per Share"}
    for row in rows[1:]:
        cells = row.find_all(["th", "td"])
        if len(cells) < 2:
            continue
        label = cells[0].get_text(strip=True)
        if label not in eps_labels:
            continue
        out = {}
        for i, cell in enumerate(cells[1:]):
            if i >= len(dates) or dates[i] is None:
                continue
            txt = cell.get_text(strip=True).replace(",", "").replace("$", "")
            if not txt or txt in ("-", "—", "N/A"):
                continue
            if txt.startswith("(") and txt.endswith(")"):
                txt = "-" + txt[1:-1]
            try:
                out[dates[i]] = float(txt)
            except ValueError:
                continue
        if out:
            s = pd.Series(out).sort_index()
            s.index = pd.DatetimeIndex(s.index)
            return s
    return None


def fetch_ttm_eps(ticker: str, fiscal_q4_month: int = 12, cache_dir: Path | None = None):
    """Fetch ~20 quarters of TTM diluted EPS from stockanalysis.com.

    Returns a pd.Series indexed by quarter-end Timestamps, or None when
    the ticker isn't supported / no data is available.

    A 7-day on-disk cache avoids re-hitting stockanalysis on every weekly
    run.
    """
    cache_file = None
    if cache_dir is not None:
        cache_dir = Path(cache_dir)
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file = cache_dir / "stockanalysis_ttm_eps.csv"
        if cache_file.exists():
            age = datetime.now() - datetime.fromtimestamp(cache_file.stat().st_mtime)
            if age < CACHE_TTL:
                try:
                    df = pd.read_csv(cache_file, index_col=0, parse_dates=True)
                    if not df.empty:
                        return df.iloc[:, 0]
                except Exception:
                    pass

    for url in _build_urls(ticker, view="trailing"):
        try:
            r = requests.get(url, headers=UA, timeout=25)
        except Exception:
            continue
        if r.status_code != 200 or len(r.content) < 30_000:
            continue
        series = _parse_eps_row(r.content, fiscal_q4_month)
        if series is not None and len(series) >= 4:
            if cache_file is not None:
                try:
                    series.to_frame(name="ttm_eps").to_csv(cache_file)
                except Exception:
                    pass
            return series

    # Empty marker so we don't refetch repeatedly for unsupported tickers
    if cache_file is not None:
        try:
            pd.DataFrame({"ttm_eps": []}).to_csv(cache_file)
        except Exception:
            pass
    return None

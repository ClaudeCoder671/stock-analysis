import pandas as pd
import numpy as np


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def get_ttm_from_quarterly(quarterly_series, date):
    """Sum of the last 4 quarters whose report date is <= *date*.
    Returns NaN if fewer than 4 quarters, any quarter is NaN, or the
    oldest of the 4 is more than 2 years before *date* (stale guard).
    """
    if quarterly_series is None:
        return np.nan
    past_q = quarterly_series[quarterly_series.index <= date]
    if len(past_q) >= 4:
        last_4 = past_q.iloc[-4:]
        if last_4.isna().any():
            return np.nan
        if (date - last_4.index[0]).days < 730:
            return last_4.sum()
    return np.nan


def get_latest(series, date):
    """Most recent value (and its date) from *series* on or before *date*."""
    if series is None:
        return np.nan, None
    past = series[series.index <= date]
    if len(past) > 0:
        return past.iloc[-1], past.index[-1]
    return np.nan, None


def _col(df, candidates):
    """Return the first column from *df* whose name is in *candidates*."""
    if df is None:
        return None
    for c in candidates:
        if c in df.columns:
            return df[c]
    return None


def _can_do_quarterly_yoy(q_rev_series, date):
    """True when quarterly TTM revenue exists for both *date* and 1 yr ago."""
    if q_rev_series is None:
        return False
    cur = get_ttm_from_quarterly(q_rev_series, date)
    ago = get_ttm_from_quarterly(q_rev_series, date - pd.DateOffset(years=1))
    return not pd.isna(cur) and not pd.isna(ago)


def _ensure_utc(df):
    if df is not None and not df.empty:
        if df.index.tz is None:
            df.index = pd.to_datetime(df.index).tz_localize('UTC')
        else:
            df.index = df.index.tz_convert('UTC')
    return df


# ---------------------------------------------------------------------------
# Main metric calculation
# ---------------------------------------------------------------------------

def calculate_metrics(data, bond_yield_series=None):
    """
    Calculate valuation metrics for one stock.

    Source selection logic (per the user's rule):
      - Prefer quarterly TTM when we can also compute year-over-year
        (i.e. we have TTM revenue for both *now* and *1 year ago*).
      - Otherwise fall back to annual data.
    This ensures every growth / comparison metric is always
    apples-to-apples against a true year-ago period.
    """

    history = data["history"]
    q_fin = data.get("quarterly_financials")
    q_bs  = data.get("quarterly_balance_sheet")
    a_fin = data.get("annual_financials")
    a_bs  = data.get("annual_balance_sheet")
    q_cf  = data.get("quarterly_cashflow")
    a_cf  = data.get("annual_cashflow")
    ext_ttm_eps = data.get("extended_ttm_eps")  # deep TTM EPS from stockanalysis

    if history is None:
        return None

    # --- Timezone normalisation -------------------------------------------
    history.index = pd.to_datetime(history.index, utc=True)
    for df in [q_fin, q_bs, a_fin, a_bs, q_cf, a_cf]:
        _ensure_utc(df)

    # Normalise the extended TTM EPS series index to UTC
    if ext_ttm_eps is not None and not ext_ttm_eps.empty:
        ext_ttm_eps = ext_ttm_eps.copy()
        ext_ttm_eps.index = pd.to_datetime(ext_ttm_eps.index)
        if ext_ttm_eps.index.tz is None:
            ext_ttm_eps.index = ext_ttm_eps.index.tz_localize('UTC')
        else:
            ext_ttm_eps.index = ext_ttm_eps.index.tz_convert('UTC')
        ext_ttm_eps = ext_ttm_eps.sort_index()

    weekly_prices = history['Close'].resample('W-FRI').last()

    # --- Prepare named series ---------------------------------------------
    q_rev    = _col(q_fin, ['Total Revenue', 'Revenue'])
    a_rev    = _col(a_fin, ['Total Revenue', 'Revenue'])
    q_ni     = _col(q_fin, ['Net Income', 'Net Income Common Stockholders'])
    a_ni     = _col(a_fin, ['Net Income', 'Net Income Common Stockholders'])
    q_eps    = _col(q_fin, ['Diluted EPS', 'Basic EPS'])
    a_eps    = _col(a_fin, ['Diluted EPS', 'Basic EPS'])
    q_shares = _col(q_fin, ['Diluted Average Shares', 'Basic Average Shares'])
    a_shares = _col(a_fin, ['Diluted Average Shares', 'Basic Average Shares'])
    if q_shares is None:
        q_shares = _col(q_bs, ['Share Issued', 'Ordinary Shares Number'])
    if a_shares is None:
        a_shares = _col(a_bs, ['Share Issued', 'Ordinary Shares Number'])

    q_oi     = _col(q_fin, ['Operating Income', 'EBIT'])
    a_oi     = _col(a_fin, ['Operating Income', 'EBIT'])
    q_tax    = _col(q_fin, ['Tax Provision'])
    a_tax    = _col(a_fin, ['Tax Provision'])
    q_pretax = _col(q_fin, ['Pretax Income'])
    a_pretax = _col(a_fin, ['Pretax Income'])
    q_ocf    = _col(q_cf,  ['Operating Cash Flow', 'Total Cash From Operating Activities'])
    a_ocf    = _col(a_cf,  ['Operating Cash Flow', 'Total Cash From Operating Activities'])
    q_capex  = _col(q_cf,  ['Capital Expenditure'])
    a_capex  = _col(a_cf,  ['Capital Expenditure'])

    # --- Currency conversion ----------------------------------------------
    currency_meta = data.get("currency_metadata", {})
    price_curr = currency_meta.get("price_currency", "USD")
    fin_curr   = currency_meta.get("financial_currency", "USD")

    fx_series = None
    need_fx   = bool(price_curr and fin_curr and price_curr != fin_curr)
    if need_fx:
        import data_manager
        pair = f"{fin_curr}{price_curr}=X"
        fx_series = data_manager.fetch_exchange_rate(pair)
        if fx_series is not None:
            fx_series = _ensure_utc(fx_series.to_frame())['Close'] \
                if isinstance(fx_series, pd.Series) else fx_series
            if isinstance(fx_series, pd.Series):
                if fx_series.index.tz is None:
                    fx_series.index = fx_series.index.tz_localize('UTC')
                else:
                    fx_series.index = fx_series.index.tz_convert('UTC')

    # --- Bond yield -------------------------------------------------------
    if bond_yield_series is not None:
        if bond_yield_series.index.tz is None:
            bond_yield_series = bond_yield_series.copy()
            bond_yield_series.index = bond_yield_series.index.tz_localize('UTC')
        elif str(bond_yield_series.index.tz) != 'UTC':
            bond_yield_series = bond_yield_series.copy()
            bond_yield_series.index = bond_yield_series.index.tz_convert('UTC')

    # --- Filter prices to earliest financial data -------------------------
    earliest = None
    for df in [a_fin, q_fin]:
        if df is not None and not df.empty:
            d = df.index.min()
            if earliest is None or d < earliest:
                earliest = d
    # The extended TTM EPS series may go further back than yfinance — let
    # weekly rows extend back to that point too so the 5Y CAGR lookup has
    # something to anchor against.
    if ext_ttm_eps is not None and not ext_ttm_eps.empty:
        d = ext_ttm_eps.index.min()
        if earliest is None or d < earliest:
            earliest = d
    if earliest is not None:
        weekly_prices = weekly_prices[weekly_prices.index >= earliest]

    # --- Iterate over weekly prices ---------------------------------------
    rows = []

    for date, price in weekly_prices.items():
        if pd.isna(price):
            continue

        # Exchange rate at this date
        fx = 1.0
        if need_fx and fx_series is not None:
            r, _ = get_latest(fx_series, date)
            if not pd.isna(r) and r > 0:
                fx = r

        def cvt(val):
            """Convert a financial-currency value to price currency."""
            return np.nan if pd.isna(val) else val * fx

        # Bond yield at this date (for Graham formula)
        aaa_yield = 4.4  # default = Graham's original baseline (multiplier = 1)
        if bond_yield_series is not None:
            y, _ = get_latest(bond_yield_series, date)
            if not pd.isna(y) and y > 0:
                aaa_yield = y

        # ==================================================================
        # SOURCE SELECTION
        # ==================================================================
        use_quarterly = _can_do_quarterly_yoy(q_rev, date)

        if use_quarterly:
            # ---------- Quarterly TTM path --------------------------------
            source = "Quarterly TTM"

            raw_rev     = get_ttm_from_quarterly(q_rev, date)
            raw_rev_1y  = get_ttm_from_quarterly(q_rev, date - pd.DateOffset(years=1))
            raw_rev_2y  = get_ttm_from_quarterly(q_rev, date - pd.DateOffset(years=2))

            raw_eps     = get_ttm_from_quarterly(q_eps, date)
            if pd.isna(raw_eps) and a_eps is not None:
                raw_eps, _ = get_latest(a_eps, date)
            # Last-resort: stockanalysis.com deep TTM EPS history
            if pd.isna(raw_eps) and ext_ttm_eps is not None:
                raw_eps, _ = get_latest(ext_ttm_eps, date)

            raw_ni      = get_ttm_from_quarterly(q_ni, date)
            if pd.isna(raw_ni) and a_ni is not None:
                raw_ni, _ = get_latest(a_ni, date)

            raw_oi_val  = get_ttm_from_quarterly(q_oi, date)
            if pd.isna(raw_oi_val) and a_oi is not None:
                raw_oi_val, _ = get_latest(a_oi, date)

            raw_tax_val = get_ttm_from_quarterly(q_tax, date)
            raw_ptx_val = get_ttm_from_quarterly(q_pretax, date)

            raw_ocf_val = get_ttm_from_quarterly(q_ocf, date)
            if pd.isna(raw_ocf_val) and a_ocf is not None:
                raw_ocf_val, _ = get_latest(a_ocf, date)
            raw_capex_val = get_ttm_from_quarterly(q_capex, date)
            if pd.isna(raw_capex_val) and a_capex is not None:
                raw_capex_val, _ = get_latest(a_capex, date)

            shares, _ = get_latest(q_shares, date)
            if pd.isna(shares):
                shares, _ = get_latest(a_shares, date)

            # Balance sheet snapshot (quarterly)
            equity    = _bs_equity(q_bs, date)
            goodwill  = _bs_val(q_bs, ['Goodwill'], date)
            intang    = _bs_val(q_bs, ['Intangible Assets', 'Other Intangible Assets'], date)
            tot_debt  = _bs_debt(q_bs, date)
            cash      = _bs_val(q_bs, ['Cash Cash Equivalents And Short Term Investments',
                                        'Cash And Cash Equivalents'], date)

            latest_q = q_fin.index[q_fin.index <= date].max() if q_fin is not None else date
            period_end   = latest_q
            period_start = period_end - pd.DateOffset(years=1) + pd.DateOffset(days=1)

        else:
            # ---------- Annual path ---------------------------------------
            # Check whether yfinance annual data is available for this date.
            annual_available = (
                a_fin is not None
                and not a_fin.empty
                and (a_fin.index <= date).any()
            )

            if not annual_available:
                # No yfinance annual yet — try the stockanalysis deep TTM
                # EPS series so we can at least populate Price + EPS + P/E
                # for old weekly rows. Without this, 5Y EPS CAGR cannot
                # anchor against the start of the series.
                ext_eps_val, _ = (
                    get_latest(ext_ttm_eps, date) if ext_ttm_eps is not None
                    else (np.nan, None)
                )
                if pd.isna(ext_eps_val):
                    rows.append(_empty_row(date, price, price_curr, fin_curr, fx))
                    continue

                rows.append(_extended_only_row(
                    date, price, ext_eps_val, price_curr, fin_curr, fx))
                continue

            available = a_fin.index[a_fin.index <= date]
            anchor = available.max()
            source = f"Annual ({anchor.strftime('%Y-%m-%d')})"

            raw_rev, _     = get_latest(a_rev, anchor)
            raw_rev_1y, _  = get_latest(a_rev, anchor - pd.DateOffset(years=1))
            raw_rev_2y, _  = get_latest(a_rev, anchor - pd.DateOffset(years=2))
            raw_eps, _     = get_latest(a_eps, anchor)
            # Prefer stockanalysis TTM EPS when it's more recent than the
            # latest annual filing (annual EPS lags ~6-9 months; TTM is
            # rolling 12 months and tracks more closely to "now").
            if ext_ttm_eps is not None:
                ext_v, ext_d = get_latest(ext_ttm_eps, date)
                if not pd.isna(ext_v) and (pd.isna(raw_eps) or
                                            (ext_d is not None and ext_d > anchor)):
                    raw_eps = ext_v
            raw_ni, _      = get_latest(a_ni, anchor)
            raw_oi_val, _  = get_latest(a_oi, anchor)
            raw_tax_val, _ = get_latest(a_tax, anchor)
            raw_ptx_val, _ = get_latest(a_pretax, anchor)
            raw_ocf_val, _ = get_latest(a_ocf, anchor)
            raw_capex_val, _ = get_latest(a_capex, anchor)

            shares, _ = get_latest(a_shares, anchor)
            if pd.isna(shares):
                shares, _ = get_latest(
                    _col(a_bs, ['Share Issued', 'Ordinary Shares Number']), anchor)

            equity   = _bs_equity(a_bs, anchor)
            goodwill = _bs_val(a_bs, ['Goodwill'], anchor)
            intang   = _bs_val(a_bs, ['Intangible Assets', 'Other Intangible Assets'], anchor)
            tot_debt = _bs_debt(a_bs, anchor)
            cash     = _bs_val(a_bs, ['Cash Cash Equivalents And Short Term Investments',
                                       'Cash And Cash Equivalents'], anchor)

            period_end   = anchor
            period_start = period_end - pd.DateOffset(years=1) + pd.DateOffset(days=1)

        # ==================================================================
        # COMPUTE METRICS (common to both paths)
        # ==================================================================

        # --- Convert financials to price currency -------------------------
        eps       = cvt(raw_eps)
        rev       = cvt(raw_rev)
        rev_2y    = cvt(raw_rev_2y)
        ni        = cvt(raw_ni)
        oi        = cvt(raw_oi_val)
        ocf       = cvt(raw_ocf_val)
        capex_c   = cvt(raw_capex_val)
        equity_c  = cvt(equity)
        debt_c    = cvt(tot_debt)
        cash_c    = cvt(cash)
        gw_c      = cvt(goodwill)
        intang_c  = cvt(intang)

        # Tangible Book Value
        tbv = np.nan
        if not pd.isna(equity_c):
            tbv = equity_c - (gw_c if not pd.isna(gw_c) else 0) \
                           - (intang_c if not pd.isna(intang_c) else 0)

        # Per-share
        bvps = tangible_bvps = np.nan
        if not pd.isna(shares) and shares > 0:
            if not pd.isna(equity_c):
                bvps = equity_c / shares
            if not pd.isna(tbv):
                tangible_bvps = tbv / shares

        # P/E
        pe = price / eps if (not pd.isna(eps) and eps > 0) else np.nan

        # P/B (tangible)
        pb = price / tangible_bvps \
            if (not pd.isna(tangible_bvps) and tangible_bvps > 0) else np.nan

        # Growth rate g (2-year revenue CAGR, raw currency)
        g = np.nan
        if not pd.isna(raw_rev) and not pd.isna(raw_rev_2y) \
                and raw_rev > 0 and raw_rev_2y > 0:
            g = (raw_rev / raw_rev_2y) ** 0.5 - 1

        # YoY revenue growth (raw currency)
        yoy = np.nan
        if not pd.isna(raw_rev) and not pd.isna(raw_rev_1y) and raw_rev_1y != 0:
            yoy = (raw_rev - raw_rev_1y) / abs(raw_rev_1y)

        # Net margin
        nm = ni / rev if (not pd.isna(ni) and not pd.isna(rev) and rev != 0) else np.nan

        # Operating margin
        op_margin = oi / rev if (not pd.isna(oi) and not pd.isna(rev) and rev != 0) else np.nan

        # Graham intrinsic value  V = EPS * (8.5 + 2g) * 4.4 / Y
        bg = p_bg = p_bg_bv = np.nan
        if not pd.isna(eps) and not pd.isna(g):
            bg = (eps * (8.5 + 2 * (g * 100)) * 4.4) / aaa_yield
            if bg != 0:
                p_bg = price / bg
            if not pd.isna(tangible_bvps):
                denom = bg + tangible_bvps
                if denom != 0:
                    p_bg_bv = price / denom


        # ROE = Net Income / Equity
        roe = np.nan
        if not pd.isna(raw_ni) and not pd.isna(equity) and equity > 0:
            roe = raw_ni / equity

        # Free Cash Flow
        fcf = fcf_ps = fcf_yield = np.nan
        if not pd.isna(raw_ocf_val) and not pd.isna(raw_capex_val):
            fcf_raw = raw_ocf_val - abs(raw_capex_val)
            fcf = cvt(fcf_raw)
            if not pd.isna(shares) and shares > 0:
                fcf_ps = fcf / shares
                if price > 0:
                    fcf_yield = fcf_ps / price

        # Debt / Equity
        de = np.nan
        if not pd.isna(tot_debt) and not pd.isna(equity) and equity > 0:
            de = tot_debt / equity

        # --- Append row ---------------------------------------------------
        rows.append({
            "Date":                 date,
            "Source":               source,
            "Period Start":         period_start.strftime('%Y-%m-%d') if period_start is not None else "",
            "Period End":           period_end.strftime('%Y-%m-%d') if period_end is not None else "",
            "Price":                price,
            "EPS":                  eps,
            "Revenue":              rev,
            "Revenue 2Y Ago":       rev_2y,
            "Net Income":           ni,
            "Operating Income":     oi,
            "Shares Outstanding":   shares,
            "Total Equity":         equity_c,
            "Goodwill":             gw_c,
            "Intangible Assets":    intang_c,
            "Tangible Book Value":  tbv,
            "Tangible BVPS":        tangible_bvps,
            "Book Value Per Share":  bvps,
            "Total Debt":           debt_c,
            "Cash":                 cash_c,
            "Operating Cash Flow":  ocf,
            "Capital Expenditure":  capex_c,
            "Free Cash Flow":       fcf,
            "FCF Per Share":        fcf_ps,
            "Growth Rate (g)":      g,
            "P/E":                  pe,
            "P/B":                  pb,
            "YoY Revenue Growth":   yoy,
            "Net Margin":           nm,
            "Operating Margin":     op_margin,
            "ROE":                  roe,
            "FCF Yield":            fcf_yield,
            "Debt/Equity":          de,
            "BG Intrinsic":         bg,
            "Price / BG Intrinsic": p_bg,
            "Price / (BG + BV)":    p_bg_bv,
            "AAA Yield":            aaa_yield,
            "Currency":             price_curr,
            "Financials Currency":  fin_curr,
            "Exchange Rate":        fx,
        })

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    df['Date'] = pd.to_datetime(df['Date']).dt.strftime('%Y-%m-%d')
    return df


# ---------------------------------------------------------------------------
# Balance-sheet helper extractors
# ---------------------------------------------------------------------------

def _bs_equity(bs_df, date):
    """Stockholders' equity, with fallback to Assets - Liabilities."""
    if bs_df is None:
        return np.nan
    eq, _ = get_latest(_col(bs_df, ['Stockholders Equity']), date)
    if pd.isna(eq):
        a, _ = get_latest(_col(bs_df, ['Total Assets']), date)
        l, _ = get_latest(_col(bs_df, ['Total Liabilities Net Minority Interest']), date)
        if not pd.isna(a) and not pd.isna(l):
            eq = a - l
    return eq


def _bs_val(bs_df, candidates, date):
    """Single balance-sheet value; returns 0 if NaN."""
    if bs_df is None:
        return 0
    v, _ = get_latest(_col(bs_df, candidates), date)
    return 0 if pd.isna(v) else v


def _bs_debt(bs_df, date):
    """Total debt, with fallback to Long-Term + Current."""
    if bs_df is None:
        return np.nan
    d, _ = get_latest(_col(bs_df, ['Total Debt']), date)
    if pd.isna(d):
        lt, _ = get_latest(_col(bs_df, ['Long Term Debt']), date)
        ct, _ = get_latest(_col(bs_df, ['Current Debt',
                                         'Current Debt And Capital Lease Obligation']), date)
        lt = 0 if pd.isna(lt) else lt
        ct = 0 if pd.isna(ct) else ct
        d = lt + ct
    return d


def _empty_row(date, price, price_curr, fin_curr, fx):
    return {
        "Date": date, "Source": "No Financials", "Price": price,
        "Currency": price_curr, "Financials Currency": fin_curr, "Exchange Rate": fx,
    }


def _extended_only_row(date, price, raw_eps, price_curr, fin_curr, fx):
    """Row for dates older than yfinance's data depth — populates only the
    columns derivable from the stockanalysis TTM EPS series (Price, EPS, P/E)
    plus the currency / FX metadata. All other fields are NaN.

    This is what lets the 5Y EPS CAGR lookup find an anchor value even when
    yfinance's 4-year window doesn't reach that far back.
    """
    eps = np.nan if pd.isna(raw_eps) else raw_eps * fx
    pe = price / eps if (not pd.isna(eps) and eps > 0 and not pd.isna(price)) else np.nan
    return {
        "Date": date,
        "Source": "Extended TTM EPS",
        "Price": price,
        "EPS": eps,
        "P/E": pe,
        "Currency": price_curr,
        "Financials Currency": fin_curr,
        "Exchange Rate": fx,
    }

"""Email alerts: run summary + Li Lu buy signals after each weekly analysis."""

import smtplib
import os
import datetime
import numpy as np
import pandas as pd
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

SENDER_EMAIL = "horatiocary@gmail.com"
RECEIVER_EMAIL = "horatiocary@gmail.com"
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD", "")
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587

# Thresholds
PE_PERCENTILE_THRESHOLD = 20   # Bottom 20% of own history
PEER_PERCENTILE_GAP = 15       # Stock's percentile must be this much below group median percentile
OP_MARGIN_MIN = 0.10           # 10%
PE_HISTORY_MIN_POINTS = 20     # Need at least 20 weeks of P/E history
CHEAP_PE_PCT_THRESHOLD = 40    # P/E pct below this => render a peer-comparison table at the bottom of the email


def send_alerts(companies_data, stock_names=None, groups=None):
    """Analyse stocks for buy signals and send email summary."""
    if not EMAIL_PASSWORD:
        print("EMAIL_PASSWORD not set — skipping email alerts.")
        return

    if stock_names is None:
        stock_names = {}
    if groups is None:
        groups = {}

    # Rule 1: Only group-title stocks can trigger buy alerts
    buy_candidates = set()
    for g_name in groups:
        buy_candidates.add(g_name.replace(" Analysis", ""))

    now = datetime.datetime.utcnow().strftime("%d %b %Y %H:%M UTC")

    # Pre-compute each stock's P/E percentile within its own history
    pe_percentiles = {}
    for ticker, df in companies_data.items():
        if df is None or df.empty:
            continue
        pe_series = df["P/E"].dropna()
        pe_series = pe_series[pe_series > 0]
        if len(pe_series) < PE_HISTORY_MIN_POINTS:
            continue
        current_pe = pe_series.iloc[-1]
        pct = (pe_series < current_pe).sum() / len(pe_series) * 100
        pe_percentiles[ticker] = pct

    # Find buy signals
    buy_signals = []
    summary_rows = []

    for ticker, df in companies_data.items():
        if df is None or df.empty:
            continue

        last = df.iloc[-1]
        name = stock_names.get(ticker, ticker)
        price = last.get("Price")
        pe = last.get("P/E")
        op_margin = last.get("Operating Margin")
        fcf = last.get("Free Cash Flow")
        pe_pct = pe_percentiles.get(ticker)

        summary_rows.append({
            "ticker": ticker, "name": name, "price": price,
            "pe": pe, "pb": last.get("P/B"), "op_margin": op_margin,
            "nm": last.get("Net Margin"), "fcf_yield": last.get("FCF Yield"),
            "p_bg": last.get("Price / BG Intrinsic"),
            "pe_pct": pe_pct,
            "eps_1y": _eps_cagr(df, 1),
            "eps_3y": _eps_cagr(df, 3),
            "eps_5y": _eps_cagr(df, 5),
        })

        # Rule 1: Must be a buy candidate
        if ticker not in buy_candidates:
            continue

        reasons = []
        fails = []

        # Rule 2: P/E at own historic low (bottom 20th percentile)
        if pe_pct is not None and pe_pct <= PE_PERCENTILE_THRESHOLD:
            reasons.append(f"P/E at {pe_pct:.0f}th percentile of own history (threshold: {PE_PERCENTILE_THRESHOLD}th)")
        else:
            if pe_pct is not None:
                fails.append(f"P/E at {pe_pct:.0f}th pct (need ≤{PE_PERCENTILE_THRESHOLD}th)")
            else:
                fails.append("Insufficient P/E history")

        # Rule 3: P/E percentile is low vs peers' percentiles
        rule3_pass, rule3_detail = _check_peer_percentile(ticker, pe_pct, groups, pe_percentiles)
        if rule3_pass:
            reasons.append(rule3_detail)
        else:
            fails.append(rule3_detail)

        # Rule 4: Operating Margin > 10%
        if op_margin is not None and op_margin > OP_MARGIN_MIN:
            reasons.append(f"Op Margin {op_margin*100:.1f}% (above {OP_MARGIN_MIN*100:.0f}%)")
        else:
            if op_margin is not None:
                fails.append(f"Op Margin {op_margin*100:.1f}% (need >{OP_MARGIN_MIN*100:.0f}%)")
            else:
                fails.append("No margin data")

        # Rule 5: Positive Free Cash Flow
        if fcf is not None and fcf > 0:
            reasons.append(f"Positive FCF")
        else:
            fails.append("Negative or missing FCF")

        # All rules must pass
        if len(reasons) == 4 and len(fails) == 0:
            buy_signals.append({
                "ticker": ticker, "name": name, "price": price,
                "pe": pe, "pe_pct": pe_pct, "op_margin": op_margin,
                "reasons": reasons,
            })

    # Build and send email
    subject = f"Stock Analysis Update — {now}"
    if buy_signals:
        subject = f"BUY SIGNAL: {', '.join(s['ticker'] for s in buy_signals)} — {now}"

    body = _build_html(now, buy_signals, buy_candidates, summary_rows,
                        pe_percentiles, groups, len(companies_data))
    _send(subject, body)


def _check_peer_percentile(ticker, ticker_pct, groups, pe_percentiles):
    """Rule 3: Check if this stock's P/E percentile is notably lower than
    the median percentile of its peers in the same group."""
    if ticker_pct is None:
        return False, "No P/E percentile data"

    # Find the group this stock is the title of
    group_name = f"{ticker} Analysis"
    peers = groups.get(group_name, [])
    if not peers:
        return False, "No peer group found"

    peer_pcts = []
    for p in peers:
        if p != ticker and p in pe_percentiles:
            peer_pcts.append(pe_percentiles[p])

    if not peer_pcts:
        return False, "No peer P/E percentile data"

    median_peer_pct = sorted(peer_pcts)[len(peer_pcts) // 2]
    gap = median_peer_pct - ticker_pct

    if gap >= PEER_PERCENTILE_GAP:
        return True, (f"P/E pct {ticker_pct:.0f}th vs peer median {median_peer_pct:.0f}th "
                       f"(gap: {gap:.0f}pts, threshold: {PEER_PERCENTILE_GAP}pts)")
    else:
        return False, (f"P/E pct {ticker_pct:.0f}th vs peer median {median_peer_pct:.0f}th "
                        f"(gap: {gap:.0f}pts, need ≥{PEER_PERCENTILE_GAP}pts)")


def _build_html(timestamp, buy_signals, buy_candidates, summary_rows,
                pe_percentiles, groups, total_stocks):
    html = f"""
    <html><body style="font-family: -apple-system, Arial, sans-serif; color: #333; max-width: 900px;">
    <h2 style="color: #1a73e8;">Stock Analysis Update</h2>
    <p style="color: #666;">{timestamp} &middot; {total_stocks} stocks analysed</p>
    """

    # Buy signals
    if buy_signals:
        html += f'<h3 style="color: #2e7d32;">Buy Signals ({len(buy_signals)})</h3>'
        for s in buy_signals:
            html += f'<div style="background: #e8f5e9; border-left: 4px solid #2e7d32; padding: 12px; margin-bottom: 12px;">'
            html += f'<strong style="font-size: 16px;">{s["ticker"]}</strong> <span style="color: #666;">{s["name"]}</span><br>'
            html += f'<span style="font-size: 14px;">Price: {_fmt_price(s["price"])} &middot; P/E: {_fmt(s["pe"], "1f")} &middot; Op Margin: {_fmt(s["op_margin"], "pct")}</span><br>'
            html += '<ul style="margin: 6px 0; padding-left: 20px; font-size: 13px;">'
            for r in s["reasons"]:
                html += f'<li>{r}</li>'
            html += '</ul></div>'
    else:
        html += '<p style="color: #666;">No buy signals this week.</p>'

    # Watchlist summary (only buy candidates)
    html += '<h3 style="color: #1a73e8; margin-top: 24px;">Watchlist</h3>'
    html += '<table style="border-collapse: collapse; width: 100%; font-size: 13px;">'
    html += ('<tr style="background: #f5f5f5;">'
             '<th style="padding: 6px; text-align: left;">Stock</th>'
             '<th style="padding: 6px; text-align: right;">P/E</th>'
             '<th style="padding: 6px; text-align: right;">P/E Pct</th>'
             '<th style="padding: 6px; text-align: right;">1Y EPS CAGR</th>'
             '<th style="padding: 6px; text-align: right;">3Y EPS CAGR</th>'
             '<th style="padding: 6px; text-align: right;">5Y EPS CAGR</th>'
             '</tr>')

    watchlist = [r for r in summary_rows if r["ticker"] in buy_candidates]
    watchlist.sort(key=lambda r: r.get("pe_pct") if r.get("pe_pct") is not None else 999)

    for r in watchlist:
        pe_pct_str = _ordinal(r["pe_pct"]) if r.get("pe_pct") is not None else "—"
        pe_pct_color = "#2e7d32" if r.get("pe_pct") is not None and r["pe_pct"] <= PE_PERCENTILE_THRESHOLD else "#333"
        html += (f'<tr style="border-bottom: 1px solid #eee;">'
                 f'<td style="padding: 6px;"><strong>{r["ticker"]}</strong></td>'
                 f'<td style="padding: 6px; text-align: right;">{_fmt(r["pe"], "1f")}</td>'
                 f'<td style="padding: 6px; text-align: right; color: {pe_pct_color};"><strong>{pe_pct_str}</strong></td>'
                 f'<td style="padding: 6px; text-align: right;">{_fmt(r.get("eps_1y"), "pct")}</td>'
                 f'<td style="padding: 6px; text-align: right;">{_fmt(r.get("eps_3y"), "pct")}</td>'
                 f'<td style="padding: 6px; text-align: right;">{_fmt(r.get("eps_5y"), "pct")}</td>'
                 f'</tr>')

    html += '</table>'

    # Peer-comparison tables: one for every watchlist stock with a P/E
    # percentile in the cheap zone (below CHEAP_PE_PCT_THRESHOLD). The
    # table shows every competitor in its "{TICKER} Analysis" peer group
    # so the user can sanity-check whether the stock is genuinely cheap
    # versus peers or just cheap-in-isolation.
    html += _build_peer_tables(watchlist, summary_rows, groups)

    html += '</body></html>'
    return html


def _build_peer_tables(watchlist, summary_rows, groups):
    """One peer-comparison table per cheap watchlist stock."""
    cheap = [r for r in watchlist
             if r.get("pe_pct") is not None and r["pe_pct"] < CHEAP_PE_PCT_THRESHOLD]
    if not cheap:
        return ""

    by_ticker = {r["ticker"]: r for r in summary_rows}

    html = (f'<h3 style="color: #1a73e8; margin-top: 32px;">'
            f'Peer comparison &mdash; stocks with P/E below '
            f'{CHEAP_PE_PCT_THRESHOLD}th percentile of own history</h3>'
            f'<p style="color: #666; font-size: 13px; margin: 0 0 16px 0;">'
            f'For each cheap stock below, the table lists every competitor in '
            f'its analysis group with their P/E, P/E percentile (of own history) '
            f'and EPS growth.</p>')

    cheap.sort(key=lambda r: r["pe_pct"])

    for r in cheap:
        ticker = r["ticker"]
        group_name = f"{ticker} Analysis"
        peers = groups.get(group_name, [])
        if not peers:
            continue

        html += (f'<h4 style="margin-top: 24px; margin-bottom: 6px;">'
                 f'{ticker} <span style="color: #666; font-weight: normal;">'
                 f'&middot; {r["name"]} &middot; P/E {_fmt(r["pe"], "1f")} '
                 f'&middot; {_ordinal(r["pe_pct"])} percentile</span></h4>')
        html += '<table style="border-collapse: collapse; width: 100%; font-size: 13px; margin-bottom: 8px;">'
        html += ('<tr style="background: #f5f5f5;">'
                 '<th style="padding: 6px; text-align: left;">Stock</th>'
                 '<th style="padding: 6px; text-align: right;">P/E</th>'
                 '<th style="padding: 6px; text-align: right;">P/E Pct</th>'
                 '<th style="padding: 6px; text-align: right;">1Y EPS CAGR</th>'
                 '<th style="padding: 6px; text-align: right;">3Y EPS CAGR</th>'
                 '<th style="padding: 6px; text-align: right;">5Y EPS CAGR</th>'
                 '</tr>')

        # Sort peers: anchor stock first, then ascending P/E pct.
        peer_rows = []
        for p in peers:
            pr = by_ticker.get(p)
            if pr is not None:
                peer_rows.append(pr)
        peer_rows.sort(key=lambda x: (
            0 if x["ticker"] == ticker else 1,
            x.get("pe_pct") if x.get("pe_pct") is not None else 999,
        ))

        for pr in peer_rows:
            pe_pct_str = _ordinal(pr["pe_pct"]) if pr.get("pe_pct") is not None else "—"
            is_anchor = pr["ticker"] == ticker
            row_bg = "#fff8dc" if is_anchor else "transparent"
            name_html = f'<strong>{pr["ticker"]}</strong>'
            if is_anchor:
                name_html += ' <span style="color: #888; font-size: 11px;">(focus)</span>'
            pe_pct_color = ("#2e7d32" if pr.get("pe_pct") is not None
                             and pr["pe_pct"] <= PE_PERCENTILE_THRESHOLD else "#333")
            html += (f'<tr style="border-bottom: 1px solid #eee; background: {row_bg};">'
                     f'<td style="padding: 6px;">{name_html}</td>'
                     f'<td style="padding: 6px; text-align: right;">{_fmt(pr.get("pe"), "1f")}</td>'
                     f'<td style="padding: 6px; text-align: right; color: {pe_pct_color};"><strong>{pe_pct_str}</strong></td>'
                     f'<td style="padding: 6px; text-align: right;">{_fmt(pr.get("eps_1y"), "pct")}</td>'
                     f'<td style="padding: 6px; text-align: right;">{_fmt(pr.get("eps_3y"), "pct")}</td>'
                     f'<td style="padding: 6px; text-align: right;">{_fmt(pr.get("eps_5y"), "pct")}</td>'
                     f'</tr>')
        html += '</table>'

    return html


def _eps_cagr(df, years):
    """Compound annual EPS growth rate over approximately the trailing N years.

    Picks the row closest to *years* before the latest date — preferring rows
    at-or-before the target, but falling back to slightly-after-target rows
    if necessary (handles the case where data only goes back ~4.9 years for
    Dec-fiscal stocks while we ask for 5 years). The CAGR is annualised
    against the ACTUAL time span between the chosen anchor and the latest
    row, so the math stays correct even when the anchor isn't exactly
    *years* old. Requires at least 60% of the requested span — anything
    shorter is too noisy to label as a long-term CAGR.
    """
    if df is None or df.empty or "EPS" not in df.columns or "Date" not in df.columns:
        return None
    eps_series = df["EPS"]
    end_eps = eps_series.iloc[-1]
    if pd.isna(end_eps) or end_eps <= 0:
        return None
    dates = pd.to_datetime(df["Date"])
    end_date = dates.iloc[-1]
    target = end_date - pd.DateOffset(years=years)

    valid = (eps_series.notna()) & (eps_series > 0)
    valid_idx = dates[valid].index
    if len(valid_idx) == 0:
        return None

    # 1. Prefer the latest row at-or-before the 5Y target.
    before = [i for i in valid_idx if dates.loc[i] <= target]
    if before:
        start_idx = before[-1]
    else:
        # 2. Fall back to the earliest available row (closest to target).
        start_idx = valid_idx[0]

    start_date = dates.loc[start_idx]
    actual_years = (end_date - start_date).days / 365.25
    if actual_years < years * 0.6 or actual_years <= 0:
        return None
    start_eps = eps_series.loc[start_idx]
    if pd.isna(start_eps) or start_eps <= 0:
        return None
    return (end_eps / start_eps) ** (1 / actual_years) - 1


def _fmt_price(v):
    if v is None: return "\u2014"
    return f"{v:,.2f}"


def _ordinal(n):
    """Convert an int percentile to 1st / 2nd / 3rd / 4th-style ordinal."""
    n = int(round(n))
    if 10 <= (n % 100) <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"

def _fmt(v, style):
    if v is None: return "\u2014"
    if style == "1f": return f"{v:.1f}"
    if style == "2f": return f"{v:.2f}"
    if style == "pct": return f"{v*100:.1f}%"
    return str(v)


def _send(subject, html_body):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = SENDER_EMAIL
    msg["To"] = RECEIVER_EMAIL
    msg.attach(MIMEText(html_body, "html"))

    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(SENDER_EMAIL, EMAIL_PASSWORD)
            server.sendmail(SENDER_EMAIL, RECEIVER_EMAIL, msg.as_string())
        print(f"Email sent: {subject}")
    except Exception as e:
        print(f"Failed to send email: {e}")

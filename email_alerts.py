"""Email alerts: run summary + buy signals after each weekly analysis."""

import smtplib
import os
import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

SENDER_EMAIL = "horatiocary@gmail.com"
RECEIVER_EMAIL = "horatiocary@gmail.com"
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD", "")
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587

# Buy signal thresholds
BUY_THRESHOLDS = {
    "Price / BG Intrinsic": 1.0,   # Trading below Graham intrinsic value
    "Price / (BG + BV)": 0.8,      # Trading well below intrinsic + book
    "P/E": 12,                      # Low P/E
}


def send_alerts(companies_data, stock_names=None):
    """Analyse all stocks for buy signals and send email summary."""
    if not EMAIL_PASSWORD:
        print("EMAIL_PASSWORD not set — skipping email alerts.")
        return

    if stock_names is None:
        stock_names = {}

    now = datetime.datetime.utcnow().strftime("%d %b %Y %H:%M UTC")
    buy_signals = []
    summary_rows = []

    for ticker, df in companies_data.items():
        if df is None or df.empty:
            continue

        last = df.iloc[-1]
        name = stock_names.get(ticker, ticker)
        price = last.get("Price")
        pe = last.get("P/E")
        pb = last.get("P/B")
        roic = last.get("ROIC")
        p_bg = last.get("Price / BG Intrinsic")
        p_bg_bv = last.get("Price / (BG + BV)")
        nm = last.get("Net Margin")
        fcf_yield = last.get("FCF Yield")

        summary_rows.append({
            "ticker": ticker, "name": name, "price": price,
            "pe": pe, "pb": pb, "roic": roic, "p_bg": p_bg,
            "p_bg_bv": p_bg_bv, "nm": nm, "fcf_yield": fcf_yield,
        })

        # Check buy signals
        reasons = []
        if _below(p_bg, BUY_THRESHOLDS["Price / BG Intrinsic"]):
            reasons.append(f"Price/BG Intrinsic = {p_bg:.2f} (below {BUY_THRESHOLDS['Price / BG Intrinsic']})")
        if _below(p_bg_bv, BUY_THRESHOLDS["Price / (BG + BV)"]):
            reasons.append(f"Price/(BG+BV) = {p_bg_bv:.2f} (below {BUY_THRESHOLDS['Price / (BG + BV)']})")
        if _below(pe, BUY_THRESHOLDS["P/E"]) and pe is not None and pe > 0:
            reasons.append(f"P/E = {pe:.1f} (below {BUY_THRESHOLDS['P/E']})")

        if reasons:
            buy_signals.append({"ticker": ticker, "name": name,
                                "price": price, "reasons": reasons})

    # Build email
    subject = f"Stock Analysis Update — {now}"
    if buy_signals:
        subject = f"🔔 {len(buy_signals)} Buy Signal(s) — {now}"

    body = _build_html(now, buy_signals, summary_rows, len(companies_data))
    _send(subject, body)


def _below(val, threshold):
    return val is not None and val > 0 and val < threshold


def _build_html(timestamp, buy_signals, summary_rows, total_stocks):
    html = f"""
    <html><body style="font-family: -apple-system, Arial, sans-serif; color: #333; max-width: 800px;">
    <h2 style="color: #1a73e8;">Stock Analysis Update</h2>
    <p style="color: #666;">{timestamp} &middot; {total_stocks} stocks analysed</p>
    """

    # Buy signals section
    if buy_signals:
        html += '<h3 style="color: #d32f2f;">Buy Signals</h3>'
        html += '<table style="border-collapse: collapse; width: 100%; font-size: 14px;">'
        html += '<tr style="background: #f5f5f5;"><th style="padding: 8px; text-align: left;">Stock</th><th style="padding: 8px; text-align: right;">Price</th><th style="padding: 8px; text-align: left;">Reasons</th></tr>'
        for s in buy_signals:
            reasons_html = "<br>".join(s["reasons"])
            html += f'<tr style="border-bottom: 1px solid #eee;"><td style="padding: 8px;"><strong>{s["ticker"]}</strong><br><small style="color: #666;">{s["name"]}</small></td><td style="padding: 8px; text-align: right;">{_fmt_price(s["price"])}</td><td style="padding: 8px; font-size: 13px;">{reasons_html}</td></tr>'
        html += '</table>'
    else:
        html += '<p style="color: #666;">No buy signals this week.</p>'

    # Top metrics summary (top 20 by lowest P/E)
    html += '<h3 style="color: #1a73e8; margin-top: 24px;">Summary (Top 20 by P/E)</h3>'
    valid = [r for r in summary_rows if r["pe"] is not None and r["pe"] > 0]
    valid.sort(key=lambda r: r["pe"])
    top = valid[:20]

    html += '<table style="border-collapse: collapse; width: 100%; font-size: 13px;">'
    html += '<tr style="background: #f5f5f5;"><th style="padding: 6px; text-align: left;">Stock</th><th style="padding: 6px; text-align: right;">Price</th><th style="padding: 6px; text-align: right;">P/E</th><th style="padding: 6px; text-align: right;">P/B</th><th style="padding: 6px; text-align: right;">ROIC</th><th style="padding: 6px; text-align: right;">Net Margin</th><th style="padding: 6px; text-align: right;">FCF Yield</th><th style="padding: 6px; text-align: right;">P/BG</th></tr>'
    for r in top:
        html += f'<tr style="border-bottom: 1px solid #eee;"><td style="padding: 6px;"><strong>{r["ticker"]}</strong></td><td style="padding: 6px; text-align: right;">{_fmt_price(r["price"])}</td><td style="padding: 6px; text-align: right;">{_fmt(r["pe"], "1f")}</td><td style="padding: 6px; text-align: right;">{_fmt(r["pb"], "2f")}</td><td style="padding: 6px; text-align: right;">{_fmt(r["roic"], "pct")}</td><td style="padding: 6px; text-align: right;">{_fmt(r["nm"], "pct")}</td><td style="padding: 6px; text-align: right;">{_fmt(r["fcf_yield"], "pct")}</td><td style="padding: 6px; text-align: right;">{_fmt(r["p_bg"], "2f")}</td></tr>'
    html += '</table>'

    html += '</body></html>'
    return html


def _fmt_price(v):
    if v is None: return "—"
    return f"{v:,.2f}"

def _fmt(v, style):
    if v is None: return "—"
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

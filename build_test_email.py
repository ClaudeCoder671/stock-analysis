"""Render the weekly email HTML from cached data, with the authoritative
(quarterly-report) P/E override applied, WITHOUT sending via SMTP.

Used to produce a test the user can eyeball. Reconstructs companies_data
from master_data.csv (the last full run's per-ticker weekly metrics), so no
network re-fetch is needed; the authoritative P/E for covered tickers is
pulled fresh from PublicEquities/pe_snapshot.json by email_alerts.

Writes test_email.html next to this file.
"""
import sys
import yaml
import pandas as pd
import data_manager
import valuation
import email_alerts as ea


def recompute_companies_data(companies, groups):
    """Recompute each ticker's weekly metrics from CACHED data (no network
    fetch), exactly as main.py does after fetching — so newly-added columns
    like EV/E are present for every ticker rather than read from a stale
    master_data.csv."""
    bond = data_manager.fetch_bond_yield_history()
    data = {}
    for tk in companies:
        try:
            loaded = data_manager.load_data(tk)
            mdf = valuation.calculate_metrics(loaded, bond)
            if mdf is None or mdf.empty:
                continue
            my_groups = [g for g, members in groups.items() if tk in members]
            mdf["Comparison Group"] = ", ".join(my_groups) if my_groups else ""
            data[tk] = mdf
        except Exception as e:
            print(f"  [skip] {tk}: {type(e).__name__}: {e}")
    return data


def main():
    cfg = yaml.safe_load(open("config.yaml"))
    groups = cfg.get("groups", {})
    companies = cfg.get("companies", [])

    companies_data = recompute_companies_data(companies, groups)
    # stock_names from cached info.json where available
    stock_names = {}
    import os, json
    for tk in companies_data:
        p = os.path.join("data", tk, "info.json")
        if os.path.exists(p):
            try:
                info = json.load(open(p))
                stock_names[tk] = info.get("shortName") or info.get("longName") or tk
            except Exception:
                stock_names[tk] = tk
        else:
            stock_names[tk] = tk

    # Capture the HTML instead of sending via SMTP.
    captured = {}

    def fake_send(subject, html):
        captured["subject"] = subject
        captured["html"] = html
        print(f"[captured] subject: {subject}")

    ea._send = fake_send
    ea.EMAIL_PASSWORD = "TEST"  # bypass the "not set -> skip" early return

    ea.send_alerts(companies_data, stock_names, groups)

    if "html" not in captured:
        print("No HTML captured — send_alerts did not build a body.")
        sys.exit(1)
    out = "test_email.html"
    with open(out, "w", encoding="utf-8") as f:
        f.write(captured["html"])
    print(f"Wrote {out} ({len(captured['html'])} bytes). Subject: {captured['subject']}")


if __name__ == "__main__":
    main()

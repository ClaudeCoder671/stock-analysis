# StockAnalysis (weekly Li Lu screen + email) — durable notes

## P/E comes from the quarterly-report analysis (authoritative)

The weekly email's P/E ratios are sourced from the **PublicEquities
quarterly-report pipeline** for every ticker it covers, instead of this
screen's own `price / EPS` calc. That pipeline is gated, ADR-ratio-correct,
and knows where yfinance is wrong (e.g. BYDDY's 2025 bonus/ADR change), so
its P/E is the single source of truth.

- **Export:** `PublicEquities/pe_snapshot.py` writes `pe_snapshot.json`
  (current P/E + full weekly P/E history per covered ticker), reusing the
  report's exact `load_and_compute()` path so the number equals the PDF's.
- **Import:** `email_alerts.apply_authoritative_pe()` (called at the top of
  `send_alerts`) reads that JSON and overrides the `P/E` column for covered
  tickers with the authoritative **weekly series** — so the displayed P/E,
  the percentile-vs-own-history, the peer tables, and the buy-signal rules
  all derive from it. Covered names are tagged with a green ✓ in the email.
- Tickers not covered keep this screen's own P/E (already computed on the
  correct ADR basis for most). The override is robust: if the snapshot is
  missing/unreadable, the email silently falls back to the screen's P/E.
- Path is `PE_SNAPSHOT_PATH` (env var; defaults to the local PublicEquities
  folder). Covered set is `pe_snapshot.COVERED` in PublicEquities.

### Ongoing freshness — REQUIRED wiring

The weekly P/E is price-driven, so `pe_snapshot.json` must be **refreshed
before each weekly email**, or the email shows a stale (but still
authoritative-basis) P/E.

- **Local run** (`Run Analysis.bat`): run
  `python pe_snapshot.py` in the PublicEquities folder first, then `main.py`
  here. Same machine → the default path resolves.
- **GitHub weekly job** (`.github/workflows/weekly-analysis.yml`, Sun 06:00
  UTC): add a step before `python main.py` that produces a fresh
  `pe_snapshot.json` and points `PE_SNAPSHOT_PATH` at it. Because
  PublicEquities is a separate private repo, this needs either (a) checking
  it out + downloading its `fundamentals.db` release + running
  `pe_snapshot.py`, or (b) PublicEquities publishing `pe_snapshot.json` as a
  release artifact that this workflow downloads. Either way needs a
  cross-repo token — supply it as a repo secret. Until wired, the CI email
  falls back to the screen's own P/E (no crash).

## Watchlist columns: P/E, EV/E, P/E Pct, EV/E Pct (+ EPS CAGRs)

The watchlist table shows both multiples and their own-history percentiles,
in that column order. **EV/E** = (price − net cash per share) / TTM EPS
(net cash = cash − total debt) — the P/E with balance-sheet cash stripped
out; it diverges sharply from P/E for cash-rich names (PDD ~8.8 P/E vs ~4.4
EV/E) and goes >P/E for net-debt names. Computed per-quarter in
`valuation.py` (`EV/E` column, every ticker) so the weekly series — and
thus the percentile — exist. For covered tickers, EV/E (current + weekly
series) is overridden by the authoritative `pe_snapshot.json`
(`ev_e_weekly`), same as P/E. Percentiles via `_percentiles()` in
`send_alerts`. **EV/E is never blank when P/E exists** — it defaults to P/E
(no cash adjustment) and only departs when a valid, positive cash-adjusted
price exists. So banks/financials (where "cash" = deposits and the net-cash
adjustment is meaningless / would go negative, e.g. PSTVY) show EV/E = P/E,
and so do any quarters missing balance-sheet data — never a "—".

## Test preview

`python build_test_email.py` renders the email by RECOMPUTING metrics from
each ticker's cached data (`data/<ticker>/`) via `valuation.calculate_metrics`
+ the authoritative snapshot to `test_email.html`, without sending (it
monkeypatches `_send`). Open the file or draft it for review.

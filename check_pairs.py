import yfinance as yf

pairs = ["CNYHKD=X", "CNYUSD=X", "HKDUSD=X"]

for pair in pairs:
    print(f"\n--- {pair} ---")
    p = yf.Ticker(pair)
    hist = p.history(period="5d")
    print(hist)

import yfinance as yf

tickers = ["0700.HK", "JD", "BABA", "AAPL"]

for ticker in tickers:
    print(f"\n--- {ticker} ---")
    t = yf.Ticker(ticker)
    
    # Fast info
    fast_info = t.fast_info
    print(f"Fast Info Currency: {fast_info.get('currency')}")
    
    # Metadata
    try:
        meta = t.get_history_metadata()
        print(f"History Metadata Currency: {meta.get('currency')}")
        print(f"History Metadata Trading Currency: {meta.get('tradingCurrency')}")
    except Exception as e:
        print(f"Metadata error: {e}")

    # Financials Currency (often in income statement metadata or just inferred)
    try:
        inc = t.income_stmt
        # yfinance doesn't always explicitly state financial currency in the dataframe attributes easily, 
        # but t.info often has 'currency' and 'financialCurrency'
        info = t.info
        print(f"Info 'currency' (Price): {info.get('currency')}")
        print(f"Info 'financialCurrency': {info.get('financialCurrency')}")
    except Exception as e:
        print(f"Info/Financials error: {e}")

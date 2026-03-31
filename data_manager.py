import yfinance as yf
import pandas as pd
import os
import json
from datetime import datetime

DATA_DIR = "data"

def ensure_data_dir():
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR)

def fetch_data(ticker):
    """
    Fetches historical price data and financial statements from Yahoo Finance.
    """
    print(f"Fetching data for {ticker}...")
    stock = yf.Ticker(ticker)
    
    # Fetch history (max available)
    # We want weekly data, but yfinance's '1wk' interval can be tricky with dates.
    # It's often safer to get daily '1d' and resample locally to ensure control over the 'week ending' date.
    # However, for simplicity and volume, let's try '1d' and resample in valuation.
    history = stock.history(period="max", interval="1d")
    
    # Fetch financials
    # yfinance returns a DataFrame where columns are dates.
    financials = stock.financials
    balance_sheet = stock.balance_sheet
    quarterly_financials = stock.quarterly_financials
    quarterly_balance_sheet = stock.quarterly_balance_sheet
    
    # Growth estimates
    try:
        # This is often in 'info'
        info = stock.info
        # Try to find a growth rate. 
        # 'revenueGrowth' is YoY. 'earningsGrowth' is YoY.
        # We need long term growth for BG formula. 
        # Often not directly available as a clean number in 'info' for free.
        # We will look for 'pegRatio' to back out or just use a default if missing.
        # Actually, let's check if 'growth' keys exist.
        # For now, we will store the whole info dict and parse later.
        growth_rate = info.get('targetMeanPrice', None) # Placeholder, likely need better source or calc
        # A better proxy might be to calculate it ourselves from the financials if missing.
        # Let's store the 'info' to extract what we can.
        stock_info = info
    except Exception as e:
        print(f"Warning: Could not fetch info for {ticker}: {e}")
        stock_info = {}

    # Currency Metadata
    currency_meta = {
        "price_currency": stock_info.get("currency"),
        "financial_currency": stock_info.get("financialCurrency")
    }

    # Cash flow statements
    cashflow = stock.cashflow
    quarterly_cashflow = stock.quarterly_cashflow

    return {
        "history": history,
        "financials": financials,
        "balance_sheet": balance_sheet,
        "quarterly_financials": quarterly_financials,
        "quarterly_balance_sheet": quarterly_balance_sheet,
        "cashflow": cashflow,
        "quarterly_cashflow": quarterly_cashflow,
        "info": stock_info,
        "currency_metadata": currency_meta
    }

def save_data(ticker, data):
    """
    Saves the fetched data to local files.
    """
    ensure_data_dir()
    ticker_dir = os.path.join(DATA_DIR, ticker)
    if not os.path.exists(ticker_dir):
        os.makedirs(ticker_dir)

    # Save History
    history_path = os.path.join(ticker_dir, "history.csv")
    new_history = data["history"]
    
    if os.path.exists(history_path):
        old_history = pd.read_csv(history_path, index_col=0, parse_dates=True)
        old_history.index = pd.to_datetime(old_history.index, utc=True, errors='coerce')
        new_history.index = pd.to_datetime(new_history.index, utc=True, errors='coerce')
        combined_history = pd.concat([old_history, new_history])
        combined_history = combined_history[combined_history.index.notna()]
        combined_history = combined_history[~combined_history.index.duplicated(keep='last')]
        combined_history.sort_index(inplace=True)
        combined_history.to_csv(history_path)
    else:
        new_history.to_csv(history_path)

    with open(os.path.join(ticker_dir, "currency_metadata.json"), "w") as f:
        json.dump(data.get("currency_metadata", {}), f, indent=4)

    # Helper to merge and save
    def merge_and_save(new_df, filename):
        path = os.path.join(ticker_dir, filename)
        if os.path.exists(path):
            try:
                old_df = pd.read_csv(path, index_col=0)
                # Ensure columns are datetime objects for sorting
                old_df.columns = pd.to_datetime(old_df.columns, errors='coerce')
                new_df.columns = pd.to_datetime(new_df.columns, errors='coerce')
                
                # Align columns (tickers might change or new columns added)
                # Concatenate
                combined = pd.concat([old_df, new_df], axis=1)
                # Remove duplicate columns (dates) - keep new ones?
                # Financials from yfinance have dates as columns.
                # We want to keep the union of dates.
                combined = combined.loc[:, ~combined.columns.duplicated(keep='last')]
                # Sort columns (dates)
                combined = combined.reindex(sorted(combined.columns, reverse=True), axis=1)
                combined.to_csv(path)
            except Exception as e:
                print(f"Error merging {filename}: {e}. Overwriting.")
                new_df.to_csv(path)
        else:
            new_df.to_csv(path)

    # Save Financials (Merge)
    merge_and_save(data["quarterly_financials"], "quarterly_financials.csv")
    merge_and_save(data["quarterly_balance_sheet"], "quarterly_balance_sheet.csv")
    merge_and_save(data["financials"], "annual_financials.csv")
    merge_and_save(data["balance_sheet"], "annual_balance_sheet.csv")
    merge_and_save(data["cashflow"], "annual_cashflow.csv")
    merge_and_save(data["quarterly_cashflow"], "quarterly_cashflow.csv")

    # Save Info
    with open(os.path.join(ticker_dir, "info.json"), "w") as f:
        json.dump(data["info"], f, indent=4, default=str)

def load_data(ticker):
    """
    Loads data from local files.
    """
    ticker_dir = os.path.join(DATA_DIR, ticker)
    if not os.path.exists(ticker_dir):
        return None

    try:
        history = pd.read_csv(os.path.join(ticker_dir, "history.csv"), index_col=0, parse_dates=True)
        q_financials = pd.read_csv(os.path.join(ticker_dir, "quarterly_financials.csv"), index_col=0, parse_dates=True)
        q_bs = pd.read_csv(os.path.join(ticker_dir, "quarterly_balance_sheet.csv"), index_col=0, parse_dates=True)
        
        # Load Annual
        a_financials = pd.read_csv(os.path.join(ticker_dir, "annual_financials.csv"), index_col=0, parse_dates=True)
        a_bs = pd.read_csv(os.path.join(ticker_dir, "annual_balance_sheet.csv"), index_col=0, parse_dates=True)
        
        # Load Cash Flow Statements
        a_cashflow = None
        q_cashflow = None
        a_cf_path = os.path.join(ticker_dir, "annual_cashflow.csv")
        q_cf_path = os.path.join(ticker_dir, "quarterly_cashflow.csv")
        if os.path.exists(a_cf_path):
            a_cashflow = pd.read_csv(a_cf_path, index_col=0, parse_dates=True)
        if os.path.exists(q_cf_path):
            q_cashflow = pd.read_csv(q_cf_path, index_col=0, parse_dates=True)

        # Transpose financials so rows are dates, easier for resampling
        q_financials = q_financials.T
        q_bs = q_bs.T
        a_financials = a_financials.T
        a_bs = a_bs.T
        if a_cashflow is not None: a_cashflow = a_cashflow.T
        if q_cashflow is not None: q_cashflow = q_cashflow.T

        # Convert index to datetime and sort
        def sort_df(df):
            if df is not None:
                df.index = pd.to_datetime(df.index, errors='coerce')
                df = df[df.index.notna()]
                df.sort_index(inplace=True)
            return df

        q_financials = sort_df(q_financials)
        q_bs = sort_df(q_bs)
        a_financials = sort_df(a_financials)
        a_bs = sort_df(a_bs)
        a_cashflow = sort_df(a_cashflow)
        q_cashflow = sort_df(q_cashflow)
        
        with open(os.path.join(ticker_dir, "info.json"), "r") as f:
            info = json.load(f)
            
        # Load Currency Metadata
        currency_meta = {}
        if os.path.exists(os.path.join(ticker_dir, "currency_metadata.json")):
            with open(os.path.join(ticker_dir, "currency_metadata.json"), "r") as f:
                currency_meta = json.load(f)

        return {
            "history": history,
            "quarterly_financials": q_financials,
            "quarterly_balance_sheet": q_bs,
            "annual_financials": a_financials,
            "annual_balance_sheet": a_bs,
            "annual_cashflow": a_cashflow,
            "quarterly_cashflow": q_cashflow,
            "info": info,
            "currency_metadata": currency_meta
        }
    except Exception as e:
        print(f"Error loading data for {ticker}: {e}")
        return None

def fetch_exchange_rate(pair):
    """
    Fetches historical exchange rate for a given pair (e.g., 'CNYHKD=X').
    Returns a Series of Close prices.
    """
    try:
        print(f"Fetching exchange rate for {pair}...")
        ticker = yf.Ticker(pair)
        hist = ticker.history(period="max")
        if hist.empty:
            return None
        return hist['Close']
    except Exception as e:
        print(f"Error fetching exchange rate {pair}: {e}")
        return None

def fetch_bond_yield_history():
    """
    Fetches historical 10-Year Treasury yield (^TNX) as a proxy for
    AAA corporate bond yield used in the Graham formula adjustment.
    Returns a Series of Close prices (yield as percentage, e.g. 4.5 = 4.5%).
    """
    try:
        print("Fetching Treasury yield history (^TNX)...")
        tnx = yf.Ticker("^TNX")
        hist = tnx.history(period="max")
        if hist.empty:
            return None
        return hist['Close']
    except Exception as e:
        print(f"Error fetching bond yield: {e}")
        return None

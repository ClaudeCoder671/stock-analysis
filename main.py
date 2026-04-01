import yaml
import datetime
import os
import data_manager
import valuation
import report_generator
import excel_generator
import json_exporter
import email_alerts

CONFIG_FILE = "config.yaml"


def load_config():
    if not os.path.exists(CONFIG_FILE):
        print("Config file not found. Creating default.")
        default_config = {"companies": ["AAPL", "MSFT"]}
        with open(CONFIG_FILE, "w") as f:
            yaml.dump(default_config, f)
        return default_config

    with open(CONFIG_FILE, "r") as f:
        return yaml.safe_load(f)


def main():
    config = load_config()
    companies = config.get("companies", [])

    # Fetch bond yield history once (shared across all stocks)
    print("Fetching bond yield history...")
    bond_yield_series = data_manager.fetch_bond_yield_history()

    companies_data = {}
    stock_names = {}

    for ticker in companies:
        print(f"\nProcessing {ticker}...")

        # 1. Fetch Data
        fetched_data = data_manager.fetch_data(ticker)

        # Capture company name from info
        info = fetched_data.get("info", {})
        stock_names[ticker] = info.get("shortName") or info.get("longName") or ticker

        # 2. Save/Merge Data
        data_manager.save_data(ticker, fetched_data)

        # 3. Load Data (to ensure we work with the merged dataset)
        loaded_data = data_manager.load_data(ticker)

        # 4. Calculate Metrics
        metrics_df = valuation.calculate_metrics(loaded_data, bond_yield_series)

        if metrics_df is not None and not metrics_df.empty:
            groups = config.get("groups", {})
            my_groups = [g_name for g_name, g_tickers in groups.items()
                         if ticker in g_tickers]
            metrics_df['Comparison Group'] = ", ".join(my_groups) if my_groups else ""

            print(f"Calculated metrics for {ticker}: {len(metrics_df)} weeks.")
            companies_data[ticker] = metrics_df
        else:
            print(f"Failed to calculate metrics for {ticker}.")

    # 5. Generate Reports
    print("\nGenerating reports...")

    date_prefix = datetime.datetime.now().strftime("%y%m%d")
    html_file = f"{date_prefix}_report.html"
    excel_file = f"{date_prefix}_stock_analysis.xlsx"

    report_generator.generate_html_report(companies_data, filename=html_file)
    excel_generator.generate_excel_report(
        companies_data, config.get("groups", {}), filename=excel_file)
    report_generator.export_to_csv(companies_data)

    # 6. Export JSON for web viewer
    json_exporter.export_json(companies_data, config.get("groups", {}), config, stock_names)

    # 7. Send email alerts
    email_alerts.send_alerts(companies_data, stock_names, config.get("groups", {}))

    print(f"\nDone! Open {excel_file} to view results.")


if __name__ == "__main__":
    main()

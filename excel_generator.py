import pandas as pd
import numpy as np
import os

REPORT_FILE = "stock_analysis.xlsx"


def generate_excel_report(companies_data, groups=None, filename=REPORT_FILE):
    """
    Generates an Excel report with data and charts for all companies.
    companies_data: dict {ticker: metrics_df}
    groups: dict {group_name: [tickers]}
    """
    try:
        writer = pd.ExcelWriter(filename, engine='xlsxwriter')
        workbook = writer.book

        all_data = []
        for ticker, df in companies_data.items():
            if df is not None:
                df_copy = df.copy()
                df_copy['Ticker'] = ticker
                all_data.append(df_copy)

        if not all_data:
            print("No data to export.")
            return

        # 1. Create Group Sheets (first, so they appear at the beginning)
        if groups:
            for g_name in groups:
                short_name = "A_" + g_name.replace(" Analysis", "")
                safe_name = short_name[:31]
                workbook.add_worksheet(safe_name)

        # 2. Master Data Sheet
        final_df = pd.concat(all_data)
        final_df.to_excel(writer, sheet_name='Master Data', index=False)

        # Helper to create chart for a ticker
        def create_chart(ticker):
            df = companies_data.get(ticker)
            if df is None or df.empty:
                return None

            data_sheet = ticker
            max_row = len(df) + 1
            col_map = {name: i for i, name in enumerate(df.columns)}

            def gc(name):
                return col_map.get(name)

            chart = workbook.add_chart({'type': 'line'})

            # Left axis: P/E, P/B
            for metric in ['P/E', 'P/B']:
                ci = gc(metric)
                if ci is not None:
                    chart.add_series({
                        'name': metric,
                        'categories': [data_sheet, 1, 0, max_row, 0],
                        'values': [data_sheet, 1, ci, max_row, ci],
                        'y2_axis': False,
                        'line': {'width': 2}
                    })

            # Right axis: growth & intrinsic ratios
            right_metrics = ['YoY Revenue Growth', 'Net Margin',
                             'Price / BG Intrinsic', 'Price / (BG + BV)',
                             'ROIC', 'ROE', 'FCF Yield']
            for metric in right_metrics:
                ci = gc(metric)
                if ci is not None:
                    chart.add_series({
                        'name': metric,
                        'categories': [data_sheet, 1, 0, max_row, 0],
                        'values': [data_sheet, 1, ci, max_row, ci],
                        'y2_axis': True,
                        'line': {'width': 2}
                    })

            # Dynamic axis ranges based on actual data
            pe_max = _safe_max(df, 'P/E', default=50)
            right_max = max(
                _safe_max(df, 'ROIC', default=1),
                _safe_max(df, 'Price / BG Intrinsic', default=3),
                _safe_max(df, 'Net Margin', default=1),
            )

            chart.set_x_axis({'name': 'Date'})
            chart.set_y_axis({'name': 'Valuation', 'min': 0, 'max': pe_max})
            chart.set_y2_axis({'name': 'Growth/Quality', 'min': 0, 'max': right_max})
            chart.set_title({'name': ticker})
            chart.set_size({'width': 600, 'height': 400})
            return chart

        # 3. Individual Sheets (Data & Charts)
        for ticker, df in companies_data.items():
            if df is None or df.empty:
                continue
            df.to_excel(writer, sheet_name=ticker, index=False)
            worksheet = writer.sheets[ticker]

            chart = create_chart(ticker)
            if chart:
                chart.set_size({'width': 1200, 'height': 600})
                worksheet.insert_chart('Z2', chart)

        # 4. Populate Group Sheets with Charts
        if groups:
            for g_name, g_tickers in groups.items():
                short_name = "A_" + g_name.replace(" Analysis", "")
                safe_name = short_name[:31]
                worksheet = writer.sheets[safe_name]

                for i, ticker in enumerate(g_tickers):
                    if ticker not in companies_data:
                        continue
                    chart = create_chart(ticker)
                    if chart:
                        r_pos = (i // 2) * 25
                        c_pos = (i % 2) * 10
                        worksheet.insert_chart(r_pos, c_pos, chart)

        writer.close()
        print(f"Excel report generated: {os.path.abspath(filename)}")

    except Exception as e:
        print(f"Error generating Excel report: {e}")


def _safe_max(df, col, default, quantile=0.95, pad=1.2):
    """Return a reasonable axis max: 95th percentile * 1.2, clamped to default minimum."""
    if col not in df.columns:
        return default
    s = df[col].dropna()
    if s.empty:
        return default
    q = s.quantile(quantile)
    return max(default, float(q * pad))

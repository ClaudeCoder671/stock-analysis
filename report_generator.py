import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import os

REPORT_FILE = "report.html"


def generate_html_report(companies_data, filename=REPORT_FILE):
    """
    Generates a single HTML report with charts for all companies.
    companies_data: dict {ticker: metrics_df}
    """
    html_content = """
    <html>
    <head>
        <title>Stock Valuation Report</title>
        <style>
            body { font-family: Arial, sans-serif; margin: 20px; }
            .company-section { margin-bottom: 50px; border-bottom: 1px solid #ccc; padding-bottom: 20px; }
            h1 { color: #333; }
            h2 { color: #555; }
        </style>
        <script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
    </head>
    <body>
        <h1>Stock Valuation Report</h1>
    """

    for ticker, df in companies_data.items():
        if df is None or df.empty:
            html_content += f"<div class='company-section'><h2>{ticker}</h2><p>No data available.</p></div>"
            continue

        # --- Chart 1: Valuation Ratios ------------------------------------
        fig1 = make_subplots(specs=[[{"secondary_y": True}]])

        fig1.add_trace(go.Scatter(x=df['Date'], y=df['P/E'], name="P/E",
                                  line=dict(width=2)), secondary_y=False)
        fig1.add_trace(go.Scatter(x=df['Date'], y=df['P/B'], name="P/B",
                                  line=dict(width=2)), secondary_y=False)
        fig1.add_trace(go.Scatter(x=df['Date'], y=df['Price / BG Intrinsic'],
                                  name="Price / BG Intrinsic",
                                  line=dict(width=2)), secondary_y=True)
        fig1.add_trace(go.Scatter(x=df['Date'], y=df['Price / (BG + BV)'],
                                  name="Price / (BG + BV)",
                                  line=dict(width=2)), secondary_y=True)

        fig1.update_layout(
            title=f"{ticker} - Valuation",
            xaxis_title="Date",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
        fig1.update_yaxes(title_text="P/E, P/B", secondary_y=False)
        fig1.update_yaxes(title_text="Price / Intrinsic", secondary_y=True)

        # --- Chart 2: Quality (ROIC, ROE, Margins) ------------------------
        fig2 = go.Figure()
        for col, name in [('ROIC', 'ROIC'), ('ROE', 'ROE'),
                          ('Operating Margin', 'Op Margin'), ('Net Margin', 'Net Margin')]:
            if col in df.columns:
                fig2.add_trace(go.Scatter(x=df['Date'], y=df[col], name=name,
                                          line=dict(width=2)))
        fig2.update_layout(
            title=f"{ticker} - Quality Metrics",
            xaxis_title="Date", yaxis_title="Ratio",
            yaxis_tickformat=".0%",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))

        # --- Chart 3: Growth & Cash Flow ----------------------------------
        fig3 = make_subplots(specs=[[{"secondary_y": True}]])
        fig3.add_trace(go.Scatter(x=df['Date'], y=df['YoY Revenue Growth'],
                                  name="YoY Revenue Growth",
                                  line=dict(width=2)), secondary_y=False)
        fig3.add_trace(go.Scatter(x=df['Date'], y=df['Growth Rate (g)'],
                                  name="Growth (g, 2Y CAGR)",
                                  line=dict(width=2)), secondary_y=False)
        if 'FCF Yield' in df.columns:
            fig3.add_trace(go.Scatter(x=df['Date'], y=df['FCF Yield'],
                                      name="FCF Yield",
                                      line=dict(width=2)), secondary_y=True)
        if 'Debt/Equity' in df.columns:
            fig3.add_trace(go.Scatter(x=df['Date'], y=df['Debt/Equity'],
                                      name="Debt/Equity",
                                      line=dict(width=2, dash='dot')), secondary_y=True)

        fig3.update_layout(
            title=f"{ticker} - Growth & Balance Sheet",
            xaxis_title="Date",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
        fig3.update_yaxes(title_text="Growth Rate", tickformat=".0%", secondary_y=False)
        fig3.update_yaxes(title_text="FCF Yield / D/E", secondary_y=True)

        div1 = fig1.to_html(full_html=False, include_plotlyjs=False)
        div2 = fig2.to_html(full_html=False, include_plotlyjs=False)
        div3 = fig3.to_html(full_html=False, include_plotlyjs=False)

        html_content += f"""
        <div class='company-section'>
            <h2>{ticker}</h2>
            {div1}
            {div2}
            {div3}
        </div>
        """

    html_content += "</body></html>"

    with open(filename, "w", encoding="utf-8") as f:
        f.write(html_content)
    print(f"Report generated: {os.path.abspath(filename)}")


def export_to_csv(companies_data):
    """Exports all data to a single CSV."""
    all_data = []
    for ticker, df in companies_data.items():
        if df is not None:
            df_copy = df.copy()
            df_copy['Ticker'] = ticker
            all_data.append(df_copy)

    if all_data:
        final_df = pd.concat(all_data)
        try:
            output_path = "master_data.csv"
            final_df.to_csv(output_path)
            print(f"Data exported to {output_path}")
        except PermissionError:
            output_path = "master_data_new.csv"
            final_df.to_csv(output_path)
            print(f"Data exported to {output_path} instead.")
    else:
        print("No data to export.")

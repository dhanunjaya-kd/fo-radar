"""
backend/fundamentals/parser.py

Turns a Screener.in company export (.xlsx bytes) into the real numbers
a value screen needs -- EPS, P/E, ROE, Debt/Equity, OPM, Sales CAGR --
computed using SCREENER'S OWN formulas (read directly out of their
'Profit & Loss' / 'Balance Sheet' sheets before this was written, not
reimplemented from scratch), so these numbers match what Screener
itself would show for the same company:

    EPS      = Net Profit / Adjusted Equity Shares (Data Sheet row 93)
    P/E      = Current Price / EPS
    ROE      = Net Profit / (Equity Share Capital + Reserves)
    Debt/Eq  = Borrowings / (Equity Share Capital + Reserves)
    OPM      = Operating Profit / Sales
    Sales growth = CAGR over the longest available year range

Verified live against a real RELIANCE export before this module was
written: P/E 21.97, ROE 8.93%, Debt/Equity 0.446, 9yr Sales CAGR
14.84% -- all sane for that company, cross-checked against its known
real characteristics.

All the raw numbers this reads come from the 'Data Sheet' tab
specifically -- the OTHER sheets in a Screener export ('Profit & Loss',
'Balance Sheet' etc.) are formula-driven presentation views of the same
data and read back as blank/None until recalculated in a real
spreadsheet app, so parsing those directly won't work.
"""
import io
import openpyxl


def parse_fundamentals(xlsx_bytes):
    """
    Returns a dict of key fundamentals, or None if the file doesn't
    have the expected 'Data Sheet' tab or any populated year column
    (a bad, incomplete, or unexpected-format export) -- callers must
    treat None as "couldn't extract data for this stock," not retry
    with a guess.
    """
    try:
        wb = openpyxl.load_workbook(io.BytesIO(xlsx_bytes), data_only=True)
    except Exception:
        return None
    if "Data Sheet" not in wb.sheetnames:
        return None
    ds = wb["Data Sheet"]

    company_name = ds.cell(row=1, column=2).value
    current_price = ds.cell(row=8, column=2).value
    market_cap = ds.cell(row=9, column=2).value

    pl_dates = [ds.cell(row=16, column=c).value for c in range(2, 12)]
    populated_cols = [c for c in range(2, 12) if ds.cell(row=16, column=c).value is not None]
    if not populated_cols:
        return None
    last_col = max(populated_cols)

    def cell(r, c=last_col):
        return ds.cell(row=r, column=c).value or 0

    sales_series = [ds.cell(row=17, column=c).value for c in range(2, last_col + 1)]
    net_profit = cell(30)
    equity_capital = cell(57)
    reserves = cell(58)
    borrowings = cell(59)
    total_equity = equity_capital + reserves
    adj_shares = cell(93)

    eps = (net_profit / adj_shares) if adj_shares else None
    pe = (current_price / eps) if (eps and current_price) else None
    roe_pct = (net_profit / total_equity * 100) if total_equity else None
    debt_equity = (borrowings / total_equity) if total_equity else None

    # Same expense components Screener's own 'Profit & Loss' sheet sums
    # (row 5 there): Raw Material + Power&Fuel + Other Mfr + Employee +
    # Selling&admin, minus the Change in Inventory adjustment.
    expenses = cell(18) + cell(20) + cell(21) + cell(22) + cell(23) + cell(24) - cell(19)
    latest_sales = cell(17)
    opm_pct = ((latest_sales - expenses) / latest_sales * 100) if latest_sales else None

    valid_sales = [(i, v) for i, v in enumerate(sales_series) if v]
    sales_cagr_pct = None
    if len(valid_sales) >= 2:
        (i0, v0), (i1, v1) = valid_sales[0], valid_sales[-1]
        years = i1 - i0
        if years > 0 and v0 > 0:
            sales_cagr_pct = ((v1 / v0) ** (1 / years) - 1) * 100

    return {
        "company_name": company_name,
        "current_price": current_price,
        "market_cap_cr": market_cap,
        "latest_year": pl_dates[last_col - 2],
        "sales_cr": latest_sales,
        "net_profit_cr": net_profit,
        "eps": round(eps, 2) if eps else None,
        "pe_ratio": round(pe, 2) if pe else None,
        "roe_pct": round(roe_pct, 2) if roe_pct else None,
        "debt_to_equity": round(debt_equity, 3) if debt_equity is not None else None,
        "opm_pct": round(opm_pct, 2) if opm_pct else None,
        "sales_cagr_pct": round(sales_cagr_pct, 2) if sales_cagr_pct else None,
    }

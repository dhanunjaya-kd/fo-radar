"""
Background data fetcher using Fyers API.

Historically dead code with a response-shape bug: fetch_option_chain()
assumed opt["ce"]["oi"] / opt["pe"]["oi"] nesting per strike, which Fyers
has never returned (its optionsChain is a FLAT list disambiguated by an
"option_type": "CE"/"PE" field). Rewritten below to reuse
screener.options_analytics.parse_option_chain(), which is unit-tested
against the real shape, so this now actually populates OptionChain
correctly if you choose to run it (e.g. from a management command or
Celery task) instead of / alongside the REST polling path in
screener/views.py and screener/tasks.py, which is what's live today.
"""
from datetime import datetime

from .client import FyersClient
from screener.models import Stock, StockSnapshot
from options.models import OptionChain
from screener.options_analytics import parse_option_chain, enrich_rows_with_iv_greeks


class FyersDataFetcher:
    def __init__(self):
        self.client = FyersClient()

    def fetch_all_quotes(self):
        """Fetch LTP for all F&O stocks."""
        stocks = Stock.objects.filter(is_fno=True)
        symbols = [f"NSE:{s.symbol}-EQ" for s in stocks]

        # Batch in groups of 50 (Fyers limit)
        all_data = []
        for i in range(0, len(symbols), 50):
            batch = symbols[i:i+50]
            resp = self.client.get_quotes(batch)
            if resp.get("s") == "ok":
                all_data.extend(resp.get("d", []))
        return all_data

    def fetch_option_chain(self, symbol, expiry, strikecount=10, days_to_expiry=3):
        """Fetch and save option chain. `expiry` must be a date (or
        'DD-MM-YYYY' string) for the OptionChain.expiry DateField."""
        resp = self.client.get_option_chain(symbol, strikecount=strikecount)
        if resp.get("s") != "ok":
            return resp

        parsed = parse_option_chain(resp)
        rows, spot = parsed['rows'], parsed['spot']
        if not rows or spot <= 0:
            return resp

        enrich_rows_with_iv_greeks(rows, spot, days_to_expiry)
        ce_oi_total = sum((r['ce']['oi'] if r['ce'] else 0) for r in rows)
        pe_oi_total = sum((r['pe']['oi'] if r['pe'] else 0) for r in rows)
        pcr = round(pe_oi_total / ce_oi_total, 2) if ce_oi_total else 1.0

        expiry_date = datetime.strptime(expiry, "%d-%m-%Y").date() if isinstance(expiry, str) else expiry
        stock = Stock.objects.get(symbol=symbol.replace("NSE:", "").replace("-EQ", ""))

        for r in rows:
            ce, pe = r.get('ce') or {}, r.get('pe') or {}
            OptionChain.objects.create(
                stock=stock, expiry=expiry_date, strike=r['strike'],
                ce_ltp=ce.get('ltp', 0), ce_oi=ce.get('oi', 0),
                ce_oi_chg=ce.get('oi_chg', 0), ce_iv=ce.get('iv') or 0,
                pe_ltp=pe.get('ltp', 0), pe_oi=pe.get('oi', 0),
                pe_oi_chg=pe.get('oi_chg', 0), pe_iv=pe.get('iv') or 0,
                pcr=pcr,
            )
        return resp

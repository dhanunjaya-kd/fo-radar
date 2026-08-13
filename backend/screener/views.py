import os
import time
import threading
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
import pandas as pd
import numpy as np
from rest_framework.views import APIView
from rest_framework.response import Response

import math

def safe_json(val):
    """Kill NaN/Inf before JSON sees it"""
    if val is None:
        return None
    if isinstance(val, float):
        if math.isnan(val) or math.isinf(val):
            return None
    return val

try:
    from .fyers_client import is_authenticated, get_quotes, get_option_analytics, get_history, CLIENT_ID
except ImportError:
    is_authenticated = lambda: False
    get_quotes = lambda x: None
    get_option_analytics = lambda symbol, strikecount=10: None
    get_history = lambda symbol, resolution="D", range_from=None, range_to=None: None
    CLIENT_ID = ""

try:
    from .options_analytics import estimate_option_premium
except ImportError:
    estimate_option_premium = lambda spot, strike, days, iv, opt_type, risk_free_rate=0.07: None

# ============================================================
# CACHES
# ============================================================
_stock_cache = {}
_index_cache = {}
_signal_cache = []
_tech_cache = {}
_cache_lock = threading.Lock()
_last_fetch = 0
CACHE_TTL = 60

# ============================================================
# STOCKS
# ============================================================
# FNO_STOCKS/SECTORS replaced this round -- previous list (201 symbols,
# built from a mix of a live-verified batch + general domain knowledge)
# checked programmatically against a real, authoritative F&O list the
# user provided directly (208 symbols, includes real F&O lot sizes and
# NEW-addition flags). Found 53 real symbols missing entirely (several
# of them recent F&O additions: BAJAJHLDNG, COCHINSHIP, FORCEMOT,
# GODFRYPHLP, GVT&D, HYUNDAI, MOTILALOFS, NAM-INDIA, PREMIERENE, RADICO,
# SWIGGY, VMM, WAAREEENER) and 46 symbols that were in the old list but
# NOT on this authoritative one (likely stale/no-longer-eligible, or
# scope mismatches from the earlier domain-knowledge-based additions).
# Replaced entirely with the user-provided 208, aligning to it as the
# source of truth rather than keeping a fuzzy union of both. One
# correction made to the source: it listed "LTM" for LTIMindtree, which
# does not match the real NSE ticker (LTIM, already well-established in
# this project) -- treated as a likely typo in the source and corrected
# rather than added as a second, wrong entry.
FNO_STOCKS = [
    "360ONE", "ABB", "ABCAPITAL", "ADANIENSOL", "ADANIENT", "ADANIGREEN",
    "ADANIPORTS", "ADANIPOWER", "ALKEM", "AMBER", "AMBUJACEM", "ANGELONE",
    "APLAPOLLO", "APOLLOHOSP", "ASHOKLEY", "ASIANPAINT", "ASTRAL", "AUBANK",
    "AUROPHARMA", "AXISBANK", "BAJAJ-AUTO", "BAJAJFINSV", "BAJAJHLDNG",
    "BAJFINANCE", "BANDHANBNK", "BANKBARODA", "BANKINDIA", "BDL", "BEL",
    "BHARATFORG", "BHARTIARTL", "BHEL", "BIOCON", "BLUESTARCO", "BOSCHLTD",
    "BPCL", "BRITANNIA", "BSE", "CAMS", "CANBK", "CDSL", "CGPOWER",
    "CHOLAFIN", "CIPLA", "COALINDIA", "COCHINSHIP", "COFORGE", "COLPAL",
    "CONCOR", "CROMPTON", "CUMMINSIND", "DABUR", "DALBHARAT", "DELHIVERY",
    "DIVISLAB", "DIXON", "DLF", "DMART", "DRREDDY", "EICHERMOT", "ETERNAL",
    "FEDERALBNK", "FORCEMOT", "FORTIS", "GAIL", "GVT&D", "GLENMARK",
    "GMRAIRPORT", "GODFRYPHLP", "GODREJCP", "GODREJPROP", "GRASIM", "HAL",
    "HAVELLS", "HCLTECH", "HDFCAMC", "HDFCBANK", "HDFCLIFE", "HEROMOTOCO",
    "HINDALCO", "HINDPETRO", "HINDUNILVR", "HINDZINC", "HYUNDAI", "ICICIBANK",
    "ICICIGI", "ICICIPRULI", "IDEA", "IDFCFIRSTB", "IEX", "INDHOTEL",
    "INDIANB", "INDIGO", "INDUSINDBK", "INDUSTOWER", "INFY", "INOXWIND",
    "IOC", "IREDA", "IRFC", "ITC", "JINDALSTEL", "JIOFIN", "JSWENERGY",
    "JSWSTEEL", "JUBLFOOD", "KALYANKJIL", "KAYNES", "KEI", "KFINTECH",
    "KOTAKBANK", "KPITTECH", "LAURUSLABS", "LICHSGFIN", "LICI", "LODHA", "LT",
    "LTF", "LTIM", "LUPIN", "M&M", "MANAPPURAM", "MANKIND", "MARICO",
    "MARUTI", "MAXHEALTH", "MAZDOCK", "MCX", "MFSL", "MOTHERSON",
    "MOTILALOFS", "MPHASIS", "MUTHOOTFIN", "NAM-INDIA", "NATIONALUM",
    "NAUKRI", "NBCC", "NESTLEIND", "NHPC", "NMDC", "NTPC", "NYKAA",
    "OBEROIRLTY", "OFSS", "OIL", "ONGC", "PAGEIND", "PATANJALI", "PAYTM",
    "PERSISTENT", "PETRONET", "PFC", "PGEL", "PHOENIXLTD", "PIDILITIND",
    "PIIND", "PNB", "PNBHOUSING", "POLICYBZR", "POLYCAB", "POWERGRID",
    "POWERINDIA", "PREMIERENE", "PRESTIGE", "RADICO", "RBLBANK", "RECLTD",
    "RELIANCE", "RVNL", "SAIL", "SBICARD", "SBILIFE", "SBIN", "SHREECEM",
    "SHRIRAMFIN", "SIEMENS", "SOLARINDS", "SONACOMS", "SRF", "SUNPHARMA",
    "SUPREMEIND", "SUZLON", "SWIGGY", "TATACONSUM", "TATAELXSI", "TMPV",
    "TATAPOWER", "TATASTEEL", "TCS", "TECHM", "TIINDIA", "TITAN",
    "TORNTPHARM", "TRENT", "TVSMOTOR", "ULTRACEMCO", "UNIONBANK", "UNITDSPR",
    "UNOMINDA", "UPL", "VBL", "VEDL", "VMM", "VOLTAS", "WAAREEENER", "WIPRO",
    "YESBANK", "ZYDUSLIFE",
]

SECTORS = {
    "360ONE": "Finance", "ABB": "Capital Goods", "ABCAPITAL": "Finance",
    "ADANIENSOL": "Power", "ADANIENT": "Conglomerate", "ADANIGREEN": "Power",
    "ADANIPORTS": "Logistics", "ADANIPOWER": "Power", "ALKEM": "Pharma",
    "AMBER": "Consumer Durables", "AMBUJACEM": "Cement", "ANGELONE": "Finance",
    "APLAPOLLO": "Metals", "APOLLOHOSP": "Healthcare", "ASHOKLEY": "Auto",
    "ASIANPAINT": "Paints", "ASTRAL": "Plastics", "AUBANK": "Banking", "AUROPHARMA": "Pharma",
    "AXISBANK": "Banking", "BAJAJ-AUTO": "Auto", "BAJAJFINSV": "Finance",
    "BAJAJHLDNG": "Finance", "BAJFINANCE": "Finance", "BANDHANBNK": "Banking",
    "BANKBARODA": "Banking", "BANKINDIA": "Banking", "BDL": "Defence", "BEL": "Defence",
    "BHARATFORG": "Auto Anc", "BHARTIARTL": "Telecom", "BHEL": "Capital Goods",
    "BIOCON": "Pharma", "BLUESTARCO": "Consumer Durables", "BOSCHLTD": "Auto Anc",
    "BPCL": "Energy", "BRITANNIA": "FMCG", "BSE": "Finance", "CAMS": "Finance",
    "CANBK": "Banking", "CDSL": "Finance", "CGPOWER": "Capital Goods", "CHOLAFIN": "Finance",
    "CIPLA": "Pharma", "COALINDIA": "Mining", "COCHINSHIP": "Defence", "COFORGE": "IT",
    "COLPAL": "FMCG", "CONCOR": "Logistics", "CROMPTON": "Consumer Durables",
    "CUMMINSIND": "Capital Goods", "DABUR": "FMCG", "DALBHARAT": "Cement",
    "DELHIVERY": "Logistics", "DIVISLAB": "Pharma", "DIXON": "Consumer Durables",
    "DLF": "Realty", "DMART": "Retail", "DRREDDY": "Pharma", "EICHERMOT": "Auto",
    "ETERNAL": "New Age Tech", "FEDERALBNK": "Banking", "FORCEMOT": "Auto",
    "FORTIS": "Healthcare", "GAIL": "Energy", "GVT&D": "Capital Goods", "GLENMARK": "Pharma",
    "GMRAIRPORT": "Infra", "GODFRYPHLP": "FMCG", "GODREJCP": "FMCG", "GODREJPROP": "Realty",
    "GRASIM": "Cement", "HAL": "Defence", "HAVELLS": "Consumer Durables", "HCLTECH": "IT",
    "HDFCAMC": "Finance", "HDFCBANK": "Banking", "HDFCLIFE": "Insurance",
    "HEROMOTOCO": "Auto", "HINDALCO": "Metals", "HINDPETRO": "Energy", "HINDUNILVR": "FMCG",
    "HINDZINC": "Metals", "HYUNDAI": "Auto", "ICICIBANK": "Banking", "ICICIGI": "Insurance",
    "ICICIPRULI": "Insurance", "IDEA": "Telecom", "IDFCFIRSTB": "Banking", "IEX": "Power",
    "INDHOTEL": "Tourism", "INDIANB": "Banking", "INDIGO": "Aviation",
    "INDUSINDBK": "Banking", "INDUSTOWER": "Telecom", "INFY": "IT", "INOXWIND": "Power",
    "IOC": "Energy", "IREDA": "Finance", "IRFC": "Finance", "ITC": "FMCG",
    "JINDALSTEL": "Metals", "JIOFIN": "Finance", "JSWENERGY": "Power", "JSWSTEEL": "Metals",
    "JUBLFOOD": "Food", "KALYANKJIL": "Jewellery", "KAYNES": "Electronics",
    "KEI": "Capital Goods", "KFINTECH": "Finance", "KOTAKBANK": "Banking", "KPITTECH": "IT",
    "LAURUSLABS": "Pharma", "LICHSGFIN": "Finance", "LICI": "Insurance", "LODHA": "Realty",
    "LT": "Infra", "LTF": "Finance", "LTIM": "IT", "LUPIN": "Pharma", "M&M": "Auto",
    "MANAPPURAM": "Finance", "MANKIND": "Pharma", "MARICO": "FMCG", "MARUTI": "Auto",
    "MAXHEALTH": "Healthcare", "MAZDOCK": "Defence", "MCX": "Finance", "MFSL": "Insurance",
    "MOTHERSON": "Auto Anc", "MOTILALOFS": "Finance", "MPHASIS": "IT",
    "MUTHOOTFIN": "Finance", "NAM-INDIA": "Finance", "NATIONALUM": "Metals",
    "NAUKRI": "E-Commerce", "NBCC": "Infra", "NESTLEIND": "FMCG", "NHPC": "Power",
    "NMDC": "Mining", "NTPC": "Power", "NYKAA": "E-Commerce", "OBEROIRLTY": "Realty",
    "OFSS": "IT", "OIL": "Energy", "ONGC": "Energy", "PAGEIND": "Textile",
    "PATANJALI": "FMCG", "PAYTM": "Fintech", "PERSISTENT": "IT", "PETRONET": "Energy",
    "PFC": "Finance", "PGEL": "Electronics", "PHOENIXLTD": "Realty",
    "PIDILITIND": "Chemicals", "PIIND": "Agro", "PNB": "Banking", "PNBHOUSING": "Finance",
    "POLICYBZR": "Fintech", "POLYCAB": "Consumer Durables", "POWERGRID": "Power",
    "POWERINDIA": "Capital Goods", "PREMIERENE": "Power", "PRESTIGE": "Realty",
    "RADICO": "Alcohol", "RBLBANK": "Banking", "RECLTD": "Finance", "RELIANCE": "Energy",
    "RVNL": "Infra", "SAIL": "Metals", "SBICARD": "Finance", "SBILIFE": "Insurance",
    "SBIN": "Banking", "SHREECEM": "Cement", "SHRIRAMFIN": "Finance",
    "SIEMENS": "Capital Goods", "SOLARINDS": "Chemicals", "SONACOMS": "Auto Anc",
    "SRF": "Chemicals", "SUNPHARMA": "Pharma", "SUPREMEIND": "Plastics", "SUZLON": "Power",
    "SWIGGY": "New Age Tech", "TATACONSUM": "FMCG", "TATAELXSI": "IT", "TMPV": "Auto",
    "TATAPOWER": "Power", "TATASTEEL": "Metals", "TCS": "IT", "TECHM": "IT",
    "TIINDIA": "Auto Anc", "TITAN": "Consumer Durables", "TORNTPHARM": "Pharma",
    "TRENT": "Retail", "TVSMOTOR": "Auto", "ULTRACEMCO": "Cement", "UNIONBANK": "Banking",
    "UNITDSPR": "Beverages", "UNOMINDA": "Auto Anc", "UPL": "Agro", "VBL": "Beverages",
    "VEDL": "Metals", "VMM": "Retail", "VOLTAS": "Consumer Durables", "WAAREEENER": "Power",
    "WIPRO": "IT", "YESBANK": "Banking", "ZYDUSLIFE": "Pharma",
}


# ============================================================
# INDEX + STOCK DATA (Fyers ONLY -- no Yahoo/yfinance involved at all)
# ============================================================

FYERS_INDEX_SYMBOLS = {
    "NIFTY 50": "NSE:NIFTY50-INDEX",
    "BANKNIFTY": "NSE:NIFTYBANK-INDEX",
    "INDIA VIX": "NSE:INDIAVIX-INDEX",
}


def _fetch_index(name, fallbacks=None):
    """Index quote (NIFTY/BANKNIFTY/VIX) via Fyers only. No yfinance
    fallback -- if Fyers isn't authenticated or doesn't return this
    index, we return a zeroed placeholder instead of quietly pulling
    from Yahoo."""
    fyers_symbol = FYERS_INDEX_SYMBOLS.get(name)
    if fyers_symbol and is_authenticated():
        try:
            resp = get_quotes([fyers_symbol])
            if resp and resp.get('s') == 'ok':
                for item in resp.get('d', []):
                    if item.get('s') != 'ok':
                        continue
                    v = item.get('v', {}) or {}
                    price = v.get('lp')
                    if price and not (isinstance(price, float) and math.isnan(price)):
                        return {
                            'price': round(price, 2),
                            'change': round(v.get('ch', 0) or 0, 2),
                            'change_percent': round(v.get('chp', 0) or 0, 2),
                        }
        except Exception as e:
            print(f"[Fyers] Index fetch error {name}: {e}")
    else:
        print(f"[Fyers] Not authenticated -- skipping index {name} (no Yahoo fallback)")
    return {'price': 0, 'change': 0, 'change_percent': 0}


def _fetch_all_quotes_fyers(symbols):
    """
    Batch-fetch current price/change/volume for every symbol via Fyers
    quotes (up to 50 symbols per call -- Fyers' documented batch limit),
    instead of one yfinance call per stock. This is the PRIMARY price
    source now. Returns {symbol: stock_dict} for whatever came back OK;
    silently drops anything that failed or came back with a NaN/zero
    price rather than raising.
    """
    results = {}
    fyers_symbols = [f"NSE:{s}-EQ" for s in symbols]
    for i in range(0, len(fyers_symbols), 50):
        batch = fyers_symbols[i:i + 50]
        try:
            resp = get_quotes(batch)
        except Exception as e:
            print(f"[Fyers] Quotes batch error: {e}")
            continue
        if not resp or resp.get('s') != 'ok':
            continue
        for item in resp.get('d', []):
            if item.get('s') != 'ok':
                continue
            v = item.get('v', {}) or {}
            sym = (item.get('n') or '').replace('NSE:', '').replace('-EQ', '')
            price = v.get('lp')
            if not sym or price is None or price <= 0 or (isinstance(price, float) and math.isnan(price)):
                continue
            results[sym] = {
                'symbol': sym, 'name': sym,
                'price': round(price, 2),
                'change': round(v.get('ch', 0) or 0, 2),
                'change_percent': round(v.get('chp', 0) or 0, 2),
                'open': v.get('open_price', price) or price,
                'high': v.get('high_price', price) or price,
                'low': v.get('low_price', price) or price,
                'close': round(price, 2),
                'volume': int(v.get('volume') or 0),
                'sector': SECTORS.get(sym, 'Unknown'),
            }
    return results


def _fetch_all_stocks(symbols):
    """
    Fyers ONLY -- batched quotes, up to 50 symbols per call. No Yahoo/
    yfinance fallback at all, per explicit request: if Fyers isn't
    authenticated, this cycle simply returns whatever it has (which may
    be nothing) rather than quietly pulling from Yahoo. This is also why
    "possibly delisted" errors are gone -- Fyers uses NSE's current live
    symbol list directly, so a correctly-named stock never hits that
    problem the way Yahoo's mirror did.
    """
    if not is_authenticated():
        print("[Scanner] Fyers not authenticated -- no data this cycle (no Yahoo fallback)")
        return {}
    return _fetch_all_quotes_fyers(symbols)


def _compute_indicators(close, high, low, volume):
    """
    Pure indicator math -- takes pandas Series (Close/High/Low/Volume),
    returns the same dict _calc_tech always has. Split out from the fetch
    logic so it's independently testable regardless of data source.
    """
    if len(close) < 20:
        return None

    # RSI (14)
    delta = close.diff()
    gain = delta.where(delta > 0, 0).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    rsi = float(100 - (100 / (1 + rs.iloc[-1])))

    # VWAP
    typical = (high + low + close) / 3
    vwap = float((typical * volume).cumsum().iloc[-1] / volume.cumsum().iloc[-1])

    # MACD
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd = float(ema12.iloc[-1] - ema26.iloc[-1])

    # ATR (14)
    tr1 = high - low
    tr2 = abs(high - close.shift())
    tr3 = abs(low - close.shift())
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = float(tr.rolling(window=14).mean().iloc[-1])

    # ADX (14) -- trend STRENGTH (not direction), via Wilder's smoothing
    period = 14
    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
    minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0)
    tr_smooth = tr.ewm(com=period - 1, adjust=False).mean().replace(0, np.nan)
    plus_di = 100 * (plus_dm.ewm(com=period - 1, adjust=False).mean() / tr_smooth)
    minus_di = 100 * (minus_dm.ewm(com=period - 1, adjust=False).mean() / tr_smooth)
    di_sum = (plus_di + minus_di).replace(0, np.nan)
    dx = 100 * (plus_di - minus_di).abs() / di_sum
    adx_val = dx.ewm(com=period - 1, adjust=False).mean().iloc[-1]
    adx = float(adx_val) if pd.notna(adx_val) else 0.0

    # Volume average (20)
    vol_avg = float(volume.rolling(window=20).mean().iloc[-1])

    # Support/Resistance (20-day)
    resistance = float(high.rolling(window=20).max().iloc[-1])
    support = float(low.rolling(window=20).min().iloc[-1])

    # Historical volatility (annualized)
    returns = close.pct_change().dropna()
    hist_vol = float(returns.std() * np.sqrt(252) * 100) if len(returns) else 20.0

    out = {
        'rsi': rsi, 'vwap': vwap, 'macd': macd, 'atr': atr, 'adx': adx,
        'volume_avg': vol_avg, 'resistance': resistance, 'support': support,
        'hist_vol': hist_vol,
    }
    # Guard the whole batch: if anything came out NaN (thin/gappy history),
    # treat this stock as unscoreable this cycle rather than let a NaN
    # leak into scoring/quantity math downstream.
    if any(isinstance(v, float) and math.isnan(v) for v in out.values()):
        return None
    return {k: round(v, 2) for k, v in out.items()}


def _fyers_history_df(symbol, days=100):
    """~`days` calendar days of daily candles from Fyers, shaped into a
    DataFrame with the same column names yfinance used, so
    _compute_indicators doesn't care which source it came from."""
    range_to = datetime.now().date()
    range_from = range_to - timedelta(days=days)
    try:
        resp = get_history(f"NSE:{symbol}-EQ", resolution="D",
                            range_from=str(range_from), range_to=str(range_to))
    except Exception as e:
        print(f"[Fyers] History error {symbol}: {e}")
        return None
    if not resp or resp.get('s') != 'ok' or not resp.get('candles'):
        return None
    df = pd.DataFrame(resp['candles'], columns=['ts', 'Open', 'High', 'Low', 'Close', 'Volume'])
    return df


def _calc_tech(symbol):
    """
    Technical indicators for a stock, sourced from Fyers only. No Yahoo/
    yfinance fallback -- if Fyers isn't authenticated or has no usable
    history for this symbol, returns None (caller skips the stock for
    this cycle) rather than pulling from Yahoo.
    """
    try:
        if not is_authenticated():
            return None
        df = _fyers_history_df(symbol, days=100)
        if df is None or len(df) < 20:
            return None
        return _compute_indicators(df['Close'], df['High'], df['Low'], df['Volume'])
    except Exception as e:
        print(f"Tech calc error {symbol}: {e}")
        return None


# ============================================================
# BACKGROUND WORKER
# ============================================================

def _build_all():
    """Fetch everything: indices, stocks, signals. Cache all."""
    global _stock_cache, _index_cache, _signal_cache, _tech_cache, _last_fetch
    
    # 1. Fetch indices FIRST (most important)
    nifty = _fetch_index("NIFTY 50", ["^NSEI", "NSEI.NS", "^NSEI.NS"])
    bank = _fetch_index("BANKNIFTY", ["^NSEBANK", "NSEBANK.NS", "NIFTY_BANK.NS", "^NSEBANK.NS"])
    vix = _fetch_index("INDIA VIX", ["^INDIAVIX", "INDIAVIX.NS", "^INDIAVIX.NS"])
    
    with _cache_lock:
        _index_cache = {
            "nifty50": nifty,
            "banknifty": bank,
            "india_vix": vix,
        }
    
    # 2. Fetch all stock prices -- Fyers only, no Yahoo involved at all.
    results = _fetch_all_stocks(FNO_STOCKS)
    
    with _cache_lock:
        _stock_cache = results
        _last_fetch = time.time()
    
    # 3. PCR -- this used to be declines/advances among the scanned stock
    # universe (an advance-decline ratio, a completely different market
    # breadth statistic) mislabeled as "PCR". That's why it never matched
    # the real options Put-Call Ratio shown elsewhere (e.g. NIFTY's real
    # PCR sitting around 0.99-1.01 while this said 2.27-3.08) -- it was
    # never actually PCR. Now pulls NIFTY's real PCR from its live option
    # chain, which is what "market PCR" conventionally means.
    pcr_proxy, pcr_sentiment = None, "N/A"
    if is_authenticated():
        try:
            nifty_oi = get_option_analytics("NSE:NIFTY50-INDEX", strikecount=10)
            if nifty_oi and nifty_oi.get('pcr') is not None:
                pcr_proxy = nifty_oi['pcr']
                pcr_sentiment = "Bearish" if pcr_proxy < 0.95 else "Bullish" if pcr_proxy > 1.05 else "Neutral"
        except Exception as e:
            print(f"[PCR] NIFTY option chain fetch failed: {e}")
    
    with _cache_lock:
        _index_cache["pcr"] = {"value": pcr_proxy, "sentiment": pcr_sentiment}
    
    # 4. Build signals from top movers
    movers = sorted(results.values(), key=lambda x: abs(x.get('change_percent', 0)), reverse=True)[:30]
    signals = []
    techs = {}
    
    for stock in movers:
        sym = stock['symbol']
        tech = _calc_tech(sym)
        if not tech:
            continue
        techs[sym] = tech
        
        price = stock['price']
        # This was 'if price <= 0: continue' -- looks like it catches bad
        # data, but NaN fails EVERY comparison in Python (nan <= 0 is
        # False, not True), so a NaN price slipped straight through this
        # guard and crashed later at qty = int(50000 / price) with
        # "cannot convert float NaN to integer". math.isnan() is required
        # here specifically because <= can't catch it.
        if price <= 0 or math.isnan(price):
            continue
        
        rsi = tech['rsi']
        macd = tech['macd']
        vwap = tech['vwap']
        adx = tech.get('adx', 0)
        vol = stock.get('volume', 0)
        vol_avg = tech.get('volume_avg', 1)

        # Same NaN issue can show up in any of the indicators (e.g. a
        # recently-listed stock with under 14 days of history won't have
        # a real ATR/ADX yet). Treat that stock as unscoreable for this
        # cycle instead of letting NaN quietly poison the score/quantity
        # math further down.
        if any(isinstance(v, float) and math.isnan(v) for v in (rsi, macd, vwap, adx, tech.get('atr', 0))):
            continue
        
        # Rebalanced to make room for ADX -- a stock can look great on
        # RSI/volume/VWAP/MACD and still be going nowhere (ADX < 20 = no
        # real trend, just noise). This was advertised in the frontend
        # banner ("ADX >= 25") for a long time without ever being checked.
        score = 0
        if 40 <= rsi <= 65: score += 15
        if vol >= vol_avg * 1.5: score += 15
        if adx >= 25: score += 20  # genuine trend strength, not chop

        # Directional confirmation -- this used to be two separate checks
        # ('price > vwap': +15, 'macd > 0': +15) that only ever rewarded
        # the BULLISH combination. A genuinely clean bearish setup
        # (price < vwap AND macd < 0) scored zero here no matter how
        # strong it was, so SELL/PE setups needed a near-perfect RSI +
        # Volume + ADX just to scrape past the gate -- which is why
        # almost everything that qualified was a BUY/CE signal. Both
        # directions now score the same for genuine internal agreement.
        bullish_aligned = price > vwap and macd > 0
        bearish_aligned = price < vwap and macd < 0
        if bullish_aligned or bearish_aligned:
            score += 30
        
        if score < 50:
            continue
        
        action = "BUY" if bullish_aligned else "SELL"
        atr = tech['atr']
        # These used to be atr*2/3/4 for targets and atr*1.5 for SL -- that's
        # sized for a multi-day swing, not an intraday option trade. One ATR
        # is a realistic estimate of a single session's full range, so
        # targets here are fractions of ONE session's move, not multiples of
        # it. (These are the STOCK-side move sizes; converted to actual
        # option-premium entry/SL/target further down via the contract's
        # own delta -- see below.)
        if action == "BUY":
            stock_sl = round(price - atr * 0.4, 2)
            stock_t1 = round(price + atr * 0.5, 2)
            stock_t2 = round(price + atr * 0.8, 2)
            stock_t3 = round(price + atr * 1.2, 2)
        else:
            stock_sl = round(price + atr * 0.4, 2)
            stock_t1 = round(price - atr * 0.5, 2)
            stock_t2 = round(price - atr * 0.8, 2)
            stock_t3 = round(price - atr * 1.2, 2)
        
        strike = round(price / (100 if price >= 10000 else 50 if price >= 2000 else 20 if price >= 500 else 10)) * (100 if price >= 10000 else 50 if price >= 2000 else 20 if price >= 500 else 10)
        opt_side = 'CE' if action == 'BUY' else 'PE'

        # --- REAL Fyers option-chain data (only for symbols that already
        # cleared the technical filter, to keep API call volume sane) ---
        # This used to be hardcoded/random. If Fyers isn't authenticated or
        # the call fails for any reason, we fall back to price-based
        # technical levels and mark live_oi False -- we never substitute a
        # fake OI/PCR/max-pain number again.
        oi = None
        if is_authenticated():
            try:
                oi = get_option_analytics(f"NSE:{sym}-EQ", strikecount=10)
            except Exception as e:
                print(f"[OI] {sym} fetch failed: {e}")
                oi = None

        # --- OI-based quality scoring ---
        # This used to not exist: 'grade' came only from the 4 price/volume
        # checks above (max 70 points), so grades A (>=90) and B (>=80)
        # were mathematically unreachable no matter what. Real quality --
        # does the options market actually agree with this price setup --
        # now supplies the missing points, so a stock only reaches A/B when
        # live OI genuinely confirms the direction, not just on chart
        # pattern alone.
        oi_confirmation = "NO_DATA"
        oi_adjustment = 0
        pattern = None

        if oi:
            buildup = oi.get('oi_buildup') or ''
            bullish_oi = 'PE writing dominant' in buildup
            bearish_oi = 'CE writing dominant' in buildup

            if action == 'BUY' and bullish_oi:
                oi_confirmation, oi_adjustment = "CONFIRMED", 20
            elif action == 'SELL' and bearish_oi:
                oi_confirmation, oi_adjustment = "CONFIRMED", 20
            elif (action == 'BUY' and bearish_oi) or (action == 'SELL' and bullish_oi):
                # CONFLICT used to just be a -15 penalty, which some
                # technically-strong setups could still survive (3 showed
                # up in one day's real log despite the penalty). Checked
                # against actual logged outcomes: the one CONFLICT signal
                # that had resolved by review time hit SL, not target --
                # small sample, but directionally consistent with the
                # obvious reasoning: if the real options market is
                # actively positioned AGAINST your technical direction,
                # that's a materially weaker bet regardless of how good
                # the chart looks. Excluded entirely now, same principle
                # as the confirmed-live-chain requirement -- not just
                # scored down, not shown as a trade recommendation at all.
                continue
            else:
                oi_confirmation, oi_adjustment = "NEUTRAL", 0

            # PCR as a secondary, smaller confirmation -- classic reading is
            # PCR > 1 = more puts written = bullish support building, and
            # PCR < 0.7 = more calls written = bearish resistance building.
            pcr_val = oi.get('pcr')
            if pcr_val is not None:
                if action == 'BUY' and pcr_val > 1.0:
                    oi_adjustment += 5
                elif action == 'SELL' and pcr_val < 0.7:
                    oi_adjustment += 5

            # Max-pain pinning: with days_to_expiry small and spot already
            # within ~1.5% of max pain, price tends to gravitate there
            # instead of trending -- worth flagging even though it doesn't
            # change the score.
            mp_dist = oi.get('max_pain_dist_pct')
            if mp_dist is not None and abs(mp_dist) < 1.5:
                pattern = 'Range-Pinned'
            elif oi_confirmation == 'CONFIRMED':
                pattern = 'OI-Confirmed Momentum'

        total_score = max(0, min(100, score + oi_adjustment))
        grade = 'A+' if total_score >= 95 else 'A' if total_score >= 85 else 'B' if total_score >= 75 else 'C' if total_score >= 60 else 'D'

        if oi:
            strike = oi.get('atm_strike') or strike
            greeks = (oi.get('greeks') or {}).get(opt_side, {})
            signal_extra = {
                "ce_oi": oi.get('ce_oi'), "pe_oi": oi.get('pe_oi'),
                "ce_oi_chg": oi.get('ce_oi_chg'), "pe_oi_chg": oi.get('pe_oi_chg'),
                "pcr": oi.get('pcr'), "max_pain": oi.get('max_pain'),
                "iv": oi.get('iv') if oi.get('iv') is not None else tech.get('hist_vol', 20),
                "resistance": oi.get('resistance') or tech.get('resistance', round(price * 1.05, 2)),
                "support": oi.get('support') or tech.get('support', round(price * 0.95, 2)),
                "oi_buildup": oi.get('oi_buildup'),
                "max_pain_dist_pct": oi.get('max_pain_dist_pct'),
                "delta": greeks.get('delta'), "theta": greeks.get('theta'),
                "vega": greeks.get('vega'), "gamma": greeks.get('gamma'),
                "live_oi": True,
            }
        else:
            # Honest fallback: price-action support/resistance and
            # historical volatility instead of options data. None (not 0,
            # not 1.0) for anything we genuinely cannot know without a
            # live option chain, so the frontend can show "--" instead of
            # a confident-looking fake number.
            signal_extra = {
                "ce_oi": None, "pe_oi": None, "ce_oi_chg": None, "pe_oi_chg": None,
                "pcr": None, "max_pain": None,
                "iv": tech.get('hist_vol', 20),
                "resistance": tech.get('resistance', round(price * 1.05, 2)),
                "support": tech.get('support', round(price * 0.95, 2)),
                "oi_buildup": None,
                "max_pain_dist_pct": None,
                "delta": None, "theta": None, "vega": None, "gamma": None,
                "live_oi": False,
            }

        # --- Reuse an already-locked trade plan if one exists ---
        # This used to recompute entry/SL/target1-3 from scratch every
        # single cycle for a stock that was ALREADY an active signal --
        # since price/ATR/premium all drift throughout the day, the same
        # stock could show SL=10 one cycle and SL=5 the next, which is
        # useless to actually trade off of. A trade plan has to hold
        # still once it's shown to you. If this (symbol, action) is
        # already being tracked today (still active, or within the
        # cooldown/reactivation window), reuse its exact frozen numbers
        # instead of deriving new ones. Only a genuinely new signal (or
        # one whose earlier plan already resolved via SL/Target 3) gets
        # fresh numbers computed below.
        from .excel_logger import get_locked_plan
        locked = get_locked_plan(sym, action)

        if locked:
            entry, strike = locked['entry'], locked['strike'] or strike
            sl = locked['sl']
            t1, t2, t3 = locked['target1'], locked['target2'], locked['target3']
            qty = locked['quantity'] or max(1, int(50000 / entry)) if entry else 1
            rr = locked['risk_reward'] or 1.5
            option_symbol = locked['option_symbol']
        else:
            # --- Convert the stock-side move into REAL option-premium terms ---
            # This used to just reuse the STOCK price as entry/SL/target (e.g.
            # "Entry ₹1,141.20" for what's supposed to be an options trade) --
            # a stock moving ₹15 does not mean the option premium also moves
            # ₹15. Translate the stock-side move into a premium move using the
            # contract's own delta.
            #
            # IMPORTANT CHANGE: this used to fall back to a Black-Scholes
            # ESTIMATE (using historical volatility as a stand-in for IV)
            # whenever Fyers didn't return a live option chain, and presented
            # that estimate exactly the same way as a real quote -- "SELL PE
            # — ₹400 STRIKE, Entry ₹3.90" with no way to tell it wasn't a
            # real, tradeable price. That's what produced confident-looking
            # recommendations on stocks where no live chain could be
            # confirmed. A trade recommendation now REQUIRES a real, live
            # Fyers option chain for this exact strike -- no chain, no
            # signal, full stop. (estimate_option_premium() is still in
            # options_analytics.py and still used elsewhere -- e.g. the OI
            # Analytics tab's fallback display -- just not for something that
            # tells you to place a trade.)
            premium_entry = None
            delta_for_premium = None
            option_symbol = None

            if oi:
                row = next((r for r in oi.get('rows', []) if r['strike'] == strike), None)
                leg = (row or {}).get(opt_side.lower()) if row else None
                if leg and leg.get('ltp'):
                    premium_entry = leg['ltp']
                    delta_for_premium = leg.get('delta', signal_extra.get('delta'))
                    option_symbol = leg.get('symbol') or None

            if premium_entry is None or delta_for_premium is None:
                # No confirmed live option chain for this exact strike --
                # skip. Don't invent a premium, and don't recommend a trade
                # we can't confirm is actually tradeable.
                continue

            d = max(abs(delta_for_premium), 0.05)  # floor so deep OTM deltas don't zero out the math
            # SL loses MORE than delta alone implies -- theta/gamma work
            # against you on an adverse move too, so weight it up rather than
            # a straight delta-only translation, which would understate real
            # option risk.
            entry = round(premium_entry, 2)
            sl = round(max(0.05, premium_entry - d * abs(price - stock_sl) * 1.4), 2)
            t1 = round(premium_entry + d * abs(stock_t1 - price), 2)
            t2 = round(premium_entry + d * abs(stock_t2 - price), 2)
            t3 = round(premium_entry + d * abs(stock_t3 - price), 2)

            qty = max(1, int(50000 / entry))
            risk = abs(entry - sl)
            rr = round(abs(t1 - entry) / risk, 2) if risk else 1.5

        signals.append({
            "symbol": sym, "name": sym, "price": price,
            "change": stock['change'], "change_percent": stock['change_percent'],
            "grade": grade, "confidence": f"{total_score}%",
            "technical_score": score, "oi_adjustment": oi_adjustment,
            "rsi": rsi, "adx": round(adx, 1),
            "oi_confirmation": oi_confirmation, "pattern": pattern,
            "sector": stock["sector"], "signal_type": "SNIPER",
            "action": action, "entry": entry, "quantity": qty,
            "sl": sl, "target1": t1, "target2": t2, "target3": t3,
            "risk_reward": rr, "pcr_chg": None, "option_symbol": option_symbol,
            "stock_sl": stock_sl, "stock_target1": stock_t1,
            "stock_target2": stock_t2, "stock_target3": stock_t3,
            "strike": strike,
            "recommendation": f"{action} {opt_side} — ₹{strike} STRIKE",
            "timestamp": datetime.now().isoformat(),
            **signal_extra,
        })
    
    signals.sort(key=lambda x: int(x['confidence'].replace('%', '')), reverse=True)

    # This used to be a hard signals[:6] regardless of how many stocks
    # actually cleared the bar. It's now everything that clears 65
    # (raised from 60 per feedback that the list was too noisy), capped
    # at 15 (was 20). Combined with the option-chain-confirmation gate
    # above (a signal can no longer exist at all without a real, live
    # Fyers option chain backing it), this cuts noise from both ends:
    # weaker technical setups are excluded, AND setups that technically
    # qualify but have no confirmed tradeable option are gone entirely.
    quality_signals = [
        s for s in signals
        if int(s['confidence'].replace('%', '')) >= 85
        and s.get('oi_confirmation') == 'CONFIRMED'
    ][:15]

    with _cache_lock:
        _signal_cache = quality_signals
        _tech_cache = techs

    # Log every newly-appeared signal to today's Excel file, and mark
    # anything that dropped out of the list since last cycle as exited --
    # gives you a running record of the whole day's signals (entry time,
    # entry/SL/targets, how long each stayed active) instead of only ever
    # seeing the current snapshot.
    try:
        from .excel_logger import sync_active_signals, check_outcomes
        newly_logged = sync_active_signals(quality_signals)
        if newly_logged:
            try:
                from trading.telegram_bot import TelegramBot
                bot = TelegramBot()
                for s in newly_logged:
                    bot.send_signal_alert(
                        symbol=s.get("symbol"),
                        signal_type=s.get("action"),
                        entry=s.get("entry"),
                        sl=s.get("sl"),
                        target=s.get("target1"),
                        grade=s.get("grade", "A"),
                    )
            except Exception as e:
                print(f"[Telegram] Failed to send new-signal alert: {e}")
        if is_authenticated():
            check_outcomes(get_quotes)
    except Exception as e:
        print(f"[ExcelLog] sync failed: {e}")

    # NIFTY/BANKNIFTY index snapshotting used to happen right here, but
    # that tied it to this function's own ~2.5-3min real cycle time (the
    # 90s sleep below plus however long the 200-stock scan above it
    # actually takes). Moved to its own faster, independent worker below
    # -- see _index_snapshot_worker -- so index snapshots can run on a
    # ~60s cadence without needing the whole stock scan to also speed up.


def _background_worker():
    from .market_hours import is_market_hours
    last_closed_log = 0
    while True:
        try:
            if is_market_hours():
                _build_all()
                print(f"[{datetime.now()}] Background refresh complete. Stocks: {len(_stock_cache)}, Signals: {len(_signal_cache)}")
                time.sleep(90)
            else:
                # Checking is_market_hours() itself costs nothing -- it's
                # a local time comparison, not a Fyers API call. So check
                # often (every 20s) for near-instant market-open detection
                # instead of the previous flat 300s sleep, which could
                # leave "market just opened" undetected for up to 5
                # minutes worst case (confirmed live: banner still
                # showing zeros 2+ min after open). Only the LOG LINE is
                # throttled to roughly every 5 min -- that was the actual
                # point of the old 300s interval (not spamming identical
                # lines all night), and this keeps that without also
                # slowing down detection.
                now = time.time()
                if now - last_closed_log >= 300:
                    print(f"[{datetime.now()}] Market closed -- waiting.")
                    last_closed_log = now
                time.sleep(20)
        except Exception as e:
            print(f"[{datetime.now()}] Background error: {e}")
            time.sleep(90)

_worker_thread = threading.Thread(target=_background_worker, daemon=True)
_worker_thread.start()


def _index_snapshot_worker():
    """
    Separate, faster loop just for NIFTY/BANKNIFTY snapshots -- was
    previously done inside _build_all() above, which tied index
    snapshots to that function's real cycle time (its own 90s sleep
    plus however long the 200-stock scan actually takes on top of
    that -- around 2.5-3 min in practice, not 90s). A 2-index quote
    fetch is cheap enough to run on its own much faster ~60s cadence
    without meaningfully adding to Fyers API load the way re-running
    the whole stock scan that often would. Calls _fetch_index directly
    each cycle for genuinely fresh data, not a stale cached value --
    the tradeoff is a small amount of duplicate quote-fetching between
    this and _build_all() (both still fetch NIFTY/BANKNIFTY/VIX
    independently, since _build_all() also needs them for the top
    banner), but that's lightweight quote calls, not full option
    chains, so it's a reasonable price for decoupling the two cadences.

    Also snapshots commodities (crude oil) every cycle now --
    snapshot_all_commodities() gates itself internally via
    index_tracker.is_mcx_hours(), completely independent of the NSE-only
    is_market_hours() check below, since MCX runs a longer session.
    That's why this call sits outside the `if is_market_hours()` branch:
    it needs to keep running (and simply no-op once genuinely outside
    MCX hours too) even after NSE closes for the day. The sleep interval
    reflects that too -- stays on the fast 60s cadence as long as EITHER
    market is open, only drops to the slow 300s check once both are shut.
    """
    from .market_hours import is_market_hours
    from .index_tracker import snapshot_all, snapshot_all_commodities, is_mcx_hours
    last_closed_log = 0
    while True:
        try:
            nse_open = is_market_hours()
            if nse_open:
                nifty = _fetch_index("NIFTY 50", ["^NSEI", "NSEI.NS", "^NSEI.NS"])
                bank = _fetch_index("BANKNIFTY", ["^NSEBANK", "NSEBANK.NS", "NIFTY_BANK.NS", "^NSEBANK.NS"])
                vix = _fetch_index("INDIA VIX", ["^INDIAVIX", "INDIAVIX.NS", "^INDIAVIX.NS"])
                snapshot_all(
                    change_percents={
                        "NIFTY": nifty.get("change_percent"),
                        "BANKNIFTY": bank.get("change_percent"),
                    },
                    vix=vix.get("price"),
                )
            snapshot_all_commodities()
            mcx_open = is_mcx_hours()
            if nse_open or mcx_open:
                time.sleep(60)
            else:
                # Same fast-check/slow-log split as _background_worker()
                # above -- checking costs nothing, only the log line needs
                # throttling. In practice MCX opens at 9 AM, before NSE's
                # 9:15, so this loop is normally already on the fast 60s
                # cadence well before NSE opens -- this only matters for
                # the narrower case of a restart happening before EITHER
                # market has opened yet (e.g. very early morning).
                now = time.time()
                if now - last_closed_log >= 300:
                    print(f"[{datetime.now()}] NSE and MCX both closed -- waiting.")
                    last_closed_log = now
                time.sleep(20)
        except Exception as e:
            print(f"[{datetime.now()}] Index snapshot worker error: {e}")
            time.sleep(60)

_index_snapshot_thread = threading.Thread(target=_index_snapshot_worker, daemon=True)
_index_snapshot_thread.start()


def _news_alert_worker():
    """
    Separate loop checking for new F&O news and sending any to Telegram
    via news.send_new_news_alerts(). Deliberately NOT gated by NSE or
    MCX market hours -- news itself (and the real-world events it
    reports on) isn't restricted to trading hours the way live quotes
    are, so this keeps checking around the clock. Runs on a 5-min
    cadence, matching news.py's own RSS cache TTL -- checking more
    often than that wouldn't find anything newer anyway.
    """
    from .news import send_new_news_alerts
    while True:
        try:
            sent = send_new_news_alerts(FNO_STOCKS)
            if sent:
                print(f"[{datetime.now()}] Sent {sent} new news alert(s) to Telegram.")
        except Exception as e:
            print(f"[{datetime.now()}] News alert worker error: {e}")
        time.sleep(300)

_news_alert_thread = threading.Thread(target=_news_alert_worker, daemon=True)
_news_alert_thread.start()

# ============================================================
# VIEWS — READ FROM CACHE ONLY, NO BLOCKING
# ============================================================

class MarketSummaryOldView(APIView):
    def get(self, request):
        with _cache_lock:
            nifty = _index_cache.get("nifty50")
            bank = _index_cache.get("banknifty")
            vix = _index_cache.get("india_vix")
            pcr = _index_cache.get("pcr", {"value": None, "sentiment": "N/A"})
            warming = len(_stock_cache) == 0

        # MarketBanner (this endpoint) is the one thing mounted on every
        # tab, polling every 30s regardless of which tab is active --
        # unlike the sniper-only endpoint, which only checks outcomes
        # while specifically on the Live Signals tab. Piggybacking the
        # same check here means SL/Target hits get caught as long as the
        # app is open at all, not just while that one tab is in view.
        # check_outcomes() is safe to call repeatedly (see excel_logger.py
        # module docstring) so there's no conflict with the existing call.
        try:
            if is_authenticated():
                from .excel_logger import check_outcomes
                check_outcomes(get_quotes)
        except Exception as e:
            print(f"[ExcelLog] outcome check (market-summary) failed: {e}")

        return Response({
            "nifty50": nifty or {"price": 0, "change": 0, "change_percent": 0},
            "banknifty": bank or {"price": 0, "change": 0, "change_percent": 0},
            "india_vix": vix or {"value": 0, "change": 0, "change_percent": 0},
            "pcr": pcr,
            "warming_up": warming,
            "timestamp": datetime.now().isoformat()
        })


class FoStockListOldView(APIView):
    def get(self, request):
        with _cache_lock:
            stocks = list(_stock_cache.values())
        
        # Fix: Replace NaN/Inf with None so JSON works
        for stock in stocks:
            for key, value in stock.items():
                if isinstance(value, float):
                    if math.isnan(value) or math.isinf(value):
                        stock[key] = None
        
        return Response({"stocks": stocks, "count": len(stocks)})


class MarketDataView(APIView):
    def get(self, request):
        with _cache_lock:
            stocks = list(_stock_cache.values())
        sorted_stocks = sorted(stocks, key=lambda x: x.get('change_percent', 0), reverse=True)
        
        with _cache_lock:
            nifty = _index_cache.get("nifty50")
            bank = _index_cache.get("banknifty")
        
        return Response({
            "indices": [
                nifty or {"name": "NIFTY 50", "price": 0, "change": 0, "change_percent": 0},
                bank or {"name": "BANKNIFTY", "price": 0, "change": 0, "change_percent": 0},
                {"name": "FINNIFTY", "price": 0, "change": 0, "change_percent": 0},
            ],
            "top_gainers": sorted_stocks[:5],
            "top_losers": sorted_stocks[-5:][::-1],
        })


class SignalsView(APIView):
    def get(self, request):
        with _cache_lock:
            signals = list(_signal_cache)
        return Response({"signals": signals, "count": len(signals)})


class SniperOnlyView(APIView):
    def get(self, request):
        with _cache_lock:
            signals = list(_signal_cache)
        return Response({"signals": signals, "count": len(signals)})


class TickerDataView(APIView):
    def get(self, request):
        with _cache_lock:
            stocks = list(_stock_cache.values())
        return Response({"ticker": stocks})


class StockDetailView(APIView):
    def get(self, request, symbol):
        sym = symbol.upper().replace(".NS", "")
        with _cache_lock:
            q = _stock_cache.get(sym)
        if not q:
            fetched = _fetch_all_stocks([sym])
            q = fetched.get(sym)
            if not q:
                return Response({"error": "Symbol not found"}, status=404)
        
        tech = _calc_tech(sym)
        return Response({
            **q,
            "ohlc": {"open": q["open"], "high": q["high"], "low": q["low"], "close": q["close"]},
            "technicals": tech or {},
            "fundamentals": {}
        })


class NewsView(APIView):
    """
    Real F&O-relevant news, pulled from ET's public RSS feeds (Markets,
    Stocks, Company) and filtered to headlines mentioning an F&O ticker
    directly. Previously returned 5 hardcoded headlines that never
    changed regardless of actual market conditions -- same pattern as
    the old fake PCR. Known limitation: only catches headlines that
    mention the bare ticker, not full company names -- see news.py.
    """
    def get(self, request):
        from .news import get_fno_news
        news = get_fno_news(FNO_STOCKS, limit=20)
        return Response({"news": news})


class FundamentalsWatchlistView(APIView):
    """
    Long-term value watchlist: NSE stocks meaningfully below their
    52-week high, ranked by combined fundamentals (P/E, ROE, Debt/
    Equity, Sales growth) via percentile ranking across whatever's been
    collected so far -- see fundamentals/ranking.py for the full method
    and reasoning (including why negative P/E is excluded from ranking
    rather than treated as "cheapest," caught from a real bad result).

    Reads from fundamentals_data.json, built by a SEPARATE background
    process (fundamentals/runner.py) -- not live-fetched here, since a
    full pass across the whole NSE list takes hours and fundamentals
    don't change that often anyway. This view is just reading whatever
    that process has saved so far, which may be a partial, still-
    growing list while the full run is in progress.

    GET /api/fundamentals-watchlist/
    Optional query params: ?min_discount=-10&limit=50
    """
    def get(self, request):
        from fundamentals.ranking import build_watchlist
        try:
            min_discount = float(request.GET.get("min_discount", -10))
        except (TypeError, ValueError):
            min_discount = -10
        try:
            limit = int(request.GET.get("limit", 50))
        except (TypeError, ValueError):
            limit = 50

        results = build_watchlist(min_discount_pct=min_discount, top_n=limit)
        return Response({"watchlist": results, "count": len(results)})


class FyersStatusView(APIView):
    def get(self, request):
        auth = is_authenticated()
        return Response({
            "authenticated": auth,
            "client_id": CLIENT_ID if auth else None,
            "status": "Connected" if auth else "Disconnected",
            "message": "Fyers API v3 active" if auth else "Please authenticate via /api/fyers/login/"
        })


class SignalExcelExportView(APIView):
    """Download today's auto-logged signal Excel file (entry time, entry/
    SL/targets, exit time for each signal that's dropped out of the
    active list). One file per trading day."""
    def get(self, request):
        from django.http import FileResponse, JsonResponse
        from .excel_logger import get_today_log_path
        path = get_today_log_path()
        if not path:
            return JsonResponse({"error": "No signals logged yet today."}, status=404)
        filename = os.path.basename(path)
        return FileResponse(open(path, 'rb'), as_attachment=True, filename=filename)


class SignalExportDatesView(APIView):
    """Every date that has a signal log available, newest first --
    powers the date picker next to the download button so past days
    are reachable, not just today. GET /api/signals/export/dates/"""
    def get(self, request):
        from .excel_logger import list_available_dates
        return Response({"dates": list_available_dates()})


class SignalExcelExportByDateView(APIView):
    """Same file the regular export gives you for today, but for any
    past date that has one. GET /api/signals/export/<YYYY-MM-DD>/"""
    def get(self, request, date_str):
        from django.http import FileResponse, JsonResponse
        from .excel_logger import get_log_path_for_date
        path = get_log_path_for_date(date_str)
        if not path:
            return JsonResponse({"error": f"No signals logged for {date_str}."}, status=404)
        filename = os.path.basename(path)
        return FileResponse(open(path, 'rb'), as_attachment=True, filename=filename)


class IndexTrackerView(APIView):
    """Today's NIFTY/BANKNIFTY/crude-oil intraday OI snapshot history,
    most recent first. GET /api/index-tracker/<NIFTY|BANKNIFTY|CRUDEOIL|CRUDEOILM>/"""
    def get(self, request, index_name):
        from .index_tracker import get_today_snapshots, TRACKABLE_NAMES
        name = index_name.upper()
        if name not in TRACKABLE_NAMES:
            return Response({"error": f"index_name must be one of {TRACKABLE_NAMES}"}, status=400)
        rows = get_today_snapshots(name)
        return Response(clean_json({"index": name, "snapshots": rows}))


class IndexBacktestView(APIView):
    """Day-wise Bias-accuracy backtest for one index or commodity, across
    15/30/60 minute look-ahead horizons -- does the Bias reading actually
    predict where price goes next, broken out per day rather than one
    aggregate number. GET /api/backtest/<NIFTY|BANKNIFTY|CRUDEOIL|CRUDEOILM>/"""
    def get(self, request, index_name):
        from .backtest_index_bias import backtest_by_day
        from .index_tracker import TRACKABLE_NAMES
        name = index_name.upper()
        if name not in TRACKABLE_NAMES:
            return Response({"error": f"index_name must be one of {TRACKABLE_NAMES}"}, status=400)
        horizons = (15, 30, 60)
        by_horizon = {h: backtest_by_day(name, h) for h in horizons}
        return Response(clean_json({"index": name, "horizons": by_horizon}))


class IndexBacktestExportView(APIView):
    """Download the day-wise backtest as an Excel file, one row per
    date+bias with a Hit% and sample count column per horizon.
    GET /api/backtest/<NIFTY|BANKNIFTY|CRUDEOIL|CRUDEOILM>/export/"""
    def get(self, request, index_name):
        from django.http import FileResponse, JsonResponse
        from .backtest_index_bias import write_backtest_report
        from .index_tracker import TRACKABLE_NAMES
        name = index_name.upper()
        if name not in TRACKABLE_NAMES:
            return JsonResponse({"error": f"index_name must be one of {TRACKABLE_NAMES}"}, status=400)
        try:
            path = write_backtest_report(name)
        except Exception as e:
            return JsonResponse({"error": f"Couldn't generate backtest report: {e}"}, status=500)
        filename = os.path.basename(path)
        return FileResponse(open(path, 'rb'), as_attachment=True, filename=filename)


class IndexTrackerExportView(APIView):
    """Download today's NIFTY/BANKNIFTY/crude-oil tracker Excel file."""
    def get(self, request, index_name):
        from django.http import FileResponse, JsonResponse
        from .index_tracker import get_today_log_path, TRACKABLE_NAMES
        name = index_name.upper()
        if name not in TRACKABLE_NAMES:
            return JsonResponse({"error": f"index_name must be one of {TRACKABLE_NAMES}"}, status=400)
        path = get_today_log_path(name)
        if not path:
            return JsonResponse({"error": f"No {name} snapshots logged yet today."}, status=404)
        filename = os.path.basename(path)
        return FileResponse(open(path, 'rb'), as_attachment=True, filename=filename)


class FyersBrowserTokenView(APIView):
    """
    Hands the frontend the app_id + access_token so services/fyersSocket.js
    can open its own authenticated WebSocket straight to Fyers
    (wss://socket.fyers.in/v3) for live tick updates.

    Previously nothing in this project ever wrote a token into
    localStorage, which is where fyersSocket.js looks -- so that socket
    could open a connection but never actually authenticate, and silently
    received no ticks. This is a stopgap for a single-user local dashboard;
    if you ever deploy this somewhere multi-user, don't expose a real
    trading token to the browser like this -- proxy ticks through the
    Channels consumers that already exist in options/consumers.py instead.
    """
    def get(self, request):
        if not is_authenticated():
            return Response({"authenticated": False, "access_token": None, "app_id": None})
        from .fyers_client import get_access_token
        try:
            token = get_access_token()
        except Exception:
            return Response({"authenticated": False, "access_token": None, "app_id": None})
        return Response({"authenticated": True, "access_token": token, "app_id": CLIENT_ID})


class OptionAnalyticsView(APIView):
    """
    Real option-chain analytics for one symbol: PCR, Max Pain, OI buildup,
    support/resistance, IV, and per-strike Greeks. Backs the 'OI Analytics'
    tab (individual stocks) AND the Crude Oil tab's options section --
    same underlying analytics either way, just resolved to a different
    Fyers symbol depending on what's asked for. Previously hardcoded every
    symbol to NSE:{sym}-EQ, which is wrong for commodities -- their option
    chain's underlying is the rolling front-month FUTURES contract, not an
    NSE equity symbol (confirmed via check_crude_oil_options.py).
    """
    def get(self, request, symbol):
        sym = symbol.upper().replace(".NS", "")
        if not is_authenticated():
            return Response({
                "symbol": sym, "live": False,
                "error": "Fyers not authenticated. Run get_fyers_token.py to log in, then retry.",
            })

        from .index_tracker import COMMODITY_BASES, _front_month_commodity_symbol
        if sym in COMMODITY_BASES:
            fyers_symbol = _front_month_commodity_symbol(COMMODITY_BASES[sym])
        else:
            fyers_symbol = f"NSE:{sym}-EQ"

        try:
            oi = get_option_analytics(fyers_symbol, strikecount=10)
        except Exception as e:
            return Response({"symbol": sym, "live": False, "error": str(e)})
        if not oi:
            return Response({
                "symbol": sym, "live": False,
                "error": "No option chain returned — symbol may have no listed F&O options, or market is closed.",
            })

        ce_data = [{"strike": r["strike"], **r["ce"]} for r in oi["rows"] if r["ce"]]
        pe_data = [{"strike": r["strike"], **r["pe"]} for r in oi["rows"] if r["pe"]]

        return Response(clean_json({
            "symbol": sym, "live": True, "spot": oi["spot"], "pcr": oi["pcr"],
            "maxPain": oi["max_pain"], "atmIv": oi["iv"], "atmStrike": oi["atm_strike"],
            "support": oi["support"], "resistance": oi["resistance"],
            "oiBuildup": oi["oi_buildup"], "greeks": oi["greeks"],
            "totalCeOi": oi["ce_oi"], "totalPeOi": oi["pe_oi"],
            "ceOiChg": oi["ce_oi_chg"], "peOiChg": oi["pe_oi_chg"],
            "ceData": ce_data, "peData": pe_data,
        }))


# ============================================================
# TELEGRAM ALERTS
# ============================================================

TELEGRAM_BOT_TOKEN = 'YOUR_BOT_TOKEN_HERE'  # <-- replace
TELEGRAM_CHAT_ID = 'YOUR_CHAT_ID_HERE'       # <-- replace

def send_telegram_alert(signal):
    """Call this when a new SNIPER signal is generated"""
    msg = f"""🎯 *SNIPER SIGNAL*

*{signal['symbol']}* | Grade {signal['grade']}

{'🟢' if signal['action'] == 'BUY' else '🔴'} *{signal['action']} {signal['action'] == 'BUY' and 'CE' or 'PE'}*
Strike: ₹{signal.get('strike', 0)}
Entry: ₹{signal.get('entry', signal.get('price', 0))}
SL: ₹{signal.get('sl', 0)}
Target: ₹{signal.get('target1', 0)}
Qty: {signal.get('quantity', 1)}

Confidence: {signal.get('confidence', 'N/A')}
R:R {signal.get('risk_reward', 2)}

⏰ Generated at {pd.Timestamp.now().strftime('%H:%M IST')}

#SNIPER #{signal['symbol']}
"""
    
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        'chat_id': TELEGRAM_CHAT_ID,
        'text': msg,
        'parse_mode': 'Markdown',
    }
    
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Telegram send failed: {e}")


# ============================================================
# JSON CLEANER
# ============================================================

class WeeklyReportView(APIView):
    """
    Download the weekly signals + index report on demand. Same content
    the Friday-scheduled command generates. GET /api/weekly-report/
    Add ?telegram=1 to also send it to Telegram right away, same as
    the scheduled command does automatically.
    """
    def get(self, request):
        from django.http import FileResponse, JsonResponse
        from .weekly_report import generate_weekly_report
        path = generate_weekly_report()
        if not path:
            return JsonResponse({"error": "Report generation failed."}, status=500)

        if request.GET.get('telegram'):
            try:
                from trading.telegram_bot import TelegramBot
                bot = TelegramBot()
                bot.send_document(path, caption=f"📊 <b>F&O Radar — Weekly Report</b>\n{os.path.basename(path)}")
            except Exception as e:
                print(f"[Telegram] Failed to send weekly report: {e}")

        filename = os.path.basename(path)
        return FileResponse(open(path, 'rb'), as_attachment=True, filename=filename)


def clean_json(data):
    """Replace NaN, Inf, -Inf with None so JSON serializes properly"""
    if isinstance(data, dict):
        return {k: clean_json(v) for k, v in data.items()}
    if isinstance(data, list):
        return [clean_json(item) for item in data]
    if isinstance(data, float):
        if math.isnan(data) or math.isinf(data):
            return None
    return data
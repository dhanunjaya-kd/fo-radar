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
_index_cache_updated_at = 0.0  # Aug 20 2026: lets _build_all() below reuse whatever
# _index_snapshot_worker's faster 60s loop already fetched instead of
# independently re-fetching the same NIFTY/BANKNIFTY/VIX quotes -- see
# both functions for why this mattered (confirmed live 429 rate-limiting
# on Fyers' /quotes endpoint, and this redundant double-fetch was a real,
# substantial, previously-accepted-as-lightweight contributor to that).
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
    from Yahoo.

    Aug 20 2026: this used to fall through to the zeroed placeholder
    completely silently whenever Fyers responded but with resp['s'] !=
    'ok' (not an exception -- a real response Fyers just didn't mark as
    ok), or responded 'ok' with no usable item inside. That's a
    different, narrower failure than is_authenticated() itself being
    false (which already logs) -- confirmed live: indices sat at 0.00
    across multiple fresh-restart cycles with NEITHER the auth-gate log
    below NOR an exception ever printing, meaning execution was reaching
    here through one of these two silent paths. Now both log the actual
    Fyers response so the real reason is visible next time instead of
    just "it's zero, no idea why."
    """
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
                print(f"[Fyers] Index fetch {name}: response was 'ok' but no usable price in it -- {resp}")
            else:
                print(f"[Fyers] Index fetch {name}: response not ok -- {resp}")
        except Exception as e:
            print(f"[Fyers] Index fetch error {name}: {e}")
    else:
        print(f"[Fyers] Not authenticated -- skipping index {name} (no Yahoo fallback)")
    return {'price': 0, 'change': 0, 'change_percent': 0}


# Aug 28 2026: SEPARATE dict from FYERS_INDEX_SYMBOLS above -- these
# broader indices (Next 50, 100, Midcap 100, Smallcap 100) are NOT
# verified against a live Fyers connection the way NIFTY50/BANKNIFTY/
# VIX are (those are proven, deployed, working in this project for
# weeks). Evidence they exist under this exact "NSE:<NAME>-INDEX"
# convention comes from generic NSE index-symbol documentation
# (matching the same pattern already proven for NIFTY50/BANKNIFTY),
# NOT a confirmed Fyers-specific test. Kept in a fully separate dict
# and function from the core index fetch deliberately -- if any of
# these turn out wrong, that failure is fully isolated and can never
# affect the already-working NIFTY50/BANKNIFTY/VIX cards.
BROADER_INDEX_SYMBOLS = {
    "NIFTY Next 50": "NSE:NIFTYNXT50-INDEX",
    "NIFTY 100": "NSE:NIFTY100-INDEX",
    "NIFTY Midcap 100": "NSE:NIFTYMIDCAP100-INDEX",
    "NIFTY Smallcap 100": "NSE:NIFTYSMLCAP100-INDEX",
}


def fetch_broader_indices():
    """
    Real quotes for the broader NSE indices shown on Market View's
    Indices Performance table -- a fully separate fetch path from
    _fetch_index() above, batched in one call (same batch pattern as
    _fetch_all_quotes_fyers, field 'n' for the returned symbol).

    Each symbol here is genuinely UNVERIFIED against a live Fyers
    connection (see BROADER_INDEX_SYMBOLS' own comment) -- this
    degrades gracefully: whichever symbols come back with a real,
    usable price are returned; whichever don't are simply OMITTED
    from the result, never a zeroed placeholder standing in for real
    data. The frontend only ever renders what's actually here, so an
    unresolved symbol just means one fewer row, not a broken table.
    """
    if not is_authenticated():
        return {}
    symbols = list(BROADER_INDEX_SYMBOLS.values())
    symbol_to_name = {v: k for k, v in BROADER_INDEX_SYMBOLS.items()}
    try:
        resp = get_quotes(symbols)
    except Exception as e:
        print(f"[Fyers] Broader indices fetch error: {e}")
        return {}
    if not resp or resp.get('s') != 'ok':
        print(f"[Fyers] Broader indices fetch: response not ok -- {resp}")
        return {}

    results = {}
    for item in resp.get('d', []):
        if item.get('s') != 'ok':
            continue
        fyers_sym = item.get('n')
        name = symbol_to_name.get(fyers_sym)
        if not name:
            continue
        v = item.get('v', {}) or {}
        price = v.get('lp')
        if price is None or price <= 0 or (isinstance(price, float) and math.isnan(price)):
            continue
        results[name] = {
            'name': name,
            'price': round(price, 2),
            'change': round(v.get('ch', 0) or 0, 2),
            'change_percent': round(v.get('chp', 0) or 0, 2),
        }
    return results


def _fetch_all_quotes_fyers(symbols):
    """
    Batch-fetch current price/change/volume for every symbol via Fyers
    quotes (up to 50 symbols per call -- Fyers' documented batch limit),
    instead of one yfinance call per stock. This is the PRIMARY price
    source now. Returns {symbol: stock_dict} for whatever came back OK;
    silently drops anything that failed or came back with a NaN/zero
    price rather than raising.

    Aug 20 2026: the whole-batch "resp['s'] != 'ok'" case used to fall
    through with zero logging, same silent-failure shape as
    _fetch_index() above and confirmed live the same way -- the whole
    208-stock scan came back empty across multiple fresh-restart cycles
    with no exception and no batch-error print anywhere, while OTHER
    Fyers endpoints (option chains, Index Tracker's Market Depth calls)
    kept working at the same moment. This points at Fyers' plain
    /quotes endpoint specifically, not a broad auth/connectivity
    problem -- now logs the actual response so that's visible instead
    of assumed.
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
            print(f"[Fyers] Quotes batch {i}-{i + len(batch)}: response not ok -- {resp}")
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


# Day-scoped cache: {symbol: {'date': 'YYYY-MM-DD', 'df': historical_df}}.
# Aug 14 2026 addition -- _calc_tech() used to re-fetch 100 days of daily
# candles from Fyers for every one of the day's ~30 top movers, EVERY
# cycle, even though 99 of those 100 days are identical to two minutes
# ago -- only today's candle moves. This caches everything except the
# most recent (today's) row once per symbol per day; _calc_tech appends
# a fresh "today" row built from the quote data _fetch_all_stocks()
# already pulled this cycle, so most cycles now cost ZERO extra Fyers
# calls here, not 30.
#
# Aug 27 2026: also now shared by _cached_index_history_df() below for
# NIFTY/BANKNIFTY's own ATR (index option calls, see index_signal.py) --
# keyed by "NIFTY"/"BANKNIFTY", which never collides with a real F&O
# stock ticker, so one cache dict serves both without any change here.
_history_cache = {}

# Aug 28 2026: SEPARATE from _history_cache above -- that one's cache
# check only looks at symbol+date, not the `days` window requested, so
# reusing it with a different days value here would silently return
# the wrong (100-day, not 365-day) window for a symbol already cached
# by _calc_tech's RSI/ADX/ATR calls. This gets its own dict and its
# own key so a 52-week lookup and a 100-day indicator lookup for the
# same symbol never collide or shadow each other.
_year_history_cache = {}  # {symbol: {'date': 'YYYY-MM-DD', 'high_52w': float, 'low_52w': float}}


def get_52_week_high_low(symbol):
    """
    Real 52-week high/low, computed from ~365 days of Fyers' History
    API daily candles -- confirmed (Aug 28 2026, via Fyers' own
    community forum and the full quotes-response field schema) that
    the Quotes API does NOT provide this directly: high_price/
    low_price there are TODAY's intraday high/low only, not a 52-week
    window. Reuses _fyers_history_df() unchanged, just with a longer
    days window -- no new Fyers call pattern introduced, same fetch
    mechanism already proven all session for RSI/ADX/ATR history.

    Cached once per symbol per day (own dict, see _year_history_cache)
    -- a fresh History API call per symbol on every request would be
    both slow and wasteful; this only re-fetches once per symbol per
    trading day.

    Returns (None, None) if history can't be fetched -- never guesses
    a 52-week range from partial or missing data.
    """
    today_str = datetime.now().strftime("%Y-%m-%d")
    cached = _year_history_cache.get(symbol)
    if cached and cached.get('date') == today_str:
        return cached['high_52w'], cached['low_52w']

    df = _fyers_history_df(symbol, days=365)
    if df is None or df.empty:
        return None, None

    high_52w = round(float(df['High'].max()), 2)
    low_52w = round(float(df['Low'].min()), 2)
    _year_history_cache[symbol] = {'date': today_str, 'high_52w': high_52w, 'low_52w': low_52w}
    return high_52w, low_52w


def _cached_history_df(symbol, days=100):
    """
    Returns cached daily-candle history for `symbol`, EXCLUDING the most
    recent row -- _calc_tech always replaces that row with a fresh one
    built from this cycle's already-fetched live quote instead. Only
    hits Fyers once per symbol per day; every other call this trading
    day is a pure in-memory lookup.

    Drops the fetched response's LAST row unconditionally, rather than
    trying to identify "today" by comparing dates -- Fyers' candle
    timestamps are raw epoch seconds, and doing that comparison
    correctly needs careful timezone handling (this function runs in the
    machine's local time; naive epoch-to-date conversion defaults to
    UTC) that's easy to get subtly wrong, especially near midnight IST.
    Dropping the last row and replacing it with a definitely-current
    live quote sidesteps that entirely -- and it's consistent with how
    the rest of this file already works: every indicator in
    _compute_indicators reads .iloc[-1] as "today", so the code already
    assumes ascending chronological order with the most recent day last.
    This isn't a new assumption, just acting on the one already baked in.
    """
    today_str = datetime.now().strftime("%Y-%m-%d")
    cached = _history_cache.get(symbol)
    if cached and cached.get('date') == today_str:
        return cached['df']

    df = _fyers_history_df(symbol, days=days)
    if df is None or df.empty or len(df) < 2:
        return None

    historical = df.iloc[:-1].reset_index(drop=True)
    _history_cache[symbol] = {'date': today_str, 'df': historical}
    return historical


def _cached_index_history_df(name, fyers_symbol, days=100):
    """
    Aug 27 2026: same caching pattern as _cached_history_df() above, but
    for an INDEX's own daily candles -- can't reuse that function
    directly since it hardcodes 'NSE:{symbol}-EQ', which is the wrong
    format for an index (NSE:NIFTY50-INDEX, not NSE:NIFTY50-EQ). Written
    as a separate function rather than modifying the working stock
    version, same "don't risk an already-working caller" principle used
    elsewhere in this project (e.g. index_tracker.py's two separate
    bullion-symbol resolvers).

    Shares the SAME _history_cache dict though, keyed by `name`
    ("NIFTY"/"BANKNIFTY" -- matching index_tracker.py's own naming, not
    FYERS_INDEX_SYMBOLS' "NIFTY 50" key, to keep this module's index
    calls consistent with the Bias/oi data they're paired with). Never
    collides with a real F&O stock ticker.

    Unlike _cached_history_df(), does NOT drop the last row / append a
    live-quote replacement -- this only feeds ATR (index_signal.py's
    SL/Target sizing), which doesn't need to be augmented with today's
    still-forming candle the way _calc_tech's fuller indicator set does.
    One day less current than the stock engine's version; simpler, and
    avoids sourcing a same-cycle live index quote into this function
    just for a marginal ATR freshness gain.
    """
    today_str = datetime.now().strftime("%Y-%m-%d")
    cached = _history_cache.get(name)
    if cached and cached.get('date') == today_str:
        return cached['df']

    range_to = datetime.now().date()
    range_from = range_to - timedelta(days=days)
    try:
        resp = get_history(fyers_symbol, resolution="D",
                            range_from=str(range_from), range_to=str(range_to))
    except Exception as e:
        print(f"[IndexSignal] {name} history error: {e}")
        return None
    if not resp or resp.get('s') != 'ok' or not resp.get('candles'):
        return None
    df = pd.DataFrame(resp['candles'], columns=['ts', 'Open', 'High', 'Low', 'Close', 'Volume'])
    if df.empty or len(df) < 2:
        return None

    _history_cache[name] = {'date': today_str, 'df': df}
    return df


def _calc_index_atr(name, fyers_symbol):
    """
    Aug 27 2026: ATR for an index (NIFTY/BANKNIFTY), reusing the exact
    same _compute_indicators() math the stock engine already uses for
    every F&O stock -- so index option calls (index_signal.py) size
    SL/Target off the same kind of volatility measure stock calls do,
    not a different concept invented from scratch. Returns None (not a
    guessed number) if there isn't enough history or Fyers has nothing
    right now -- caller (index_signal.generate_index_call) already
    treats a None ATR as "can't generate a call yet."
    """
    try:
        if not is_authenticated():
            return None
        df = _cached_index_history_df(name, fyers_symbol, days=100)
        if df is None or len(df) < 20:
            return None
        indicators = _compute_indicators(df['Close'], df['High'], df['Low'], df['Volume'])
        return indicators['atr'] if indicators else None
    except Exception as e:
        print(f"[IndexSignal] {name} ATR calc error: {e}")
        return None


def _calc_tech(symbol, live_quote=None):
    """
    Technical indicators for a stock, sourced from Fyers only. No Yahoo/
    yfinance fallback -- if Fyers isn't authenticated or has no usable
    history for this symbol, returns None (caller skips the stock for
    this cycle) rather than pulling from Yahoo.

    `live_quote` (optional): this cycle's already-fetched quote dict for
    this symbol (from _fetch_all_stocks -- has open/high/low/price/
    volume). When given, today's candle is built from THIS instead of a
    second Fyers history call that would otherwise also include today --
    the quotes call already happened this cycle regardless, so reusing
    it here is genuinely free. Falls back to the original, slower path
    (a full history fetch that includes today, no caching) when not
    given, so any other caller keeps working exactly as before.
    """
    try:
        if not is_authenticated():
            return None

        if live_quote is not None:
            historical = _cached_history_df(symbol, days=100)
            if historical is None:
                return None
            today_row = pd.DataFrame([{
                'ts': int(datetime.now().timestamp()),
                'Open': live_quote.get('open') or live_quote.get('price'),
                'High': live_quote.get('high') or live_quote.get('price'),
                'Low': live_quote.get('low') or live_quote.get('price'),
                'Close': live_quote.get('price'),
                'Volume': live_quote.get('volume', 0),
            }])
            df = pd.concat([historical, today_row], ignore_index=True)
        else:
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
    global _stock_cache, _index_cache, _index_cache_updated_at, _signal_cache, _tech_cache, _last_fetch

    # 1. Indices -- Aug 20 2026: reuse _index_snapshot_worker's fetch if
    # it's recent (that loop runs every 60s specifically for this, and
    # independently re-fetching the identical 3 symbols here was
    # confirmed to meaningfully add to real Fyers /quotes rate-limiting,
    # not just a "lightweight" duplicate as originally assumed). Falls
    # back to fetching directly if the shared cache is empty or older
    # than 90s (covers cold start, before the snapshot worker's first
    # cycle completes, and the case where that worker's thread has died).
    with _cache_lock:
        cache_age = time.time() - _index_cache_updated_at
        cached_indices = dict(_index_cache) if _index_cache else None

    if cached_indices and cache_age < 90:
        nifty = cached_indices.get("nifty50", {'price': 0, 'change': 0, 'change_percent': 0})
        bank = cached_indices.get("banknifty", {'price': 0, 'change': 0, 'change_percent': 0})
        vix = cached_indices.get("india_vix", {'price': 0, 'change': 0, 'change_percent': 0})
    else:
        nifty = _fetch_index("NIFTY 50", ["^NSEI", "NSEI.NS", "^NSEI.NS"])
        bank = _fetch_index("BANKNIFTY", ["^NSEBANK", "NSEBANK.NS", "NIFTY_BANK.NS", "^NSEBANK.NS"])
        vix = _fetch_index("INDIA VIX", ["^INDIAVIX", "INDIAVIX.NS", "^INDIAVIX.NS"])
        with _cache_lock:
            _index_cache = {"nifty50": nifty, "banknifty": bank, "india_vix": vix}
            _index_cache_updated_at = time.time()
    
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
        tech = _calc_tech(sym, live_quote=stock)
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
        # Aug 27 2026: deferred import matching this file's existing
        # convention (get_locked_plan right above is imported the same
        # way) -- used by both branches below.
        from .lot_size_resolver import get_lot_size

        if locked:
            entry, strike = locked['entry'], locked['strike'] or strike
            sl = locked['sl']
            t1, t2, t3 = locked['target1'], locked['target2'], locked['target3']
            # Aug 27 2026: real lot size as the fallback here too (was
            # int(50000/entry)) -- this branch is a rare defensive case
            # (an already-locked plan whose stored quantity is somehow
            # empty), not the primary path, but should stay consistent
            # with the real fix rather than quietly keep the old
            # capital-based distortion alive in an edge case.
            qty = locked['quantity'] or get_lot_size(sym) or 1
            rr = locked['risk_reward'] or 1.5
            option_symbol = locked['option_symbol']
            # Already-tracked outcome status for this locked plan -- see
            # get_locked_plan()'s Aug 20 update. A genuinely fresh signal
            # (the else branch below) hasn't had a chance to hit anything
            # yet, so it starts at sl_hit=False / furthest_target_hit=0.
            sl_hit = locked.get('sl_hit', False)
            furthest_target_hit = locked.get('furthest_target_hit', 0)
        else:
            sl_hit = False
            furthest_target_hit = 0
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

            # Aug 27 2026: real, live-resolved NSE lot size -- REPLACES
            # int(50000/entry) entirely. That old math gave a cheap-
            # premium stock a wildly oversized position purely because
            # it was cheap, nothing to do with signal quality (real
            # example: a Rs 4.03 premium got ~12,400 units vs a
            # Rs 11.60 premium's ~4,300, same Rs 50k budget). One real
            # lot is what a trader actually holds. No confirmed live
            # lot size for this symbol -> skip the signal entirely,
            # same "no confirmed data, no signal" rule already applied
            # a few lines up for a missing option chain -- never
            # fabricate a quantity.
            lot_size = get_lot_size(sym)
            if lot_size is None:
                continue
            qty = lot_size
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
            "sl_hit": sl_hit,
            "furthest_target_hit": furthest_target_hit,
            "outcome_status": (
                "SL Hit" if sl_hit
                else (f"Target {furthest_target_hit} Hit" if furthest_target_hit else "Open")
            ),
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
    each cycle for genuinely fresh data, not a stale cached value, and
    now also WRITES that fetch into the shared _index_cache (see
    _build_all() above) so that function reuses it instead of
    independently re-fetching the same 3 symbols. That duplication used
    to be accepted as "lightweight enough not to matter" -- confirmed
    Aug 20 2026 that it was a real, meaningful contributor to hitting an
    actual Fyers 429 rate limit on /quotes, not just a lightweight
    quote-call tradeoff, so it's eliminated now rather than accepted.

    Also snapshots commodities (crude oil) every cycle now --
    snapshot_all_commodities() gates itself internally via
    index_tracker.is_mcx_hours(), completely independent of the NSE-only
    is_market_hours() check below, since MCX runs a longer session.
    That's why this call sits outside the `if is_market_hours()` branch:
    it needs to keep running (and simply no-op once genuinely outside
    MCX hours too) even after NSE closes for the day. The sleep interval
    reflects that too -- stays on the fast 60s cadence as long as EITHER
    market is open, only drops to the slow 300s check once both are shut.

    Aug 27 2026: also turns a confirmed NIFTY/BANKNIFTY Bias into an
    actual tradeable options call -- see index_signal.py's module
    docstring for the full reasoning (strike-at-the-OI-wall, same SL/
    Target math as the stock engine). Uses THIS cycle's own snapshot_
    all() result (index_tracker.get_last_oi_snapshot() -- same oi dict
    already fetched, no second option-chain call) plus the index's own
    ATR (fetched/cached separately, ~once/day via _calc_index_atr()).
    Runs only when NSE is open -- an index options call doesn't apply
    outside NSE F&O hours the way commodity snapshotting does.
    """
    from .market_hours import is_market_hours
    from .index_tracker import snapshot_all, snapshot_all_commodities, is_mcx_hours, get_last_oi_snapshot
    from . import index_signal
    last_closed_log = 0
    while True:
        try:
            nse_open = is_market_hours()
            if nse_open:
                nifty = _fetch_index("NIFTY 50", ["^NSEI", "NSEI.NS", "^NSEI.NS"])
                bank = _fetch_index("BANKNIFTY", ["^NSEBANK", "NSEBANK.NS", "NIFTY_BANK.NS", "^NSEBANK.NS"])
                vix = _fetch_index("INDIA VIX", ["^INDIAVIX", "INDIAVIX.NS", "^INDIAVIX.NS"])
                global _index_cache, _index_cache_updated_at
                with _cache_lock:
                    _index_cache = {"nifty50": nifty, "banknifty": bank, "india_vix": vix}
                    _index_cache_updated_at = time.time()
                index_rows = snapshot_all(
                    change_percents={
                        "NIFTY": nifty.get("change_percent"),
                        "BANKNIFTY": bank.get("change_percent"),
                    },
                    vix=vix.get("price"),
                )

                for name, fyers_symbol in (("NIFTY", "NSE:NIFTY50-INDEX"), ("BANKNIFTY", "NSE:NIFTYBANK-INDEX")):
                    row = (index_rows or {}).get(name)
                    oi = get_last_oi_snapshot(name)
                    if not row or not oi:
                        continue
                    try:
                        atr = _calc_index_atr(name, fyers_symbol)
                        call = index_signal.generate_index_call(name, row.get("Bias"), oi, row.get("Spot"), atr)
                        # Outcome check only when a call is actually locked
                        # and we have its exact option_symbol -- one small
                        # extra quote call per active index call, not per
                        # cycle regardless (matches the "only fetch what's
                        # actually needed" principle already used
                        # throughout this project).
                        if call and call.get("option_symbol") and is_authenticated():
                            resp = get_quotes([call["option_symbol"]])
                            if resp and resp.get("s") == "ok":
                                for item in resp.get("d", []):
                                    if item.get("s") == "ok":
                                        ltp = (item.get("v") or {}).get("lp")
                                        if ltp:
                                            index_signal.check_call_outcome(name, ltp)
                    except Exception as e:
                        print(f"[IndexSignal] {name} call generation failed: {e}")
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


def _daily_backtest_worker():
    """
    Aug 27 2026: runs the full backtest checklist (backfill -> stock
    P&L backtest -> NIFTY positional -> BANKNIFTY positional)
    automatically, TWICE a day -- once shortly after market close
    (catches the day's just-finished signals) and once again early the
    next morning (catches anything that only fully resolved overnight,
    and re-confirms nothing was missed before the new trading day
    starts). Same daemon-thread pattern as the 3 workers above -- no
    Celery/Redis needed here either. See daily_backtest.py for the
    actual checklist logic.

    Uses a per-slot 'last run date' check so each of the two daily
    windows only fires once, even though this loop checks the clock
    frequently -- checking is free; the actual cycle is not (real
    Fyers history calls per unresolved row, real PDF generation).
    Mon-Fri only, matching market_hours.py's own weekend assumption.
    """
    CLOSE_RUN_HOUR, CLOSE_RUN_MINUTE = 16, 0     # ~20min after CAS/derivatives close (3:40 PM)
    MORNING_RUN_HOUR, MORNING_RUN_MINUTE = 8, 0  # well before 9:00 AM pre-open

    last_close_run_date = None
    last_morning_run_date = None

    while True:
        try:
            now = datetime.now()
            today_str = now.strftime("%Y-%m-%d")
            is_weekday = now.weekday() < 5

            if is_weekday and now.hour == CLOSE_RUN_HOUR and now.minute >= CLOSE_RUN_MINUTE and last_close_run_date != today_str:
                last_close_run_date = today_str
                print(f"[{now}] Daily backtest: running scheduled close-time cycle.")
                from .daily_backtest import run_daily_backtest_cycle
                run_daily_backtest_cycle(trigger="scheduled-close", backfill_days=7)

            if is_weekday and now.hour == MORNING_RUN_HOUR and now.minute >= MORNING_RUN_MINUTE and last_morning_run_date != today_str:
                last_morning_run_date = today_str
                print(f"[{now}] Daily backtest: running scheduled morning cycle.")
                from .daily_backtest import run_daily_backtest_cycle
                run_daily_backtest_cycle(trigger="scheduled-morning", backfill_days=7)

            time.sleep(60)
        except Exception as e:
            print(f"[{datetime.now()}] Daily backtest worker error: {e}")
            time.sleep(60)

_daily_backtest_thread = threading.Thread(target=_daily_backtest_worker, daemon=True)
_daily_backtest_thread.start()


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
            breadth = _compute_breadth(list(_stock_cache.values()))
            sectors = _compute_sector_performance(list(_stock_cache.values()))
            sentiment = _compute_market_sentiment(list(_stock_cache.values()))
            movers = _compute_market_movers(list(_stock_cache.values()))

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
            "breadth": breadth,
            "sectors": sectors,
            "sentiment": sentiment,
            "movers": movers,
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


def get_technical_signal(symbol):
    """
    Aug 28 2026: real Bullish/Neutral/Bearish technical read for the
    upcoming Watchlist redesign, based on RSI. Deliberately reuses
    StockDetailView's exact existing pattern (check _stock_cache first
    -- free if this symbol happens to already be cached; fall back to
    _fetch_all_stocks([sym]) for a single fresh quote; then
    _calc_tech(sym, live_quote=q) for the full indicator set including
    TODAY's candle) rather than the _build_all()-populated _tech_cache
    global, which ONLY covers the day's top 30 movers by |change%| --
    a watchlist can contain any of the 208 F&O stocks, most of which
    won't be in that moving top-30 subset on a given day.

    RSI thresholds (>=60 Bullish, <=40 Bearish, else Neutral) sit
    around the same 40-65 "favorable" band this codebase's own signal-
    quality criteria already uses elsewhere (previously shown in the
    UI as "RSI 40-65 | ADX >=25 | Vol >=1.5x") -- not a new, unrelated
    scale invented just for this.

    Returns None if a fresh quote or enough history isn't available --
    never guesses a direction.
    """
    sym = symbol.upper().replace(".NS", "")
    with _cache_lock:
        q = _stock_cache.get(sym)
    if not q:
        fetched = _fetch_all_stocks([sym])
        q = fetched.get(sym)
        if not q:
            return None

    tech = _calc_tech(sym, live_quote=q)
    if not tech or tech.get('rsi') is None:
        return None

    rsi = tech['rsi']
    if rsi >= 60:
        label = 'Bullish'
    elif rsi <= 40:
        label = 'Bearish'
    else:
        label = 'Neutral'
    return {'label': label, 'rsi': rsi, 'adx': tech.get('adx')}


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
        
        tech = _calc_tech(sym, live_quote=q)
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

    Aug 28 2026: added "broad_news" -- the F&O-ticker filter above
    means genuinely relevant macro/global news (bond yields, Fed
    decisions, global market moves) was being silently dropped
    whenever it didn't happen to name a specific stock, confirmed live
    ("not getting any news related to global tension, only F&O
    stocks"). get_broad_market_news() is the SAME feeds, unfiltered --
    see its own docstring for why it's a separate function rather than
    a change to get_fno_news() itself.
    """
    def get(self, request):
        from .news import get_fno_news, get_broad_market_news
        news = get_fno_news(FNO_STOCKS, limit=20)
        broad_news = get_broad_market_news(limit=15)
        return Response({"news": news, "broad_news": broad_news})


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


class SignalWatchlistCsvView(APIView):
    """Today's active qualifying signals as a Fyers-Watchlist-importable
    CSV. There is no Fyers API endpoint to push directly into a Watchlist
    (checked Aug 20 2026 -- watchlist write access isn't part of
    fyers-apiv3's exposed surface, only manual add/CSV-import via Fyers
    Web/App). Fyers Web DOES support Watchlist -> Import from a CSV with
    a single 'Symbol' column, so this is the closest real automation:
    generate the file in that exact importable shape, using the real
    Fyers option_symbol string already attached to each signal (the same
    one Fyers' own option-chain response returned -- not reconstructed),
    so the daily manual step becomes 'download, then Import in Fyers
    Web' instead of typing each strike by hand.
    GET /api/signals/watchlist-csv/"""
    def get(self, request):
        from django.http import HttpResponse, JsonResponse
        import csv
        import io

        with _cache_lock:
            signals = list(_signal_cache)

        seen = set()
        rows = []
        for s in signals:
            sym = s.get("option_symbol")
            if sym and sym not in seen:
                rows.append(sym)
                seen.add(sym)

        if not rows:
            return JsonResponse({"error": "No active signals with a confirmed option symbol right now."}, status=404)

        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(["Symbol"])
        for sym in rows:
            writer.writerow([sym])

        response = HttpResponse(buffer.getvalue(), content_type="text/csv")
        filename = f"sniper_watchlist_{datetime.now().strftime('%Y-%m-%d_%H%M')}.csv"
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response


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
    """Intraday OI snapshot history for one index/commodity, most recent
    first -- today's by default, or a specific past date via ?date=.
    GET /api/index-tracker/<NIFTY|BANKNIFTY|CRUDEOIL|CRUDEOILM>/?date=2026-08-12"""
    def get(self, request, index_name):
        from .index_tracker import get_today_snapshots, get_snapshots_for_date, TRACKABLE_NAMES
        name = index_name.upper()
        if name not in TRACKABLE_NAMES:
            return Response({"error": f"index_name must be one of {TRACKABLE_NAMES}"}, status=400)
        date_str = request.GET.get("date")
        rows = get_snapshots_for_date(name, date_str) if date_str else get_today_snapshots(name)
        return Response(clean_json({"index": name, "date": date_str, "snapshots": rows}))


class IndexTrackerAvailableDatesView(APIView):
    """Which dates actually have logged snapshot data for one index --
    lets the frontend offer a real, populated date picker rather than
    letting someone guess at a date that has nothing behind it.
    GET /api/index-tracker/<NIFTY|BANKNIFTY|CRUDEOIL|CRUDEOILM>/dates/"""
    def get(self, request, index_name):
        from .index_tracker import list_available_dates, TRACKABLE_NAMES
        name = index_name.upper()
        if name not in TRACKABLE_NAMES:
            return Response({"error": f"index_name must be one of {TRACKABLE_NAMES}"}, status=400)
        return Response({"index": name, "dates": list_available_dates(name)})


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


class CASAuctionMovesView(APIView):
    """
    Day-by-day price move specifically attributable to the CAS
    auction window (3:15-3:35 PM): last reading before it starts vs
    first reading after it resolves, isolating the auction's real
    effect from ordinary intraday movement. NIFTY/BANKNIFTY only --
    CAS is an NSE cash-market mechanism, doesn't apply to commodities.
    Days before the market_hours.py fix (Aug 13, 2026) won't have a
    valid post-auction reading and are correctly excluded rather than
    guessed at -- real data only accumulates from today forward.
    GET /api/cas-auction-moves/<NIFTY|BANKNIFTY>/
    """
    def get(self, request, index_name):
        from .index_tracker import compute_cas_auction_moves
        name = index_name.upper()
        if name not in ("NIFTY", "BANKNIFTY"):
            return Response({"error": "index_name must be NIFTY or BANKNIFTY -- CAS doesn't apply to commodities"}, status=400)
        moves = compute_cas_auction_moves(name)
        return Response(clean_json({"index": name, "moves": moves}))


class IndexSignalView(APIView):
    """
    Aug 27 2026: current locked index option call(s) for NIFTY/
    BANKNIFTY, if Index Tracker's Bias has confirmed strongly enough to
    generate one -- see index_signal.py for the full strike-selection
    and SL/Target methodology (strike at the OI wall the Bias just
    confirmed, same ATR+delta math the stock Live Signals already use).
    Empty list (not an error) when Bias is currently Neutral for both,
    or nothing's fired yet this session.
    GET /api/index-signals/
    """
    def get(self, request):
        from . import index_signal
        calls = [c for c in (index_signal.get_locked_call("NIFTY"), index_signal.get_locked_call("BANKNIFTY")) if c]
        return Response(clean_json({"calls": calls, "count": len(calls)}))


class CommodityCurrentSymbolView(APIView):
    """
    Aug 27 2026: the live-resolved Fyers front-month symbol for a
    commodity (e.g. MCX:CRUDEOIL26AUGFUT) -- lets the frontend build a
    real Fyers chart link for Crude/Gold/Silver, the same way NIFTY/
    BANKNIFTY/VIX already can via their fixed INDEX symbols
    (MarketBanner.jsx couldn't do this before: the contract rolls
    monthly, and nothing exposed the CURRENT resolved string to it --
    hardcoding today's would go quietly stale next month).

    Deliberately reuses index_tracker.py's existing resolvers rather
    than re-deriving the rollover rule in JS, which would silently
    drift out of sync the next time either rule changes on the backend
    (exactly the kind of duplication this project has avoided
    elsewhere -- e.g. the two separate bullion-symbol resolvers already
    kept intentionally separate rather than one guessing at the
    other's job). CRUDEOIL/CRUDEOILM resolution is pure date math, no
    Fyers call; GOLD/GOLDM/SILVER/SILVERM's resolver does call Fyers
    but is already cached per-day (index_tracker._bullion_options_
    symbol_cache), so this is cheap on every call after the first each
    day. Returns {"symbol": None} rather than an error if nothing's
    resolvable right now (e.g. bullion with no live contract found in
    the probe window) -- same "don't guess" contract as the resolvers
    themselves already follow.
    GET /api/commodity-symbol/<CRUDEOIL|CRUDEOILM|GOLD|GOLDM|SILVER|SILVERM>/
    """
    def get(self, request, base_name):
        from .index_tracker import (
            COMMODITY_BASES, _NEAR_MONTHLY_BASES,
            _front_month_commodity_symbol, _front_month_bullion_symbol_with_options,
        )
        name = base_name.upper()
        if name not in COMMODITY_BASES:
            return Response({"error": f"base_name must be one of {list(COMMODITY_BASES)}"}, status=400)
        base = COMMODITY_BASES[name]
        try:
            symbol = (
                _front_month_commodity_symbol(base) if base in _NEAR_MONTHLY_BASES
                else _front_month_bullion_symbol_with_options(base)
            )
        except Exception as e:
            print(f"[CommodityCurrentSymbolView] {name} resolve failed: {e}")
            symbol = None
        return Response({"symbol": symbol})


class DailyBacktestStatusView(APIView):
    """
    Aug 27 2026: latest daily-backtest cycle's results -- backfill
    range, stock/NIFTY/BANKNIFTY summaries, PDF availability, any
    errors. Powers a dedicated frontend tab. All fields are None/empty
    until the first cycle has run at least once (either the scheduled
    close/morning run, or a manual trigger via DailyBacktestRunView).
    GET /api/daily-backtest/status/
    """
    def get(self, request):
        from .daily_backtest import get_last_run
        return Response(clean_json(get_last_run()))


class DailyBacktestRunView(APIView):
    """
    Aug 27 2026: manual 'Run Now' trigger for the same daily-backtest
    cycle the background worker runs automatically twice a day (the
    single-click option, alongside the automatic one). Fires the real
    checklist in a background thread and returns immediately -- the
    full cycle can take a while (real Fyers history calls per
    unresolved row, real PDF generation), so this doesn't hold the
    HTTP request open for it. Poll DailyBacktestStatusView (compare
    'started_at' against the time this was called) to see when it's
    finished.
    GET /api/daily-backtest/run/
    """
    def get(self, request):
        from .daily_backtest import run_daily_backtest_cycle_async
        run_daily_backtest_cycle_async(trigger="manual")
        return Response({"started": True, "message": "Daily backtest cycle started in the background -- poll /api/daily-backtest/status/ for results."})


class DailyBacktestReportDownloadView(APIView):
    """Download one of the latest daily-backtest cycle's PDFs.
    GET /api/daily-backtest/download/<stock|nifty|banknifty>/"""
    def get(self, request, report_type):
        from django.http import FileResponse, JsonResponse
        from .daily_backtest import get_last_run
        run = get_last_run()
        key_map = {"stock": "stock_pdf", "nifty": "nifty_pdf", "banknifty": "banknifty_pdf"}
        key = key_map.get(report_type.lower())
        if not key:
            return JsonResponse({"error": "report_type must be one of stock, nifty, banknifty"}, status=400)
        path = run.get(key)
        if not path or not os.path.exists(path):
            return JsonResponse({"error": f"No {report_type} report available yet -- run the daily backtest first."}, status=404)
        filename = os.path.basename(path)
        return FileResponse(open(path, 'rb'), as_attachment=True, filename=filename)


class DailyBacktestRangeView(APIView):
    """
    Aug 27 2026: on-demand backtest for a specific date range -- powers
    the date-range picker in the Daily Backtest tab. Pure preview
    computation: no PDF written, no Telegram send, doesn't touch the
    scheduled cycle's cached last-run status. Safe to call as often as
    someone drags the date picker.
    GET /api/daily-backtest/range/?start=YYYY-MM-DD&end=YYYY-MM-DD
    """
    def get(self, request):
        from .daily_backtest import run_range_backtest
        start = request.GET.get("start")
        end = request.GET.get("end")
        if not start or not end:
            return Response({"error": "start and end query params (YYYY-MM-DD) are required"}, status=400)
        try:
            result = run_range_backtest(start, end)
        except ValueError as e:
            return Response({"error": str(e)}, status=400)
        return Response(clean_json(result))


class DailyBacktestRangeReportView(APIView):
    """
    Aug 29 2026: the actual downloadable PDF for a specific date range
    -- DailyBacktestRangeView above only ever returns a JSON preview,
    by design. This is the real counterpart: reuses the exact same
    compute_metrics()/write_pdf_report() pipeline (Strategy Scorecard,
    R-Multiple, Long vs Short, every section) the full daily-cycle PDF
    already uses, scoped to just the requested window.
    GET /api/daily-backtest/range/report/?start=YYYY-MM-DD&end=YYYY-MM-DD
    """
    def get(self, request):
        from django.http import FileResponse, JsonResponse
        from .daily_backtest import run_range_report
        start = request.GET.get("start")
        end = request.GET.get("end")
        if not start or not end:
            return Response({"error": "start and end query params (YYYY-MM-DD) are required"}, status=400)
        try:
            path = run_range_report(start, end)
        except ValueError as e:
            return Response({"error": str(e)}, status=400)
        if not path or not os.path.exists(path):
            return JsonResponse({"error": f"No resolved stock trades between {start} and {end}."}, status=404)
        filename = os.path.basename(path)
        return FileResponse(open(path, 'rb'), as_attachment=True, filename=filename)


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

        # Aug 24 2026: switched to the options-aware resolver -- the
        # plain _front_month_bullion_symbol() validates only a futures
        # LTP, which a real live test showed can return a stale price
        # for an ALREADY-EXPIRED contract (MCX:GOLD26AUGFUT specifically
        # -- confirmed via the real Fyers symbol master that only Oct/
        # Dec are actually current). This variant additionally confirms
        # a real options chain exists for the candidate before using it.
        #
        # Aug 28 2026: added INDEX_SYMBOLS (NIFTY/BANKNIFTY) -- this view
        # never actually handled indices before. Every symbol NOT in
        # COMMODITY_BASES silently fell through to f"NSE:{sym}-EQ",
        # which is the WRONG Fyers symbol for an index (NSE:NIFTY50-
        # INDEX, not NSE:NIFTY-EQ) -- calling this with "NIFTY" would
        # have failed to resolve anything, not just returned imprecise
        # data. Reuses index_tracker.INDEX_SYMBOLS directly rather than
        # hardcoding the mapping a second time here.
        from .index_tracker import COMMODITY_BASES, _front_month_commodity_symbol, _front_month_bullion_symbol_with_options, _NEAR_MONTHLY_BASES, INDEX_SYMBOLS
        if sym in COMMODITY_BASES:
            base = COMMODITY_BASES[sym]
            fyers_symbol = _front_month_commodity_symbol(base) if base in _NEAR_MONTHLY_BASES else _front_month_bullion_symbol_with_options(base)
        elif sym in INDEX_SYMBOLS:
            fyers_symbol = INDEX_SYMBOLS[sym]
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
            "pcrVolume": oi.get("pcr_volume"),
            "maxPain": oi["max_pain"], "atmIv": oi["iv"], "atmStrike": oi["atm_strike"],
            "atmStraddlePrice": oi.get("atm_straddle_price"),
            "maxPainDistPct": oi.get("max_pain_dist_pct"),
            "support": oi["support"], "resistance": oi["resistance"],
            "oiBuildup": oi["oi_buildup"], "greeks": oi["greeks"],
            "totalCeOi": oi["ce_oi"], "totalPeOi": oi["pe_oi"],
            "ceOiChg": oi["ce_oi_chg"], "peOiChg": oi["pe_oi_chg"],
            "ceData": ce_data, "peData": pe_data,
        }))


class FiftyTwoWeekRangeView(APIView):
    """
    Aug 28 2026: real 52-week high/low PLUS a Bullish/Neutral/Bearish
    technical read, for a single F&O stock symbol -- built for the
    Watchlist redesign. Combined into one endpoint (not two) because a
    Watchlist row wants both together; no reason to make the frontend
    fire two separate requests per row for data that's always shown
    side by side.

    GET /api/52-week-range/<symbol>/ ->
      {"symbol", "high52w", "low52w", "technical": {"label","rsi","adx"} | null}

    Every field is null if it can't be resolved right now -- never a
    guessed range or a fabricated direction.
    """
    def get(self, request, symbol):
        sym = symbol.upper().replace(".NS", "")
        high52w, low52w = get_52_week_high_low(sym)
        technical = get_technical_signal(sym)
        return Response(clean_json({
            "symbol": sym, "high52w": high52w, "low52w": low52w,
            "technical": technical,
        }))


class BroaderIndicesView(APIView):
    """
    Aug 28 2026: real quotes for the broader NSE indices (Next 50, 100,
    Midcap 100, Smallcap 100) shown on Market View's Indices
    Performance table -- built for the Module 4 redesign.

    Deliberately its OWN endpoint, not folded into /api/market-summary/
    -- that endpoint is polled every 30s by several components
    (MarketBanner, MarketBreadth, SectorPerformance, the Sentiment
    gauge), all reading from the already-cached _stock_cache with zero
    added Fyers cost. fetch_broader_indices() makes a genuinely NEW
    live Fyers call every time it's invoked -- bolting that onto the
    already-heavily-polled endpoint would add a recurring live API
    call to every one of those unrelated components' polls too.

    GET /api/broader-indices/ -> {"indices": {name: {price, change,
    change_percent}, ...}} -- only includes indices that actually
    resolved; see fetch_broader_indices() for why some entries may be
    silently absent (unverified Fyers symbols, degrades gracefully).
    """
    def get(self, request):
        return Response(clean_json({"indices": fetch_broader_indices()}))


class StrategyBacktestRunView(APIView):
    """
    Aug 28 2026: triggers a background price-action strategy backtest
    across the F&O universe -- see strategy_backtest.py for the full
    engine and why OI-confirmation can't be included (only price-
    action conditions: rsi_min, rsi_max, adx_min).

    POST /api/strategy-backtest/run/
    Body: {"strategy": {"rsi_min": 40, "rsi_max": 65, "adx_min": 25},
           "days": 180}  -- days optional, defaults to 180
    Symbols default to the full FNO_STOCKS universe -- ~208 sequential
    Fyers History calls, runs as a background thread (see
    strategy_backtest.py's own module docstring), NOT synchronously --
    this endpoint returns immediately with the current run state; poll
    StrategyBacktestStatusView for progress and results.

    A trigger while a run is already in progress is a no-op (returns
    the ALREADY-RUNNING job's state, doesn't start a competing run --
    verified in strategy_backtest.py's own test suite).
    """
    def post(self, request):
        from .strategy_backtest import start_multi_symbol_backtest
        strategy = request.data.get("strategy") or {}
        days = int(request.data.get("days", 180))
        symbols = request.data.get("symbols") or FNO_STOCKS
        state = start_multi_symbol_backtest(symbols, strategy, days=days)
        return Response(clean_json({
            "running": state["running"],
            "started_at": state["started_at"],
            "symbols_total": state["symbols_total"],
        }))


class StrategyBacktestStatusView(APIView):
    """
    Aug 28 2026: poll the current/last price-action strategy backtest
    run. While running, returns progress only (no trades yet). Once
    complete, computes real metrics via backtest_signal_pnl.py's
    already-proven compute_metrics()/compute_capital_base()/
    compute_equity_curve() -- reusing that pipeline rather than a
    second, parallel aggregation implementation. Trades are scaled to
    a real rupee P&L first (scale_trades_to_lots()) -- the raw
    engine output is a per-SHARE price difference, not yet a real
    position-sized rupee figure.

    Aug 29 2026: scale_trades_to_lots() replaced the old fixed-capital
    version -- per explicit request, sizing now uses each symbol's
    real F&O lot size instead of a capital-derived share count. It
    also now returns an excluded count (trades dropped because their
    symbol had no resolvable live lot size) -- surfaced honestly below
    as excluded_trades, rather than silently vanishing from the trade
    count with no explanation.

    GET /api/strategy-backtest/status/
    """
    def get(self, request):
        from .strategy_backtest import get_strategy_backtest_status, scale_trades_to_lots, serialize_datetimes
        from .backtest_signal_pnl import compute_metrics, compute_capital_base, compute_equity_curve

        state = get_strategy_backtest_status()
        response = {
            "running": state["running"], "started_at": state["started_at"],
            "finished_at": state["finished_at"], "symbols_total": state["symbols_total"],
            "symbols_done": state["symbols_done"], "error": state["error"],
        }

        if state["trades"] is not None:
            scaled, excluded_trades = scale_trades_to_lots(state["trades"])
            capital_base = compute_capital_base(scaled)
            metrics = compute_metrics(scaled, capital_base)
            equity_curve = compute_equity_curve(scaled, capital_base)
            response["trade_count"] = len(scaled)
            response["excluded_trades"] = excluded_trades
            response["metrics"] = serialize_datetimes(metrics)
            response["capital_base"] = capital_base
            response["equity_curve"] = serialize_datetimes(equity_curve)
            response["trades"] = serialize_datetimes(scaled)
        return Response(clean_json(response))


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


def _compute_breadth(stocks):
    """
    Aug 28 2026: real market breadth computed from the F&O universe this
    project already scans every cycle (_stock_cache, FNO_STOCKS -- 208
    symbols) -- NOT full-NSE breadth. A full-market breadth reading
    (thousands of stocks) would need an entirely new, much larger
    batch-quote flow this project has never had; scoped and labeled
    honestly to the real ~208-stock F&O universe already being tracked
    here, rather than presenting a smaller sample as if it were the
    whole market.

    "Unchanged" is a real, exact 0.0% change_percent reading from
    Fyers, not a rounding artifact -- a stock that genuinely hasn't
    traded yet today (or traded at exactly yesterday's close) reads
    this way; not fabricated or estimated.
    """
    if not stocks:
        return {
            "advances": 0, "declines": 0, "unchanged": 0, "total": 0,
            "advances_pct": 0, "declines_pct": 0, "unchanged_pct": 0,
            "total_volume": 0,
        }
    advances = sum(1 for s in stocks if (s.get("change_percent") or 0) > 0)
    declines = sum(1 for s in stocks if (s.get("change_percent") or 0) < 0)
    unchanged = sum(1 for s in stocks if (s.get("change_percent") or 0) == 0)
    total = len(stocks)
    total_volume = sum(s.get("volume") or 0 for s in stocks)
    return {
        "advances": advances, "declines": declines, "unchanged": unchanged,
        "total": total,
        "advances_pct": round(advances / total * 100, 1) if total else 0,
        "declines_pct": round(declines / total * 100, 1) if total else 0,
        "unchanged_pct": round(unchanged / total * 100, 1) if total else 0,
        "total_volume": total_volume,
    }


def _compute_sector_performance(stocks):
    """
    Aug 28 2026: real sector-level aggregation from the F&O universe
    this project already scans -- each stock's own `sector` field
    (already set from the SECTORS mapping in _fetch_all_quotes_fyers)
    grouped and averaged. This is a SIMPLE AVERAGE of each sector's
    stocks' change_percent, NOT a market-cap-weighted index reading --
    this project has no market-cap data wired into the live scan to
    weight by, so a cap-weighted figure would just be invented. Stated
    plainly as a simple average, not presented as a precise sector
    index the way NIFTY IT/NIFTY AUTO etc. are on NSE's own site.

    Sorted by real performance (best first) -- matches how this is
    actually used (scanning for which sectors are leading today), not
    alphabetical order.
    """
    from collections import defaultdict
    by_sector = defaultdict(list)
    for s in stocks:
        sector = s.get("sector") or "Unknown"
        by_sector[sector].append(s)

    results = []
    for sector, group in by_sector.items():
        changes = [s.get("change_percent") or 0 for s in group]
        avg_chg = round(sum(changes) / len(changes), 2) if changes else 0
        advances = sum(1 for c in changes if c > 0)
        declines = sum(1 for c in changes if c < 0)
        results.append({
            "sector": sector,
            "change_percent": avg_chg,
            "advances": advances,
            "declines": declines,
            "stock_count": len(group),
        })
    results.sort(key=lambda r: r["change_percent"], reverse=True)
    return results


def _compute_market_movers(stocks, limit=10):
    """
    Aug 28 2026: real top gainers/losers from the F&O universe's
    current change_percent -- same 208-stock scan every other
    Dashboard-tier panel uses. No fabricated per-mover timestamp (the
    mockup's own Market Movers panel showed a time per row, but this
    project doesn't track "when a stock became a top mover" as its
    own event -- only the current live change% snapshot, which is
    what's returned here).
    """
    sorted_stocks = sorted(stocks, key=lambda s: s.get('change_percent') or 0, reverse=True)
    gainers = [s for s in sorted_stocks if (s.get('change_percent') or 0) > 0][:limit]
    losers = sorted(
        [s for s in sorted_stocks if (s.get('change_percent') or 0) < 0],
        key=lambda s: s.get('change_percent') or 0,
    )[:limit]
    return {
        "gainers": [{"symbol": s["symbol"], "price": s["price"], "change_percent": s["change_percent"]} for s in gainers],
        "losers": [{"symbol": s["symbol"], "price": s["price"], "change_percent": s["change_percent"]} for s in losers],
    }


def _classify_sentiment_band(chg):
    """Assigns one of 5 sentiment bands to a single stock's change% --
    thresholds are a reasonable first cut, not empirically tuned, same
    "watch and retune" status as every other threshold in this project
    (PCR bands, Bias vote margins, price-confirmation thresholds)."""
    if chg >= 2.0:
        return "Very Bullish"
    if chg >= 0.5:
        return "Bullish"
    if chg > -0.5:
        return "Neutral"
    if chg > -2.0:
        return "Bearish"
    return "Very Bearish"


_SENTIMENT_BAND_VALUE = {"Very Bullish": 100, "Bullish": 75, "Neutral": 50, "Bearish": 25, "Very Bearish": 0}
_SENTIMENT_BAND_ORDER = ["Very Bullish", "Bullish", "Neutral", "Bearish", "Very Bearish"]


def _compute_market_sentiment(stocks):
    """
    Aug 28 2026: real market sentiment gauge computed ENTIRELY from the
    F&O universe's own change_percent distribution -- the same
    208-stock data breadth/sector performance already use. Deliberately
    NOT a hand-mixed formula blending PCR/VIX/Bias with invented
    weights -- the overall 0-100 score is the mathematically CONSISTENT
    weighted average of the same 5-band breakdown returned alongside
    it (each band's fixed sentiment value x its real percentage of
    stocks), so the gauge number and the legend can never quietly
    drift apart into two independently-guessed figures. Verified by
    this module's own test suite: score == weighted_avg(bands), always.
    """
    if not stocks:
        return {"score": 50, "label": "Neutral", "bands": []}

    counts = {name: 0 for name in _SENTIMENT_BAND_ORDER}
    for s in stocks:
        chg = s.get("change_percent") or 0
        band = _classify_sentiment_band(chg)
        counts[band] += 1

    total = len(stocks)
    bands = []
    weighted_sum = 0
    for name in _SENTIMENT_BAND_ORDER:
        count = counts[name]
        pct = round(count / total * 100, 1) if total else 0
        bands.append({"label": name, "count": count, "pct": pct})
        weighted_sum += _SENTIMENT_BAND_VALUE[name] * count

    score = round(weighted_sum / total, 1) if total else 50

    if score >= 80:
        label = "Very Bullish"
    elif score >= 60:
        label = "Bullish"
    elif score >= 40:
        label = "Neutral"
    elif score >= 20:
        label = "Bearish"
    else:
        label = "Very Bearish"

    return {"score": score, "label": label, "bands": bands}


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

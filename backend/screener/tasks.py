from celery import shared_task
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from django.utils import timezone
from datetime import timedelta
import pandas as pd
import numpy as np

from .models import Stock, StockSnapshot, Signal, MarketOverview
from .scoring_engine import ScoringEngine, PredictionEngine
from .fyers_client import is_authenticated, get_quotes, get_option_analytics
from .views import _fyers_history_df


def to_fyers_symbol(stock):
    return f"NSE:{stock}-EQ"


@shared_task
def scan_all_stocks():
    """Run every 5 minutes during market hours."""
    engine = ScoringEngine()
    pred_engine = PredictionEngine()
    stocks = Stock.objects.filter(is_fno=True)
    signals_created = 0
    failed_stocks = []

    # Fyers only -- no Yahoo/yfinance fallback anywhere in this pipeline.
    fyers_connected = is_authenticated()
    print(f"[SCANNER] Fyers connected: {fyers_connected}")

    if not fyers_connected:
        print("[SCANNER] Fyers not authenticated -- skipping this run entirely (no Yahoo fallback)")
        return {"signals_created": 0, "failed_stocks": ["Fyers not authenticated"]}

    for stock in stocks:
        try:
            quote = get_quotes([to_fyers_symbol(stock.symbol)])
            if not (quote and quote.get("s") == "ok" and quote.get("d")):
                failed_stocks.append(f"{stock.symbol}: no Fyers quote")
                continue
            v = quote["d"][0].get("v", {})
            ltp = v.get("lp", 0)
            prev_close = v.get("prev_close_price", ltp)
            volume = int(v.get("volume", 0))  # was v.get("v", 0) -- wrong key, always read 0
            change_pct = round(((ltp - prev_close) / prev_close) * 100, 2) if prev_close else 0

            hist = _fyers_history_df(stock.symbol, days=100)
            if hist is None or len(hist) < 20:
                failed_stocks.append(f"{stock.symbol}: empty Fyers history")
                continue

            avg_volume = int(hist['Volume'].tail(20).mean()) if not hist.empty else volume

            # Technicals from history
            rsi = calculate_rsi(hist['Close']) if not hist.empty else 50
            adx = calculate_adx(hist) if not hist.empty else 20
            macd_val, macd_sig = calculate_macd(hist['Close']) if not hist.empty else (0, 0)
            ema_20 = hist['Close'].ewm(span=20).mean().iloc[-1] if not hist.empty else ltp
            ema_50 = hist['Close'].ewm(span=50).mean().iloc[-1] if not hist.empty else ltp
            vwap = calculate_vwap(hist) if not hist.empty else ltp
            atr = calculate_atr(hist, period=14) if not hist.empty else ltp * 0.015

            # Save snapshot
            StockSnapshot.objects.create(
                stock=stock, ltp=ltp, change_pct=change_pct,
                volume=volume, avg_volume=avg_volume,
                rsi=rsi, adx=adx, macd=macd_val,
                ema_20=ema_20, ema_50=ema_50, vwap=vwap
            )

            # Real Fyers option-chain data. This used to be:
            #   pcr = np.random.uniform(0.4, 1.6)
            #   max_pain = round(ltp / 50) * 50   # not max pain, just nearest round number
            #   iv = np.random.uniform(20, 60)
            #   ce_oi_chg = np.random.uniform(-500000, 500000)
            # i.e. every number below was random regardless of what Fyers
            # actually reported. Falls back to a clearly-labeled proxy
            # (nearest strike instead of real max pain, historical vol
            # instead of options IV, zero OI change) only when Fyers has no
            # option chain for this symbol / isn't authenticated -- never a
            # random number standing in for a real one.
            oi = None
            if fyers_connected:
                try:
                    oi = get_option_analytics(to_fyers_symbol(stock.symbol), strikecount=10)
                except Exception as oe:
                    print(f"[SCANNER] Option chain failed for {stock.symbol}: {oe}")

            if oi:
                pcr = oi.get('pcr') or 1.0
                max_pain = oi.get('max_pain') or (round(ltp / 50) * 50)
                iv = oi.get('iv') or (float(np.std(hist['Close'].pct_change().dropna()) * np.sqrt(252) * 100) if not hist.empty else 25.0)
                ce_oi_chg = oi.get('ce_oi_chg') or 0
                pe_oi_chg = oi.get('pe_oi_chg') or 0
                oi_buildup_label = oi.get('oi_buildup') or 'Unclear'
            else:
                pcr = 1.0
                max_pain = round(ltp / 50) * 50  # proxy: nearest round strike, NOT real max pain
                iv = float(np.std(hist['Close'].pct_change().dropna()) * np.sqrt(252) * 100) if not hist.empty else 25.0
                ce_oi_chg = 0
                pe_oi_chg = 0
                oi_buildup_label = 'No live option data'

            data = {
                'ltp': ltp, 'change_pct': change_pct,
                'volume': volume, 'avg_volume': avg_volume,
                'rsi': rsi, 'adx': adx, 'macd': macd_val, 'macd_signal': macd_sig,
                'ema_20': ema_20, 'ema_50': ema_50, 'vwap': vwap,
                'pcr': pcr, 'max_pain': max_pain, 'iv': iv,
                'ce_oi_chg': ce_oi_chg, 'pe_oi_chg': pe_oi_chg,
                'news_sentiment_score': 0.0,
            }

            score, breakdown = engine.calculate_score(data)
            grade = engine.get_grade(score)
            signal_type, option_type = engine.get_signal(score, change_pct, pcr, rsi, adx)
            entry, sl, t1, t2, t3, rr, strike = engine.calculate_targets(ltp, option_type, atr=atr)
            pred = pred_engine.predict({**data, 'score': score})

            Signal.objects.update_or_create(
                stock=stock, is_active=True,
                defaults={
                    'score': score, 'grade': grade, 'signal_type': signal_type,
                    'option_type': option_type, 'strike': strike,
                    'entry': entry, 'stop_loss': sl, 'target_1': t1,
                    'target_2': t2, 'target_3': t3, 'risk_reward': rr,
                    'confidence': min(score + 10, 95), 'pcr': pcr,
                    'max_pain': max_pain, 'iv': iv,
                    'oi_buildup': 'CE writing' if ce_oi_chg > pe_oi_chg else 'PE writing',
                    'trend': 'UP' if change_pct > 0 else 'DOWN',
                    'expires_at': timezone.now() + timedelta(days=3),
                    'prediction_1d': pred['prediction_1d'],
                    'prediction_3d': pred['prediction_3d'],
                    'prediction_confidence': pred['confidence'],
                }
            )
            signals_created += 1

        except Exception as e:
            failed_stocks.append(f"{stock.symbol}: {str(e)[:50]}")
            continue

    print(f"[SCANNER] Created/Updated {signals_created} signals. Failed: {len(failed_stocks)}")
    if failed_stocks:
        print(f"[SCANNER] Failed stocks: {failed_stocks[:10]}")

    try:
        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)(
            "screener", {"type": "signal_update", "data": {"refreshed": True, "count": signals_created}}
        )
    except Exception as e:
        print(f"[SCANNER] WebSocket broadcast error: {e}")

    return f"Scanned {signals_created} stocks, {len(failed_stocks)} failed"


@shared_task
def update_market_overview():
    try:
        if not is_authenticated():
            print("[MARKET] Fyers not authenticated -- skipping overview update (no Yahoo fallback)")
            return

        resp = get_quotes(["NSE:NIFTY50-INDEX", "NSE:NIFTYBANK-INDEX"])
        if not resp or resp.get('s') != 'ok':
            print("[MARKET] Fyers quotes failed for indices")
            return
        quotes = {item['n']: item.get('v', {}) for item in resp.get('d', []) if item.get('s') == 'ok'}
        nifty_v = quotes.get("NSE:NIFTY50-INDEX", {})
        bank_v = quotes.get("NSE:NIFTYBANK-INDEX", {})
        if not nifty_v.get('lp') or not bank_v.get('lp'):
            print("[MARKET] Fyers returned no usable index data")
            return
        nifty_spot = nifty_v['lp']
        nifty_change = nifty_v.get('chp', 0)
        banknifty_spot = bank_v['lp']
        banknifty_change = bank_v.get('chp', 0)

        total_signals = Signal.objects.filter(is_active=True).count()
        buy_signals = Signal.objects.filter(is_active=True, signal_type__in=['BUY_NOW', 'BUY']).count()
        sell_signals = Signal.objects.filter(is_active=True, signal_type='SELL').count()

        # Average PCR across active signals that have a real one, instead
        # of a hardcoded 1.08 regardless of market conditions.
        pcr_values = list(Signal.objects.filter(is_active=True, pcr__isnull=False).values_list('pcr', flat=True))
        total_pcr = round(sum(pcr_values) / len(pcr_values), 2) if pcr_values else None

        MarketOverview.objects.create(
            nifty_spot=nifty_spot, nifty_change=nifty_change,
            banknifty_spot=banknifty_spot, banknifty_change=banknifty_change,
            total_pcr=total_pcr, total_signals=total_signals,
            buy_signals=buy_signals, sell_signals=sell_signals
        )

        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)(
            "market_overview", {"type": "overview_update", "data": {"refreshed": True}}
        )
    except Exception as e:
        print(f"[MARKET] Overview error: {e}")


# ========== TECHNICAL INDICATORS ==========

def calculate_rsi(prices, period=14):
    delta = prices.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs)).iloc[-1]

def calculate_adx(df, period=14):
    high, low, close = df['High'], df['Low'], df['Close']
    plus_dm = high.diff()
    minus_dm = -low.diff()
    plus_dm[plus_dm < 0] = 0
    minus_dm[minus_dm < 0] = 0
    tr = pd.concat([high - low, abs(high - close.shift()), abs(low - close.shift())], axis=1).max(axis=1)
    atr = tr.rolling(period).mean()
    plus_di = 100 * (plus_dm.rolling(period).mean() / atr)
    minus_di = 100 * (minus_dm.rolling(period).mean() / atr)
    dx = (abs(plus_di - minus_di) / (plus_di + minus_di)) * 100
    return dx.rolling(period).mean().iloc[-1]

def calculate_macd(prices, fast=12, slow=26, signal=9):
    ema_fast = prices.ewm(span=fast).mean()
    ema_slow = prices.ewm(span=slow).mean()
    macd = ema_fast - ema_slow
    macd_signal = macd.ewm(span=signal).mean()
    return macd.iloc[-1], macd_signal.iloc[-1]

def calculate_vwap(df):
    typical = (df['High'] + df['Low'] + df['Close']) / 3
    vwap = (typical * df['Volume']).cumsum() / df['Volume'].cumsum()
    return vwap.iloc[-1]

def calculate_atr(df, period=14):
    high, low, close = df['High'], df['Low'], df['Close']
    tr = pd.concat([high - low, abs(high - close.shift()), abs(low - close.shift())], axis=1).max(axis=1)
    return tr.rolling(window=period).mean().iloc[-1]
"""
F&O Sniper Scoring Engine v3.0
Calculates scores, grades, signals, and predictions for NSE F&O stocks.
"""
import numpy as np
from datetime import datetime, timedelta

class ScoringEngine:
    """Core scoring algorithm matching your WARRENER screenshot logic."""

    def __init__(self):
        self.weights = {
            'price_action': 0.25,
            'volume': 0.20,
            'technical': 0.20,
            'options': 0.20,
            'sentiment': 0.15,
        }

    def calculate_score(self, data):
        """
        data dict expected keys:
        - ltp, change_pct, volume, avg_volume
        - rsi, adx, macd, ema_20, ema_50, vwap
        - pcr, max_pain, iv, ce_oi_chg, pe_oi_chg
        - news_sentiment_score (-1 to 1)
        - sector_strength
        """
        scores = {}

        # 1. Price Action Score (0-25)
        pa_score = 0
        change = abs(data.get('change_pct', 0))
        if change > 3:
            pa_score = 25
        elif change > 2:
            pa_score = 20
        elif change > 1:
            pa_score = 15
        elif change > 0.5:
            pa_score = 10
        else:
            pa_score = 5

        # Trend alignment bonus
        if data.get('ltp', 0) > data.get('ema_20', 0) > data.get('ema_50', 0):
            pa_score += 5
        scores['price_action'] = min(pa_score, 25)

        # 2. Volume Score (0-20)
        vol_ratio = data.get('volume', 1) / max(data.get('avg_volume', 1), 1)
        if vol_ratio > 3:
            vol_score = 20
        elif vol_ratio > 2:
            vol_score = 16
        elif vol_ratio > 1.5:
            vol_score = 12
        elif vol_ratio > 1:
            vol_score = 8
        else:
            vol_score = 4
        scores['volume'] = vol_score

        # 3. Technical Score (0-20)
        tech_score = 0
        rsi = data.get('rsi', 50)
        adx = data.get('adx', 20)

        # RSI logic
        if 40 <= rsi <= 60:
            tech_score += 8
        elif 30 <= rsi < 40 or 60 < rsi <= 70:
            tech_score += 12
        elif rsi < 30 or rsi > 70:
            tech_score += 16

        # ADX (trend strength)
        if adx > 40:
            tech_score += 4
        elif adx > 25:
            tech_score += 3
        else:
            tech_score += 1

        # MACD
        if data.get('macd', 0) > 0 and data.get('macd_signal', 0) > 0:
            tech_score += 4
        elif data.get('macd', 0) > 0:
            tech_score += 2

        scores['technical'] = min(tech_score, 20)

        # 4. Options Analytics Score (0-20)
        opt_score = 0
        pcr = data.get('pcr', 1.0)

        # PCR logic
        if pcr < 0.7:
            opt_score += 12  # Extreme call writing = bullish
        elif pcr < 1.0:
            opt_score += 8
        elif pcr > 1.3:
            opt_score += 12  # Extreme put writing = bearish (for PE signals)
        elif pcr > 1.0:
            opt_score += 8
        else:
            opt_score += 5

        # Max Pain distance
        max_pain = data.get('max_pain', 0)
        ltp = data.get('ltp', 0)
        if max_pain > 0:
            mp_dist = abs(ltp - max_pain) / max_pain * 100
            if mp_dist < 1:
                opt_score += 4
            elif mp_dist < 2:
                opt_score += 2

        # OI Buildup
        ce_chg = data.get('ce_oi_chg', 0)
        pe_chg = data.get('pe_oi_chg', 0)
        if ce_chg > pe_chg * 2:
            opt_score += 4  # CE writing dominance
        elif pe_chg > ce_chg * 2:
            opt_score += 4  # PE writing dominance

        scores['options'] = min(opt_score, 20)

        # 5. Sentiment Score (0-15)
        sent_score = 0
        news_sent = data.get('news_sentiment_score', 0)
        if news_sent > 0.3:
            sent_score = 15
        elif news_sent > 0.1:
            sent_score = 10
        elif news_sent > -0.1:
            sent_score = 7
        elif news_sent > -0.3:
            sent_score = 4
        else:
            sent_score = 2
        scores['sentiment'] = sent_score

        # Calculate total
        total = sum(scores.values())
        return min(total, 100), scores

    def get_grade(self, score):
        if score >= 90: return 'A+'
        if score >= 80: return 'A'
        if score >= 70: return 'B+'
        if score >= 60: return 'B'
        if score >= 50: return 'C+'
        if score >= 40: return 'C'
        return 'D'

    def get_signal(self, score, change_pct, pcr, rsi, adx):
        """Determine signal type based on composite analysis."""
        if score >= 85 and adx > 25:
            if change_pct > 1 and pcr < 1.0:
                return 'BUY_NOW', 'CE'
            elif change_pct < -1 and pcr > 1.0:
                return 'BUY_NOW', 'PE'
            elif change_pct > 0.5:
                return 'BUY', 'CE'
            else:
                return 'BUY', 'PE'
        elif score >= 70:
            if change_pct > 0.5 and pcr < 1.0:
                return 'BUY', 'CE'
            elif change_pct < -0.5 and pcr > 1.0:
                return 'BUY', 'PE'
            else:
                return 'WATCHLIST', 'CE'
        elif score >= 50:
            return 'WATCHLIST', 'CE' if change_pct > 0 else 'PE'
        elif score < 40 and rsi > 80:
            return 'SELL', 'PE'
        elif score < 40 and rsi < 20:
            return 'SELL', 'CE'
        else:
            return 'NEUTRAL', 'CE'

    def calculate_targets(self, ltp, signal_type, atr=None):
        """Calculate Entry, SL, T1, T2, T3, R:R using REAL ATR."""
        # If no ATR provided or ATR is too small, use 1.5% of price as minimum
        if atr is None or atr < ltp * 0.005:
            atr = ltp * 0.015  # 1.5% default stop for stocks without ATR
        
        if signal_type == 'CE':
            entry = round(ltp, 1)
            sl = round(ltp - (atr * 1.5), 1)
            t1 = round(ltp + (atr * 1.5), 1)
            t2 = round(ltp + (atr * 2.5), 1)
            t3 = round(ltp + (atr * 3.5), 1)
        else:
            entry = round(ltp, 1)
            sl = round(ltp + (atr * 1.5), 1)
            t1 = round(ltp - (atr * 1.5), 1)
            t2 = round(ltp - (atr * 2.5), 1)
            t3 = round(ltp - (atr * 3.5), 1)

        risk = abs(entry - sl)
        reward = abs(t1 - entry)
        rr = f"{reward/risk:.1f}:1" if risk > 0 else "N/A"

        # Round strike to nearest standard NSE option strike
        if ltp > 20000:          # Index-like
            strike = round(ltp / 100) * 100
        elif ltp > 10000:        # Large index
            strike = round(ltp / 50) * 50
        elif ltp > 3000:         # High-priced stocks (TCS, etc)
            strike = round(ltp / 20) * 20
        elif ltp > 1000:         # Mid-priced stocks
            strike = round(ltp / 10) * 10
        else:                    # Low-priced stocks
            strike = round(ltp / 5) * 5

        return entry, sl, t1, t2, t3, rr, strike


class PredictionEngine:
    """Predicts 1-day and 3-day price movement probability."""

    def __init__(self):
        self.lookback_days = 20

    def predict(self, data):
        """
        Returns dict with:
        - prediction_1d: predicted % move next day
        - prediction_3d: predicted % move next 3 days
        - confidence: 0-100
        - direction: 'UP', 'DOWN', 'SIDEWAYS'
        """
        score = data.get('score', 50)
        change_pct = data.get('change_pct', 0)
        pcr = data.get('pcr', 1.0)
        rsi = data.get('rsi', 50)
        adx = data.get('adx', 20)
        vol_ratio = data.get('volume', 1) / max(data.get('avg_volume', 1), 1)
        macd = data.get('macd', 0)

        # Base prediction from score and momentum
        if score >= 80 and change_pct > 2 and adx > 30:
            pred_1d = change_pct * 0.3
            pred_3d = change_pct * 0.8
            direction = 'UP' if change_pct > 0 else 'DOWN'
            conf = min(score + 10, 95)
        elif score >= 70 and change_pct > 1:
            pred_1d = change_pct * 0.25
            pred_3d = change_pct * 0.6
            direction = 'UP' if change_pct > 0 else 'DOWN'
            conf = score
        elif score >= 60:
            pred_1d = change_pct * 0.2
            pred_3d = change_pct * 0.4
            direction = 'UP' if change_pct > 0 else 'DOWN'
            conf = score - 10
        elif score < 40:
            pred_1d = -change_pct * 0.15 if change_pct > 0 else change_pct * 0.15
            pred_3d = -change_pct * 0.3 if change_pct > 0 else change_pct * 0.3
            direction = 'DOWN' if change_pct > 0 else 'UP'  # Reversal
            conf = 60
        else:
            pred_1d = 0
            pred_3d = 0
            direction = 'SIDEWAYS'
            conf = 40

        # Adjust based on PCR
        if pcr < 0.7 and direction == 'UP':
            pred_1d *= 1.2
            pred_3d *= 1.3
            conf += 5
        elif pcr > 1.3 and direction == 'DOWN':
            pred_1d *= 1.2
            pred_3d *= 1.3
            conf += 5

        # Volume confirmation
        if vol_ratio > 2:
            conf += 5
            pred_1d *= 1.1

        # RSI extreme reversal
        if rsi > 75 and direction == 'UP':
            pred_1d *= 0.5
            conf -= 10
        elif rsi < 25 and direction == 'DOWN':
            pred_1d *= 0.5
            conf -= 10

        return {
            'prediction_1d': round(pred_1d, 2),
            'prediction_3d': round(pred_3d, 2),
            'confidence': min(conf, 100),
            'direction': direction,
        }

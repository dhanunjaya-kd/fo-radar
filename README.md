## F&O Radar — Full Stack

Full-stack NSE F&O options scanner: WARRENER-style dark UI, live signal scoring, day-wise SL/Target outcome tracking, a day-wise Bias-accuracy backtest for NIFTY/BANKNIFTY, a live Excel OI dashboard mirror, paper trading, PnL tracking, and 1–3 day price predictions.

## Architecture

```
fo-sniper-fullstack/
├── backend/          Django + Channels + Celery + PostgreSQL
│   ├── fno_sniper/   Core Django config
│   ├── screener/     Scoring engine, signal logging, Index Tracker, Bias backtest, live OI Excel dashboard
│   ├── options/      Option chain analytics
│   ├── fyers_api/    Fyers v3 API integration
│   ├── news/         NewsAPI + sentiment
│   ├── trading/      Paper trading + PnL + Telegram
│   └── backtest/     Not currently used — see note under Features
└── frontend/         Vite + React + Tailwind
    └── src/
        ├── components/  SignalList, Watchlist, Analytics, IndexTracker, SniperCard, etc.
        ├── hooks/       useSignals (live) — useWebSocket exists but isn't wired to anything
        └── services/    API helpers
```

## Quick Start

The full stack below is what this project is built for, but day to day it's only ever actually been run with just the two commands under "Minimal" — the Redis/Celery/uvicorn steps are for scheduled tasks and the WebSocket layer, neither of which the running app currently depends on.

**Minimal — what's actually been used and tested:**
```bash
cd backend && python manage.py runserver
cd frontend && npm run dev
# Open http://localhost:5173
```

**Full path — adds Celery Beat scheduled tasks + a working WebSocket layer:**
```bash
cd backend
pip install -r requirements.txt
# Setup .env (copy from .env.example)
python manage.py migrate
python manage.py shell < seed_stocks.py
redis-server --daemonize yes
celery -A fno_sniper worker -l info --detach
celery -A fno_sniper beat -l info --detach
python -m uvicorn fno_sniper.asgi:application --host 0.0.0.0 --port 8000 --reload
```
```bash
cd frontend
npm install
npm run dev
# Open http://localhost:5173
```

### Deploy
- **Frontend**: `cd frontend && vercel --prod`
- **Backend**: Connect Render to this repo, use `render.yaml`

Neither of these has actually been deployed yet — these are the intended commands for whenever that happens, not a claim that it's live somewhere.

## WebSocket Endpoints
```
ws://localhost:8000/ws/screener/          → Live signals
ws://localhost:8000/ws/options/RELIANCE/  → Options dive
ws://localhost:8000/ws/alerts/            → Alert feed
ws://localhost:8000/ws/market-overview/   → Market stats
```
These are real, implemented routes (Django Channels, previously debugged — a broken import that used to crash the ASGI app entirely was already fixed here). Two things worth knowing: they need Redis running (the "full path" above, not the minimal one), and the frontend doesn't currently open a connection to any of them. Every tab you actually see gets its data by polling the REST endpoints below every 30–60 seconds, not via push.

## REST API Endpoints
These are the ones the running frontend actually calls:
```
GET  /api/sniper-only/                             → Live Signals tab
GET  /api/market-summary/                          → Top NIFTY/BANKNIFTY/VIX/PCR banner
GET  /api/signals/                                 → Watchlist tab
GET  /api/option-analytics/<symbol>/               → OI Analytics tab
GET  /api/index-tracker/<NIFTY|BANKNIFTY>/         → Index Tracker tab
GET  /api/index-tracker/<NIFTY|BANKNIFTY>/export/  → Download today's index snapshot log
GET  /api/index-backtest/<NIFTY|BANKNIFTY>/        → Day-wise Bias-accuracy backtest
GET  /api/index-backtest/<NIFTY|BANKNIFTY>/export/ → Download the backtest report
GET  /api/signals/export/                          → Download today's signal log
GET  /api/signals/export/dates/                    → List of past dates with a log
GET  /api/signals/export/<date>/                   → Download a past day's signal log
GET  /api/stock-detail/<symbol>/                   → Individual stock detail
GET  /api/fyers-status/                            → Fyers auth status
GET  /api/news/                                    → News feed
```
A separate, parallel set (`/api/screener/`, `/api/options/`, `/api/trading/`, `/api/news/` via `include()`) is also registered in `urls.py`. Those aren't what the frontend calls — treat the list above as the source of truth for how the app actually works. One specific note on `/api/news/`: `screener`'s own `NewsView` is registered ahead of the separate `news` app's `include()` at the identical path, so it's `screener`'s view that actually serves this endpoint — the dedicated `news` app's own list view is unreachable dead code as a result (only its `/fetch/` sub-path is genuinely reachable, since that path doesn't collide).

## Live OI Excel Dashboard
A real-time NIFTY/BANKNIFTY/SENSEX option-chain mirror, driven by `xlwings` against a genuinely visible, live Excel window — not a static export. Runs inside the same background scan cycle as the rest of the scanner (`screener/oi_live_dashboard.py`, wired into `screener/views.py`'s worker).
```
signal_logs/<date>/oi_live_dashboard_<date>.xlsx
```
- A fresh file every trading day, in that day's own log folder — nothing accumulates across days in one growing file.
- Per-symbol sheets (NIFTY, BANKNIFTY, SENSEX), each a continuously-appending table (Time, Value, Call/Put Sum, Difference, Call/Put Boundary, Call/Put ITM) with a fixed boundary panel off to the side — showing the latest Call/Put Boundary strikes, Bias, and PCR — that never interrupts the growing table.
- Colour-coded by real movement (green/red on genuine up/down vs. the previous row), not a static palette.
- Requires `xlwings` and a real Excel install (Windows) — silently disabled with a one-time log line if either isn't available, never a fake/empty dashboard.

## Sniper v3 — noise control + intraday trigger (Oct 2 2026)

Oct 1 2026 produced 38 live calls in one session. Root causes found by analysing the repo's own logs (364 logged calls, 18 days, 165 resolved to Target/SL — see the docstring of `backend/screener/sniper_v3.py` for the numbers):

- **There was no intraday timing.** RSI/MACD/ADX/"VWAP" are all computed on *daily* candles (VWAP is a 100-day average), so the same stocks re-qualified every cycle and calls arrived in bursts.
- **Churn was logged as new calls.** The old `[:8]` slice re-sorted on near-tied confidence; stocks rotated in/out and each rotation became a row (11 of Oct 1's 38 rows are "Expired" for that reason alone).
- **RSI was rewarded in 40–65 for both directions.** SELL calls with RSI ≥ 50 won 35% vs 79% below 50. BUY calls with ADX ≤ 35 had −0.12R gross expectancy vs +0.50R above 35.
- **Cost, not signal quality, was the biggest unmodelled drag.** Option R:R is ~0.89 and the spread gate allowed 15% of premium (~0.6R round trip) against a measured +0.19R gross edge.

What changed (all reversible by env var — see `backend/.env.example`):

| Layer | Behaviour | Default |
|---|---|---|
| Directional RSI, BUY-ADX | entry gates (never remove an already-active call) | enforced |
| Cost-to-risk | reject legs whose round-trip spread > 0.30R | enforced |
| SignalBook | sticky slots, 1 call/symbol/day, ≤2 per sector, ≤3 new per 30 min, entries 09:15–14:00, 150-min hold cap | enforced |
| Intraday trigger | session-VWAP + opening-range events on completed 5m candles, fetched only for shortlisted names | **shadow** |

Check it against your own logs (no network needed):

```bash
cd backend
python -m screener.sniper_replay                          # all logged days: legacy vs v3 call counts / outcomes
python -m screener.sniper_replay --file <signals_xxx.xlsx>
python -m screener.sniper_replay --trigger-report         # after a few shadow sessions: TRIGGERED vs NO_TRIGGER outcomes
python -m unittest screener.tests.test_sniper_v3
```

Replay on the repo's logs + Oct 1: 358 calls → 152 with the structural rules alone, → 81 with the RSI/BUY-ADX gates (those two were fitted on the same data, so treat that last step as in-sample). Oct 1 alone: 38 → 14. The intraday trigger, cost gate and relative-RVOL cannot be replayed (5m history and bid/ask are not logged); `sniper_v3_trigger_<date>.csv` and the new per-signal fields (`trigger_state`, `cost_to_risk`, `rvol_relative`, `rank_score`) collect that evidence going forward. Flip `SNIPER_TRIGGER_MODE=enforce` only once `--trigger-report` shows TRIGGERED beating NO_TRIGGER across several *days* — calls inside one day are strongly correlated.

## Chart Patterns tab

The Scanner and Charts tabs were removed (Oct 2 2026) — this tab plus the Fundamental Research page (price chart + fundamentals) replace them. A reference-style pattern scanner: filters (family, direction, status, shape quality, formed-within, volume-confirmed), pattern cards with the fitted trendlines drawn on daily candles plus Breakout / Target / Stop / R:R, and a detail panel with a large chart and the pattern's definition.

- **Detector** (`backend/screener/chart_patterns.py`): ATR-scaled swing pivots, then double/triple top & bottom, head & shoulders (+inverse), rising/falling wedge, ascending/descending/symmetrical triangle, rectangle, ascending/descending channel, bull/bear flag & pennant, rounded top/bottom, cup & handle. Bearish shapes are detected once and the bullish ones by mirroring the price series, so the two sides are exactly symmetric. Pivots must be *confirmed*, so a pattern shows up a few bars after a human might call it (no repainting).
- **Scan** (`pattern_scanner.py`): press *Scan now / Scan again* for a universe. It fetches ~1 year (365 days, ~250 bars) of daily candles per stock from Fyers, **one paced call per symbol, one scan at a time**, and waits while the rate-limit breaker is open. A cold Nifty 500 scan takes a few minutes; All stocks (~2,400) much longer. Results persist to `backend/runtime/chart_patterns_<universe>.json` (git-ignored) so the tab works immediately after a restart.
- **Detail panel**: large chart with numbered touches, span bracket, the break, target zone and volume strip; the pattern's definition and a plain-language reading of this specific one; candlestick confluence on the break candle; and **base rates**.
- **Base rates** (`pattern_backtest.py`): during a scan the detector is re-run on growing prefixes of each stock's history. A pattern becomes an instance the first time it is *Confirmed* with a fresh break; entry is that bar's close, target/stop are the levels printed then, and the outcome is whichever is touched first within 40 sessions (same-bar touches count as the stop). Rates are only shown from 15+ instances and are labelled for what they are: this universe, about a year, gross of costs, one market regime. They are **not** a multi-decade statistic.
- **Search**: a stock with no pattern in the scan gets an *Analyze now* button (`GET /api/chart-patterns/symbol/<SYMBOL>/`) that runs the detector on that one stock in relaxed mode and says plainly whether it found nothing or only weaker candidates (flagged *Below the quality bar*).
- **API**: `GET /api/chart-patterns/` (server-side filter / sort / paging; also returns `base_rates`), `POST /api/chart-patterns/scan/`, `GET /api/chart-patterns/scan/?universe=`, `GET /api/chart-patterns/symbol/<SYMBOL>/`.
- **Honest limits**: daily timeframe only (weekly/monthly need multi-year history that isn't fetched). Detection on closes is subjective, and **no success rate is implied — these shapes are not back-tested here**. As a sanity check, `test_chart_patterns.py` runs the detector on pure random walks: on 250-bar walks it still flags a Fair-or-better shape in ~30% of them (Strong-or-better ~17%, Textbook ~3%) and fails if a future change makes it noisier. The UI shows this baseline in the detail panel. Treat a card as a chart worth looking at, not a signal.

```bash
cd backend && python -m unittest screener.tests.test_chart_patterns screener.tests.test_pattern_scanner screener.tests.test_pattern_backtest
```

## Shadow Candidate Testing (A–J)
Ten pass/reject filters run silently alongside every live signal, purely observational — none of them gate a real trade. Each is a hypothesis about a possible future improvement to the live Sniper logic (a faster trend check, a liquidity gate, re-validating an existing scoring component against fresh data, etc.), logged to its own Excel columns per signal. A candidate is only ever considered for promotion to a real, live gate once it clears an explicit evidence bar — 30+ resolved signals, 10+ real wins *and* 10+ real losses in its PASS subset, and a proven 1+ percentage point improvement in win rate over the baseline — checked automatically, never eyeballed. As of today, none have cleared that bar.

## Features
- ✅ WARRENER-style dark green UI
- ✅ 208 NSE F&O stocks
- ✅ Score/Grade/Signal engine
- ✅ 1-day & 3-day price predictions
- ✅ Paper trading mode
- ✅ PnL tracker
- ✅ Day-wise SL/Target outcome tracking, per-day Excel logs
- ✅ Day-wise NIFTY/BANKNIFTY Bias-accuracy backtest, downloadable from Index Tracker
- ✅ Live OI Excel dashboard (NIFTY/BANKNIFTY/SENSEX, xlwings-driven, per-day file) — see section above
- ✅ Shadow candidate testing framework (A–J) — see section above
- ✅ News sentiment analysis
- ✅ Telegram alerts
- ✅ Fyers v3 API (SHA256 auth)
- ⚠️ WebSocket infrastructure exists (Channels) but isn't wired to the frontend — live-feeling updates currently come from polling, not push
- ✅ OI Analytics charts
- ✅ Responsive design
- ⛔ `backend/backtest/` app — leftover from an earlier codebase generation, points at an Excel file that doesn't exist on disk, its DB table was never migrated. Not the same thing as the Bias backtest above, which is real.

## Environment Variables
See `backend/.env.example` for all required variables.

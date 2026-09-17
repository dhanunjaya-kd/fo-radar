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

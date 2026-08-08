# F&O Sniper Scanner v3.0 — Full Stack

Complete full-stack F&O scanner with WARRENER-style dark UI, live WebSocket feed, paper trading, PnL tracking, backtest integration, and 1-3 day price predictions.

## Architecture

```
fo-sniper-fullstack/
├── backend/          Django + Channels + Celery + PostgreSQL
│   ├── fno_sniper/   Core Django config
│   ├── screener/     Scoring engine + predictions
│   ├── options/      Option chain analytics
│   ├── fyers_api/    Fyers v3 API integration
│   ├── news/         NewsAPI + sentiment
│   ├── trading/      Paper trading + PnL + Telegram
│   └── backtest/     Sniper V8.1 Excel integration
└── frontend/         Vite + React + Tailwind + Recharts
    └── src/
        ├── components/  Header, SignalList, OptionsDive, etc.
        ├── hooks/       useWebSocket, useSignals
        └── utils/       API helpers
```

## Quick Start

### 1. Backend (Local)
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

### 2. Frontend (Local)
```bash
cd frontend
npm install
npm run dev
# Open http://localhost:5173
```

### 3. Deploy
- **Frontend**: `cd frontend && vercel --prod`
- **Backend**: Connect Render to this repo, use `render.yaml`

## WebSocket Endpoints
```
ws://localhost:8000/ws/screener/          → Live signals
ws://localhost:8000/ws/options/RELIANCE/ → Options dive
ws://localhost:8000/ws/alerts/            → Alert feed
ws://localhost:8000/ws/market-overview/   → Market stats
```

## REST API Endpoints
```
GET  /api/screener/signals/         → All active signals
GET  /api/screener/signals/top/     → Top 20 signals
GET  /api/screener/signals/predictions/ → High-confidence predictions
GET  /api/options/dive/<symbol>/    → Options dive data
POST /api/trading/paper-trade/      → Execute paper trade
GET  /api/trading/paper-trades/     → List paper trades
GET  /api/trading/pnl/today/        → Today's PnL
GET  /api/news/                     → News feed
```

## Features
- ✅ WARRENER-style dark green UI
- ✅ 180 NSE F&O stocks
- ✅ Score/Grade/Signal engine
- ✅ 1-day & 3-day price predictions
- ✅ Paper trading mode
- ✅ PnL tracker
- ✅ Backtest integration (Sniper V8.1)
- ✅ News sentiment analysis
- ✅ Telegram alerts
- ✅ Fyers v3 API (SHA256 auth)
- ✅ Live WebSocket feed
- ✅ OI Analytics charts
- ✅ Responsive design

## Environment Variables
See `backend/.env.example` for all required variables.


dhanu
# FO Sniper — audit + fixes (Claude, 2026-07-29)

Full file-by-file audit of the zip you uploaded, plus the fixes actually
made. Read the "How to verify" section before trusting any of this in
production — I tested everything I could without a live Fyers session
(market was effectively unreachable from my sandbox), but the real
end-to-end path (does a live option chain actually come back and look
sane) needs to run on your machine with your token.

## The core problem (why your screenshots looked wrong)

Every OI/PCR/Max-Pain/IV number on screen was either hardcoded or
`Math.random()` / `np.random.uniform()`. None of it ever came from Fyers,
even though you had a real, connected Fyers app. Root causes, found and
fixed:

1. **No option-chain fetch existed.** `screener/fyers_client.py` (the
   client that actually authenticates) had no method to call Fyers'
   option-chain endpoint at all.
2. **A second, broken Fyers integration** (`fyers_api/` app) did have an
   option-chain method, but its auth never persisted a token to disk
   (`FyersAuth.access_token` lived only in memory on a throwaway request),
   so it always sent `Authorization: appid:None`. It also assumed a
   response shape Fyers has never returned.
3. **Three different hardcoded Fyers App IDs** scattered across files,
   none of them read from `.env` consistently, and the one your working
   client used (`6OWXIMCOXF-100`) didn't match your actual connected app
   (`LYNP1Z6GGG-100`, confirmed against your API dashboard screenshot).
4. **`.env` variable name mismatch** — `settings.py` looked for
   `FYERS_APP_SECRET`/`FYERS_SECRET_ID`; your `.env` defines
   `FYERS_SECRET_KEY`. Neither matched, so it silently used a stale
   hardcoded default.
5. **Token file mismatch** — your real daily login script
   (`get_fyers_token.py`) saves to `fyers_auth.json`; the working client
   only read `fyers_access_token.txt`. Different files.
6. With no real data available anywhere, three separate places
   (`screener/tasks.py`, `screener/scanner.py`, `screener/views.py`) each
   independently mocked the numbers instead, and two frontend files
   (`Analytics.jsx`, the orphaned `Dashboard.jsx`) did the same with
   `Math.random()`.

## What's fixed now

### Backend

- **`screener/options_analytics.py`** *(new file)* — real PCR, Max Pain,
  support/resistance (from OI walls), OI buildup classification, and
  IV + Greeks (Delta/Gamma/Theta/Vega) via Black-Scholes. Fyers'
  option-chain response has no IV/Greeks field at all (confirmed against
  current docs), so these are computed locally from each strike's LTP.
  Pure functions, no Django/network dependency — unit-tested against a
  synthetic Fyers-shaped response (resistance/support pick the correct
  OI-heaviest strikes, the BS solver round-trips a known IV within 0.5%).

- **`screener/fyers_client.py`** — added `get_option_chain()` and
  `get_option_analytics()` using the official `fyers_apiv3` SDK method
  (`fyers.optionchain(data=...)`), not a hand-rolled REST call. Fixed
  `CLIENT_ID` to read from Django settings instead of a hardcoded stale
  app id. Fixed token loading to check **both** `fyers_access_token.txt`
  and `fyers_auth.json`, using whichever was written more recently — so
  it works regardless of which of your auth scripts you ran that day.
  Verified against your actual uploaded token: reads correctly, resolves
  to `LYNP1Z6GGG-100`.

- **`screener/views.py`** (`_build_all()`, the function actually behind
  `/api/sniper-only/` — confirmed this is what your screenshots were
  rendering) — replaced hardcoded `ce_oi_chg: 0, pe_oi_chg: 0, pcr: 1.0,
  max_pain: <fake>` with a real Fyers option-chain fetch for every symbol
  that clears the technical filter. **If Fyers isn't authenticated or a
  symbol has no options, fields are now `None` (shown as "—" in the UI),
  never a fake number.** `live_oi` is now set truthfully instead of being
  hardcoded `False`. Also fixed a labeling bug where the recommendation
  text always said "CE" even on SELL/PE signals. Tested both branches
  (live data present / absent) end-to-end with mocked inputs.

- **`screener/tasks.py`** — same mock-data fix applied to the Celery
  pipeline, for when/if you switch to that architecture.

- **`fno_sniper/asgi.py`** — fixed a hard crash: it imported
  `fno_sniper.consumers`, a module that never existed in this project.
  `uvicorn fno_sniper.asgi:application` could not boot at all. Now routes
  through each app's real `routing.py` (`screener`, `options`, `trading`),
  and resolves a route collision where `screener` and `trading` both
  registered `ws/alerts/` for two different consumer classes. Verified by
  actually importing the module — it now loads and lists all 4 real
  WebSocket routes correctly.

- **`fno_sniper/settings.py`** — fixed the `FYERS_SECRET_KEY` env name
  mismatch; removed the stale hardcoded App ID default.

- **`fyers_api/auth.py` + `fyers_api/client.py`** — actually fixed rather
  than just flagged: `generate_access_token()` now persists the token to
  `fyers_auth.json` (same file/format your working script uses), and
  `FyersAuth.__init__` loads a previously-saved token instead of always
  starting at `None`. Fixed the option-chain call's wrong param name
  (`date` → `timestamp`/`strikecount`, matching Fyers' actual API).

- **`fyers_api/data_fetcher.py`** — `fetch_option_chain()` was dead code
  with a response-shape bug (assumed nested `opt["ce"]["oi"]`; Fyers
  returns a flat list disambiguated by `option_type`). Rewritten to reuse
  the tested `options_analytics.parse_option_chain()`, so if you ever want
  to populate the `OptionChain` DB model instead of the REST-polling path,
  it'll actually work now.

- **New endpoint** `GET /api/option-analytics/<symbol>/` — full real
  option-chain analytics (PCR, Max Pain, support/resistance, IV, Greeks
  per strike) for one symbol, on demand.

- **Deleted** (confirmed 100% unused, never imported by anything):
  `screener/scanner.py`, `screener/engine.py`.

### Frontend

- **`Analytics.jsx`** ("OI Analytics" tab) — was 100% `Math.random()`,
  no API call at all, even the Greeks panel showed the same 4 hardcoded
  numbers regardless of stock. Rewritten to call the new
  `/api/option-analytics/` endpoint. Shows an honest "no live option
  chain data" state instead of a fake chart when Fyers isn't reachable.
  Greeks panel now shows real ATM CE/PE Delta/Gamma/Theta/Vega.

- **`services/api.js`** — fixed a real syntax bug: an unquoted-identifier
  array literal (`{ symbol: RELIANCE, name: Reliance, ... }` instead of
  string literals) that throws `ReferenceError` the moment that fallback
  code path runs. Fixed `getOptionsData`'s URL (was pointing at a path
  that doesn't exist). Added `getOptionAnalytics()`.

- **`hooks/useWebSocket.js`** — fixed a route mismatch (`ws/market/`
  doesn't exist server-side; the real route is `ws/market-overview/`).

- **Deleted** (confirmed unused, not imported by `main.jsx`/`App.jsx`):
  `pages/Dashboard.jsx`.

- Verified every `.jsx`/`.js` file in the frontend compiles cleanly
  (real esbuild syntax check — your uploaded `node_modules` had
  Windows-only native binaries, so I installed a scratch Linux copy just
  to run this check; it wasn't included in the zip you got back).

## Round 2 fixes (this pass)

- **`fyers_api/auth.py` — actually fixed, not just deprecated.**
  `generate_access_token()` now persists the token to `fyers_auth.json`
  (same file `get_fyers_token.py` writes), and `FyersAuth.__init__` loads
  a saved token back instead of always starting at `None`. Verified: a
  fresh `FyersAuth()` now loads your real 652-char token correctly.
- **`fyers_api/client.py`** — fixed the option-chain call's actual bug
  (`date` isn't a real param; corrected to `timestamp`/`strikecount`).
- **`fyers_api/data_fetcher.py`** — rewrote the parsing to use the real,
  tested flat-list shape instead of the never-returned nested one.
- **Consolidated the Fyers auth scripts.** Deleted `exchange_token.py`,
  `fyers_auth.py`, and the duplicate root-level `fyers_client.py` — all
  either redundant or pointed at a stale/wrong app id. `get_fyers_token.py`
  is now the one script to run.
- **`services/fyersSocket.js` (live tick WebSocket) — partially fixed,
  read this carefully.** I found and fixed a genuinely wrong endpoint URL
  (`wss://socket.fyers.in/v3` isn't a real Fyers host — corrected to
  `wss://api.fyers.in/socket/v2/data/`, per Fyers' own docs) and wired a
  new `/api/fyers-browser-token/` endpoint + frontend code so the browser
  actually has a token to authenticate with (previously nothing ever put
  one in `localStorage`). **However**, I could not verify from
  documentation whether the auth handshake message, the subscribe message
  shape, or the tick payload encoding (JSON vs binary/protobuf — Fyers' v3
  notes mention this changed significantly) in this file are correct. If
  ticks still don't flow after this fix, that's why. The properly
  verified way to consume this feed is the official Python SDK
  (`fyers_apiv3.FyersWebsocket.data_ws.FyersDataSocket`) run on the
  backend, pushing ticks out over the Channels WebSocket routes already
  fixed in `asgi.py`, rather than trusting a hand-rolled browser
  implementation of Fyers' wire protocol.
- **Found and fixed: the Watchlist tab was 100% hardcoded fake data,
  always, with no way to ever show anything real.** `hooks/useSignals.js`
  fetched `/api/screener/signals/` — a path that was never registered
  anywhere — so it always 404'd, and the component permanently fell back
  to a baked-in `MOCK_SIGNALS` array (this is where the NESTLEIND/
  BAJAJ-AUTO/TVSMOTOR/CONCOR/BIOCON/ETERNAL numbers in some of your
  screenshots came from — not your market, not even random, just a fixed
  demo array). Fixed the URL to the real live endpoint (`/api/signals/`,
  confirmed to read the same live cache as `/api/sniper-only/`) and fixed
  `Watchlist.jsx`'s field names, which were also written for a different,
  older signal shape (`stock_symbol`/`score`/`ltp` instead of the real
  `symbol`/`confidence`/`price`) and would have shown "undefined" even
  after the URL fix.
- Same copy-paste URL bug existed in **`services/api.js`**:
  `getMarketSummary()` was accidentally calling the signals endpoint, and
  `getSignals()` pointed at the same never-registered `/screener/signals/`
  path. Both fixed.
- **Tab badge counts** ("Live Signals 6", "Watchlist 1") were hardcoded
  constants that never changed regardless of actual data. Now pull from
  the real signal count.
- Re-ran the full backend import check, `manage.py check`, a full
  frontend esbuild syntax sweep, and direct unit tests of the two new
  views (`FyersBrowserTokenView`, `OptionAnalyticsView`) with mocked
  dependencies — all pass.

## What's still open (didn't fully solve, in priority order)

1. **`services/fyersSocket.js` message protocol** — see the Round 2 note
   above. URL and token are fixed; the message-level format is unverified.
2. **News sentiment score** was also `np.random.uniform(-0.5, 0.5)` in
   `tasks.py`; I zeroed it to neutral (honest, not random) but didn't wire
   real sentiment — `news/fetcher.py` and the `textblob`/`newsapi`
   packages are already installed and unused, so that's a contained
   follow-up if you want it.
3. **Rate limits**: `_build_all()` now calls the option chain once per
   symbol that clears the technical filter (usually 5-15 of the 30
   movers checked), every 90 seconds. That's well inside Fyers' limits,
   but if you widen the mover list, watch this.
4. The Django ORM + Celery + Channels architecture (`Signal` model,
   `options/consumers.py` push updates) still isn't the live path — the
   ad-hoc thread + in-memory cache in `screener/views.py` is what
   actually serves your frontend. That's a bigger architectural decision
   (which one do you want to be "the" backend) that I didn't make for you.
5. `Analytics.jsx` still defaults to a hardcoded `'RELIANCE'` when no
   stock is selected — `App.jsx` renders `<Analytics />` with no props
   and there's no stock-picker UI wired to it yet. Real value would be a
   symbol search box inside that tab; didn't add it to keep this pass
   focused on the data pipeline itself.
6. Didn't trace every screenshot you sent to its exact source component
   (e.g. the compact "2.7x vol / BUY NOW" row layout in your first image)
   — the ones I found and fixed (the live signal cards, the OI Analytics
   tab, and the Watchlist tab) account for the overwhelming majority of
   what was wrong.

## Round 3 — OI-based quality scoring (this pass)

You asked for the logic that actually picks "quality stocks" using live OI,
not just displays OI as a side field. Two real problems, fixed together:

- **Found: Grade A and B were mathematically impossible.** The technical
  score (`RSI in range` +20, `volume ≥1.5x avg` +15, `price>VWAP` +15,
  `MACD>0` +20) maxes out at 70, but grading required `A>=90`, `B>=80`.
  Every signal that ever passed the filter could only ever be graded C —
  the top badges you saw in the frontend for those tiers were never
  reachable from live data.

- **Fixed by making OI confirmation the missing points, not just a display
  field.** After the real option-chain fetch, each signal now gets:
  - `oi_confirmation`: `CONFIRMED` (options positioning agrees with the
    technical direction — e.g. BUY signal + PE writing dominant/bullish)
    → **+20** to score; `CONFLICT` (BUY signal but CE writing
    dominant/bearish, i.e. resistance building against you) → **-15**;
    `NEUTRAL` (no clear dominance) → no change; `NO_DATA` when Fyers
    wasn't reachable → no change (never penalized for missing data, only
    rewarded for confirming data).
  - A smaller **PCR confirmation** (+5) when PCR agrees with the
    direction (PCR>1 for BUY, PCR<0.7 for SELL) — standard put/call
    sentiment reading.
  - `pattern`: `"Range-Pinned"` when spot is within 1.5% of Max Pain
    (price tends to gravitate there into expiry instead of trending), or
    `"OI-Confirmed Momentum"` when OI backs up the move.
  - Regraded on the combined `technical_score + oi_adjustment` (0-100),
    with `A+`/`A`/`B`/`C`/`D` thresholds that are now actually reachable —
    and reaching A/B now *requires* live OI agreement, not just chart
    pattern.

- **The "quality stocks" list is no longer a fixed top-6.** It used to
  return exactly 6 signals regardless of how many genuinely cleared the
  bar — padding with weak filler on quiet days, discarding good setups
  past #6 on active ones. Now returns everything at grade C or better
  (score ≥ 60), capped at 20.

- **`SniperCard.jsx`** — added visible "✓ OI Confirmed" / "⚠ OI Conflict"
  and pattern badges, and added the new `A+` grade to the color map (it
  was missing, since `A+` didn't exist before this pass).

- Unit-tested end to end with a mocked BUY-direction technical setup
  crossed with CONFIRMED / CONFLICT / Range-Pinned / no-data OI
  responses: confirmed grades land where expected, and a technically
  bullish stock whose real options data showed resistance building
  against it was correctly scored below the quality threshold and
  dropped from the list — this is the actual mechanism that answers
  "grab OI buildup for every stock that meets my parameters."

## Round 4 — real ADX filter + UI matching your reference (this pass)

- **Found: `ADX ≥25` was advertised in the "Live Signals" banner but never
  computed anywhere.** Same for `PE <40` (explicitly disabled in a code
  comment to avoid Yahoo rate limiting, but still shown in the UI as if
  active). Every signal passed regardless of whether the stock was
  actually trending or just chopping sideways.
- **Added real ADX(14)** via Wilder's smoothing in `_calc_tech()` — the
  same method your earlier standalone SNIPER scripts used
  (`ewm(com=period-1)`). Verified it actually distinguishes a trending
  move from sideways chop using synthetic price data (ADX 100 vs 12.4 in
  a deliberately extreme test; more realistically it'll separate real
  setups by 20-40 points).
- **Rebalanced the technical score** to make room for it: RSI/Volume/
  VWAP/MACD now 15 points each (was 20/15/15/20), ADX≥25 worth 20. Base
  max is 80 instead of 70; combined with the OI adjustment from Round 3
  (up to +25), total is clipped to 100. Gate raised from 45→50 to keep
  roughly the same selectivity. Removed the dead PE-check comment block.
  Unit-tested: two otherwise-identical stocks, one trending (ADX 32) one
  choppy (ADX 15), score exactly 20 points apart (80 vs 60) and grade B
  vs C — confirmed.
- **Fixed the banner text** in `SignalList.jsx` to describe what's
  actually checked now, instead of claiming `PE <40` which was never real.
- **Redesigned `OptionsDive.jsx`** (the detail modal) to match your
  reference screenshots much more closely: circular grade badge with
  score + letter, directional CE/PE OI boxes in Lakhs with real
  interpretation text ("CE WRITING (bearish)" / "PE unwinding (bullish)"
  etc., derived from the actual sign of the number — not a canned
  string), Max Pain distance, PCR/IV with real dominant-side labels,
  Support/Resistance pills, and insight lines built from
  `oi_confirmation`/`pattern` (only shown when there's something real to
  say). Added an honest "no live option chain" banner for when
  `live_oi` is false, instead of quietly showing price-based numbers as
  if they were real OI.
- **Redesigned `SniperCard.jsx`** (the grid card) to match: same grade
  badge treatment, Lakh-formatted directional OI, support/resistance
  icons, and a "🔍 Dive for full analysis" affordance in the footer
  matching the vocabulary in your reference screenshots.
- Re-verified: backend imports, `manage.py check`, full frontend esbuild
  sweep, and a dedicated ADX unit test — all pass.

## Round 5 — stale ticker fixes + a file-sync gotcha (this pass)

- You hit `ImportError: cannot import name 'MarketSummaryView'` on your
  machine. I checked: the `urls.py`/`views.py` in this zip are internally
  consistent (both agree on `MarketSummaryOldView`) — that error means the
  `urls.py` actually running on your machine isn't the one from this zip.
  **When applying updates, replace the whole `backend/fno_sniper/` and
  `backend/screener/` folders rather than individual files**, and clear
  `__pycache__` if in doubt.
- Note for next time: while that import error is live, your background
  data-fetch thread still runs and logs "Background refresh complete" —
  that's not a sign the app is working, it's an independent background
  thread that starts regardless of whether Django's URL routing loaded.
  If urls.py fails to import, no HTTP request can be served at all, even
  though the log looks like progress is happening.
- **Real fix, not just noise:** your `FNO_STOCKS` list in `views.py` had
  several genuinely dead NSE tickers causing the "possibly delisted"
  errors on every cycle — verified against actual NSE/exchange circulars,
  not guessed: `ZOMATO`→`ETERNAL` (Feb 2025), `TATAMOTORS`→`TMPV` (Oct
  2025), `IBULHSGFIN`→`SAMMAANCAP` (Jul 2024), `GMRINFRA`→`GMRAIRPORT`
  (Sep 2024). `MCDOWELL-N`, `CADILAHC`, and `MINDTREE` were removed
  outright — their correct replacements (`UNITDSPR`, `ZYDUSLIFE`, `LTIM`)
  were already sitting in the same list, so they were pure duplicates.
  `GUJGASLTD`/`JBCHEPHARM`/`LTIM`/`PEL` were left alone — they failed in
  the same log but I couldn't confirm an actual rename, and `LTIM`
  failing is suspicious since that ticker is definitely still valid, so
  that batch looks like a transient Yahoo hiccup rather than a real
  problem.

## Round 6 — NaN crash fix + full Yahoo→Fyers migration (this pass)

- **Fixed the actual crash**: `"Background error: cannot convert float NaN
  to integer"`. Root cause: `if price <= 0: continue` was meant to skip
  bad data, but any comparison with NaN in Python evaluates to False
  (`nan <= 0` is `False`, not `True`), so a NaN price slipped straight
  through that guard and crashed later at `qty = int(50000 / price)`.
  Fixed with an explicit `math.isnan()` check (comparisons can't catch
  it, isnan() can) at both the point of use and at the source
  (`_fetch_stock`), plus a guard on the technical indicators themselves
  in case a thin-history stock produces NaN RSI/MACD/ADX. Unit-tested: a
  stock with a NaN price is now silently skipped for that cycle instead
  of crashing the whole background thread.
- **You asked why Yahoo was still in the picture when we're on Fyers —
  fair question, and the honest answer was "because nothing had actually
  switched it over yet."** Migrated the entire technical scan
  (price/change/volume for all ~155 stocks, NIFTY/BANKNIFTY/VIX, and the
  60-90 day OHLC history that RSI/MACD/ADX/VWAP are computed from) to
  Fyers as the PRIMARY source:
  - `_fetch_all_quotes_fyers()` — batches up to 50 symbols per Fyers
    quotes call instead of 155 individual yfinance calls. This also
    kills the entire "possibly delisted" class of errors at the root —
    Fyers uses NSE's current live symbol list directly, so a
    correctly-named stock never hits a stale-ticker problem there the
    way Yahoo's mirror does.
  - `_calc_tech()` now pulls 100 days of daily candles from Fyers'
    History API first; the indicator math itself (RSI/MACD/ADX/VWAP/
    ATR/support-resistance) is unchanged, just fed from a different
    source. Split into a shared `_compute_indicators()` so both paths
    run identical, already-tested math.
  - `_fetch_index()` (NIFTY/BANKNIFTY/VIX) same treatment, using Fyers'
    real index symbols (`NSE:NIFTY50-INDEX` etc).
  - **yfinance is now strictly a fallback** — only used per-symbol if
    Fyers isn't authenticated or didn't return that specific stock in
    its batch. If your token is valid, yfinance should essentially never
    fire anymore.
  - Unit-tested both paths end to end with mocked Fyers responses (quotes
    + history + indices) and confirmed the yfinance fallback still works
    correctly when `is_authenticated()` is False.

## Frontend: the blank page

Your console (thank you for grabbing that — genuinely the fastest way to
find this) pointed at `MarketBanner.jsx:87`, "Objects are not valid as a
React child (found: object with keys {value, sentiment})". I checked: the
`MarketBanner.jsx` in this zip already correctly extracts `pcr.value` and
`pcr.sentiment` separately — it never renders that object directly,
anywhere. Your crashing file's line numbers don't even line up with this
one. Same story with the WebSocket log showing the old wrong URL
(`wss://socket.fyers.in/v3`) instead of the fixed one — that fix has been
in the zip since Round 2. **This means the frontend you're running predates
all of the frontend fixes, not just this one file.**

Given file-by-file copying has now caused this exact class of problem
three times (twice on the backend, now once on the frontend), the fix
isn't a new patch — it's: close `npm run dev`, delete `frontend/src`
entirely, and copy the whole `frontend/src` folder from this zip in
fresh. Don't cherry-pick.

## Round 7 — option-premium targets, not stock-price targets (this pass)

- **Real, substantial fix**: entry/SL/target1-3 were always just the
  underlying STOCK's price (e.g. "Entry ₹1,141.20" on a card that's
  supposedly recommending an options trade) run through ATR multiples of
  2x/3x/4x -- sized for a multi-day swing, and not even in the right
  units for an option. Rebuilt from the ground up:
  - Stock-side move assumptions are now fractions of ONE ATR (0.4/0.5/
    0.8/1.2), representing a realistic single session's range, not
    2-4x it.
  - That stock-side move gets translated into an actual option-premium
    move via the contract's own delta: live delta + live LTP when a real
    option chain is available (looks up the exact strike/side Fyers
    returned), or a Black-Scholes ESTIMATE (using historical volatility
    as a stand-in for IV) when it isn't -- never the stock price
    mislabeled as a premium.
  - SL is weighted 1.4x the delta-implied move, since an adverse stock
    move costs an option more than delta alone suggests (theta/gamma
    work against you too).
  - Quantity now sizes off the actual premium (`50000 / premium`), not
    the stock price.
  - Added `stock_sl`/`stock_target1-3` fields alongside the premium
    numbers so the underlying assumption is inspectable.
  - Unit-tested both the live-LTP path and the Black-Scholes-estimate
    path: entry/SL/targets are correctly ordered, all positive, and the
    premium is a realistic small number (~₹10-40) instead of the ₹1000+
    stock price.
  - Note honestly: this makes targets realistically *sized* for
    intraday options. A specific "70% hit rate" isn't something I can
    verify without running this against real historical option data
    (a backtest engine, which is a separate build) -- I didn't want to
    print a number I can't back up.
- **Removed `MarqueeTicker`** (the full-market scrolling ticker showing
  all 155 stocks as one continuous strip) from `App.jsx` per feedback --
  relevant stocks already show properly in the Signals/Watchlist tabs;
  this was redundant and, without its CSS animation running, degenerates
  into an unreadable wall of text (which is what showed up in the
  screenshot).

## Important: today (when this round shipped) was a Saturday

NSE doesn't trade on Saturdays. If you're testing on a non-trading day,
Fyers' option chain will have nothing live to return regardless of any
code fix -- that's expected, not a bug. Test the live-data behavior
Monday-Friday, 9:15 AM-3:30 PM IST.

## Also confirmed (again): both backend and frontend were still stale

The exact same 7 pre-Round-5 stock tickers (ZOMATO, TATAMOTORS,
MCDOWELL-N, CADILAHC, IBULHSGFIN, GMRINFRA, MINDTREE) were still showing
in the log, and the frontend console still showed the pre-Round-2
WebSocket URL and the exact same MarketBanner crash from before -- both
confirmed absent from this zip by direct grep before writing this. On
top of that, the Network tab showed several component files loading as
HTTP 304 (Not Modified) -- the *browser* was serving its own cached copy
of some files even if the disk copy was updated. Two independent causes,
same symptom. Fix:
1. Delete `C:\Users\FixAdmin\Downloads\fo-sniper-fullstack` entirely
   (back up `.env`, `fyers_auth.json`, `db.sqlite3` first)
2. Extract this zip to a **brand new folder** (e.g. a dated name) rather
   than back into the same Downloads path, to rule out Windows silently
   creating a `(1)`/`(2)` duplicate folder on conflict
3. In the browser, open DevTools -> Network tab -> check **"Disable
   cache"** (keep DevTools open while testing), or just hard-refresh
   with Ctrl+Shift+R

## Round 8 — fixed why only CE/BUY signals ever showed up

- **Real bug, found from your screenshots showing zero PE setups**: the
  score only ever rewarded the bullish combination
  (`price > vwap: +15`, `macd > 0: +15`) as two separate checks. A
  genuinely clean bearish setup (`price < vwap` AND `macd < 0`) scored
  **zero** from both of those, no matter how strong it was -- so a SELL/
  PE setup needed a near-perfect RSI + Volume + ADX just to scrape past
  the score-50 gate, while any half-decent bullish setup sailed through.
  That's why everything that qualified was BUY/CE.
- Fixed: both directions now score the same 30 points for genuine
  internal agreement (`price>vwap AND macd>0` for bullish, `price<vwap
  AND macd<0` for bearish). Unit-tested with two otherwise-identical
  synthetic stocks, one bullish-aligned and one bearish-aligned -- they
  now score identically (80/80) and correctly produce BUY vs SELL.
- Confirmed real Fyers data IS flowing correctly (per your screenshots --
  live OI, real premiums like ₹32 entry instead of the ₹1,141 stock
  price, "OI Confirmed" badges) -- the file-sync issue from earlier
  rounds appears resolved.
- The "still shows Yahoo" log lines: `_fetch_all_stocks()` only falls
  back to yfinance for whatever Fyers didn't return for that cycle. Your
  log's very first cycle logged "Fyers not authenticated" (token likely
  not loaded yet at that exact moment) -- later cycles clearly did
  authenticate, given the real OI in your screenshots. JBCHEPHARM/LTIM/
  PEL specifically failing on *every* cycle even once Fyers is
  authenticated suggests Fyers isn't returning those 3 in its batch
  response for some reason I can't diagnose without live access -- if
  they keep failing, simplest fix is dropping them from `FNO_STOCKS`.
- Clarified rather than built: the "POST-RESULT — stocks that already
  reported" table (earnings Rev YoY/PAT YoY/pattern classification) needs
  quarterly financial statement data, which Fyers (a trading/market-data
  API) doesn't provide -- that's a different data source entirely, out
  of scope for a Fyers-only build. The Watchlist tab already shows real
  live data now, which is the part that matters.

## Round 9 — Yahoo fully removed, Watchlist rebuilt as a table, OI Analytics symbol search, smaller cards

- **Removed News tab entirely** (`App.jsx`, deleted `NewsFeed.jsx`) -- it
  showed generic canned news unrelated to your actual signal stocks, per
  feedback.
- **Yahoo/yfinance removed completely, not just as a fallback.**
  `_fetch_all_stocks()`, `_calc_tech()`, and `_fetch_index()` in
  `screener/views.py` now return empty/None if Fyers isn't authenticated
  instead of quietly pulling from Yahoo -- there is no code path left in
  the live pipeline that can call yfinance. Also cleaned up
  `screener/tasks.py` (the Celery pipeline) the same way, and fixed a
  pre-existing bug found while doing this: it read `v.get("v", 0)` for
  volume, which doesn't exist in Fyers' quote schema (the real key is
  `"volume"`) -- volume was always reading 0 there. Also replaced a
  hardcoded `total_pcr=1.08` with a real average of active signals' PCR.
  Removed `yfinance` from `requirements.txt`. Unit-tested: with Fyers
  unauthenticated, the scanner now returns empty rather than falling
  back to Yahoo.
- **Watchlist rebuilt as a compact table**, matching the layout of the
  reference you sent -- columns, colored pill badges -- but populated
  with real fields (grade, entry/SL, OI confirmation status, BUY/SELL
  signal) instead of the earnings-specific columns in that reference,
  which need financial-statement data Fyers doesn't provide. Also fixed
  a filter bug where Watchlist only ever showed BUY signals; now shows
  both sides now that SELL/PE signals actually appear (Round 8 fix).
- **OI Analytics tab is no longer stuck on RELIANCE.** Added a search box
  (type any symbol) plus quick-pick chips for whatever's currently in
  your live signals, defaulting to your top signal instead of a
  hardcoded stock.
- **SniperCard shrunk ~10%** -- padding, font sizes, and gaps trimmed
  throughout (not the aggressive full-shrink, just a modest tightening).
- Full backend + frontend verification re-run after every change in this
  round.

## Round 10 — automatic Excel signal log (new feature, not a fix)

You asked for every signal to automatically land in an Excel sheet the
moment it appears (and to track when it drops out), with entry/SL/
targets included. Built:

- **`screener/excel_logger.py`** (new file) -- the moment a signal first
  appears in a scan cycle, it gets appended as a new row to
  `backend/signal_logs/signals_YYYY-MM-DD.xlsx` (one file per trading
  day, created automatically). Columns: Timestamp, Symbol, Action,
  Grade, Confidence, Stock Price, Change%, Strike, Entry (Premium), SL,
  Target 1/2/3, Qty, R:R, OI Confirmation, Pattern, PCR, IV%, RSI, ADX,
  Sector, Exited At.
- When a signal that was active drops out of the list on a later cycle
  (conditions no longer qualify), its existing row gets an "Exited At"
  timestamp filled in -- so you get entry time AND how long it stayed
  active, without re-scanning the whole sheet (row numbers are tracked
  in memory for O(1) updates). Repeated cycles of the same still-active
  signal never create duplicate rows.
- Wired into `_build_all()` -- runs automatically every scan cycle, no
  separate step needed.
- Added `GET /api/signals/export/` to download today's file directly,
  plus a "📥 Download today's log (Excel)" button in the Live Signals tab
  header.
- Added `openpyxl` to `requirements.txt` -- **you'll need to run `pip
  install -r requirements.txt` again** (or just `pip install openpyxl`)
  after updating, or the backend will error on startup.
- Unit-tested the full lifecycle: new signal logged correctly, exit
  timestamp fills in when it drops out, no duplicate rows across
  repeated cycles of the same signal, and confirmed `_build_all()`
  itself drives this end to end (not just the module in isolation).

## Round 11 — F&O confirmation gate, duplicate-signal fix, alerts, NIFTY/BANKNIFTY tracker

- **Trades now require a confirmed live Fyers option chain, full stop.**
  Previously, if Fyers had no chain for a stock, the code fell back to a
  Black-Scholes *estimate* and presented it identically to a real quote
  ("SELL PE — ₹400 STRIKE, Entry ₹3.90") -- that's what produced
  confident-looking recommendations on stocks with no confirmed
  tradeable contract. Now: no live chain for that exact strike, no
  signal. Unit-tested.
- **Fixed duplicate Excel rows** -- a stock hovering right at the score
  threshold flickers in/out every cycle; each flicker used to log a new
  row. Added a 30-minute cooldown: reappearing within that window
  reactivates the same row (clears "Exited At") instead of duplicating.
  Only a longer gap counts as a genuinely new setup. Unit-tested.
- **Quality bar raised** (score ≥65, was 60; cap 15, was 20) -- combined
  with the confirmation gate above, this should meaningfully cut signal
  volume without losing the real ones.
- **New-signal alerts**: sound ping (Web Audio, no file needed) +
  optional browser notification the moment a new signal appears --
  "🔔 Enable alerts" button in the Live Signals header.
- **NIFTY/BANKNIFTY Index Tracker** (new tab) -- snapshots both indices'
  option-chain analytics (PCR, ATM Put/Call OI + writing/unwinding
  status, IV, support/resistance, Max Pain, derived Bias) every scan
  cycle to a daily Excel file, viewable as a table or downloadable.
  Deliberately NOT built: "Fut OI Chg" (needs a separate rolling futures
  contract symbol) -- flagged in the UI rather than faked.
- Full backend + frontend verification re-run; targeted unit tests for
  the cooldown logic and index-tracker bias derivation.

## Round 12 — PCR fix, Fyers chart links, and real outcome tracking

- **Found and fixed a real mislabeling bug**: the top-banner "PCR" was
  never actually the options Put-Call Ratio — it was
  `declining_stocks / advancing_stocks` among your scanned universe (a
  market-breadth stat) mislabeled as PCR. That's why it never matched
  the real per-index PCR shown in the Index Tracker (2.27-3.08 vs
  0.76-1.01). Now pulls NIFTY's real option-chain PCR, which is what
  "market PCR" actually means.
- **NIFTY/BANKNIFTY/VIX cards are now clickable** -- hover shows "↗
  chart", click opens the real symbol on Fyers' own chart popout
  (confirmed URL format, not guessed).
- **Built real outcome tracking for the Excel signal log** -- this is
  the big one. Every open position's exact option contract is polled
  each cycle and checked against its own SL/Target 1/2/3. The moment one
  is crossed, it's recorded with a timestamp (upgrading as further
  targets are reached: hitting Target 2 supersedes an earlier Target 1
  record). A position stops being watched once SL hits or Target 3 (the
  furthest) is reached. This is what makes the end-of-day download
  actually show which signals worked, not just which ones appeared.
  Fully unit-tested: no false positives before a level is crossed, SL
  path, sequential target upgrades, and tracking correctly stopping.
- **Wrote `SYSTEM_ARCHITECTURE.md`** -- a complete, current-state
  explanation of the whole system and the logic behind every number,
  separate from this round-by-round changelog.
- **Deliberately did not build**: Crude Oil (needs MCX rolling-contract
  symbol resolution I couldn't fully verify in the time available --
  rather not guess) and Dow Jones (Fyers doesn't provide any US index
  data at all, confirmed via search).

## Round 13 — expanded the scanning universe (162 → 201 stocks)

- You asked a fair question: with the stricter filters from Round 11
  (score ≥65 + confirmed live option chain), are we now missing good
  setups? Checked the real numbers: the actual current NSE F&O universe
  is ~200-220 stocks; the scanner was only checking 162. Some real,
  liquid F&O stocks were never even looked at, regardless of setup
  quality.
- Verified against a live current F&O source (fetched, not guessed) and
  found 9 large, definitely-F&O stocks missing entirely: **ADANIPOWER,
  BAJAJ-AUTO, ONGC, ASIANPAINT, DMART, SHRIRAMFIN, HINDZINC, ADANIGREEN,
  ADANIENSOL**.
- Added a further ~30 well-established F&O names (COFORGE, ASHOKLEY,
  APOLLOTYRE, BANKBARODA, MUTHOOTFIN, CDSL, BSE, MCX, and others) to
  close most of the remaining gap. Total now 201.
- **Honest caveat**: the first batch of 9 was verified against a live
  fetch; the rest is high-confidence domain knowledge, not individually
  re-verified one by one the way the ZOMATO/TATAMOTORS renames were
  earlier. NSE revises the F&O list periodically -- if any of the newer
  additions start erroring the way old tickers used to, that's the
  signal to check and fix, same pattern as before.
- Verified: no missing sector labels, no duplicates, full backend check
  still clean.

## Round 14 — Index Tracker: more confirming data

Added 4 new columns, all real data, no filler:
- **Change %** — the index's actual day move, passed in from data already
  fetched for the top banner (no extra API call)
- **Total Put OI / Total Call OI** — chain-wide totals across all fetched
  strikes, not just the at-the-money one. Gives the macro positioning
  picture alongside the existing ATM-specific numbers.
- **Price Confirms Bias** — reuses the same confirmation concept already
  built for individual stock signals (Round 3): does the index's actual
  price move agree with what the OI-derived Bias implies? ✓ Confirmed
  when they agree, ⚠ Conflict when OI says one thing and price is doing
  another (a real signal worth noticing, not something to explain away).
- Unit-tested both the confirm and conflict paths.

## How to verify on your machine

1. `cd backend && pip install -r requirements.txt` (a fresh venv — the
   Windows one in your upload won't run on other machines; I removed it
   from what's zipped back to you)
2. Make sure `fyers_auth.json` or `fyers_access_token.txt` has today's
   token (run `python get_fyers_token.py` if not)
3. `python manage.py runserver` and hit `http://127.0.0.1:8000/api/fyers-status/`
   — should show `"authenticated": true`
4. Hit `http://127.0.0.1:8000/api/option-analytics/RELIANCE/` directly —
   you should see real `pcr`, `maxPain`, `atmIv`, `ceData`/`peData` with
   actual strikes, not zeros
5. `cd frontend && npm install && npm run dev` — the Signals tab and OI
   Analytics tab should now show real numbers (or an honest "no data"
   state) instead of identical placeholder values on every card

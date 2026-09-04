# FYERS Exact Strike Extension

This optional Chrome/Chromium Manifest V3 extension connects the F&O Radar signal drawer to FYERS Web.

## What it does

When the user clicks a signal contract such as `SELL ANGELONE SEP 300 PE`:

1. F&O Radar exposes the exact backend option symbol (`NSE:ANGELONE26SEP300PE`).
2. The extension intercepts that click before the React fallback.
3. A FYERS Web tab is opened.
4. The extension waits for FYERS to become interactive.
5. It enters the exact option symbol into a visible FYERS search field.
6. It selects only an exact symbol match. It never intentionally clicks a similar strike.

The extension does not place, modify, or cancel orders.

## Install locally

1. Open Chrome/Edge and go to the browser's Extensions page.
2. Enable **Developer mode**.
3. Choose **Load unpacked**.
4. Select this directory:
   `browser-extension/fyers-exact-strike`
5. Keep the extension enabled.
6. Run F&O Radar on `http://localhost:5173` (or `http://127.0.0.1:5173`).
7. Open a signal drawer and click the option contract.

## Important

FYERS is a cross-origin application, so the normal F&O Radar webpage cannot reliably manipulate FYERS's UI. The extension is therefore required for automatic search/selection.

FYERS can change its web UI. The controller deliberately refuses to click a merely similar symbol; if it cannot find an exact match, it stops rather than opening the wrong strike.

The normal F&O Radar fallback still opens FYERS and copies the exact symbol when the extension is not installed.

// Optional helper: when installed, the extension opens the signal's
// underlying NSE equity in FYERS. It intentionally does not attempt to
// select the option strike.
document.documentElement.dataset.fyersStockExtension = '1';

function openUnderlyingStock(symbol) {
  if (!symbol) return;

  chrome.runtime.sendMessage({
    type: 'FO_RADAR_OPEN_STOCK',
    symbol
  }).then((result) => {
    if (!result?.ok) {
      console.warn('[F&O Radar] FYERS stock opener:', result?.error || 'not available');
    }
  }).catch(() => {
    console.warn('[F&O Radar] FYERS stock opener is unavailable.');
  });
}

document.addEventListener('fyers-stock-open', (event) => {
  const symbol = event.detail?.symbol;
  openUnderlyingStock(symbol);
}, false);

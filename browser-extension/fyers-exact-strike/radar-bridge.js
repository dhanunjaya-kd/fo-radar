// Marker visible to the page DOM so the React app knows the extension is
// installed. The extension owns exact-strike navigation.
document.documentElement.dataset.fyersExactStrikeExtension = '1';

function openExactStrike(symbol) {
  if (!symbol) return;

  chrome.runtime.sendMessage({
    type: 'FO_RADAR_OPEN_OPTION',
    symbol
  }).then((result) => {
    if (!result?.ok) {
      console.warn('[F&O Radar] FYERS exact-strike extension:', result?.error || 'not available');
    }
  }).catch(() => {
    console.warn('[F&O Radar] FYERS exact-strike extension is unavailable.');
  });
}

// Preferred path: the React app explicitly hands the clicked contract to the
// extension. This avoids relying on event-ordering between an isolated-world
// content script and React's delegated click handler.
document.addEventListener('fyers-exact-strike-open', (event) => {
  const symbol = event.detail?.symbol || event.target?.getAttribute?.('data-fyers-option-symbol');
  openExactStrike(symbol);
}, false);

// Fallback path: intercept a direct click on the contract button.
document.addEventListener('click', (event) => {
  const button = event.target.closest('[data-fyers-option-symbol]');
  if (!button) return;

  const symbol = button.getAttribute('data-fyers-option-symbol');
  if (!symbol) return;

  event.preventDefault();
  event.stopPropagation();
  event.stopImmediatePropagation();
  openExactStrike(symbol);
}, true);

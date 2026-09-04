// Marker visible to the page DOM so the React app knows the extension is
// installed. The extension owns the click before React's onClick runs.
document.documentElement.dataset.fyersExactStrikeExtension = '1';

document.addEventListener('click', (event) => {
  const button = event.target.closest('[data-fyers-option-symbol]');
  if (!button) return;

  const symbol = button.getAttribute('data-fyers-option-symbol');
  if (!symbol) return;

  // Prevent the React fallback from opening a second FYERS tab. The
  // extension will open FYERS and select the exact contract.
  event.preventDefault();
  event.stopPropagation();

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
}, true);

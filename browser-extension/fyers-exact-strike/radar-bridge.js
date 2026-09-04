// Marker visible to the page DOM so the React app can choose the
// extension-controlled path instead of opening a second FYERS tab itself.
document.documentElement.dataset.fyersExactStrikeExtension = '1';

document.addEventListener('click', (event) => {
  const button = event.target.closest('[data-fyers-option-symbol]');
  if (!button) return;

  const symbol = button.getAttribute('data-fyers-option-symbol');
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
});

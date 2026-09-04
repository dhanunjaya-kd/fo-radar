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
    // Extension is optional; the normal web-app fallback remains available.
  });
});

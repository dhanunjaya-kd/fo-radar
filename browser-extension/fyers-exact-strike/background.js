const pending = new Map();

function normalizeSymbol(symbol) {
  return String(symbol || '').trim().toUpperCase();
}

function isOptionSymbol(symbol) {
  return /^NSE:[A-Z0-9&.-]+\d{2}(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\d+(CE|PE)$/.test(symbol);
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message?.type !== 'FO_RADAR_OPEN_OPTION') return;

  const symbol = normalizeSymbol(message.symbol);
  if (!isOptionSymbol(symbol)) {
    sendResponse({ ok: false, error: 'Invalid NSE option symbol' });
    return;
  }

  const requestId = crypto.randomUUID();
  pending.set(requestId, { symbol, createdAt: Date.now(), tabId: null });

  chrome.tabs.create({ url: 'https://trade.fyers.in/', active: true }, (tab) => {
    if (chrome.runtime.lastError || !tab?.id) {
      pending.delete(requestId);
      sendResponse({ ok: false, error: chrome.runtime.lastError?.message || 'Unable to open FYERS' });
      return;
    }

    const request = pending.get(requestId);
    if (request) request.tabId = tab.id;

    chrome.tabs.sendMessage(tab.id, {
      type: 'FO_RADAR_SELECT_OPTION',
      requestId,
      symbol
    }).catch(() => {});

    sendResponse({ ok: true, requestId, tabId: tab.id });
  });

  return true;
});

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message?.type !== 'FO_RADAR_FYERS_READY' || !sender.tab?.id) return;

  const now = Date.now();
  const entries = [...pending.entries()].filter(([, value]) => now - value.createdAt < 60_000);

  for (const [requestId, value] of entries) {
    if (value.tabId !== null && value.tabId !== sender.tab.id) continue;

    chrome.tabs.sendMessage(sender.tab.id, {
      type: 'FO_RADAR_SELECT_OPTION',
      requestId,
      symbol: value.symbol
    }).catch(() => {});
    pending.delete(requestId);
    break;
  }

  sendResponse({ ok: true });
});

chrome.tabs.onRemoved.addListener((tabId) => {
  for (const [requestId, value] of pending) {
    if (value.tabId === tabId) pending.delete(requestId);
  }
});

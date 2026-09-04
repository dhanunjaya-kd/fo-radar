const pending = new Map();

function normalizeSymbol(symbol) {
  return String(symbol || '').trim().toUpperCase();
}

function isOptionSymbol(symbol) {
  return /^NSE:[A-Z0-9&.-]+\d{2}(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\d+(CE|PE)$/.test(symbol);
}

function sendSelection(tabId, requestId, symbol) {
  chrome.tabs.sendMessage(tabId, {
    type: 'FO_RADAR_SELECT_OPTION',
    requestId,
    symbol
  }).catch(() => {});
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

    sendResponse({ ok: true, requestId, tabId: tab.id });

    // Wait for the FYERS page/content script to finish loading. This avoids
    // the race where tabs.sendMessage runs before the content script exists.
    const listener = (updatedTabId, changeInfo) => {
      if (updatedTabId !== tab.id || changeInfo.status !== 'complete') return;
      chrome.tabs.onUpdated.removeListener(listener);
      const current = pending.get(requestId);
      if (current) sendSelection(tab.id, requestId, current.symbol);
    };
    chrome.tabs.onUpdated.addListener(listener);
  });

  return true;
});

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message?.type !== 'FO_RADAR_FYERS_READY' || !sender.tab?.id) return;

  const now = Date.now();
  for (const [requestId, value] of pending) {
    if (now - value.createdAt >= 60_000) {
      pending.delete(requestId);
      continue;
    }
    if (value.tabId === sender.tab.id) {
      sendSelection(sender.tab.id, requestId, value.symbol);
      pending.delete(requestId);
      break;
    }
  }

  sendResponse({ ok: true });
});

chrome.tabs.onRemoved.addListener((tabId) => {
  for (const [requestId, value] of pending) {
    if (value.tabId === tabId) pending.delete(requestId);
  }
});

const pending = new Map();

function normalizeSymbol(symbol) {
  return String(symbol || '').trim().toUpperCase();
}

function isNseEquitySymbol(symbol) {
  return /^NSE:[A-Z0-9&.-]+-EQ$/.test(symbol);
}

function sendSelection(tabId, requestId, symbol) {
  chrome.tabs.sendMessage(tabId, {
    type: 'FO_RADAR_SELECT_STOCK',
    requestId,
    symbol
  }).catch(() => {});
}

async function cdpSelectSymbol(tabId, symbol) {
  const target = { tabId };
  try {
    await new Promise((resolve, reject) => {
      chrome.debugger.attach(target, '1.3', () => {
        if (chrome.runtime.lastError) reject(new Error(chrome.runtime.lastError.message));
        else resolve();
      });
    });

    const evalResult = await new Promise((resolve, reject) => {
      chrome.debugger.sendCommand(target, 'Runtime.evaluate', {
        expression: `(() => {
          const visible = (e) => {
            if (!e) return false;
            const r = e.getBoundingClientRect();
            const s = getComputedStyle(e);
            return r.width > 250 && r.height > 180 && s.display !== 'none' && s.visibility !== 'hidden';
          };
          const candidates = [...document.querySelectorAll('canvas, [class*="chart" i], [id*="chart" i]')].filter(visible);
          const el = candidates.sort((a,b) => b.getBoundingClientRect().width*b.getBoundingClientRect().height - a.getBoundingClientRect().width*a.getBoundingClientRect().height)[0];
          if (!el) return null;
          const r = el.getBoundingClientRect();
          return {x: r.left + r.width/2, y: r.top + Math.min(r.height/2, 300)};
        })()`,
        returnByValue: true
      }, (result) => {
        if (chrome.runtime.lastError) reject(new Error(chrome.runtime.lastError.message));
        else resolve(result?.result?.value || null);
      });
    });

    if (!evalResult) throw new Error('FYERS chart element not found');

    await new Promise((resolve, reject) => {
      chrome.debugger.sendCommand(target, 'Input.dispatchMouseEvent', {
        type: 'mousePressed', x: evalResult.x, y: evalResult.y, button: 'left', clickCount: 1
      }, (result) => {
        if (chrome.runtime.lastError) reject(new Error(chrome.runtime.lastError.message));
        else resolve(result);
      });
    });
    await new Promise((resolve, reject) => {
      chrome.debugger.sendCommand(target, 'Input.dispatchMouseEvent', {
        type: 'mouseReleased', x: evalResult.x, y: evalResult.y, button: 'left', clickCount: 1
      }, (result) => {
        if (chrome.runtime.lastError) reject(new Error(chrome.runtime.lastError.message));
        else resolve(result);
      });
    });

    const bare = symbol.replace(/^NSE:/i, '').toUpperCase();
    for (const char of bare) {
      await new Promise((resolve, reject) => {
        chrome.debugger.sendCommand(target, 'Input.dispatchKeyEvent', {
          type: 'keyDown', key: char, text: char, unmodifiedText: char
        }, (result) => {
          if (chrome.runtime.lastError) reject(new Error(chrome.runtime.lastError.message));
          else resolve(result);
        });
      });
      await new Promise((resolve, reject) => {
        chrome.debugger.sendCommand(target, 'Input.dispatchKeyEvent', {
          type: 'keyUp', key: char
        }, (result) => {
          if (chrome.runtime.lastError) reject(new Error(chrome.runtime.lastError.message));
          else resolve(result);
        });
      });
    }

    await new Promise((resolve, reject) => {
      chrome.debugger.sendCommand(target, 'Input.dispatchKeyEvent', {
        type: 'keyDown', key: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13, nativeVirtualKeyCode: 13
      }, (result) => {
        if (chrome.runtime.lastError) reject(new Error(chrome.runtime.lastError.message));
        else resolve(result);
      });
    });
    await new Promise((resolve, reject) => {
      chrome.debugger.sendCommand(target, 'Input.dispatchKeyEvent', {
        type: 'keyUp', key: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13, nativeVirtualKeyCode: 13
      }, (result) => {
        if (chrome.runtime.lastError) reject(new Error(chrome.runtime.lastError.message));
        else resolve(result);
      });
    });

    return true;
  } finally {
    try {
      await new Promise((resolve) => chrome.debugger.detach(target, () => resolve()));
    } catch (_) {}
  }
}

async function driveStock(tabId, requestId, symbol) {
  await new Promise((resolve) => setTimeout(resolve, 1800));
  try {
    const ok = await cdpSelectSymbol(tabId, symbol);
    if (ok) return;
  } catch (error) {
    console.warn('[F&O Radar] CDP stock selection failed:', error?.message || error);
  }
  sendSelection(tabId, requestId, symbol);
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message?.type !== 'FO_RADAR_OPEN_STOCK') return;

  const symbol = normalizeSymbol(message.symbol);
  if (!isNseEquitySymbol(symbol)) {
    sendResponse({ ok: false, error: 'Invalid NSE equity symbol' });
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

    const listener = (updatedTabId, changeInfo) => {
      if (updatedTabId !== tab.id || changeInfo.status !== 'complete') return;
      chrome.tabs.onUpdated.removeListener(listener);
      const current = pending.get(requestId);
      if (current) driveStock(tab.id, requestId, current.symbol);
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
      driveStock(sender.tab.id, requestId, value.symbol);
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

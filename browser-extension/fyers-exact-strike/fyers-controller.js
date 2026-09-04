(() => {
  let handledRequest = null;

  const INPUT_SELECTORS = [
    'input[placeholder*="Search" i]',
    'input[placeholder*="symbol" i]',
    'input[placeholder*="scrip" i]',
    'input[aria-label*="Search" i]',
    'input[type="search"]',
    'input[role="combobox"]',
    '[contenteditable="true"]'
  ];

  function visible(element) {
    if (!element) return false;
    const style = getComputedStyle(element);
    const rect = element.getBoundingClientRect();
    return style.visibility !== 'hidden' && style.display !== 'none' && rect.width > 0 && rect.height > 0;
  }

  function findSearchInput() {
    for (const selector of INPUT_SELECTORS) {
      const candidates = [...document.querySelectorAll(selector)].filter(visible);
      if (candidates.length) return candidates[0];
    }
    return null;
  }

  function fireInput(input, value) {
    input.focus();
    if (input instanceof HTMLInputElement || input instanceof HTMLTextAreaElement) {
      const proto = input instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
      const setter = Object.getOwnPropertyDescriptor(proto, 'value')?.set;
      if (setter) setter.call(input, value);
      else input.value = value;
    } else {
      input.textContent = value;
    }
    input.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'insertText', data: value }));
    input.dispatchEvent(new Event('change', { bubbles: true }));
  }

  function exactSymbolText(symbol) {
    const full = symbol.toUpperCase();
    const bare = full.replace(/^NSE:/, '');
    return [...document.querySelectorAll('body *')]
      .filter(visible)
      .filter((el) => el.children.length === 0)
      .find((el) => {
        const text = (el.textContent || '').trim().toUpperCase();
        return text === full || text === bare;
      });
  }

  function chartLooksLike(symbol) {
    const bare = symbol.replace(/^NSE:/i, '').toUpperCase();
    const text = (document.body?.innerText || '').toUpperCase();
    return text.includes(bare);
  }

  function clickSymbolSearchLauncher() {
    const candidates = [...document.querySelectorAll('button,[role="button"],[tabindex="0"]')].filter(visible);
    const launcher = candidates.find((el) => {
      const text = (el.textContent || '').trim().toUpperCase();
      const aria = (el.getAttribute('aria-label') || '').toUpperCase();
      return /SEARCH|SYMBOL|SCRIPT|SCRIP/.test(`${text} ${aria}`);
    });
    if (launcher) {
      launcher.click();
      return true;
    }
    return false;
  }

  async function waitForInput(timeoutMs = 6000) {
    const start = Date.now();
    while (Date.now() - start < timeoutMs) {
      const input = findSearchInput();
      if (input) return input;
      clickSymbolSearchLauncher();
      await new Promise((resolve) => setTimeout(resolve, 250));
    }
    return null;
  }

  function key(target, type, keyValue) {
    target.dispatchEvent(new KeyboardEvent(type, {
      key: keyValue,
      code: keyValue === 'Enter' ? 'Enter' : `Key${keyValue}`,
      bubbles: true,
      cancelable: true,
      composed: true
    }));
  }

  async function typeSymbolIntoChart(symbol) {
    const bare = symbol.replace(/^NSE:/i, '').toUpperCase();
    const target = document.querySelector('canvas') || document.body;
    if (!target) return false;

    target.focus?.();
    target.click?.();
    await new Promise((resolve) => setTimeout(resolve, 150));

    for (const char of bare) {
      key(target, 'keydown', char);
      key(target, 'keypress', char);
      key(target, 'keyup', char);
      await new Promise((resolve) => setTimeout(resolve, 20));
    }
    key(target, 'keydown', 'Enter');
    key(target, 'keyup', 'Enter');

    const start = Date.now();
    while (Date.now() - start < 8000) {
      await new Promise((resolve) => setTimeout(resolve, 300));
      if (exactSymbolText(symbol) || chartLooksLike(symbol)) return true;
    }
    return false;
  }

  async function selectStock(symbol, requestId) {
    if (handledRequest === requestId) return true;

    const input = await waitForInput();
    if (input) {
      handledRequest = requestId;
      fireInput(input, symbol);

      const start = Date.now();
      while (Date.now() - start < 8000) {
        await new Promise((resolve) => setTimeout(resolve, 300));
        const exact = exactSymbolText(symbol);
        if (exact) {
          exact.click();
          return true;
        }
      }
      handledRequest = null;
    }

    // FYERS documents that typing a symbol while the chart is active changes
    // the chart symbol. Use that native chart shortcut as the fallback.
    return typeSymbolIntoChart(symbol);
  }

  chrome.runtime.onMessage.addListener((message) => {
    if (message?.type !== 'FO_RADAR_SELECT_STOCK' || !message.symbol) return;

    const requestId = message.requestId || crypto.randomUUID();
    let attempts = 0;
    const timer = setInterval(async () => {
      attempts += 1;
      const done = await selectStock(message.symbol, requestId);
      if (done || attempts >= 20) clearInterval(timer);
    }, 500);

    setTimeout(() => clearInterval(timer), 20_000);
  });

  chrome.runtime.sendMessage({ type: 'FO_RADAR_FYERS_READY' }).catch(() => {});
})();

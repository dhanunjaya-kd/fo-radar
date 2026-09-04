(() => {
  let handled = false;

  const SELECTORS = [
    'input[placeholder*="Search" i]',
    'input[placeholder*="symbol" i]',
    'input[placeholder*="scrip" i]',
    'input[aria-label*="Search" i]',
    'input[type="search"]'
  ];

  function visible(element) {
    if (!element) return false;
    const style = getComputedStyle(element);
    const rect = element.getBoundingClientRect();
    return style.visibility !== 'hidden' && style.display !== 'none' && rect.width > 0 && rect.height > 0;
  }

  function findSearchInput() {
    for (const selector of SELECTORS) {
      const candidates = [...document.querySelectorAll(selector)].filter(visible);
      if (candidates.length) return candidates[0];
    }
    return null;
  }

  function fireInput(input, value) {
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set;
    if (setter) setter.call(input, value);
    else input.value = value;
    input.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'insertText', data: value }));
    input.dispatchEvent(new Event('change', { bubbles: true }));
  }

  function textMatch(symbol) {
    const normalized = symbol.replace(/^NSE:/, '').toUpperCase();
    return [...document.querySelectorAll('body *')]
      .filter(visible)
      .find((el) => {
        const text = (el.textContent || '').trim().toUpperCase();
        return text === symbol || text === normalized || text.includes(symbol);
      });
  }

  async function selectExactOption(symbol) {
    if (handled) return false;

    const input = findSearchInput();
    if (!input) return false;

    handled = true;
    input.focus();
    fireInput(input, symbol);

    await new Promise((resolve) => setTimeout(resolve, 700));

    // Prefer an exact symbol row/text. We deliberately do not click a merely
    // similar result: opening the wrong strike is worse than doing nothing.
    const exact = textMatch(symbol);
    if (exact) {
      exact.click();
      await new Promise((resolve) => setTimeout(resolve, 900));
      return true;
    }

    // Some FYERS builds use Enter to select the highlighted exact search hit.
    input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', code: 'Enter', bubbles: true }));
    input.dispatchEvent(new KeyboardEvent('keyup', { key: 'Enter', code: 'Enter', bubbles: true }));
    await new Promise((resolve) => setTimeout(resolve, 900));
    return true;
  }

  chrome.runtime.onMessage.addListener((message) => {
    if (message?.type !== 'FO_RADAR_SELECT_OPTION' || !message.symbol) return;
    handled = false;

    const timer = setInterval(async () => {
      const done = await selectExactOption(message.symbol);
      if (done) clearInterval(timer);
    }, 500);

    setTimeout(() => clearInterval(timer), 20_000);
  });

  chrome.runtime.sendMessage({ type: 'FO_RADAR_FYERS_READY' }).catch(() => {});
})();

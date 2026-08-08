// API Configuration
// Relative on purpose -- Vite's dev-server proxy (vite.config.js) forwards
// /api/* to the Django backend on this same machine, so this works from
// localhost, home wifi, or a Tailscale IP without any changes. Set
// VITE_API_URL to override for a real deployment (separately-hosted backend).
const API_BASE = import.meta.env.VITE_API_URL || '/api';

// Helper: Handle API errors gracefully
const handleResponse = async (response) => {
  if (!response.ok) {
    const errorData = await response.json().catch(() => ({}));
    throw new Error(errorData.detail || errorData.message || `HTTP ${response.status}: ${response.statusText}`);
  }
  return response.json();
};

// Helper: Fetch with timeout
const fetchWithTimeout = async (url, options = {}, timeout = 10000) => {
  const controller = new AbortController();
  const id = setTimeout(() => controller.abort(), timeout);

  try {
    const response = await fetch(url, {
      ...options,
      signal: controller.signal,
      headers: {
        'Content-Type': 'application/json',
        ...options.headers,
      },
    });
    clearTimeout(id);
    return response;
  } catch (error) {
    clearTimeout(id);
    if (error.name === 'AbortError') {
      throw new Error('Request timed out. Backend may be down.');
    }
    throw error;
  }
};

// ==================== API ENDPOINTS ====================

export const api = {
  // Market Summary (Banner data)
  getMarketSummary: async () => {
    try {
      // This used to call '/screener/signals/' -- a copy-paste leftover
      // from getSignals below, not the market-summary endpoint at all.
      const res = await fetchWithTimeout(`${API_BASE}/market-summary/`);
      return await handleResponse(res);
    } catch (error) {
      console.warn('Market summary fetch failed:', error.message);
      // Return fallback data so UI never breaks
      return {
        nifty: { value: 22438.788, change: 125.30, changePercent: 0.56 },
        banknifty: { value: 47817.601, change: -45.20, changePercent: -0.09 }, 
        vix: { value: 13.45, change: -0.82 },
        pcr: 1.02,
      };
    }
  },

  // Scanner Signals
  getSignals: async () => {
    try {
      // '/screener/signals/' was never a registered path (the real one is
      // '/signals/', which reads the same live cache '/sniper-only/' does)
      // -- this always 404'd.
      const res = await fetchWithTimeout(`${API_BASE}/signals/`);
      return await handleResponse(res);
    } catch (error) {
      console.warn('Signals fetch failed:', error.message);
      return { stocks: [], error: error.message };
    }
  },

  // News
  getNews: async (symbol = null) => {
    try {
      const url = symbol 
        ? `${API_BASE}/news/?symbol=${encodeURIComponent(symbol)}`
        : `${API_BASE}/news/`;
      const res = await fetchWithTimeout(url);
      return await handleResponse(res);
    } catch (error) {
      console.warn('News fetch failed:', error.message);
      return [];
    }
  },

  // Options Chain / OI Data (DB-backed, populated only if the Celery
  // pipeline in screener/tasks.py has run and Fyers was authenticated)
  getOptionsData: async (symbol, expiry = 'current') => {
    try {
      const res = await fetchWithTimeout(
        `${API_BASE}/options/chain/${encodeURIComponent(symbol)}/?expiry=${expiry}`
      );
      return await handleResponse(res);
    } catch (error) {
      console.warn('Options fetch failed:', error.message);
      return null;
    }
  },

  // Token bridge for services/fyersSocket.js's browser-side WebSocket
  getFyersBrowserToken: async () => {
    try {
      const res = await fetchWithTimeout(`${API_BASE}/fyers-browser-token/`);
      return await handleResponse(res);
    } catch (error) {
      console.warn('Token bridge fetch failed:', error.message);
      return { authenticated: false, access_token: null };
    }
  },

  // Real-time option chain analytics: PCR, Max Pain, support/resistance,
  // IV, Greeks -- fetched fresh from Fyers on every call. Backs the
  // 'OI Analytics' tab.
  getOptionAnalytics: async (symbol) => {
    const res = await fetchWithTimeout(`${API_BASE}/option-analytics/${encodeURIComponent(symbol)}/`, {}, 15000);
    return await handleResponse(res);
  },

  // F&O Stock List (for Marquee)
  getFOStocks: async () => {
    try {
      const res = await fetchWithTimeout(`${API_BASE}/stocks/fo-list/`);
      return await handleResponse(res);
    } catch (error) {
      console.warn('F&O list fetch failed:', error.message);
      // Fallback: Top F&O stocks
      return [
        { symbol: 'RELIANCE', name: 'Reliance', close: 1278.00, change: 0.46 },
        { symbol: 'TCS', name: 'TCS', close: 4150.00, change: 0.80 },
        { symbol: 'HDFCBANK', name: 'HDFC Bank', close: 1680.00, change: -0.30 },
        { symbol: 'INFY', name: 'Infosys', close: 1845.60, change: 1.50 },
        { symbol: 'ICICIBANK', name: 'ICICI Bank', close: 1187.40, change: 0.50 },
        { symbol: 'SBIN', name: 'SBI', close: 760.00, change: 2.10 },
        { symbol: 'BHARTIARTL', name: 'Bharti Airtel', close: 1423.80, change: -0.80 },
        { symbol: 'ITC', name: 'ITC', close: 478.90, change: 0.30 },
        { symbol: 'KOTAKBANK', name: 'Kotak', close: 1789.50, change: -0.50 },
        { symbol: 'LT', name: 'L&T', close: 3567.80, change: 1.80 },
        { symbol: 'AXISBANK', name: 'Axis Bank', close: 1123.40, change: 0.90 },
        { symbol: 'HINDUNILVR', name: 'HUL', close: 2456.70, change: -0.20 },
        { symbol: 'BAJFINANCE', name: 'Bajaj Finance', close: 6850.00, change: 1.10 },
        { symbol: 'ASIANPAINT', name: 'Asian Paints', close: 3120.00, change: -0.40 },
        { symbol: 'MARUTI', name: 'Maruti Suzuki', close: 11200.00, change: 0.70 },
      ];
    }
  },

  // Paper Trade
  placePaperTrade: async (tradeData) => {
    try {
      const res = await fetchWithTimeout(`${API_BASE}/paper-trade/`, {
        method: 'POST',
        body: JSON.stringify(tradeData),
      });
      return await handleResponse(res);
    } catch (error) {
      console.warn('Paper trade failed:', error.message);
      throw error;
    }
  },

  // P&L Tracker
  getPnL: async () => {
    try {
      const res = await fetchWithTimeout(`${API_BASE}/pnl/`);
      return await handleResponse(res);
    } catch (error) {
      console.warn('PnL fetch failed:', error.message);
      return { trades: [], totalPnL: 0, winRate: 0 };
    }
  },
};

export default api;
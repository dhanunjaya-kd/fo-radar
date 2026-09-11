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
    const res = await fetchWithTimeout(`${API_BASE}/market-summary/`);
    return await handleResponse(res);
  },

  // Scanner Signals
  getSignals: async () => {
    try {
      // '/screener/signals/' was never a registered path (the real one is
      // '/signals/', which reads the same live cache '/sniper-only/' does).
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
      // No fabricated market rows. Preserve the endpoint's array contract
      // while honestly returning no rows when the backend is unavailable.
      return [];
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
      // Trading app routes live under /api/trading/, not /api/pnl/.
      const res = await fetchWithTimeout(`${API_BASE}/trading/pnl/summary/`);
      const data = await handleResponse(res);
      // Preserve the field name used by older UI components, but map it
      // from the backend's real total_pnl value -- never invent a fallback.
      return {
        ...data,
        totalPnL: data.total_pnl ?? 0,
        winRate: data.win_rate ?? 0,
      };
    } catch (error) {
      console.warn('PnL fetch failed:', error.message);
      return { trades: [], totalPnL: null, winRate: null, error: error.message };
    }
  },
};

export default api;

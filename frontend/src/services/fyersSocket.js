// ============================================
// Fyers v3 WebSocket — Market Data Only
// App: FOSniperFullstack (Non-trading)
// App ID: LYNP1Z6GGG-100
// ============================================
//
// !!! PARTIALLY VERIFIED — read before assuming this works !!!
// The endpoint below was wrong (this file had 'wss://socket.fyers.in/v3',
// which is not a real Fyers host) -- corrected to the one Fyers' own docs
// specify: https://support.fyers.in/portal/en/kb/articles/how-can-i-use-the-data-websocket-in-api-v3-to-access-real-time-data
//
// What I could NOT verify from documentation alone: the exact shape of
// the auth handshake and subscribe messages below ({method:'auth',...},
// {method:'sub',...}), and whether tick payloads arrive as JSON or a
// binary/protobuf frame (Fyers' v3 release notes mention the websocket
// output format changed significantly from v2). If ticks still don't
// arrive after the URL fix, that's the most likely reason -- the
// officially correct way to consume this feed is the Python SDK's
// `fyers_apiv3.FyersWebsocket.data_ws.FyersDataSocket`, which handles
// the real wire format for you. The robust fix is to run that on the
// backend and push ticks out over the Django Channels WebSocket routes
// already wired in fno_sniper/asgi.py, instead of hand-rolling the Fyers
// protocol again in the browser.
const FYERS_WS_URL = 'wss://api.fyers.in/socket/v2/data/';
const APP_ID = 'LYNP1Z6GGG-100';

class FyersSocket {
  constructor() {
    this.ws = null;
    this.subscriptions = new Set();
    this.callbacks = new Map();
    this.reconnectAttempts = 0;
    this.maxReconnect = 5;
    this.isAuthenticated = false;
  }

  getAccessToken() {
    // Try localStorage first, then sessionStorage
    return localStorage.getItem('fyers_access_token') 
        || sessionStorage.getItem('fyers_access_token') 
        || '';
  }

  connect() {
    if (this.ws?.readyState === WebSocket.OPEN) return;

    this.ws = new WebSocket(FYERS_WS_URL);

    this.ws.onopen = () => {
      console.log('🔌 Fyers WS Connected');
      this.reconnectAttempts = 0;
      this.authenticate();
    };

    this.ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        this.handleMessage(data);
      } catch (e) {
        console.error('WS Parse Error:', e);
      }
    };

    this.ws.onclose = () => {
      console.log('🔌 Fyers WS Disconnected');
      this.isAuthenticated = false;
      if (this.reconnectAttempts < this.maxReconnect) {
        setTimeout(() => {
          this.reconnectAttempts++;
          console.log(`Reconnecting... attempt ${this.reconnectAttempts}`);
          this.connect();
        }, 3000);
      }
    };

    this.ws.onerror = (err) => {
      console.error('WS Error:', err);
    };
  }

  authenticate() {
    const token = this.getAccessToken();
    if (!token) {
      console.warn('⚠️ No Fyers access token found. Run auth flow first.');
      return;
    }

    const authMsg = {
      method: 'auth',
      data: {
        app_id: APP_ID,
        access_token: token,
      },
    };
    this.send(authMsg);
    console.log('🔑 Sending auth...');
  }

  subscribe(symbols) {
    if (!Array.isArray(symbols)) symbols = [symbols];
    symbols.forEach(s => this.subscriptions.add(s));
    
    this.send({
      method: 'sub',
      data: { symbol: symbols },
    });
    console.log('📡 Subscribed:', symbols);
  }

  unsubscribe(symbols) {
    if (!Array.isArray(symbols)) symbols = [symbols];
    symbols.forEach(s => this.subscriptions.delete(s));
    
    this.send({
      method: 'unsub',
      data: { symbol: symbols },
    });
  }

  send(msg) {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(msg));
    } else {
      console.warn('WS not open, queueing message');
    }
  }

  handleMessage(data) {
    // Auth response
    if (data.s === 'ok' && data.type === 'auth') {
      console.log('✅ Fyers WS Authenticated');
      this.isAuthenticated = true;
      // Re-subscribe to any pending symbols
      if (this.subscriptions.size > 0) {
        this.subscribe([...this.subscriptions]);
      }
      return;
    }

    // Auth failed
    if (data.s === 'error' && data.type === 'auth') {
      console.error('❌ Auth failed:', data.message);
      return;
    }

    // Market data tick
    if (data.symbol && this.callbacks.has(data.symbol)) {
      this.callbacks.get(data.symbol).forEach(cb => cb(data));
    }
  }

  onTick(symbol, callback) {
    if (!this.callbacks.has(symbol)) {
      this.callbacks.set(symbol, new Set());
    }
    this.callbacks.get(symbol).add(callback);
    this.subscribe(symbol);
  }

  offTick(symbol, callback) {
    if (this.callbacks.has(symbol)) {
      this.callbacks.get(symbol).delete(callback);
      if (this.callbacks.get(symbol).size === 0) {
        this.unsubscribe(symbol);
      }
    }
  }

  disconnect() {
    this.ws?.close();
  }
}

export const fyersSocket = new FyersSocket();
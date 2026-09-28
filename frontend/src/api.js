const browserLocation = new URL(window.location.href);
const defaultApiBase = import.meta.env.DEV
  ? `${browserLocation.protocol}//${browserLocation.hostname}:8000`
  : browserLocation.origin;
export const API = (import.meta.env.VITE_API_BASE_URL || import.meta.env.VITE_API_URL || defaultApiBase).replace(/\/$/, '');
const defaultWebSocketBase = new URL(API, browserLocation.origin);
defaultWebSocketBase.protocol = defaultWebSocketBase.protocol === 'https:' ? 'wss:' : 'ws:';
export const WS = (import.meta.env.VITE_WS_BASE_URL || defaultWebSocketBase.origin).replace(/\/$/, '');
export const PUBLIC_APP_URL = (import.meta.env.VITE_PUBLIC_APP_URL || browserLocation.origin).replace(/\/$/, '');
export function sessionJoinUrl(session) {
  if (import.meta.env.VITE_PUBLIC_APP_URL) {
    return `${PUBLIC_APP_URL}/join/${session.code}`;
  }
  if (!session) return '';
  if (session.join_url) {
    if (browserLocation.hostname !== 'localhost' && browserLocation.hostname !== '127.0.0.1') {
      try {
        const u = new URL(session.join_url);
        if (u.hostname === 'localhost' || u.hostname === '127.0.0.1') {
          u.hostname = browserLocation.hostname;
          return u.toString();
        }
      } catch (e) {}
    }
    return session.join_url;
  }
  return `${browserLocation.origin}/join/${session.code}`;
}

if (import.meta.env.PROD && (!API.startsWith('https://') || !WS.startsWith('wss://') || !PUBLIC_APP_URL.startsWith('https://'))) {
  throw new Error('Production app/API/WebSocket URLs must use HTTPS and WSS.');
}
export async function request(path, options = {}) {
  const response = await fetch(`${API}${path}`, {headers: {'Content-Type': 'application/json', ...(options.headers || {})}, ...options});
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || 'Request failed');
  return data;
}
export const apiBase = API;

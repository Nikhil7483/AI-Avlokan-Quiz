function cleanUrl(url) {
  if (!url || typeof url !== 'string') return '';
  const trimmed = url.trim().replace(/\/$/, '');
  // Ignore literal placeholder brackets if pasted by accident
  if (trimmed.includes('<') || trimmed.includes('>') || trimmed.includes('[') || trimmed.includes(']')) {
    return '';
  }
  return trimmed;
}

function getBrowserLocation() {
  try {
    return new URL(window.location.href);
  } catch {
    return { protocol: 'https:', hostname: 'localhost', origin: (typeof window !== 'undefined' && window.location?.origin) || '' };
  }
}

export function getSavedApiUrl() {
  try {
    return (typeof window !== 'undefined' && localStorage.getItem('apiBaseUrl')) || '';
  } catch {
    return '';
  }
}

export function setApiBaseUrl(url) {
  try {
    const cleaned = cleanUrl(url);
    if (cleaned) {
      localStorage.setItem('apiBaseUrl', cleaned);
    } else {
      localStorage.removeItem('apiBaseUrl');
    }
    window.location.reload();
  } catch {}
}

const browserLocation = getBrowserLocation();
const savedApi = cleanUrl(getSavedApiUrl());
const rawApi = cleanUrl(import.meta.env.VITE_API_BASE_URL || import.meta.env.VITE_API_URL);
const defaultApiBase = import.meta.env.DEV
  ? `${browserLocation.protocol}//${browserLocation.hostname}:8000`
  : 'https://ai-avlokan-quiz.onrender.com';

export const API = savedApi || rawApi || defaultApiBase;

function resolveWsOrigin(apiBaseUrl) {
  try {
    const target = apiBaseUrl.startsWith('http') ? apiBaseUrl : `${browserLocation.protocol}//${apiBaseUrl}`;
    const parsed = new URL(target, browserLocation.origin);
    parsed.protocol = parsed.protocol === 'https:' ? 'wss:' : 'ws:';
    return parsed.origin;
  } catch {
    return (browserLocation.origin || '').replace(/^http/, 'ws');
  }
}

const rawWs = cleanUrl(import.meta.env.VITE_WS_BASE_URL);
export const WS = rawWs || resolveWsOrigin(API);

const rawPublic = cleanUrl(import.meta.env.VITE_PUBLIC_APP_URL);
export const PUBLIC_APP_URL = rawPublic || browserLocation.origin;

export function sessionJoinUrl(session) {
  if (PUBLIC_APP_URL && !PUBLIC_APP_URL.includes('localhost') && !PUBLIC_APP_URL.includes('127.0.0.1')) {
    return `${PUBLIC_APP_URL}/join/${session?.code || ''}`;
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
  return `${browserLocation.origin}/join/${session.code || ''}`;
}

if (import.meta.env.PROD && (!API.startsWith('https://') || !WS.startsWith('wss://') || !PUBLIC_APP_URL.startsWith('https://'))) {
  console.warn('Production notice: Make sure API and app URLs use HTTPS/WSS in Vercel environment variables.');
}

export async function request(path, options = {}) {
  const response = await fetch(`${API}${path}`, {
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || 'Request failed');
  return data;
}

export const apiBase = API;

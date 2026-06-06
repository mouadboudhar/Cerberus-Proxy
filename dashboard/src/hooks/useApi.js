import { useCallback, useEffect, useState } from 'react';

const TOKEN_KEY = 'cbrs_token';

export function getToken() {
  return localStorage.getItem(TOKEN_KEY);
}
export function setToken(token) {
  localStorage.setItem(TOKEN_KEY, token);
}
export function clearToken() {
  localStorage.removeItem(TOKEN_KEY);
}

/**
 * Low-level request helper. Injects the dashboard token, JSON-encodes the body,
 * and on 401 clears the token and bounces to /login.
 */
export async function apiRequest(path, { method = 'GET', body, headers = {} } = {}) {
  const token = getToken();
  const opts = { method, headers: { ...headers } };
  if (token) opts.headers['X-Dashboard-Token'] = token;
  if (body !== undefined) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
  }

  const res = await fetch(path, opts);

  if (res.status === 401) {
    clearToken();
    if (window.location.pathname !== '/login') {
      window.location.assign('/login');
    }
    throw new Error('unauthorized');
  }
  if (!res.ok) {
    let detail;
    try {
      detail = (await res.json()).detail;
    } catch {
      /* non-JSON error body */
    }
    throw new Error(detail || `request failed (${res.status})`);
  }
  if (res.status === 204) return null;
  const ct = res.headers.get('content-type') || '';
  return ct.includes('application/json') ? res.json() : res.text();
}

/**
 * Data-fetching hook: { data, loading, error, refetch }.
 * Auto-injects the dashboard token and handles 401 via apiRequest.
 */
export function useApi(path, { auto = true } = {}) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(auto);
  const [error, setError] = useState(null);

  const refetch = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const d = await apiRequest(path);
      setData(d);
      return d;
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [path]);

  useEffect(() => {
    if (auto) refetch();
  }, [auto, refetch]);

  return { data, loading, error, refetch };
}

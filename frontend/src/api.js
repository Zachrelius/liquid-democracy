/**
 * API client — wraps fetch, attaches JWT, handles errors.
 * Supports access_token + refresh_token flow.
 */

let _token = null;
let _refreshToken = null;
let _refreshPromise = null;

export function setToken(token) {
  _token = token;
}

export function setTokens(accessToken, refreshToken) {
  _token = accessToken;
  _refreshToken = refreshToken;
}

export function getRefreshToken() {
  return _refreshToken;
}

function authHeaders() {
  const h = { 'Content-Type': 'application/json' };
  if (_token) h['Authorization'] = `Bearer ${_token}`;
  return h;
}

/**
 * Try to refresh the access token using the stored refresh token.
 * Returns true on success, false on failure.
 * Deduplicates concurrent refresh attempts.
 */
export async function refreshAccessToken() {
  if (!_refreshToken) return false;

  // Deduplicate: if a refresh is already in flight, wait for it
  if (_refreshPromise) {
    return _refreshPromise;
  }

  _refreshPromise = (async () => {
    try {
      const res = await fetch('/api/auth/refresh', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: _refreshToken }),
      });
      if (!res.ok) return false;
      const data = await res.json();
      _token = data.access_token;
      _refreshToken = data.refresh_token;
      // Persist to sessionStorage
      sessionStorage.setItem('token', data.access_token);
      sessionStorage.setItem('refreshToken', data.refresh_token);
      return true;
    } catch {
      return false;
    } finally {
      _refreshPromise = null;
    }
  })();

  return _refreshPromise;
}

async function request(method, path, body) {
  const opts = { method, headers: authHeaders() };
  if (body !== undefined) opts.body = JSON.stringify(body);

  let res;
  try {
    res = await fetch(path, opts);
  } catch (err) {
    throw { message: 'Network error — is the server running?', status: 0 };
  }

  if (res.status === 401) {
    // Try refreshing the token before giving up
    const refreshed = await refreshAccessToken();
    if (refreshed) {
      // Retry the original request with the new token
      const retryOpts = { method, headers: authHeaders() };
      if (body !== undefined) retryOpts.body = JSON.stringify(body);
      try {
        res = await fetch(path, retryOpts);
      } catch (err) {
        throw { message: 'Network error — is the server running?', status: 0 };
      }
      // If still 401 after refresh, give up
      if (res.status === 401) {
        window.dispatchEvent(new Event('auth:unauthorized'));
        throw { message: 'Session expired. Please log in again.', status: 401 };
      }
    } else {
      window.dispatchEvent(new Event('auth:unauthorized'));
      throw { message: 'Session expired. Please log in again.', status: 401 };
    }
  }

  if (res.status === 204) return null;

  let data;
  const ct = res.headers.get('Content-Type') || '';
  if (ct.includes('application/json')) {
    data = await res.json();
  } else {
    data = await res.text();
  }

  if (!res.ok) {
    // Pydantic validation errors come as { detail: [...] }
    const detail = data?.detail;
    let message;
    if (Array.isArray(detail)) {
      message = detail.map(e => `${e.loc?.slice(1).join('.')} — ${e.msg}`).join('; ');
    } else if (typeof detail === 'string') {
      message = detail;
    } else {
      message = `Server error ${res.status}`;
    }
    throw { message, status: res.status, raw: data };
  }

  return data;
}

const api = {
  get: (path) => request('GET', path),
  post: (path, body) => request('POST', path, body),
  put: (path, body) => request('PUT', path, body),
  patch: (path, body) => request('PATCH', path, body),
  delete: (path) => request('DELETE', path),

  // Auth endpoints (no JSON body — uses form encoding for /login)
  async login(username, password) {
    const form = new URLSearchParams({ username, password });
    let res;
    try {
      res = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: form.toString(),
      });
    } catch {
      throw { message: 'Network error — is the server running?', status: 0 };
    }
    const data = await res.json();
    if (!res.ok) {
      throw { message: data?.detail || 'Login failed', status: res.status };
    }
    return data; // { access_token, refresh_token, token_type }
  },

  async logout() {
    const rt = _refreshToken;
    if (rt && _token) {
      try {
        await request('POST', '/api/auth/logout', { refresh_token: rt });
      } catch {
        // Ignore errors during logout
      }
    }
  },
};

export default api;

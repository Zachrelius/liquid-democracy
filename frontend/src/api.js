/**
 * API client — wraps fetch, attaches JWT, safely parses responses, and
 * refreshes expired access tokens. Phase 103 keeps every API path on the
 * same content-type-aware error parser so an HTML gateway page can never
 * surface as a JSON parser exception.
 */

let _token = null;
let _refreshToken = null;
let _refreshPromise = null;

export const TEMPORARY_UNAVAILABLE_MESSAGE =
  'The service is temporarily busy. Please try again in a moment.';
export const REQUEST_TIMEOUT_MESSAGE =
  'The request took too long. Please try again.';

const DEFAULT_GET_TIMEOUT_MS = 15000;
const DEFAULT_AUTH_TIMEOUT_MS = 15000;
const TEMPORARY_STATUSES = new Set([502, 503, 504]);

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
  if (_token) h.Authorization = `Bearer ${_token}`;
  return h;
}

/**
 * Normalize API error envelopes without ever stringifying or displaying an
 * arbitrary body. Structured Pydantic/SlowAPI detail remains authoritative;
 * an unstructured 502/503/504 receives calm overload copy.
 */
export function normalizeApiError(data, status) {
  const detail = data && typeof data === 'object' ? data.detail : null;
  if (Array.isArray(detail)) {
    return detail.map(e => `${e.loc?.slice(1).join('.')} — ${e.msg}`).join('; ');
  }
  if (typeof detail === 'string') return detail;
  if (data && typeof data === 'object' && typeof data.error === 'string') {
    return data.error;
  }
  if (TEMPORARY_STATUSES.has(status)) return TEMPORARY_UNAVAILABLE_MESSAGE;
  return `Server error ${status}`;
}

function apiError(message, status, extra = {}) {
  return { message, status, ...extra };
}

/**
 * The single response parser used by JSON requests, token refresh, form-data,
 * login, and download errors. It tolerates empty bodies and malformed JSON;
 * raw text/HTML is retained only as non-user-facing diagnostic data.
 */
export async function parseApiResponse(res) {
  if (res.status === 204) return null;

  const contentType = res.headers.get('Content-Type') || '';
  const text = await res.text();
  let data = null;
  let malformedJson = false;

  if (text && /(^|\s|;)application\/(?:[\w.+-]*\+)?json(?:;|$)/i.test(contentType)) {
    try {
      data = JSON.parse(text);
    } catch {
      malformedJson = true;
    }
  } else if (text) {
    data = text;
  }

  if (!res.ok) {
    throw apiError(normalizeApiError(data, res.status), res.status, {
      // Existing callers inspect structured validation/import detail. Never
      // retain an HTML/text gateway body where it could later be rendered.
      raw: data && typeof data === 'object' ? data : null,
      malformedJson,
    });
  }
  if (malformedJson) {
    throw apiError('The server sent an unreadable response. Please try again.', res.status, {
      code: 'invalid_response',
    });
  }
  return data;
}

/** Build one abort signal from caller cancellation plus a bounded timeout. */
function fetchControl({ signal, timeoutMs } = {}) {
  const controller = new AbortController();
  let timedOut = false;
  const abortFromCaller = () => controller.abort(signal?.reason);
  if (signal) {
    if (signal.aborted) abortFromCaller();
    else signal.addEventListener('abort', abortFromCaller, { once: true });
  }
  const timer = Number.isFinite(timeoutMs) && timeoutMs > 0
    ? setTimeout(() => {
      timedOut = true;
      controller.abort();
    }, timeoutMs)
    : null;
  return {
    signal: controller.signal,
    didTimeout: () => timedOut,
    cleanup() {
      if (timer) clearTimeout(timer);
      signal?.removeEventListener('abort', abortFromCaller);
    },
  };
}

export function isAbortError(error) {
  return error?.name === 'AbortError' || error?.code === 'request_aborted';
}

function mapFetchError(error, control) {
  if (error?.status !== undefined) return error;
  if (control.didTimeout()) {
    return apiError(REQUEST_TIMEOUT_MESSAGE, 0, { code: 'request_timeout' });
  }
  if (control.signal.aborted || error?.name === 'AbortError') {
    return apiError('', 0, { name: 'AbortError', code: 'request_aborted' });
  }
  return apiError("Couldn't reach the server. Check your connection and try again.", 0, {
    code: 'network_error',
  });
}

async function controlledFetch(path, options, controlOptions, consume = response => response) {
  const control = fetchControl(controlOptions);
  try {
    const response = await fetch(path, { ...options, signal: control.signal });
    // Keep the caller signal and timeout wired until the response body has
    // been consumed. fetch() can resolve at headers while response.text() or
    // response.blob() is still stalled.
    return await consume(response);
  } catch (error) {
    throw mapFetchError(error, control);
  } finally {
    control.cleanup();
  }
}

async function controlledParsedFetch(path, options, controlOptions) {
  return controlledFetch(path, options, controlOptions, async response => {
    try {
      return { unauthorized: false, data: await parseApiResponse(response) };
    } catch (error) {
      if (error?.status === 401) return { unauthorized: true, data: null };
      throw error;
    }
  });
}

/**
 * Try to refresh the access token using the stored refresh token.
 * Concurrent callers share one attempt. AuthContext's boot-time probe keeps
 * the historical boolean API; an ordinary request asks server errors to be
 * propagated so a gateway 502 is not misreported as a logged-out session.
 */
export async function refreshAccessToken({ throwOnServerError = false } = {}) {
  if (!_refreshToken) return false;
  if (!_refreshPromise) {
    _refreshPromise = (async () => {
      const data = await controlledFetch('/api/auth/refresh', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: _refreshToken }),
      }, { timeoutMs: DEFAULT_AUTH_TIMEOUT_MS }, parseApiResponse);
      if (!data?.access_token || !data?.refresh_token) return false;
      _token = data.access_token;
      _refreshToken = data.refresh_token;
      sessionStorage.setItem('token', data.access_token);
      sessionStorage.setItem('refreshToken', data.refresh_token);
      return true;
    })().finally(() => {
      _refreshPromise = null;
    });
  }

  try {
    return await _refreshPromise;
  } catch (error) {
    if (throwOnServerError && (
      error?.status >= 500
      || error?.code === 'network_error'
      || error?.code === 'request_timeout'
      || error?.code === 'invalid_response'
      || isAbortError(error)
    )) throw error;
    return false;
  }
}

async function request(method, path, body, requestOptions = {}) {
  const opts = { method, headers: authHeaders() };
  if (body !== undefined) opts.body = JSON.stringify(body);
  const timeoutMs = requestOptions.timeoutMs
    ?? (method === 'GET' ? DEFAULT_GET_TIMEOUT_MS : undefined);

  let result = await controlledParsedFetch(path, opts, {
    signal: requestOptions.signal,
    timeoutMs,
  });

  if (result.unauthorized) {
    const refreshed = await refreshAccessToken({ throwOnServerError: true });
    if (refreshed) {
      const retryOpts = { method, headers: authHeaders() };
      if (body !== undefined) retryOpts.body = JSON.stringify(body);
      result = await controlledParsedFetch(path, retryOpts, {
        signal: requestOptions.signal,
        timeoutMs,
      });
      if (result.unauthorized) {
        window.dispatchEvent(new Event('auth:unauthorized'));
        throw apiError('Session expired. Please log in again.', 401);
      }
    } else {
      window.dispatchEvent(new Event('auth:unauthorized'));
      throw apiError('Session expired. Please log in again.', 401);
    }
  }

  return result.data;
}

async function requestFormData(path, formData, requestOptions = {}) {
  const headers = {};
  if (_token) headers.Authorization = `Bearer ${_token}`;
  let result = await controlledParsedFetch(path, {
    method: 'POST', headers, body: formData,
  }, { signal: requestOptions.signal, timeoutMs: requestOptions.timeoutMs });

  if (result.unauthorized) {
    const refreshed = await refreshAccessToken({ throwOnServerError: true });
    if (refreshed) {
      const retryHeaders = {};
      if (_token) retryHeaders.Authorization = `Bearer ${_token}`;
      result = await controlledParsedFetch(path, {
        method: 'POST', headers: retryHeaders, body: formData,
      }, { signal: requestOptions.signal, timeoutMs: requestOptions.timeoutMs });
      if (result.unauthorized) {
        window.dispatchEvent(new Event('auth:unauthorized'));
        throw apiError('Session expired. Please log in again.', 401);
      }
    } else {
      window.dispatchEvent(new Event('auth:unauthorized'));
      throw apiError('Session expired. Please log in again.', 401);
    }
  }
  return result.data;
}

async function downloadFile(path, fallbackName, requestOptions = {}) {
  const result = await controlledFetch(path, {
    method: 'GET', headers: authHeaders(),
  }, {
    signal: requestOptions.signal,
    timeoutMs: requestOptions.timeoutMs ?? DEFAULT_GET_TIMEOUT_MS,
  }, async response => {
    if (response.status === 401) return { unauthorized: true };
    if (!response.ok) await parseApiResponse(response);
    return {
      unauthorized: false,
      blob: await response.blob(),
      contentDisposition: response.headers.get('Content-Disposition') || '',
    };
  });
  if (result.unauthorized) {
    window.dispatchEvent(new Event('auth:unauthorized'));
    throw apiError('Session expired. Please log in again.', 401);
  }

  const match = result.contentDisposition.match(/filename="?([^";]+)"?/);
  const name = (match && match[1]) || fallbackName || 'download';
  const url = window.URL.createObjectURL(result.blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = name;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.URL.revokeObjectURL(url);
}

const api = {
  get: (path, options) => request('GET', path, undefined, options),
  download: (path, fallbackName, options) => downloadFile(path, fallbackName, options),
  post: (path, body, options) => request('POST', path, body, options),
  put: (path, body, options) => request('PUT', path, body, options),
  patch: (path, body, options) => request('PATCH', path, body, options),
  delete: (path, opts) => request('DELETE', path, opts?.body, opts),
  postFormData: (path, form, options) => requestFormData(path, form, options),

  async login(username, password, options = {}) {
    const form = new URLSearchParams({ username, password });
    return controlledFetch('/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: form.toString(),
    }, {
      signal: options.signal,
      timeoutMs: options.timeoutMs ?? DEFAULT_AUTH_TIMEOUT_MS,
    }, parseApiResponse);
  },

  async logout() {
    const rt = _refreshToken;
    if (rt && _token) {
      try {
        await request('POST', '/api/auth/logout', { refresh_token: rt });
      } catch {
        // Logging out locally must remain available during an outage.
      }
    }
  },
};

export default api;

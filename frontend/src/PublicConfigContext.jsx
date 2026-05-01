import { createContext, useContext, useEffect, useState } from 'react';
import api from './api';

/**
 * Phase 9 Session 3 — public-config provider.
 *
 * Reads `GET /api/public-config` once at app boot and exposes the resulting
 * feature-flag bag to descendants. Currently used for `polis_token_configured`
 * which drives the manual-fallback UX on every Polis admin surface (when the
 * token isn't configured we treat the pol.is API call as if it didn't run and
 * surface "complete this on pol.is" reminders).
 *
 * The endpoint is unauthenticated, so we fetch it eagerly without waiting for
 * an authenticated session. If the fetch fails (e.g., backend down at boot),
 * we fall back to `polis_token_configured: false` — the safe, manual-fallback
 * mode where every Polis admin surface assumes no programmatic access.
 */

const PublicConfigContext = createContext(null);

const DEFAULT_CONFIG = {
  polis_token_configured: false,
};

export function PublicConfigProvider({ children }) {
  const [config, setConfig] = useState(DEFAULT_CONFIG);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await api.get('/api/public-config');
        if (!cancelled) {
          setConfig({ ...DEFAULT_CONFIG, ...(data || {}) });
        }
      } catch {
        // Fall back to safe defaults — we already initialized to DEFAULT_CONFIG.
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  return (
    <PublicConfigContext.Provider value={{ ...config, loading }}>
      {children}
    </PublicConfigContext.Provider>
  );
}

export function usePublicConfig() {
  const ctx = useContext(PublicConfigContext);
  if (!ctx) {
    // Defensive: a Polis component rendered outside the provider tree should
    // not crash the page; treat as manual-fallback.
    return { ...DEFAULT_CONFIG, loading: false };
  }
  return ctx;
}

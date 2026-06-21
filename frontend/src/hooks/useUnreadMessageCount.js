import { useEffect, useState } from 'react';

import api from '../api';

/**
 * Phase 77 — unread message count for the org nav badge. Polls the cheap
 * unread-count endpoint every 60s (matching the pending-actions /
 * notification badge cadence). Quietly fails to 0 (badge just hides).
 */
export default function useUnreadMessageCount(orgSlug) {
  const [count, setCount] = useState(0);
  const [loading, setLoading] = useState(true);

  async function load() {
    if (!orgSlug) {
      setCount(0);
      setLoading(false);
      return;
    }
    try {
      const data = await api.get(`/api/orgs/${orgSlug}/messages/unread-count`);
      setCount(data?.unread_count || 0);
    } catch {
      setCount(0);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    if (!orgSlug) return undefined;
    const t = setInterval(load, 60_000);
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [orgSlug]);

  return { count, loading, refresh: load };
}

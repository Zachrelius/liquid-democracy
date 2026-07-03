import { useEffect, useState } from 'react';

import api from '../api';

/**
 * Phase 86 (B-4) — open content-report count for the moderator nav badge.
 * Mirrors usePendingActionsCount: cheap /count endpoint, 60s poll, quiet
 * failure (the badge just doesn't show). ``eligible`` is false for callers
 * without comment.moderate.
 */
export default function useOpenReportsCount(orgSlug) {
  const [count, setCount] = useState(0);
  const [eligible, setEligible] = useState(false);

  async function load() {
    if (!orgSlug) {
      setCount(0); setEligible(false);
      return;
    }
    try {
      const data = await api.get(`/api/orgs/${orgSlug}/reports/count`);
      setCount(data.open_count || 0);
      setEligible(!!data.eligible);
    } catch {
      setCount(0); setEligible(false);
    }
  }

  useEffect(() => {
    load();
    if (!orgSlug) return undefined;
    const t = setInterval(load, 60_000);
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [orgSlug]);

  return { count, eligible, refresh: load };
}

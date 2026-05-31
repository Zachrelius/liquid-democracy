import { useEffect, useState } from 'react';

import api from '../api';

/**
 * Phase 44 F2b — fetch the org's pending-actions count for nav-badge
 * + in-context banner discovery.
 *
 * Returns { count, byActionType, eligible, loading, refresh }. Polls
 * every 60 seconds while the hook is mounted (cheap endpoint; matches
 * the cadence of the existing notification-count poll).
 */
export default function usePendingActionsCount(orgSlug) {
  const [count, setCount] = useState(0);
  const [byActionType, setByActionType] = useState({});
  const [eligible, setEligible] = useState(false);
  const [loading, setLoading] = useState(true);

  async function load() {
    if (!orgSlug) {
      setCount(0); setByActionType({}); setEligible(false);
      setLoading(false);
      return;
    }
    try {
      const data = await api.get(`/api/orgs/${orgSlug}/admin/pending-actions/count`);
      setCount(data.pending_count || 0);
      setByActionType(data.pending_count_by_action_type || {});
      setEligible(!!data.eligible);
    } catch {
      // Quietly fail — the badge just doesn't show.
      setCount(0); setByActionType({}); setEligible(false);
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

  return { count, byActionType, eligible, loading, refresh: load };
}

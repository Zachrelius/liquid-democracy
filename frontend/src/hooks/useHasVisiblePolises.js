import { useEffect, useState } from 'react';

import api from '../api';

/**
 * Phase 82 C2 — drives the member "Deliberations" nav link visibility. Polls
 * the cheap has-visible endpoint (mirrors useUnreadMessageCount's shape /
 * cadence). The link renders only when the org has ≥1 Polis this member is
 * eligible to see — no org setting, no dead button. Quietly fails to false.
 */
export default function useHasVisiblePolises(orgSlug) {
  const [hasVisible, setHasVisible] = useState(false);

  useEffect(() => {
    let alive = true;
    async function load() {
      if (!orgSlug) { if (alive) setHasVisible(false); return; }
      try {
        const data = await api.get(`/api/orgs/${orgSlug}/polises/has-visible`);
        if (alive) setHasVisible(!!data?.has_visible);
      } catch {
        if (alive) setHasVisible(false);
      }
    }
    load();
    if (!orgSlug) return undefined;
    const t = setInterval(load, 60_000);
    return () => { alive = false; clearInterval(t); };
  }, [orgSlug]);

  return hasVisible;
}

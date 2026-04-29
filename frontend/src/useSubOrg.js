import { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import { useOrg } from './OrgContext';
import api from './api';

/**
 * Phase 8.5 — shared hook for sub-org admin pages.
 *
 * Returns `{ parentSlug, subSlug, subOrg, loading, error, reload }`.
 *
 * Decision-6 implicit admin power is enforced server-side; this hook just
 * resolves which parent the URL's sub_slug belongs under and fetches the
 * sub-org detail. Pages should surface 403/404 from inline action calls.
 *
 * Source for `parentSlug`: walk from `currentOrg`. If it's already a sub-org,
 * walk up to its parent; otherwise it IS the parent.
 */
export default function useSubOrg() {
  const { sub_slug } = useParams();
  const { currentOrg, userOrgs } = useOrg();
  const [subOrg, setSubOrg] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [tick, setTick] = useState(0);

  let parentSlug = null;
  if (currentOrg) {
    if (currentOrg.parent_org_id) {
      const parent = userOrgs.find(o => o.id === currentOrg.parent_org_id);
      parentSlug = parent?.slug || null;
    } else {
      parentSlug = currentOrg.slug;
    }
  }

  useEffect(() => {
    if (!parentSlug || !sub_slug) {
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    (async () => {
      try {
        const data = await api.get(`/api/orgs/${parentSlug}/sub-orgs/${sub_slug}`);
        if (!cancelled) {
          setSubOrg(data);
          setError(null);
        }
      } catch (e) {
        if (!cancelled) {
          setSubOrg(null);
          setError(e);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [parentSlug, sub_slug, tick]);

  return {
    parentSlug,
    subSlug: sub_slug,
    subOrg,
    loading,
    error,
    reload: () => setTick(t => t + 1),
  };
}

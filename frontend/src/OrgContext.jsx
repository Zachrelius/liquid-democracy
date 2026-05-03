import { createContext, useContext, useState, useEffect, useCallback, useRef, useMemo } from 'react';
import { useParams } from 'react-router-dom';
import { useAuth } from './AuthContext';
import api from './api';

const OrgContext = createContext(null);

/**
 * Phase 11 — URL-driven OrgContext.
 *
 * `currentOrg` is now derived from `useParams().org_slug` (and, when present,
 * `useParams().sub_slug`) by lookup against `userOrgs` / cached sub-orgs of
 * the parent. Non-org-scoped routes (`/`, `/login`, `/orgs`, `/settings`,
 * etc.) leave `currentOrg` as `null`.
 *
 * localStorage is demoted to a "last-used org slug for next sign-in" hint:
 * we write `currentOrgSlug` whenever the URL-derived currentOrg changes, but
 * we no longer read it during normal navigation — only OrgSelector consults
 * it to decide whether to auto-redirect a single-org user.
 *
 * The `setCurrentOrg` setter is preserved for the rare call sites that need
 * a "pick + remember" operation (e.g., OrgSelector's selectOrg, CreateOrg's
 * post-create flow). It writes localStorage but does NOT navigate; callers
 * are expected to navigate themselves.
 */
export function OrgProvider({ children }) {
  const { user } = useAuth();
  const params = useParams();
  const urlOrgSlug = params.org_slug || null;
  const urlSubSlug = params.sub_slug || null;

  const [userOrgs, setUserOrgs] = useState([]);
  const [loading, setLoading] = useState(true);

  // Phase 8.5: cache of sub-orgs visible to the current user, keyed by parent
  // org slug. Populated lazily — see fetchSubOrgsFor.
  const [subOrgsByParent, setSubOrgsByParent] = useState({});

  const refreshOrgs = useCallback(async () => {
    if (!user) {
      setUserOrgs([]);
      setLoading(false);
      return;
    }
    try {
      const orgs = await api.get('/api/orgs');
      setUserOrgs(orgs);
    } catch {
      setUserOrgs([]);
    } finally {
      setLoading(false);
    }
  }, [user]);

  useEffect(() => {
    refreshOrgs();
  }, [refreshOrgs]);

  // Phase 8.5 — fetch the list of sub-orgs visible to the current user
  // under a given parent slug. Caches the result by parent slug. Backend
  // privacy filter (Decision 7) handles which sub-orgs are returned.
  const subOrgsCacheRef = useRef({});
  useEffect(() => { subOrgsCacheRef.current = subOrgsByParent; }, [subOrgsByParent]);

  const fetchSubOrgsFor = useCallback(async (parentSlug, force = false) => {
    if (!parentSlug) return [];
    const cached = subOrgsCacheRef.current[parentSlug];
    if (!force && cached) return cached;
    try {
      const list = await api.get(`/api/orgs/${parentSlug}/sub-orgs`);
      setSubOrgsByParent(prev => ({ ...prev, [parentSlug]: list }));
      return list;
    } catch {
      setSubOrgsByParent(prev => ({ ...prev, [parentSlug]: [] }));
      return [];
    }
  }, []);

  // Convenience: drop cached sub-org list for a parent (call after CRUD).
  const invalidateSubOrgs = useCallback((parentSlug) => {
    setSubOrgsByParent(prev => {
      const next = { ...prev };
      delete next[parentSlug];
      return next;
    });
  }, []);

  // Phase 11 — auto-fetch sub-orgs when on a sub-org route so currentOrg
  // resolves to the sub-org rather than falling back to the parent.
  useEffect(() => {
    if (!urlOrgSlug || !urlSubSlug) return;
    // Only fire if we don't already have the cache for this parent.
    if (subOrgsCacheRef.current[urlOrgSlug]) return;
    fetchSubOrgsFor(urlOrgSlug);
  }, [urlOrgSlug, urlSubSlug, fetchSubOrgsFor]);

  // URL-derived currentOrg.
  // - When the URL has org_slug + sub_slug, prefer the matching sub-org
  //   (falling back to the parent until the sub-org cache loads).
  // - When the URL has just org_slug, use the parent.
  // - Otherwise null.
  // Membership check: the parent must be in userOrgs (a slug we're a member
  // of). Non-member slug → currentOrg stays null and `accessDenied` is true,
  // letting the wrapper render the inline "no access" surface.
  const { currentOrg, accessDenied } = useMemo(() => {
    if (!urlOrgSlug) return { currentOrg: null, accessDenied: false };
    // While userOrgs is still loading, suppress the access-denied flag so
    // we don't flash the error on first paint.
    if (loading) return { currentOrg: null, accessDenied: false };
    const parent = userOrgs.find(o => o.slug === urlOrgSlug);
    if (!parent) {
      return { currentOrg: null, accessDenied: true };
    }
    if (urlSubSlug) {
      const subs = subOrgsByParent[urlOrgSlug] || [];
      const sub = subs.find(s => s.slug === urlSubSlug);
      if (sub) {
        return { currentOrg: sub, accessDenied: false };
      }
      // Sub cache hasn't loaded yet — fall back to parent so child pages
      // see *something* useful while useSubOrg / fetchSubOrgsFor finishes.
      return { currentOrg: parent, accessDenied: false };
    }
    return { currentOrg: parent, accessDenied: false };
  }, [urlOrgSlug, urlSubSlug, userOrgs, subOrgsByParent, loading]);

  // Persist last-used org slug whenever URL-derived currentOrg changes —
  // only used by OrgSelector to decide whether to auto-redirect a single-
  // org user on next sign-in.
  useEffect(() => {
    if (currentOrg?.slug && !currentOrg.parent_org_id) {
      // Track the parent slug as "last used" — sub-org slugs aren't useful
      // as a sign-in-resume hint because they require parent context.
      try {
        localStorage.setItem('currentOrgSlug', currentOrg.slug);
      } catch { /* best-effort */ }
    }
  }, [currentOrg]);

  // setCurrentOrg — kept for OrgSelector / CreateOrg's "pick" surfaces.
  // Writes localStorage as a sign-in hint; does NOT navigate (callers do).
  const setCurrentOrg = useCallback((org) => {
    if (org?.slug && !org.parent_org_id) {
      try { localStorage.setItem('currentOrgSlug', org.slug); } catch { /* ignore */ }
    } else if (!org) {
      try { localStorage.removeItem('currentOrgSlug'); } catch { /* ignore */ }
    }
  }, []);

  const isAdmin = !!(currentOrg && (currentOrg.user_role === 'admin' || currentOrg.user_role === 'owner'));
  const isOwner = !!(currentOrg && currentOrg.user_role === 'owner');
  const isModerator = !!(currentOrg && currentOrg.user_role === 'moderator');
  const isModeratorOrAdmin = isAdmin || isModerator;

  return (
    <OrgContext.Provider value={{
      currentOrg,
      setCurrentOrg,
      userOrgs,
      isAdmin,
      isOwner,
      isModerator,
      isModeratorOrAdmin,
      loading,
      refreshOrgs,
      // Phase 8.5
      subOrgsByParent,
      fetchSubOrgsFor,
      invalidateSubOrgs,
      // Phase 11 — true when URL has org_slug but user isn't a member.
      accessDenied,
    }}>
      {children}
    </OrgContext.Provider>
  );
}

export function useOrg() {
  const ctx = useContext(OrgContext);
  if (!ctx) throw new Error('useOrg must be used within OrgProvider');
  return ctx;
}

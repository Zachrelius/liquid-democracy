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

  // Phase 80 — public read-only fallback. When the URL points at an org the
  // viewer is NOT a member of (incl. logged-out visitors), we fetch the
  // org's public info; if it's `activity_visibility='public'` we render the
  // org-scoped pages in read-only mode rather than the access-denied pane.
  const [publicOrg, setPublicOrg] = useState(null);
  // The slug whose public-info check has COMPLETED (success or fail). While
  // this !== urlOrgSlug for a non-member, the org is still "resolving" and we
  // must show a loading state rather than flashing access-denied or falling
  // through to a member render with a null org.
  const [publicOrgCheckedSlug, setPublicOrgCheckedSlug] = useState(null);

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

  // Phase 80 — whether the URL org is one the viewer is an active member of.
  const isMemberOfUrlOrg = useMemo(() => {
    if (!urlOrgSlug || loading) return false;
    return userOrgs.some(o => o.slug === urlOrgSlug);
  }, [urlOrgSlug, userOrgs, loading]);

  // Phase 80 — fetch the public org info when the viewer is NOT a member of
  // the URL org. Gated on `!isMemberOfUrlOrg` so members never pay this
  // round-trip. Skipped for sub-org URLs (public surface is parent-only).
  useEffect(() => {
    let alive = true;
    if (!urlOrgSlug || loading || isMemberOfUrlOrg || urlSubSlug) {
      setPublicOrg(null);
      setPublicOrgCheckedSlug(null);
      return;
    }
    // Mark this slug as not-yet-resolved so the memo/layout show a loading
    // state until the fetch settles (avoids an access-denied flash + a stray
    // member-endpoint fetch with a null org).
    setPublicOrgCheckedSlug(null);
    api.get(`/api/orgs/${urlOrgSlug}/public`)
      .then(data => {
        if (alive) setPublicOrg(data && data.slug === urlOrgSlug ? data : null);
      })
      .catch(() => { if (alive) setPublicOrg(null); })
      .finally(() => { if (alive) setPublicOrgCheckedSlug(urlOrgSlug); });
    return () => { alive = false; };
  }, [urlOrgSlug, urlSubSlug, loading, isMemberOfUrlOrg]);

  // True while we still don't know whether a non-member URL org is a public
  // read-only org. OrgScopedLayout shows a loading state during this window.
  const resolvingPublicOrg = !!urlOrgSlug && !urlSubSlug && !loading
    && !isMemberOfUrlOrg && publicOrgCheckedSlug !== urlOrgSlug;

  // URL-derived currentOrg.
  // - When the URL has org_slug + sub_slug, prefer the matching sub-org
  //   (falling back to the parent until the sub-org cache loads).
  // - When the URL has just org_slug, use the parent.
  // - Otherwise null.
  // Membership check: the parent must be in userOrgs (a slug we're a member
  // of). Non-member slug → Phase 80 public read-only fallback (when the org
  // is activity_visibility='public') or else `accessDenied`.
  const { currentOrg, accessDenied, isMember, isPublicReadOnly } = useMemo(() => {
    const none = { currentOrg: null, accessDenied: false, isMember: false, isPublicReadOnly: false };
    if (!urlOrgSlug) return none;
    // While userOrgs is still loading, suppress the access-denied flag so
    // we don't flash the error on first paint.
    if (loading) return none;
    const parent = userOrgs.find(o => o.slug === urlOrgSlug);
    if (!parent) {
      // Non-member. Phase 80 — public read-only fallback (parent-org only).
      if (urlSubSlug) return { ...none, accessDenied: true };
      if (publicOrgCheckedSlug !== urlOrgSlug) return none; // resolving; don't flash denied
      if (
        publicOrg
        && publicOrg.slug === urlOrgSlug
        && publicOrg.activity_visibility === 'public'
      ) {
        return {
          currentOrg: publicOrg,
          accessDenied: false,
          isMember: false,
          isPublicReadOnly: true,
        };
      }
      return { ...none, accessDenied: true };
    }
    if (urlSubSlug) {
      const subs = subOrgsByParent[urlOrgSlug] || [];
      const sub = subs.find(s => s.slug === urlSubSlug);
      if (sub) {
        return { currentOrg: sub, accessDenied: false, isMember: true, isPublicReadOnly: false };
      }
      // Sub cache hasn't loaded yet — fall back to parent so child pages
      // see *something* useful while useSubOrg / fetchSubOrgsFor finishes.
      return { currentOrg: parent, accessDenied: false, isMember: true, isPublicReadOnly: false };
    }
    return { currentOrg: parent, accessDenied: false, isMember: true, isPublicReadOnly: false };
  }, [urlOrgSlug, urlSubSlug, userOrgs, subOrgsByParent, loading, publicOrg, publicOrgCheckedSlug]);

  // Persist last-used org slug whenever URL-derived currentOrg changes —
  // used by OrgSelector to decide whether to auto-redirect a single-org
  // user on next sign-in, AND (Phase 16 F5) by Nav.jsx to resolve org-
  // context-dependent links on non-org-scoped routes like /settings.
  // Both keys carry the same value:
  //   - `currentOrgSlug` is the legacy name (Phase 11) read by OrgSelector.
  //   - `lastOrgSlug` is the Phase 16 F5 contract; Nav.jsx reads this to
  //     synthesize a stand-in currentOrg for nav rendering when the URL
  //     is non-org-scoped. Single key would have worked too; dual-write
  //     keeps the older read path stable and honors the spec naming.
  useEffect(() => {
    // Phase 80 — only persist the "last used org" hint for actual members;
    // a non-member's read-only browse shouldn't become their resume target.
    if (isMember && currentOrg?.slug && !currentOrg.parent_org_id) {
      // Track the parent slug as "last used" — sub-org slugs aren't useful
      // as a sign-in-resume hint because they require parent context.
      try {
        localStorage.setItem('currentOrgSlug', currentOrg.slug);
        localStorage.setItem('lastOrgSlug', currentOrg.slug);
      } catch { /* best-effort */ }
    }
  }, [currentOrg, isMember]);

  // setCurrentOrg — kept for OrgSelector / CreateOrg's "pick" surfaces.
  // Writes localStorage as a sign-in hint; does NOT navigate (callers do).
  // Phase 16 F5 — also writes `lastOrgSlug` so Nav.jsx can resolve org-
  // context-dependent links on non-org-scoped routes.
  const setCurrentOrg = useCallback((org) => {
    if (org?.slug && !org.parent_org_id) {
      try {
        localStorage.setItem('currentOrgSlug', org.slug);
        localStorage.setItem('lastOrgSlug', org.slug);
      } catch { /* ignore */ }
    } else if (!org) {
      try {
        localStorage.removeItem('currentOrgSlug');
        localStorage.removeItem('lastOrgSlug');
      } catch { /* ignore */ }
    }
  }, []);

  // Phase 12 Stage 1: 'owner' system_key renamed to 'steward'. The legacy
  // 'owner' check is preserved to safely handle any cached stale API
  // responses during the deploy cutover; new responses always send 'steward'.
  const isAdmin = !!(currentOrg && (currentOrg.user_role === 'admin' || currentOrg.user_role === 'steward' || currentOrg.user_role === 'owner'));
  const isOwner = !!(currentOrg && (currentOrg.user_role === 'steward' || currentOrg.user_role === 'owner'));
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
      // Phase 80 — membership + read-only flags for the public surface.
      isMember,
      isPublicReadOnly,
      resolvingPublicOrg,
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

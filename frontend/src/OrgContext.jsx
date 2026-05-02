import { createContext, useContext, useState, useEffect, useCallback, useRef } from 'react';
import { useAuth } from './AuthContext';
import api from './api';

const OrgContext = createContext(null);

export function OrgProvider({ children }) {
  const { user } = useAuth();
  const [userOrgs, setUserOrgs] = useState([]);
  const [currentOrg, setCurrentOrgState] = useState(null);
  const [loading, setLoading] = useState(true);

  // Phase 8.5: cache of sub-orgs visible to the current user, keyed by parent
  // org slug. Populated lazily — see fetchSubOrgsFor.
  const [subOrgsByParent, setSubOrgsByParent] = useState({});

  const setCurrentOrg = useCallback((org) => {
    setCurrentOrgState(org);
    if (org) {
      localStorage.setItem('currentOrgSlug', org.slug);
    } else {
      localStorage.removeItem('currentOrgSlug');
    }
  }, []);

  const refreshOrgs = useCallback(async () => {
    if (!user) {
      setUserOrgs([]);
      setCurrentOrgState(null);
      setLoading(false);
      return;
    }
    try {
      const orgs = await api.get('/api/orgs');
      setUserOrgs(orgs);

      const savedSlug = localStorage.getItem('currentOrgSlug');
      const savedOrg = savedSlug ? orgs.find(o => o.slug === savedSlug) : null;

      if (savedOrg) {
        setCurrentOrgState(savedOrg);
      } else if (orgs.length === 1) {
        setCurrentOrg(orgs[0]);
      } else if (orgs.length > 1) {
        // Multiple orgs, none saved — user must pick
        setCurrentOrgState(null);
      } else {
        // No orgs
        setCurrentOrgState(null);
      }
    } catch {
      setUserOrgs([]);
      setCurrentOrgState(null);
    } finally {
      setLoading(false);
    }
  }, [user, setCurrentOrg]);

  useEffect(() => {
    refreshOrgs();
  }, [refreshOrgs]);

  // Phase 8.5 — fetch the list of sub-orgs visible to the current user
  // under a given parent slug. Caches the result by parent slug. Backend
  // privacy filter (Decision 7) handles which sub-orgs are returned.
  //
  // Phase 9.6 — `subOrgsByParent` was previously in the dep array, which
  // produced a new function identity on every cache write. Consumers that
  // listed `fetchSubOrgsFor` in their effect deps (e.g. SubOrgList) ended
  // up in an infinite render loop: fetch → setState → new identity →
  // re-run effect → fetch again. Switched to a ref for the cache-read
  // shortcut so the callback identity is stable across renders.
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

import { createContext, useContext, useState, useEffect, useCallback } from 'react';
import { useAuth } from './AuthContext';
import api from './api';

const OrgContext = createContext(null);

export function OrgProvider({ children }) {
  const { user } = useAuth();
  const [userOrgs, setUserOrgs] = useState([]);
  const [currentOrg, setCurrentOrgState] = useState(null);
  const [loading, setLoading] = useState(true);

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

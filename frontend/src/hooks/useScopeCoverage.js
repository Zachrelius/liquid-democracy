import { useEffect, useMemo, useState } from 'react';
import api from '../api';

/**
 * Phase 8.5 — Decision 10 scope-coverage helper.
 *
 * Builds, for the current viewer:
 *   - parentName: the viewer's parent org name (e.g. "Demo Org")
 *   - viewerSubOrgIds: Set of sub-org ids the viewer is a member of
 *   - subOrgsById: map id → { id, name, slug }
 *   - membershipByUser: map user_id → Set<sub_org_id> (active members only)
 *   - coverageFor(candidateUserId): array of strings:
 *       [parentName] + [sub-org names the candidate also covers, intersected
 *       with the viewer's scopes].
 *     If the candidate is missing one or more of the viewer's sub-org scopes,
 *     callers can detect that via missingScopesFor() to render the "only"
 *     qualifier and the cross-scope disclosure copy.
 *   - missingScopesFor(candidateUserId): array of sub-org names from
 *     viewerSubOrgs that the candidate is NOT a member of.
 *
 * Composition path (b) per spec: the user-detail endpoint does not include
 * sub-org memberships, so we fetch the parent org's sub-org list and each
 * sub-org's member roster once when the modal mounts. Privacy: we only
 * iterate sub-orgs the viewer can see (i.e. is a member of); we never
 * disclose membership in sub-orgs the viewer does not belong to.
 */
export default function useScopeCoverage(parentSlug, viewerUserId) {
  const [subOrgs, setSubOrgs] = useState([]);
  const [membershipByUser, setMembershipByUser] = useState({});
  const [parentName, setParentName] = useState(null);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    if (!parentSlug || !viewerUserId) {
      setLoaded(true);
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        // Fetch parent org details (for name) + sub-orgs visible to the viewer.
        const [parentOrg, subOrgList] = await Promise.all([
          api.get(`/api/orgs/${parentSlug}`).catch(() => null),
          api.get(`/api/orgs/${parentSlug}/sub-orgs`).catch(() => []),
        ]);
        if (cancelled) return;
        setParentName(parentOrg?.name || null);

        // Determine which sub-orgs the viewer is a member of. We can only
        // safely fetch member rosters from sub-orgs the viewer is a member
        // of (or admin of); the backend's GET /sub-orgs/{slug}/members route
        // returns 403 for non-members. We probe each one and silently drop
        // the ones that 403.
        const memberLists = await Promise.all(
          (subOrgList || []).map((s) =>
            api
              .get(`/api/orgs/${parentSlug}/sub-orgs/${s.slug}/members`)
              .then((members) => ({ subOrg: s, members }))
              .catch(() => null)
          )
        );
        if (cancelled) return;

        const accessibleSubOrgs = [];
        const membership = {}; // user_id -> Set<sub_org_id>
        for (const entry of memberLists) {
          if (!entry) continue;
          const { subOrg, members } = entry;
          // Only include sub-orgs where the viewer themselves shows up as an
          // active member. Decision 10 privacy rule: don't reveal a candidate's
          // membership in a sub-org the viewer isn't in.
          const viewerMember = members.find(
            (m) => m.user_id === viewerUserId && m.status === 'active'
          );
          if (!viewerMember) continue;
          accessibleSubOrgs.push(subOrg);
          for (const m of members) {
            if (m.status !== 'active') continue;
            if (!membership[m.user_id]) membership[m.user_id] = new Set();
            membership[m.user_id].add(subOrg.id);
          }
        }
        setSubOrgs(accessibleSubOrgs);
        setMembershipByUser(membership);
      } finally {
        if (!cancelled) setLoaded(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [parentSlug, viewerUserId]);

  const subOrgsById = useMemo(() => {
    const m = {};
    for (const s of subOrgs) m[s.id] = s;
    return m;
  }, [subOrgs]);

  const viewerSubOrgIds = useMemo(() => {
    const s = membershipByUser[viewerUserId];
    return s ? new Set(s) : new Set();
  }, [membershipByUser, viewerUserId]);

  // Given a candidate user id, return the human-readable coverage list and
  // the missing-scopes list relative to the viewer.
  const coverageFor = (candidateUserId) => {
    if (!parentName) return { coverage: [], missing: [], hasFullCoverage: true };
    const candidateSubOrgs = membershipByUser[candidateUserId] || new Set();
    // Coverage is the parent org plus each viewer-accessible sub-org the
    // candidate is a member of.
    const coverage = [parentName];
    const missing = [];
    for (const id of viewerSubOrgIds) {
      const so = subOrgsById[id];
      if (!so) continue;
      if (candidateSubOrgs.has(id)) {
        coverage.push(so.name);
      } else {
        missing.push(so.name);
      }
    }
    return { coverage, missing, hasFullCoverage: missing.length === 0 };
  };

  return {
    loaded,
    parentName,
    subOrgs,
    viewerSubOrgIds,
    membershipByUser,
    coverageFor,
  };
}

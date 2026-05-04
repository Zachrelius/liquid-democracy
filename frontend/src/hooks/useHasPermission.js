// Phase 12.5 F1 — permission-driven UI gating helpers.
//
// Reads the resolved permission keys for the current user on the active org
// from `currentOrg.user_permissions` (backend B4 enrichment of the
// `/api/orgs/{slug}` response). When `currentOrg` is null (user is on a
// non-org-scoped route) or the field is absent (cached pre-12.5 response),
// every check returns false — calling code should treat that as "no
// permission, hide the surface."
//
// Two flavors:
//   useHasPermission(key)         — true iff the user has that key.
//   useHasAnyPermission([k1, k2]) — true iff the user has at least one.
//
// Both are intentionally tiny so call sites can use them inline:
//   {useHasPermission('proposal.delete') && <DeleteButton />}
//   {useHasAnyPermission(ADMIN_NAV_SUBSECTION_PERMISSIONS.members) && ...}

import { useOrg } from '../OrgContext';

export function useHasPermission(permissionKey) {
  const { currentOrg } = useOrg();
  return (
    Array.isArray(currentOrg?.user_permissions) &&
    currentOrg.user_permissions.includes(permissionKey)
  );
}

export function useHasAnyPermission(permissionKeys) {
  const { currentOrg } = useOrg();
  if (!Array.isArray(currentOrg?.user_permissions)) return false;
  if (!Array.isArray(permissionKeys) || permissionKeys.length === 0) return false;
  return permissionKeys.some((k) => currentOrg.user_permissions.includes(k));
}

import { Navigate } from 'react-router-dom';
import { useOrg } from './OrgContext';
import { urlFor } from './utils/urls';

/**
 * Phase 12.6 G4 — AdminOnlyRoute is now permission-gated, not role-tier-gated.
 *
 * Same shape as AdminRoute; same any-semantics on the `permissions` prop.
 * Pre-12.6 this guard required `isAdmin` (admin or steward only, no
 * moderator). Post-12.6 the gate is whatever permission set the caller
 * passes — typically a more restrictive subset than AdminRoute (e.g.,
 * `org.edit_settings` for the Settings page; `delegate_application.approve`
 * for the Delegates page).
 *
 * The two guards (AdminRoute / AdminOnlyRoute) are functionally
 * indistinguishable now — both gate on a passed-in permission list. The
 * original split was a role-tier convenience that's no longer load-
 * bearing. They're kept as separate components for now to keep call-site
 * intent explicit ("this used to require the admin tier" vs. "this used
 * to require moderator-or-admin"), and to keep the diff for 12.6 surgical.
 * A future cleanup pass could merge them into one PermissionRoute.
 */
export default function AdminOnlyRoute({ children, permissions = [] }) {
  const { loading, currentOrg, accessDenied } = useOrg();

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="text-gray-500">Loading...</div>
      </div>
    );
  }

  // Phase 11 — accessDenied is handled by OrgScopedLayout's inline message.
  if (accessDenied) {
    return children;
  }

  if (!currentOrg) {
    return <Navigate to="/orgs" replace />;
  }

  const userPerms = Array.isArray(currentOrg.user_permissions)
    ? currentOrg.user_permissions
    : null;

  // Cache-safety fallback (mirrors AdminRoute / 12.5 F1 Nav.jsx pattern).
  if (userPerms === null) {
    const role = currentOrg.user_role;
    const isAdminOrSteward = role === 'admin' || role === 'steward' || role === 'owner';
    if (!isAdminOrSteward) {
      return <Navigate to={urlFor(currentOrg, 'proposals')} replace />;
    }
    return children;
  }

  const hasAny = permissions.some((p) => userPerms.includes(p));
  if (!hasAny) {
    return <Navigate to={urlFor(currentOrg, 'proposals')} replace />;
  }

  return children;
}

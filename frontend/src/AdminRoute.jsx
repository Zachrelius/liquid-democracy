import { Navigate } from 'react-router-dom';
import { useOrg } from './OrgContext';
import { urlFor } from './utils/urls';

/**
 * Phase 12.6 G2 — AdminRoute is now permission-gated, not role-tier-gated.
 *
 * Pass a `permissions` prop with the list of permission keys that grant
 * access to the route. Any-semantics: user must have AT LEAST ONE of the
 * listed permissions (resolved from `currentOrg.user_permissions`, which
 * 12.5 B4 added to the `/api/orgs/{slug}` response). This matches the
 * 12.5 F1 nav visibility model so the route guard and the nav read from
 * the same source of truth (`ADMIN_NAV_SUBSECTION_PERMISSIONS`).
 *
 * On access denial, redirects to `/{slug}/proposals` for consistency with
 * the prior role-tier behavior.
 *
 * Pre-12.6 the gate was `isModeratorOrAdmin` (role tier). The bug Z's wife
 * hit: a Member granted `proposal.create` via the matrix saw the admin →
 * Proposals nav link (correct, 12.5 F1) but clicking it bounced because
 * the route guard still checked role tier. This refactor closes that gap.
 */
export default function AdminRoute({ children, permissions = [] }) {
  const { loading, currentOrg, accessDenied } = useOrg();

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="text-gray-500">Loading...</div>
      </div>
    );
  }

  // Phase 11 — accessDenied is handled by OrgScopedLayout's inline message;
  // let the wrapper render so the user sees the explanation rather than a
  // silent /orgs redirect.
  if (accessDenied) {
    return children;
  }

  if (!currentOrg) {
    return <Navigate to="/orgs" replace />;
  }

  const userPerms = Array.isArray(currentOrg.user_permissions)
    ? currentOrg.user_permissions
    : null;

  // Cache-safety fallback (mirrors 12.5 F1 Nav.jsx pattern): if the API
  // response predates 12.5 B4 and lacks `user_permissions` entirely, fall
  // back to the legacy role-tier check so admins/moderators don't get
  // locked out during deploy cutover. Once cached responses age out
  // (~1 week post-deploy), this branch becomes dead code and can be
  // removed.
  if (userPerms === null) {
    const role = currentOrg.user_role;
    const isAdminOrSteward = role === 'admin' || role === 'steward' || role === 'owner';
    const isModerator = role === 'moderator';
    if (!(isAdminOrSteward || isModerator)) {
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

import { Link } from 'react-router-dom';

import { urlFor } from '../utils/urls';
import usePendingActionsCount from '../hooks/usePendingActionsCount';

/**
 * Phase 44 F2b — in-context discovery banner.
 *
 * Surfaces on the Members / Topics / RolePermissions / OrgSettings
 * admin pages reading "N change(s) awaiting your approval" with a
 * link to the pending-actions queue. Visible only when the viewer is
 * eligible AND there is at least one pending action of the matching
 * type.
 *
 * Props:
 *   - orgSlug: the org slug to query (typically the parent slug for
 *     sub-org pages so the queue is org-wide).
 *   - actionType: filter the count by this action_type. If omitted,
 *     the banner shows the org-wide pending count.
 */
export default function PendingActionsBanner({ orgSlug, actionType }) {
  const { count, byActionType, eligible } = usePendingActionsCount(orgSlug);
  if (!orgSlug || !eligible) return null;

  const n = actionType ? (byActionType[actionType] || 0) : count;
  if (n <= 0) return null;

  const label = actionType
    ? labelFor(actionType, n)
    : `${n} action${n === 1 ? '' : 's'} awaiting your approval`;

  return (
    <div className="mb-4 bg-blue-50 border border-blue-200 rounded-lg p-3 flex items-center justify-between gap-3">
      <p className="text-sm text-blue-900">{label}</p>
      <Link
        to={urlFor(orgSlug, 'admin-pending-actions')}
        className="text-sm font-medium text-[var(--brand-accent)] hover:underline shrink-0"
      >
        Review →
      </Link>
    </div>
  );
}

function labelFor(actionType, n) {
  const noun = {
    'member.remove': n === 1 ? 'member removal' : 'member removals',
    'topic.delete': n === 1 ? 'topic deletion' : 'topic deletions',
    'role_permissions.edit': n === 1 ? 'permission change' : 'permission changes',
    'org.delete': n === 1 ? 'org-deletion request' : 'org-deletion requests',
  }[actionType] || (n === 1 ? 'pending action' : 'pending actions');
  return `${n} ${noun} awaiting your approval`;
}

import { Link } from 'react-router-dom';
import { useOrg } from '../OrgContext';
import { urlFor } from '../utils/urls';

/**
 * Renders a user's display name as a clickable link to their profile.
 * Accepts either a `user` object ({ id, display_name }) or individual props.
 *
 * Phase 11 — user-profile routes are org-scoped (`/:org_slug/users/:id`),
 * so this component reads currentOrg from context and resolves the parent
 * slug for link construction. When no org context is available (rare —
 * UserLink should only render inside org-scoped pages), fall back to a
 * non-link span.
 */
export default function UserLink({ user, userId, displayName, className = '' }) {
  const { currentOrg, userOrgs } = useOrg();
  const id = user?.id ?? userId;
  const name = user?.display_name ?? displayName;
  if (!id || !name) return <span className={className}>{name || 'Unknown'}</span>;

  // Resolve parent slug (sub-org → walk up to parent).
  let parentSlug = null;
  if (currentOrg) {
    if (currentOrg.parent_org_id) {
      parentSlug = userOrgs.find(o => o.id === currentOrg.parent_org_id)?.slug || null;
    } else {
      parentSlug = currentOrg.slug;
    }
  }

  if (!parentSlug) {
    return <span className={className}>{name}</span>;
  }
  return (
    <Link
      to={urlFor(parentSlug, 'user-profile', id)}
      className={`text-[#2E75B6] hover:underline font-medium ${className}`}
    >
      {name}
    </Link>
  );
}

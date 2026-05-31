// Phase 11 — URL helper for path-based org URLs.
//
// Centralizes the route shape so future URL-shape changes are a one-file edit.
// Pattern: urlFor(org, kind, ...args) returns a string path.
//
// `org` is the org object (must have .slug) or a slug string. For sub-org
// kinds, pass the parent org for the slug; the sub-slug is the next arg.
// For non-org-scoped routes, pass null (or omit) — those use static paths.
//
// Usage examples:
//   urlFor(currentOrg, 'proposals')                     -> '/{slug}/proposals'
//   urlFor(currentOrg, 'proposal-detail', 42)           -> '/{slug}/proposals/42'
//   urlFor(currentOrg, 'admin-members')                 -> '/{slug}/admin/members'
//   urlFor(parentOrg, 'admin-sub-org-members', 'team')  -> '/{parent}/admin/sub-orgs/team/members'
//   urlFor(currentOrg, 'polis-voter', 7)                -> '/{slug}/polises/7'

function slugOf(orgOrSlug) {
  if (!orgOrSlug) return null;
  if (typeof orgOrSlug === 'string') return orgOrSlug;
  return orgOrSlug.slug || null;
}

export function urlFor(org, kind, ...args) {
  const slug = slugOf(org);

  // Org-scoped app routes
  switch (kind) {
    case 'proposals':
      return `/${slug}/proposals`;
    case 'proposal-detail': {
      const [id] = args;
      return `/${slug}/proposals/${id}`;
    }
    case 'delegations':
      return `/${slug}/delegations`;
    case 'user-profile': {
      const [userId] = args;
      return `/${slug}/users/${userId}`;
    }
    case 'polis-voter': {
      const [polisId] = args;
      return `/${slug}/polises/${polisId}`;
    }
    // Phase 19 — public delegate page surfaces.
    case 'delegate-profile':
      return `/${slug}/delegate-profile`;
    case 'delegates':
      return `/${slug}/delegates`;
    case 'delegate-public': {
      const [handleOrUsername] = args;
      return `/${slug}/delegates/${handleOrUsername}`;
    }
    case 'delegate-applications-review':
      return `/${slug}/delegate-applications`;

    // Org-scoped admin routes
    case 'admin-settings':
      return `/${slug}/admin/settings`;
    // Phase 12 Stage 2 — role-permissions matrix page (Cluster F1).
    case 'admin-permissions':
      return `/${slug}/admin/settings/permissions`;
    case 'admin-members':
      return `/${slug}/admin/members`;
    case 'admin-proposals':
      return `/${slug}/admin/proposals`;
    case 'admin-topics':
      return `/${slug}/admin/topics`;
    // Phase 30.1 B4 — 'admin-delegates' URL case removed. The legacy
    // admin Delegate Applications page was deleted; the canonical
    // surface lives at urlFor(slug, 'delegate-applications').
    case 'admin-analytics':
      return `/${slug}/admin/analytics`;
    case 'admin-polises':
      return `/${slug}/admin/polises`;
    // Phase 44 — multi-admin approval pending-actions queue.
    case 'admin-pending-actions':
      return `/${slug}/admin/pending-actions`;
    case 'admin-polises-create':
      return `/${slug}/admin/polises/create`;
    case 'admin-polis-detail': {
      const [polisId] = args;
      return `/${slug}/admin/polises/${polisId}`;
    }
    case 'admin-sub-orgs':
      return `/${slug}/admin/sub-orgs`;

    // Sub-org admin routes (slug = parent slug, args[0] = sub_slug)
    case 'admin-sub-org-root': {
      const [subSlug] = args;
      return `/${slug}/admin/sub-orgs/${subSlug}`;
    }
    case 'admin-sub-org-settings': {
      const [subSlug] = args;
      return `/${slug}/admin/sub-orgs/${subSlug}/settings`;
    }
    case 'admin-sub-org-members': {
      const [subSlug] = args;
      return `/${slug}/admin/sub-orgs/${subSlug}/members`;
    }
    case 'admin-sub-org-proposals': {
      const [subSlug] = args;
      return `/${slug}/admin/sub-orgs/${subSlug}/proposals`;
    }
    case 'admin-sub-org-topics': {
      const [subSlug] = args;
      return `/${slug}/admin/sub-orgs/${subSlug}/topics`;
    }
    case 'admin-sub-org-polises': {
      const [subSlug] = args;
      return `/${slug}/admin/sub-orgs/${subSlug}/polises`;
    }
    case 'admin-sub-org-polises-create': {
      const [subSlug] = args;
      return `/${slug}/admin/sub-orgs/${subSlug}/polises/create`;
    }
    case 'admin-sub-org-polis-detail': {
      const [subSlug, polisId] = args;
      return `/${slug}/admin/sub-orgs/${subSlug}/polises/${polisId}`;
    }

    // Phase 34.2 E1 — non-admin sub-org routes. URL shape:
    //   /{parent_slug}/sub-orgs/{sub_slug}/{resource}
    // Pre-34.2 the Nav top-bar emitted flat /{sub_slug}/{resource} which
    // hit the top-level resolver in OrgContext — `userOrgs.find(o => o.slug
    // === sub_slug)` finds the sub-org only if it has an OrgMembership row
    // (Phase 34 hotfix #1 added this for Cedar Court Condos; user-created
    // sub-orgs like Gloomhaven don't have one). The nested URL pattern
    // resolves the PARENT via userOrgs + the sub via fetchSubOrgsFor, so
    // it works for ALL sub-orgs regardless of OrgMembership shape.
    // `slug` here is the PARENT org's slug; `args[0]` is the sub-org slug.
    case 'sub-org-proposals': {
      const [subSlug] = args;
      return `/${slug}/sub-orgs/${subSlug}/proposals`;
    }
    case 'sub-org-proposal-detail': {
      const [subSlug, id] = args;
      return `/${slug}/sub-orgs/${subSlug}/proposals/${id}`;
    }
    case 'sub-org-delegations': {
      const [subSlug] = args;
      return `/${slug}/sub-orgs/${subSlug}/delegations`;
    }
    case 'sub-org-delegates': {
      const [subSlug] = args;
      return `/${slug}/sub-orgs/${subSlug}/delegates`;
    }
    case 'sub-org-delegate-public': {
      const [subSlug, handle] = args;
      return `/${slug}/sub-orgs/${subSlug}/delegates/${handle}`;
    }

    default:
      throw new Error(`urlFor: unknown route kind '${kind}'`);
  }
}

export default urlFor;

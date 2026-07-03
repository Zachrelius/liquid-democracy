// Phase 12.5 F1 — subsection → permissions mapping for admin nav visibility.
//
// A subsection is visible if the user has at least one of the listed
// permissions (resolved client-side via `useHasAnyPermission` reading from
// `currentOrg.user_permissions`, populated by the backend B4 enrichment of
// `/api/orgs/{slug}`).
//
// New permission keys added in future passes update this mapping. The
// mapping is intentionally a flat constant so it stays trivial to grep
// and edit; co-locating it with each subsection page would scatter the
// gating logic across the codebase.
export const ADMIN_NAV_SUBSECTION_PERMISSIONS = {
  proposals: [
    'proposal.create',
    'proposal.delete',
    'proposal.advance_phase',
    'proposal.resolve_tie',
    'proposal.set_thresholds',
  ],
  topics: ['topic.create', 'topic.edit', 'topic.delete'],
  members: [
    'member.approve_join',
    'member.remove',
    'member.suspend',
    'member.change_role',
    'member.invite',
  ],
  subOrgs: ['sub_org.create', 'sub_org.delete', 'sub_org.edit_settings'],
  delegates: ['delegate_application.approve'],
  polises: ['polis.create', 'polis.manage'],
  settings: ['org.edit_settings', 'org.edit_branding'],
  permissions: ['role_permissions.edit'],
  analytics: ['analytics.view'],
  audit: ['audit.view_org'],
  // Phase 44 — Pending actions queue is visible to anyone who could
  // initiate one of the four wrapped destructive actions. The list
  // endpoint also enforces eligibility server-side
  // (engine.can_view_pending_actions).
  pendingActions: [
    'member.remove',
    'topic.delete',
    'role_permissions.edit',
  ],
  // Phase 86 (B-4) — content-report queue is gated on comment.moderate (the
  // same key the backend queue endpoint enforces; no new permission key).
  reports: ['comment.moderate'],
};

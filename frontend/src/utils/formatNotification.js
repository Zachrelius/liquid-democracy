// Phase 13 F1/F2 — single source of truth for notification text rendering.
//
// The backend stores each notification as (event_type, payload, actor_id,
// org_id, target_type, target_id). This helper turns that shape into a short
// human sentence suitable for both the dropdown row in the notification
// center (F1) and the row on the full notifications page (F2). Keeping the
// formatter in one place prevents the dropdown and the full page from
// drifting out of sync as new event types are added.
//
// Payload keys this helper expects (best-effort; missing keys fall back to
// neutral phrasing):
//   actor_display_name, proposal_title, org_name, polis_title, decision,
//   status. The backend emission sites are responsible for populating these.

function actor(notif, fallback = 'Someone') {
  return notif?.payload?.actor_display_name || fallback;
}

function quoted(value) {
  if (!value) return '';
  return `"${value}"`;
}

/**
 * Build a short sentence describing the notification.
 * Returns a string. Never throws; unknown event types fall back to the raw
 * event key so we never render "undefined" to the user.
 */
export function formatNotification(notif) {
  if (!notif || !notif.event_type) return '';
  const p = notif.payload || {};
  switch (notif.event_type) {
    // ---- Comments -----------------------------------------------------
    case 'comment.replied':
      return `${actor(notif)} replied to your comment${p.proposal_title ? ` on ${quoted(p.proposal_title)}` : ''}`;
    case 'comment.posted_on_your_proposal':
      return `${actor(notif)} commented on ${quoted(p.proposal_title) || 'your proposal'}`;
    // ---- Proposals ----------------------------------------------------
    case 'proposal.entered_voting':
      return `Voting opened on ${quoted(p.proposal_title) || 'a proposal'}`;
    case 'proposal.closed':
      if (p.status) {
        return `${quoted(p.proposal_title) || 'A proposal'} has closed (${p.status})`;
      }
      return `${quoted(p.proposal_title) || 'A proposal'} has closed`;
    case 'proposal.extended_by_stability':
      return `Voting was extended on ${quoted(p.proposal_title) || 'a proposal'} (Stable Result Required)`;
    // ---- Membership ---------------------------------------------------
    case 'member.join_request':
      return `${actor(notif)} requested to join ${p.org_name || 'your organization'}`;
    case 'invitation.accepted':
      return `${actor(notif)} accepted your invitation${p.org_name ? ` to ${p.org_name}` : ''}`;
    // ---- Delegation ---------------------------------------------------
    // Phase 30.1 B4 — legacy delegate.applied / delegate.application_decided
    // notification formatters removed alongside the legacy
    // DelegateApplication surface. The Phase 19 events
    // (delegate_application_*) are formatted further down.
    case 'follow.requested':
      return `${actor(notif)} wants to follow you`;
    case 'follow.approved':
      return `${actor(notif)} approved your follow request`;
    // ---- Polis --------------------------------------------------------
    case 'polis.created':
      return `New deliberation: ${quoted(p.polis_title) || 'a new Polis was created'}`;
    // ---- Weighted governance (Phase 88c / 90a) ------------------------
    case 'org.voting_model_changed':
      return `${actor(notif)} changed how votes are counted in ${p.org_name || 'your organization'}`;
    case 'shares.received':
      return `You received ${p.amount || 'additional'} ${p.unit_label || 'shares'} in ${p.org_name || 'your organization'}`;
    default:
      // Unknown event type — render the key so QA can spot the gap.
      return notif.event_type;
  }
}

/**
 * Build the click-through path for a notification.
 *
 * Item 22 (Phase 13 spec): routing must use the notification's own
 * org_slug (resolved by the backend from org_id). NEVER fall back to the
 * legacy "first parent org" heuristic — that's exactly the bug Item 22
 * was logging in the old NotificationBadge.
 *
 * If the notification carries no org_slug (account-level events such as
 * follow.approved), we route to /notifications (the full feed) so the user
 * lands somewhere sensible instead of guessing at an org.
 */
export function notificationHref(notif) {
  if (!notif) return '/notifications';
  const slug = notif.org_slug || null;
  const targetType = notif.target_type || null;
  const targetId = notif.target_id || null;
  const eventType = notif.event_type || '';
  const payload = notif.payload || {};

  // Account-level notifications (no org context). These either don't have
  // an org_slug at emission time or are intentionally global to the user.
  if (!slug) {
    if (eventType.startsWith('follow.')) {
      // Follow events live at the user's account level. The /notifications
      // feed is the most useful landing — Phase 13 doesn't add a dedicated
      // "incoming follow requests" page outside the existing per-org
      // delegations surface.
      return '/notifications';
    }
    return '/notifications';
  }

  // Phase 30.1 B4 — legacy "delegate.*" event-type routing removed; the
  // /admin/delegates page no longer exists. The Phase 19
  // delegate_application_* events route via target_type/target_id in the
  // standard handler below.

  // Phase 20 — Stable Result Required extension events point at the
  // proposal that just got extended.
  if (eventType === 'proposal.extended_by_stability') {
    if (targetId) return `/${slug}/proposals/${targetId}`;
  }

  // Polis events: voter-facing Polis page.
  if (targetType === 'polis' && targetId) {
    return `/${slug}/polises/${targetId}`;
  }

  // Phase 90a — a shares grant lands on the share activity feed.
  if (eventType === 'shares.received') {
    return `/${slug}/shares`;
  }
  // Phase 88c — a voting-model change lands on the members page.
  if (eventType === 'org.voting_model_changed') {
    return `/${slug}/members`;
  }

  // Comments: deep-link to the comment via #comment-{id} so the user lands
  // on the proposal page with the comment in view. The emission site is
  // expected to put proposal_id in the payload (the comment row itself
  // doesn't expose proposal_id without a join).
  if (targetType === 'comment') {
    const proposalId = payload.proposal_id;
    if (proposalId && targetId) {
      return `/${slug}/proposals/${proposalId}#comment-${targetId}`;
    }
    if (proposalId) return `/${slug}/proposals/${proposalId}`;
  }

  // Proposals: direct link to the proposal page.
  if (targetType === 'proposal' && targetId) {
    return `/${slug}/proposals/${targetId}`;
  }

  // Invitations: the inviter is the recipient — route to the members admin
  // page where invitations are managed.
  if (targetType === 'invitation') {
    return `/${slug}/admin/members`;
  }

  // Membership join-request: same admin surface.
  if (eventType === 'member.join_request') {
    return `/${slug}/admin/members`;
  }

  // Final fallback: the org's proposals list. Better than the account-level
  // /notifications page when we know the org but not a specific target.
  return `/${slug}/proposals`;
}

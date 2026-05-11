import { useNavigate } from 'react-router-dom';

/**
 * Phase 15 G1 — Smart back-link for /help/* pages.
 *
 * Replaces the static `<Link to="/orgs">← Back</Link>` pattern that was
 * shared across PolisHelp / VotingMethodsHelp / StableResultHelp /
 * RolePermissionsHelp / NotificationsHelp / OrganizationsHelp. Calling
 * `history.back()` returns the visitor to wherever they were before the
 * help page (typically the page that linked here, e.g. OrgSettings →
 * /help/stable-result back returns to OrgSettings rather than dropping
 * into the org picker).
 *
 * Falls back to `/orgs` when `window.history.length <= 1` (visitor opened
 * the help page directly via URL, no prior in-app history). This matches
 * the prior behavior for direct-URL hits without breaking the in-app
 * navigation case (audit Item 33, retired 2026-05-06).
 */
export default function HelpBackLink() {
  const navigate = useNavigate();
  function handleBack() {
    if (typeof window !== 'undefined' && window.history.length > 1) {
      window.history.back();
    } else {
      navigate('/orgs');
    }
  }
  return (
    <button
      type="button"
      onClick={handleBack}
      className="text-sm text-[var(--brand-accent)] hover:underline mb-4 inline-block"
    >
      ← Back
    </button>
  );
}

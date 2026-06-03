import { useOrg } from '../OrgContext';
import LeaveOrgSection from '../components/LeaveOrgSection';

/**
 * Phase 50 — member-accessible "Leave organization" page.
 *
 * Reachable at /:org_slug/leave by ANY active member of the org (no
 * admin gate). The same Leave control admins see in OrgSettings is
 * surfaced here so a non-admin can find it — discoverable via the
 * Nav user-menu link.
 */
export default function LeaveOrg() {
  const { currentOrg } = useOrg();

  return (
    <div className="max-w-3xl mx-auto px-4 sm:px-6 lg:px-8 py-6 space-y-4">
      <header className="space-y-1">
        <h1 className="text-2xl font-bold text-gray-900">Leave organization</h1>
        <p className="text-sm text-gray-500">
          End your membership in <strong>{currentOrg?.name || 'this organization'}</strong>.
        </p>
      </header>
      <LeaveOrgSection />
    </div>
  );
}

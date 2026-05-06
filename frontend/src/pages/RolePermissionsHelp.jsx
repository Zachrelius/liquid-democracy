import HelpBackLink from '../components/HelpBackLink';

/**
 * Phase 12 Stage 2 D2 — public help page for the role-permissions matrix.
 *
 * Route: /help/role-permissions (public — no `ProtectedRoute` wrapping;
 * mirrors the other /help/* pages).
 *
 * Content covers:
 *   1. What each preset role traditionally does (the defaults).
 *   2. Examples of common configurations.
 *   3. Why some Steward permissions are locked (self-lockout protection).
 *   4. Where audit log entries appear.
 *   5. EXPLICITLY: what is NOT in the matrix and why (org.delete +
 *      org.transfer_stewardship are Steward-only operations that cannot
 *      be reassigned via the matrix; they live outside the matrix because
 *      they're load-bearing protections).
 */
export default function RolePermissionsHelp() {
  return (
    <div className="max-w-3xl mx-auto px-4 py-8 space-y-8">
      <div>
        {/* Phase 15 G1 — back-link uses history.back() with /orgs fallback. */}
        <HelpBackLink />
        <h1 className="text-2xl font-bold text-[var(--brand-primary)]">About Role Permissions</h1>
        <p className="text-sm text-gray-500 mt-1">
          How the matrix works, what each role does by default, and which
          operations live outside the matrix on purpose.
        </p>
      </div>

      <section className="bg-white border border-gray-200 rounded-xl p-6 space-y-3">
        <h2 className="text-lg font-semibold text-[var(--brand-primary)]">The four preset roles</h2>
        <p className="text-sm text-gray-700 leading-relaxed">
          Every organization is created with four built-in roles:
        </p>
        <ul className="text-sm text-gray-700 leading-relaxed list-disc pl-6 space-y-1">
          <li><strong>Steward</strong> — full administrative trust. Created with the org; only one transfer-able role per org. Some Steward permissions are locked to prevent self-lockout (see below).</li>
          <li><strong>Admin</strong> — manages day-to-day org operations. Defaults match Steward except for the org-deletion path (which only the Steward can do).</li>
          <li><strong>Moderator</strong> — manages content and member onboarding. Defaults: create proposals + topics, advance proposal phases, approve member joins, send invitations, create Polis conversations, moderate comments.</li>
          <li><strong>Member</strong> — base participant. Members can vote, delegate, comment, and view org content; the matrix doesn't gate those activities. Members get no admin-tier grants by default; an org can grant them specific permissions through the matrix.</li>
        </ul>
      </section>

      <section className="bg-white border border-gray-200 rounded-xl p-6 space-y-3">
        <h2 className="text-lg font-semibold text-[var(--brand-primary)]">Common configurations</h2>
        <p className="text-sm text-gray-700 leading-relaxed">
          Defaults work for most organizations. A few examples of when you might change them:
        </p>
        <ul className="text-sm text-gray-700 leading-relaxed list-disc pl-6 space-y-2">
          <li><strong>Want moderators to delete their own bad-faith proposals?</strong> Grant <code className="text-xs bg-gray-100 px-1 py-0.5 rounded">proposal.delete</code> to Moderator.</li>
          <li><strong>Want only the Steward to remove members?</strong> Revoke <code className="text-xs bg-gray-100 px-1 py-0.5 rounded">member.remove</code> from Admin.</li>
          <li><strong>Running a high-trust org where members can create their own topics?</strong> Grant <code className="text-xs bg-gray-100 px-1 py-0.5 rounded">topic.create</code> to Member.</li>
          <li><strong>Letting an admin manage permissions but not the org's core settings?</strong> Grant <code className="text-xs bg-gray-100 px-1 py-0.5 rounded">role_permissions.edit</code> but revoke <code className="text-xs bg-gray-100 px-1 py-0.5 rounded">org.edit_settings</code> from a custom-fit Admin (in Stage 2 you have to use one of the four preset roles; future passes may add custom roles).</li>
        </ul>
      </section>

      <section className="bg-white border border-gray-200 rounded-xl p-6 space-y-3">
        <h2 className="text-lg font-semibold text-[var(--brand-primary)]">Why some Steward permissions are locked</h2>
        <p className="text-sm text-gray-700 leading-relaxed">
          Three Steward permissions are locked TRUE and cannot be unset via the matrix:
        </p>
        <ul className="text-sm text-gray-700 leading-relaxed list-disc pl-6 space-y-1">
          <li><code className="text-xs bg-gray-100 px-1 py-0.5 rounded">member.change_role</code> — without this, a Steward who removes their own admin and moderator subordinates can't promote anyone else, and the org's role tree stops being editable.</li>
          <li><code className="text-xs bg-gray-100 px-1 py-0.5 rounded">org.edit_settings</code> — basic org operability. Without this the Steward can't even change the org's name.</li>
          <li><code className="text-xs bg-gray-100 px-1 py-0.5 rounded">role_permissions.edit</code> — the meta-permission for editing the matrix itself. Without this the Steward can't UNDO a bad save and the org becomes structurally frozen.</li>
        </ul>
        <p className="text-sm text-gray-700 leading-relaxed">
          These three together are the minimum a Steward needs to recover from any matrix configuration. They render as locked checkboxes in the UI.
        </p>
      </section>

      <section className="bg-white border border-gray-200 rounded-xl p-6 space-y-3">
        <h2 className="text-lg font-semibold text-[var(--brand-primary)]">Audit log</h2>
        <p className="text-sm text-gray-700 leading-relaxed">
          Every save to the matrix produces a single audit entry of type <code className="text-xs bg-gray-100 px-1 py-0.5 rounded">role_permissions.updated</code>, with a structured list of every cell that flipped (which role, which permission, old value, new value). A save that changes nothing produces no audit entry. The audit log is visible at the org's audit-log surface (admin nav).
        </p>
      </section>

      <section className="bg-white border border-amber-200 bg-amber-50/30 rounded-xl p-6 space-y-3">
        <h2 className="text-lg font-semibold text-[var(--brand-primary)]">What is <em>NOT</em> in the matrix and why</h2>
        <p className="text-sm text-gray-700 leading-relaxed">
          Two operations are deliberately Steward-only and cannot be reassigned via the matrix:
        </p>
        <ul className="text-sm text-gray-700 leading-relaxed list-disc pl-6 space-y-1">
          <li><strong>Deleting the organization</strong> (<code className="text-xs bg-amber-100 px-1 py-0.5 rounded">org.delete</code>) — irreversible destruction of every proposal, vote, and member record. Only the Steward can do this; the UI control is hidden from anyone else.</li>
          <li><strong>Transferring the Steward role</strong> (<code className="text-xs bg-amber-100 px-1 py-0.5 rounded">org.transfer_stewardship</code>) — assigning Stewardship to another member. This endpoint may not exist in your build yet; if it does, only the current Steward can use it.</li>
        </ul>
        <p className="text-sm text-gray-700 leading-relaxed">
          These live outside the matrix on purpose. If they were grantable through the matrix, an org could accidentally lock itself out of administering itself or hand permanent control to the wrong person via a one-click checkbox. The protection is hardcoded; the UI button is hidden from non-Stewards as defense-in-depth on top of the server-side check.
        </p>
      </section>
    </div>
  );
}

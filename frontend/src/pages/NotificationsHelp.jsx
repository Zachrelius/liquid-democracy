import { Link } from 'react-router-dom';

/**
 * Phase 13 D1 — public help page for the notification system.
 *
 * Route: /help/notifications (public — no `ProtectedRoute` wrapping;
 * mirrors the other /help/* pages).
 *
 * Content covers:
 *   1. Opt-in by default — explicit statement of philosophy.
 *   2. The 12 event types with one-line descriptions.
 *   3. The four digest cadence options (real-time / daily / weekly / off).
 *   4. How quiet hours work.
 *   5. That transactional emails (verification, password reset) are NOT
 *      affected by these preferences.
 */
export default function NotificationsHelp() {
  return (
    <div className="max-w-3xl mx-auto px-4 py-8 space-y-8">
      <div>
        <Link to="/orgs" className="text-sm text-[var(--brand-accent)] hover:underline mb-4 inline-block">
          ← Back
        </Link>
        <h1 className="text-2xl font-bold text-[var(--brand-primary)]">About Notifications</h1>
        <p className="text-sm text-gray-500 mt-1">
          What events fire, how to opt in, and how digests + quiet hours work.
        </p>
      </div>

      <section className="bg-white border border-amber-200 bg-amber-50/30 rounded-xl p-6 space-y-3">
        <h2 className="text-lg font-semibold text-[var(--brand-primary)]">Notifications are off by default</h2>
        <p className="text-sm text-gray-700 leading-relaxed">
          Liquid Democracy is built around the idea that you can delegate to people you trust and get on with your life. That means we do not ship a notification system that pings you about everything. Every event-channel pair starts disabled; you choose what you want to be notified about.
        </p>
        <p className="text-sm text-gray-700 leading-relaxed">
          Open the notification center (the bell icon) and visit Notification preferences in your account settings to enable any of the 12 event types in either the in-app feed or via email.
        </p>
      </section>

      <section className="bg-white border border-gray-200 rounded-xl p-6 space-y-3">
        <h2 className="text-lg font-semibold text-[var(--brand-primary)]">The 12 event types</h2>
        <p className="text-sm text-gray-700 leading-relaxed">
          Events are grouped into 5 categories on the preferences page:
        </p>
        <div className="text-sm text-gray-700 leading-relaxed space-y-3">
          <div>
            <p className="font-semibold">Comments</p>
            <ul className="list-disc pl-6 space-y-1">
              <li><strong>Reply to your comment</strong> — someone replied to a comment you posted on a proposal.</li>
              <li><strong>Comment on your proposal</strong> — someone left a top-level comment on a proposal you authored.</li>
            </ul>
          </div>
          <div>
            <p className="font-semibold">Proposals</p>
            <ul className="list-disc pl-6 space-y-1">
              <li><strong>Proposal entered voting</strong> — voting opened on a proposal in an org you belong to (and you are eligible to vote).</li>
              <li><strong>Proposal closed</strong> — a proposal you voted on or authored has reached its final state (passed / failed).</li>
              <li><strong>Vote support nearing floor</strong> — for proposals using sustained-majority voting, a heads-up that support has dropped near the configured floor.</li>
            </ul>
          </div>
          <div>
            <p className="font-semibold">Membership</p>
            <ul className="list-disc pl-6 space-y-1">
              <li><strong>New member request to join</strong> — someone asked to join an org you have permission to approve members for.</li>
              <li><strong>Invitation accepted</strong> — someone you invited finished joining the org.</li>
            </ul>
          </div>
          <div>
            <p className="font-semibold">Delegation</p>
            <ul className="list-disc pl-6 space-y-1">
              <li><strong>New delegate application</strong> — someone applied to become a public delegate in an org you have permission to approve.</li>
              <li><strong>Your delegate application</strong> — your delegate application was approved or denied.</li>
              <li><strong>Follow request</strong> — someone requested permission to follow your votes (or to delegate to you).</li>
              <li><strong>Follow approved</strong> — your follow request was approved by the target user.</li>
            </ul>
          </div>
          <div>
            <p className="font-semibold">Polis</p>
            <ul className="list-disc pl-6 space-y-1">
              <li><strong>New deliberation</strong> — a new Polis deliberation was created in an org you belong to.</li>
            </ul>
          </div>
        </div>
      </section>

      <section className="bg-white border border-gray-200 rounded-xl p-6 space-y-3">
        <h2 className="text-lg font-semibold text-[var(--brand-primary)]">Email digest cadence</h2>
        <p className="text-sm text-gray-700 leading-relaxed">
          For events you have enabled the email channel on, you choose how often the emails arrive:
        </p>
        <ul className="text-sm text-gray-700 leading-relaxed list-disc pl-6 space-y-1">
          <li><strong>Real-time</strong> — every event sends its own email when it happens.</li>
          <li><strong>Daily (9am local)</strong> — one digest email per day at 9am in your timezone, grouping all events from the prior 24 hours by org and event type. Empty digests are not sent.</li>
          <li><strong>Weekly (Monday 9am local)</strong> — one digest per week, same shape as daily but covering the prior 7 days.</li>
          <li><strong>Off</strong> — no email is sent for any event, regardless of per-event email toggles. The in-app feed still works normally.</li>
        </ul>
      </section>

      <section className="bg-white border border-gray-200 rounded-xl p-6 space-y-3">
        <h2 className="text-lg font-semibold text-[var(--brand-primary)]">Quiet hours</h2>
        <p className="text-sm text-gray-700 leading-relaxed">
          A single checkbox on the preferences page: "Don't email me between 9pm and 9am in my timezone." When enabled, real-time emails that would arrive in the quiet window are queued and delivered at 9am instead. Quiet hours only affects the email channel — in-app notifications appear in the feed regardless of the time of day (the in-app feed is silent by design, so quiet hours doesn't apply to it).
        </p>
      </section>

      <section className="bg-white border border-gray-200 rounded-xl p-6 space-y-3">
        <h2 className="text-lg font-semibold text-[var(--brand-primary)]">Opting out</h2>
        <p className="text-sm text-gray-700 leading-relaxed">
          You can change any preference at any time. Three options:
        </p>
        <ul className="text-sm text-gray-700 leading-relaxed list-disc pl-6 space-y-1">
          <li>Visit Notification preferences in your account settings and uncheck the events you no longer want.</li>
          <li>Click the "Unsubscribe from these" link in the footer of any notification email — that flips just that event-type's email channel to off.</li>
          <li>Set the digest cadence to "Off" to silence all email notifications without changing per-event toggles.</li>
        </ul>
      </section>

      <section className="bg-white border border-amber-200 bg-amber-50/30 rounded-xl p-6 space-y-3">
        <h2 className="text-lg font-semibold text-[var(--brand-primary)]">Transactional emails are not affected</h2>
        <p className="text-sm text-gray-700 leading-relaxed">
          Some emails are essential to the platform working at all and are not subject to your notification preferences. These include:
        </p>
        <ul className="text-sm text-gray-700 leading-relaxed list-disc pl-6 space-y-1">
          <li>Email verification (when you create an account or change your email).</li>
          <li>Password reset.</li>
          <li>Org invitation emails (when someone invites you to join an org).</li>
        </ul>
        <p className="text-sm text-gray-700 leading-relaxed">
          These always send and are not on the unsubscribe path. If you want to stop receiving them, the right move is to deactivate the relevant account or invitation, not to turn off notifications.
        </p>
      </section>
    </div>
  );
}

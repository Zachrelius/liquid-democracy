import HelpBackLink from '../components/HelpBackLink';

/**
 * Phase 13 D1 — public help page for the notification system.
 * Phase 13.3 D1 — updated for per-event cadence + 4-column matrix +
 * three voting-opened event types + adjustable quiet hours + retired
 * sustained_majority.floor_approached.
 *
 * Route: /help/notifications (public — no `ProtectedRoute` wrapping;
 * mirrors the other /help/* pages).
 *
 * Content covers:
 *   1. Opt-in by default — explicit statement of philosophy.
 *   2. The 13 event types with one-line descriptions, including the
 *      three voting-opened events with priority-resolution semantics.
 *   3. The four channels (in-app, weekly digest, daily digest, immediate
 *      email) — per-event, NOT mutually exclusive.
 *   4. How adjustable quiet hours work.
 *   5. That transactional emails (verification, password reset) are NOT
 *      affected by these preferences.
 */
export default function NotificationsHelp() {
  return (
    <div className="max-w-3xl mx-auto px-4 py-8 space-y-8">
      <div>
        {/* Phase 15 G1 — back-link uses history.back() with /orgs fallback. */}
        <HelpBackLink />
        <h1 className="text-2xl font-bold text-[var(--brand-primary)]">About Notifications</h1>
        <p className="text-sm text-gray-500 mt-1">
          What events fire, how to opt in per-channel-per-event, and how quiet hours work.
        </p>
      </div>

      <section className="bg-white border border-amber-200 bg-amber-50/30 rounded-xl p-6 space-y-3">
        <h2 className="text-lg font-semibold text-[var(--brand-primary)]">Notifications are off by default</h2>
        <p className="text-sm text-gray-700 leading-relaxed">
          Liquid Democracy is built around the idea that you can delegate to people you trust and get on with your life. That means we do not ship a notification system that pings you about everything. Every event-channel pair starts disabled; you choose what you want to be notified about.
        </p>
        <p className="text-sm text-gray-700 leading-relaxed">
          Open the notification center (the bell icon) and visit Notification preferences in your account settings to enable any of the 13 event types in any of the four channels.
        </p>
      </section>

      <section className="bg-white border border-gray-200 rounded-xl p-6 space-y-3">
        <h2 className="text-lg font-semibold text-[var(--brand-primary)]">The four channels (per-event)</h2>
        <p className="text-sm text-gray-700 leading-relaxed">
          For each event type, you choose any combination of these channels — they're independent toggles, not mutually exclusive:
        </p>
        <ul className="text-sm text-gray-700 leading-relaxed list-disc pl-6 space-y-1">
          <li><strong>In-App</strong> — a row appears in your notification dropdown + on <code className="text-xs bg-gray-100 px-1 py-0.5 rounded">/notifications</code>. Silent until you check the badge.</li>
          <li><strong>Weekly Digest</strong> — included in a single email at 9am Monday in your timezone, grouped by org and event type.</li>
          <li><strong>Daily Digest</strong> — included in a single email at 9am every day in your timezone.</li>
          <li><strong>Immediate Email</strong> — fires as soon as the event happens (subject to quiet hours, see below).</li>
        </ul>
        <p className="text-sm text-gray-700 leading-relaxed">
          The columns on the preferences page are ordered left-to-right by ascending intrusiveness so you can pick the gentlest channel that gives you the signal you want. You can pick more than one — for example, "Daily Digest + Immediate Email" on a high-importance event for belt-and-suspenders coverage.
        </p>
        <p className="text-sm text-gray-700 leading-relaxed">
          Empty digests don't send. If you opt into Daily Digest for an event but no events fire on a given day, no email goes out.
        </p>
      </section>

      <section className="bg-white border border-gray-200 rounded-xl p-6 space-y-3">
        <h2 className="text-lg font-semibold text-[var(--brand-primary)]">The 13 event types</h2>
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
              <li><strong>Voting opened (generic)</strong> — voting opened on a proposal in an org you belong to. The legacy "everyone gets the same notification" event; useful if you don't want to think about delegation state.</li>
              <li><strong>Voting opened (you vote)</strong> — voting opened on a proposal whose topic you have NOT delegated. You need to vote yourself.</li>
              <li><strong>Voting opened (you vote on others' behalf)</strong> — voting opened on a proposal whose topic someone has delegated to you. You're voting on their behalf.</li>
              <li><strong>Proposal closed</strong> — a proposal you voted on or authored has reached its final state (passed / failed).</li>
            </ul>
            <div className="mt-2 p-3 bg-amber-50/50 border border-amber-200 rounded-lg">
              <p className="text-xs text-gray-700 leading-relaxed">
                <strong>One notification per voting-opened trigger.</strong> If you opt into multiple voting-opened events, you'll receive the most relevant one for each proposal — never multiple notifications for the same proposal entering voting. Priority order: "delegated to you" beats "you vote" beats generic.
              </p>
            </div>
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
        <h2 className="text-lg font-semibold text-[var(--brand-primary)]">Quiet hours (adjustable)</h2>
        <p className="text-sm text-gray-700 leading-relaxed">
          Below the matrix, a single checkbox: "Don't email me during quiet hours." When enabled, two time pickers appear — Start and End — letting you set the window in your timezone. Defaults are 21:00 (9pm) start and 09:00 (9am) end, but you can pick any window.
        </p>
        <p className="text-sm text-gray-700 leading-relaxed">
          During the quiet window, immediate emails that would have arrived are queued and delivered when the window ends. Daily and Weekly digests are unaffected (they already run on a schedule). In-App notifications also unaffected — the in-app feed is silent by design, so quiet hours doesn't apply to it.
        </p>
      </section>

      <section className="bg-white border border-gray-200 rounded-xl p-6 space-y-3">
        <h2 className="text-lg font-semibold text-[var(--brand-primary)]">Opting out</h2>
        <p className="text-sm text-gray-700 leading-relaxed">
          You can change any preference at any time. Three paths:
        </p>
        <ul className="text-sm text-gray-700 leading-relaxed list-disc pl-6 space-y-1">
          <li>Visit Notification preferences in your account settings and uncheck the channels you no longer want, per event.</li>
          <li>Click the "Unsubscribe from these" link in the footer of any notification email — that flips ALL email channels (immediate / daily / weekly) for that event type to off in one click. The In-App channel stays on if you had it on.</li>
          <li>Uncheck every email channel for an event to stop email entirely while keeping the in-app feed.</li>
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

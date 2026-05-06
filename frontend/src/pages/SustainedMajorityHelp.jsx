import HelpBackLink from '../components/HelpBackLink';

export default function SustainedMajorityHelp() {
  return (
    <div className="max-w-3xl mx-auto px-4 py-8 space-y-8">
      <div>
        {/* Phase 11 — help pages are public/non-org-scoped.
            Phase 15 G1 — back-link uses history.back() with /orgs fallback. */}
        <HelpBackLink />
        <h1 className="text-2xl font-bold text-[var(--brand-primary)]">Sustained-Majority Voting</h1>
        <p className="text-sm text-gray-500 mt-1">
          A governance feature that requires support to <em>hold</em> through the
          voting window — not just at a single moment.
        </p>
      </div>

      {/* When to use */}
      <section className="bg-blue-50 border border-blue-200 rounded-xl p-6 space-y-3">
        <h2 className="text-lg font-semibold text-[var(--brand-primary)]">When should we use it?</h2>
        <p className="text-sm text-gray-700 leading-relaxed">
          Sustained-majority is opt-in and default-off. Most decisions don&apos;t need it:
          a routine vote on a meeting time, a non-binding poll, an internal sense-check —
          turning it on for those would be overkill.
        </p>
        <p className="text-sm text-gray-700 leading-relaxed">
          It exists for the cases where the <em>durability</em> of the majority matters:
        </p>
        <ul className="text-sm text-gray-700 space-y-2 leading-relaxed list-disc pl-5">
          <li>
            <strong>Binding decisions</strong> — charter changes, significant spending,
            policies that bind future members.
          </li>
          <li>
            <strong>Slow-burn decisions</strong> where late-window manipulation could
            flip a narrow majority. The mechanism makes &quot;snap votes&quot; in the
            final hour ineffective.
          </li>
          <li>
            <strong>Decisions where delegators need time to react.</strong> If a delegate
            casts an unexpected vote, sustained-majority gives delegators a window to
            change their delegation or vote directly.
          </li>
        </ul>
      </section>

      {/* How it works (admin) */}
      <section className="bg-white border border-gray-200 rounded-xl p-6 space-y-3">
        <h2 className="text-lg font-semibold text-[var(--brand-primary)]">For org admins</h2>
        <p className="text-sm text-gray-700 leading-relaxed">
          In <strong>Org Settings → Sustained-Majority Voting</strong>, you choose:
        </p>
        <dl className="text-sm text-gray-700 space-y-3 leading-relaxed">
          <div>
            <dt className="font-medium text-[var(--brand-primary)]">Default on for new proposals</dt>
            <dd className="ml-4 text-gray-600">
              When checked, every new proposal uses sustained-majority unless the author
              opts out. When unchecked, proposals are normal unless the author opts in.
            </dd>
          </div>
          <div>
            <dt className="font-medium text-[var(--brand-primary)]">Allow per-proposal override</dt>
            <dd className="ml-4 text-gray-600">
              When checked, proposal authors can flip the toggle on or off for their own
              proposal. When unchecked, the org default applies to every proposal —
              authors don&apos;t see the toggle.
            </dd>
          </div>
          <div>
            <dt className="font-medium text-[var(--brand-primary)]">Required support level</dt>
            <dd className="ml-4 text-gray-600">
              The headline support percentage the proposal must reach to pass. Defaults
              to 50% — the same as the platform&apos;s normal pass threshold.
            </dd>
          </div>
          <div>
            <dt className="font-medium text-[var(--brand-primary)]">Drop-below floor</dt>
            <dd className="ml-4 text-gray-600">
              If support dips below this percentage during the voting window, the
              configured failure mode triggers. Set this 5–10 percentage points below
              the threshold so transient dips don&apos;t fire — but high enough to catch
              real reversals.
            </dd>
          </div>
          <div>
            <dt className="font-medium text-[var(--brand-primary)]">Failure mode</dt>
            <dd className="ml-4 text-gray-600">
              <ul className="space-y-1 list-disc pl-5">
                <li>
                  <strong>Fail immediately</strong> — the proposal closes the moment
                  support drops below the floor. Strictest option.
                </li>
                <li>
                  <strong>Extend the voting window once</strong> — push the deadline forward
                  to give voters time to recover support. A second breach fails the proposal.
                </li>
                <li>
                  <strong>Escalate to admin review</strong> — the proposal moves to
                  &quot;awaiting review&quot; (status: <code>unresolved</code>) and an
                  org admin chooses how to handle it: extend, fail, mark passed, or
                  return to deliberation.
                </li>
              </ul>
            </dd>
          </div>
        </dl>
      </section>

      {/* Voter view */}
      <section className="bg-white border border-gray-200 rounded-xl p-6 space-y-3">
        <h2 className="text-lg font-semibold text-[var(--brand-primary)]">For voters and delegators</h2>
        <p className="text-sm text-gray-700 leading-relaxed">
          Sustained-majority proposals show a small <span className="text-xs bg-blue-50 text-[var(--brand-accent)] border border-blue-200 px-1.5 py-0.5 rounded">⏳ Sustained</span>{' '}
          badge in the proposal list — a flag to check back during the window rather than
          fire-and-forget.
        </p>
        <p className="text-sm text-gray-700 leading-relaxed">
          On the proposal page, you&apos;ll see a support indicator with the floor marked
          as a red zone, plus a chart of support over the voting window. If your effective
          ballot is contributing to a proposal whose support is approaching the floor
          (within 5 percentage points), you get an in-app banner so you have time to:
        </p>
        <ul className="text-sm text-gray-700 space-y-1 leading-relaxed list-disc pl-5">
          <li>Review your vote (and change it if you want)</li>
          <li>Review your delegation (and revoke it if your delegate is voting differently than you&apos;d expect)</li>
        </ul>
        <p className="text-xs text-gray-500 italic">
          Note: floor-approach notifications are in-app only for now. Email notifications
          are coming in a future release.
        </p>
      </section>

      {/* Multi-option */}
      <section className="bg-white border border-gray-200 rounded-xl p-6 space-y-3">
        <h2 className="text-lg font-semibold text-[var(--brand-primary)]">Approval and ranked-choice proposals</h2>
        <p className="text-sm text-gray-700 leading-relaxed">
          Floors don&apos;t map cleanly to multi-option votes (what does &quot;floor&quot;
          even mean when there are five options?). Instead, sustained-majority on
          approval / ranked-choice proposals locks the <em>computed winner</em> during
          the final 25% of the voting window: any change to who would win triggers the
          configured failure mode.
        </p>
        <p className="text-sm text-gray-700 leading-relaxed">
          The proposal page shows a &quot;stable-result lock&quot; indicator when the
          window enters that final stretch — that&apos;s your cue to firm up your vote.
        </p>
      </section>

      {/* What happens to delegators */}
      <section className="bg-white border border-gray-200 rounded-xl p-6 space-y-3">
        <h2 className="text-lg font-semibold text-[var(--brand-primary)]">What happens if my delegate votes against my preference?</h2>
        <p className="text-sm text-gray-700 leading-relaxed">
          The platform doesn&apos;t track preferences directly — it tracks votes and
          delegations. But if your delegate&apos;s vote on a sustained-majority proposal
          drives support toward the floor, you&apos;ll see the floor-approach banner
          on the proposal page (assuming your effective ballot is contributing — i.e.
          the chain resolves to a vote, rather than abstaining or non-resolving).
        </p>
        <p className="text-sm text-gray-700 leading-relaxed">
          From there you can revoke or change your delegation, or vote directly on this
          proposal — your direct vote always takes precedence over a delegation. The
          delegation chain doesn&apos;t change for other proposals.
        </p>
      </section>

      {/* Audit */}
      <section className="bg-white border border-gray-200 rounded-xl p-6 space-y-3">
        <h2 className="text-lg font-semibold text-[var(--brand-primary)]">What gets logged?</h2>
        <p className="text-sm text-gray-700 leading-relaxed">
          Every state-changing event in this feature is recorded in the audit log:
          config changes (which keys changed, old → new), per-proposal toggles, window
          extensions, floor-breach failures, escalations, and the admin&apos;s
          resolution choice (with optional reason). Ballot content is never recorded —
          just the aggregate breach numbers (yes / no / abstain counts at the breach
          moment).
        </p>
      </section>
    </div>
  );
}

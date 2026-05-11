import HelpBackLink from '../components/HelpBackLink';

/**
 * Phase 20 F3 — Help page for the redesigned Stable Result Required
 * feature. Renamed from SustainedMajorityHelp.jsx; the floor / failure-
 * mode / approaching-floor mechanics are gone, replaced by the unified
 * stable-window mechanic with sliding-window check during extensions.
 *
 * Route: /help/stable-result. The legacy /help/sustained-majority route
 * is kept as a redirect-equivalent by aliasing to the same component in
 * App.jsx so existing in-app links and bookmarks don't 404.
 */
export default function StableResultHelp() {
  return (
    <div className="max-w-3xl mx-auto px-4 py-8 space-y-8">
      <div>
        {/* Phase 11 — help pages are public/non-org-scoped.
            Phase 15 G1 — back-link uses history.back() with /orgs fallback. */}
        <HelpBackLink />
        <h1 className="text-2xl font-bold text-[var(--brand-primary)]">Stable Result Required</h1>
        <p className="text-sm text-gray-500 mt-1">
          A governance feature that requires the voting result to be
          <em> stable</em> across the closing portion of the voting window.
        </p>
      </div>

      {/* What it is */}
      <section className="bg-blue-50 border border-blue-200 rounded-xl p-6 space-y-3">
        <h2 className="text-lg font-semibold text-[var(--brand-primary)]">What it is</h2>
        <p className="text-sm text-gray-700 leading-relaxed">
          When a proposal has <strong>Stable Result Required</strong> turned on,
          the result must be stable across the closing portion of the voting
          window — the &quot;stable window&quot;. If the result destabilizes,
          voting is automatically extended to give voters time to react.
        </p>
        <ul className="text-sm text-gray-700 space-y-2 leading-relaxed list-disc pl-5">
          <li>
            <strong>Binary proposals</strong> destabilize when support drops
            below the proposal&apos;s pass threshold during the stable window.
          </li>
          <li>
            <strong>Approval and ranked-choice proposals</strong> destabilize
            when the computed winner gets displaced (the new winner set has no
            options in common with the previous one).
          </li>
        </ul>
        <p className="text-sm text-gray-700 leading-relaxed">
          During an extension, voting closes early as soon as the result has
          been stable for the stable window&apos;s duration — a sliding-window
          check that doesn&apos;t make voters wait the full extension out
          unnecessarily. If stability isn&apos;t re-established, voting closes
          at the extension&apos;s natural deadline.
        </p>
      </section>

      {/* When to use it */}
      <section className="bg-white border border-gray-200 rounded-xl p-6 space-y-3">
        <h2 className="text-lg font-semibold text-[var(--brand-primary)]">When to use it</h2>
        <p className="text-sm text-gray-700 leading-relaxed">
          Stable Result Required is opt-in and default-off. Most decisions
          don&apos;t need it: a routine vote on a meeting time, a non-binding
          poll, an internal sense-check — turning it on for those is overkill.
        </p>
        <p className="text-sm text-gray-700 leading-relaxed">
          It&apos;s designed for cases where the durability of the result
          matters:
        </p>
        <ul className="text-sm text-gray-700 space-y-2 leading-relaxed list-disc pl-5">
          <li>
            <strong>High-stakes proposals</strong> — charter changes, significant
            spending commitments, policies that bind future members.
          </li>
          <li>
            <strong>Late-window manipulation concerns</strong> — when you want
            to make snap votes in the closing minutes ineffective, especially
            from public delegates carrying weighted votes.
          </li>
          <li>
            <strong>Decisions where delegators need time to react.</strong> If
            a delegate casts a surprising vote, the extension gives delegators
            a window to revisit their delegation or vote directly.
          </li>
        </ul>
      </section>

      {/* How extensions work */}
      <section className="bg-white border border-gray-200 rounded-xl p-6 space-y-3">
        <h2 className="text-lg font-semibold text-[var(--brand-primary)]">How extensions work</h2>
        <p className="text-sm text-gray-700 leading-relaxed">
          When the result destabilizes during the stable window, voting is
          extended by <strong>the stable window&apos;s duration</strong> — for
          example, a 7-day vote with a 25% stable window gets a 42-hour
          extension.
        </p>
        <p className="text-sm text-gray-700 leading-relaxed">
          During the extension, voting can close <em>early</em> as soon as
          the result has been stable for the stable window&apos;s duration.
          This is a sliding-window check: the system looks back at every
          snapshot in the most recent stable-window-duration of voting; if
          all of them show a stable result, voting closes immediately. You
          don&apos;t have to wait the full extension out if stability is
          re-established.
        </p>
        <p className="text-sm text-gray-700 leading-relaxed">
          Each org sets a <strong>maximum total extension</strong> — a cap
          on the cumulative extension time across all extensions combined,
          expressed as a fraction of the original voting period. Once the
          extension budget is exhausted, the proposal closes at its current
          deadline regardless of whether the result is stable.
        </p>
        <p className="text-sm text-gray-700 leading-relaxed">
          With the platform defaults (25% stable window, 25% maximum
          extension), exactly one extension fits the budget. Bumping the
          maximum total extension to 50% would accommodate two extensions;
          to 100%, four. Setting it to 0% logs destabilization without
          granting any extension at all.
        </p>
      </section>

      {/* Configuration */}
      <section className="bg-white border border-gray-200 rounded-xl p-6 space-y-3">
        <h2 className="text-lg font-semibold text-[var(--brand-primary)]">Configuration</h2>
        <p className="text-sm text-gray-700 leading-relaxed">
          In <strong>Org Settings → Stable Result Required</strong>, you choose:
        </p>
        <dl className="text-sm text-gray-700 space-y-3 leading-relaxed">
          <div>
            <dt className="font-medium text-[var(--brand-primary)]">Stable Result Required (default for new proposals)</dt>
            <dd className="ml-4 text-gray-600">
              When checked, every new proposal requires a stable result
              unless the author opts out. When unchecked, proposals are
              normal unless the author opts in.
            </dd>
          </div>
          <div>
            <dt className="font-medium text-[var(--brand-primary)]">Allow per-proposal override</dt>
            <dd className="ml-4 text-gray-600">
              When checked, proposal authors can flip the toggle on or off
              for their own proposal. When unchecked, the org default
              applies to every proposal — authors don&apos;t see the toggle.
            </dd>
          </div>
          <div>
            <dt className="font-medium text-[var(--brand-primary)]">Stable window (% of voting period)</dt>
            <dd className="ml-4 text-gray-600">
              The closing portion of the voting period where stability is
              required. Default 25%. For a 1-week vote, that&apos;s the last
              42 hours.
            </dd>
          </div>
          <div>
            <dt className="font-medium text-[var(--brand-primary)]">Maximum total extension (% of voting period)</dt>
            <dd className="ml-4 text-gray-600">
              The cap on cumulative extension time. Default 25%. For a
              1-week vote, that&apos;s up to 42 hours of extensions in
              total. Number of extensions is mechanically derived from this
              and the stable window: floor(maximum / stable window) =
              extensions allowed before force-close.
            </dd>
          </div>
        </dl>
      </section>

      {/* Audit / what gets logged */}
      <section className="bg-white border border-gray-200 rounded-xl p-6 space-y-3">
        <h2 className="text-lg font-semibold text-[var(--brand-primary)]">What gets logged</h2>
        <p className="text-sm text-gray-700 leading-relaxed">
          Every state-changing event in this feature is recorded in the
          audit log: config changes (which keys changed, old → new),
          per-proposal toggles, every extension granted (with the
          destabilization detail that triggered it), and the final close
          (whether stability was re-established or the extension budget
          was exhausted). Ballot content is never recorded — just the
          aggregate breach numbers at the destabilization moment.
        </p>
      </section>
    </div>
  );
}

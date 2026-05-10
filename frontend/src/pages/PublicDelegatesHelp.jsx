import HelpBackLink from '../components/HelpBackLink';

/**
 * Phase 19 D1 — public help page for the public-delegate surface.
 *
 * Route: /help/public-delegates (public — no `ProtectedRoute` wrapping;
 * mirrors the other /help/* pages).
 *
 * Two main sections per the spec:
 *
 *   1. For delegators (evaluating delegates) — how to read a delegate
 *      page, what to look for (transparency + accepting status, topics
 *      they cover, rationale on past votes, position statements), how
 *      delegation works once you've decided.
 *
 *   2. For prospective public delegates — what becoming a public delegate
 *      means, the three per-topic visibility states, the page-visibility
 *      ladder + drafting flow + the `private_delegators` intermediate
 *      state, what an approval process feels like, expectations around
 *      rationale, how reverting topics to `private` interacts with
 *      existing delegations (D15 — public-origin auto-revoked,
 *      private-origin preserved).
 */
export default function PublicDelegatesHelp() {
  return (
    <div className="max-w-3xl mx-auto px-4 py-8 space-y-8">
      <div>
        {/* Phase 15 G1 — back-link uses history.back() with /orgs fallback. */}
        <HelpBackLink />
        <h1 className="text-2xl font-bold text-[var(--brand-primary)]">About Public Delegates</h1>
        <p className="text-sm text-gray-500 mt-1">
          How to read a delegate page, how to think about becoming one, and what the visibility states mean.
        </p>
      </div>

      {/* ----------------------------------------------------------------- */}
      {/* For delegators                                                    */}
      {/* ----------------------------------------------------------------- */}
      <section className="bg-blue-50 border border-blue-200 rounded-xl p-6 space-y-3">
        <h2 className="text-lg font-semibold text-[var(--brand-primary)]">For delegators &mdash; evaluating a delegate</h2>
        <p className="text-sm text-gray-700 leading-relaxed">
          A public delegate page is the artifact a delegate writes about themselves so you can decide
          whether to delegate to them. Each page is per-organization &mdash; the same person may have a
          public delegate page in one org and not in another, with different content in each.
        </p>
      </section>

      <section className="bg-white border border-gray-200 rounded-xl p-6 space-y-3">
        <h2 className="text-lg font-semibold text-[var(--brand-primary)]">How to read a delegate page</h2>
        <p className="text-sm text-gray-700 leading-relaxed">
          Three blocks of content sit on every public delegate page, plus past-vote signal:
        </p>
        <ul className="text-sm text-gray-700 leading-relaxed list-disc pl-6 space-y-2">
          <li>
            <strong>Org-scoped intro (top of page).</strong> The delegate&apos;s &ldquo;about me&rdquo; for
            this organization &mdash; who they are, why they&apos;re willing to be a public delegate here,
            what&apos;s known about their values and background.
          </li>
          <li>
            <strong>Per-topic positions and bios.</strong> For each topic the delegate participates in
            publicly, a short bio of their experience on the topic and an optional position statement
            (&ldquo;on housing I generally favor X&rdquo;). The position statement is the most useful
            piece for evaluating fit &mdash; it&apos;s the delegate&apos;s declared posture, not just
            their voting record.
          </li>
          <li>
            <strong>Past-vote rationale.</strong> When a delegate votes on a proposal, they can attach a
            short writeup explaining their reasoning. Rationales appear on the public delegate page
            grouped by topic, and on the proposal&apos;s vote breakdown. Rationale is opt-in per
            vote; a delegate without rationale on past votes isn&apos;t hiding anything &mdash; they
            just haven&apos;t opted in. A delegate <em>with</em> consistent rationale is doing
            something specific: declaring how they think.
          </li>
        </ul>
      </section>

      <section className="bg-white border border-gray-200 rounded-xl p-6 space-y-3">
        <h2 className="text-lg font-semibold text-[var(--brand-primary)]">What to look for</h2>
        <ul className="text-sm text-gray-700 leading-relaxed list-disc pl-6 space-y-2">
          <li>
            <strong>Transparency vs. accepting status.</strong> Each topic on the delegate&apos;s page
            is in one of two public states: <em>public</em> (the delegate is transparent about their
            posture and vote history but not currently accepting new delegations) or
            <em> public_accepting</em> (transparent + actively accepting new delegations). Topics
            marked public-only are typically a delegate who&apos;s past their accepting window or
            paused for some reason. You can usually still delegate via the regular delegation flow,
            but the delegate has chosen not to invite it through the browse page.
          </li>
          <li>
            <strong>Topics they cover.</strong> Delegation is per-topic. A delegate may be public on
            housing and on transportation but not on schools. Match the delegate&apos;s topic coverage
            to what you actually want to delegate.
          </li>
          <li>
            <strong>Rationale signal on past votes.</strong> A delegate who consistently writes
            rationale on their votes is giving you a much higher-confidence sample than one whose
            page just shows the vote tallies. The browse page&apos;s sort options surface this
            (&ldquo;recent rationale ratio&rdquo; ranks delegates with lots of recent rationale higher).
          </li>
          <li>
            <strong>Position statements.</strong> Read these closely. A delegate&apos;s position
            statement on a topic is the most direct way to know what they&apos;ll do on a future
            proposal you can&apos;t yet predict.
          </li>
        </ul>
      </section>

      <section className="bg-white border border-gray-200 rounded-xl p-6 space-y-3">
        <h2 className="text-lg font-semibold text-[var(--brand-primary)]">Once you&apos;ve decided to delegate</h2>
        <p className="text-sm text-gray-700 leading-relaxed">
          From the delegate&apos;s page or from the browse page (
          <code className="text-xs bg-gray-100 px-1 py-0.5 rounded">/{'{org}'}/delegates</code>),
          click <strong>Delegate to this person</strong> on the topic you want. This creates a
          per-topic delegation in the same way you&apos;d create one from the Delegations page.
          Unlike the &ldquo;follow request&rdquo; flow used for private delegations, public-delegate
          delegations don&apos;t require approval from the delegate &mdash; the delegate has already
          publicly declared they&apos;re accepting (that&apos;s what <code className="text-xs bg-gray-100 px-1 py-0.5 rounded">public_accepting</code>
          means).
        </p>
        <p className="text-sm text-gray-700 leading-relaxed">
          You can revoke or change a delegation at any time from your Delegations page. The
          delegate is notified that you delegated; revoking is silent.
        </p>
      </section>

      {/* ----------------------------------------------------------------- */}
      {/* For prospective public delegates                                  */}
      {/* ----------------------------------------------------------------- */}
      <section className="bg-blue-50 border border-blue-200 rounded-xl p-6 space-y-3">
        <h2 className="text-lg font-semibold text-[var(--brand-primary)]">For prospective public delegates</h2>
        <p className="text-sm text-gray-700 leading-relaxed">
          Becoming a public delegate means publishing a per-org page that other members can read,
          delegate from, and hold you accountable to. It&apos;s opt-in, gradual, and reversible.
          Below is how to think about it.
        </p>
      </section>

      <section className="bg-white border border-gray-200 rounded-xl p-6 space-y-3">
        <h2 className="text-lg font-semibold text-[var(--brand-primary)]">The three per-topic visibility states</h2>
        <p className="text-sm text-gray-700 leading-relaxed">
          Visibility is set <em>per topic</em>, not per delegate. You can be private on schools,
          public on transportation, and public-accepting on housing, all at the same time. The
          three states mean:
        </p>
        <ul className="text-sm text-gray-700 leading-relaxed list-disc pl-6 space-y-2">
          <li>
            <strong><code className="text-xs bg-gray-100 px-1 py-0.5 rounded">private</code></strong>
            &mdash; default. No one else can see your bio, position statement, or rationale on
            votes for this topic. You can still vote and delegations to you (made through the
            regular delegation flow, with explicit consent) still work; the topic just isn&apos;t
            part of your public delegate identity.
          </li>
          <li>
            <strong><code className="text-xs bg-gray-100 px-1 py-0.5 rounded">public</code></strong>
            &mdash; transparent without invitation. Your bio, position statement, and any
            rationale on past votes for this topic are visible on your public page. <em>New</em>
            delegations are not invited from the browse page (people can still delegate to you via
            the regular flow if they know who you are). Use this for topics where you want your
            voting record to be readable without actively soliciting delegation.
          </li>
          <li>
            <strong><code className="text-xs bg-gray-100 px-1 py-0.5 rounded">public_accepting</code></strong>
            &mdash; transparent and accepting delegation. Same visibility as
            <code className="text-xs bg-gray-100 px-1 py-0.5 rounded">public</code>, plus a
            &ldquo;Delegate to me on this topic&rdquo; button on your page and inclusion in the
            org&apos;s delegate browse page. Some orgs require approval to set a topic to
            public_accepting; see &ldquo;Approval&rdquo; below.
          </li>
        </ul>
      </section>

      <section className="bg-white border border-gray-200 rounded-xl p-6 space-y-3">
        <h2 className="text-lg font-semibold text-[var(--brand-primary)]">The drafting flow and <code className="text-xs bg-gray-100 px-1 py-0.5 rounded">private_delegators</code></h2>
        <p className="text-sm text-gray-700 leading-relaxed">
          Your delegate page itself has an additional gate called <strong>page visibility</strong>
          that&apos;s independent of per-topic visibility. Three values:
        </p>
        <ul className="text-sm text-gray-700 leading-relaxed list-disc pl-6 space-y-2">
          <li>
            <strong><code className="text-xs bg-gray-100 px-1 py-0.5 rounded">private</code></strong>
            &mdash; only you can see your own page. This is the default when you first start
            drafting; nobody sees your work-in-progress.
          </li>
          <li>
            <strong><code className="text-xs bg-gray-100 px-1 py-0.5 rounded">private_delegators</code></strong>
            &mdash; intermediate state. Approved followers of yours <em>in this org</em> can see
            the page; nobody else. Useful for iterating with people who already trust you (people
            who&apos;ve made follow-based private delegations to you) before going fully public.
            The follow scoping uses the per-org follow relationships introduced in Phase 18 &mdash;
            a follower from a different org can&apos;t see this org&apos;s page just because
            they&apos;re your follower elsewhere.
          </li>
          <li>
            <strong><code className="text-xs bg-gray-100 px-1 py-0.5 rounded">public</code></strong>
            &mdash; this state is <em>derived</em>, not stored: as soon as any of your topics in
            this org is in <code className="text-xs bg-gray-100 px-1 py-0.5 rounded">public</code> or
            <code className="text-xs bg-gray-100 px-1 py-0.5 rounded">public_accepting</code>, your
            page is visible to anyone who can access the org. This is automatic; you don&apos;t toggle
            it directly. Drop all topics back to private and your page returns to whatever
            page-visibility setting you have.
          </li>
        </ul>
        <div className="bg-gray-50 rounded-lg p-4 mt-2">
          <p className="text-sm text-gray-600 leading-relaxed">
            <strong>Effective visibility</strong> is the lower of the two: page-visibility is the
            ceiling, per-topic visibility is the floor. If page-visibility is
            <code className="text-xs bg-white px-1 py-0.5 rounded">private</code> you stay invisible
            even if a topic is public-accepting. If page-visibility is
            <code className="text-xs bg-white px-1 py-0.5 rounded">private_delegators</code> and a
            topic is public, your followers see you (page-visibility ceiling holds) but anyone
            else doesn&apos;t.
          </p>
        </div>
      </section>

      <section className="bg-white border border-gray-200 rounded-xl p-6 space-y-3">
        <h2 className="text-lg font-semibold text-[var(--brand-primary)]">What an approval process feels like</h2>
        <p className="text-sm text-gray-700 leading-relaxed">
          Some orgs require approval before a topic transitions to
          <code className="text-xs bg-gray-100 px-1 py-0.5 rounded">public_accepting</code>. Others
          don&apos;t &mdash; you go straight from <code className="text-xs bg-gray-100 px-1 py-0.5 rounded">public</code> to
          <code className="text-xs bg-gray-100 px-1 py-0.5 rounded">public_accepting</code>. The
          org&apos;s setting determines which.
        </p>
        <p className="text-sm text-gray-700 leading-relaxed">
          When approval is required, the flow goes: you submit a request from your delegate-profile
          page; an approver (someone with the
          <code className="text-xs bg-gray-100 px-1 py-0.5 rounded">delegate_application.approve</code>
          permission &mdash; usually Stewards and Admins) is notified; they read your bio and position
          statement and either approve or deny with a comment. If denied, you can revise and
          resubmit. Becoming <code className="text-xs bg-gray-100 px-1 py-0.5 rounded">public</code>
          (without accepting) is always free &mdash; transparency about voting record never requires
          approval, only the act of inviting new delegations does.
        </p>
        <p className="text-sm text-gray-700 leading-relaxed">
          The transparent-only state (<code className="text-xs bg-gray-100 px-1 py-0.5 rounded">public</code>)
          is a useful intermediate &mdash; you can publish your reasoning publicly and demonstrate
          accountability without yet being approved to actively solicit delegation. Many delegates
          start there.
        </p>
      </section>

      <section className="bg-white border border-gray-200 rounded-xl p-6 space-y-3">
        <h2 className="text-lg font-semibold text-[var(--brand-primary)]">Expectations around rationale</h2>
        <p className="text-sm text-gray-700 leading-relaxed">
          Per-vote rationale is opt-in per vote &mdash; never required. When you cast a vote on a
          proposal, an inline composer lets you write a short explanation of your reasoning. If
          you fill it in, the rationale is public for any topic in
          <code className="text-xs bg-gray-100 px-1 py-0.5 rounded">public</code> or
          <code className="text-xs bg-gray-100 px-1 py-0.5 rounded">public_accepting</code> state.
          For private topics, rationale stays invisible just like the rest of your page on that
          topic.
        </p>
        <p className="text-sm text-gray-700 leading-relaxed">
          The norm we hope to encourage is &ldquo;rationale on the votes that mattered.&rdquo; You
          don&apos;t need to write something on every vote &mdash; some are obvious, some are
          procedural. But on the contested ones, a few sentences from you helps the people
          delegating to you understand what they&apos;re trusting, and helps anyone considering
          delegation see how you think.
        </p>
        <p className="text-sm text-gray-700 leading-relaxed">
          Rationale can be edited or deleted later from the proposal&apos;s vote section. Deleting
          rationale doesn&apos;t change your vote; only the explanation goes away.
        </p>
      </section>

      <section className="bg-white border border-amber-200 bg-amber-50/30 rounded-xl p-6 space-y-3">
        <h2 className="text-lg font-semibold text-[var(--brand-primary)]">Reverting a topic to <code className="text-sm bg-amber-100 px-1 py-0.5 rounded">private</code></h2>
        <p className="text-sm text-gray-700 leading-relaxed">
          Going back from <code className="text-xs bg-amber-100 px-1 py-0.5 rounded">public</code>
          or <code className="text-xs bg-amber-100 px-1 py-0.5 rounded">public_accepting</code> on a
          topic to <code className="text-xs bg-amber-100 px-1 py-0.5 rounded">private</code> is a
          load-bearing action with two distinct effects:
        </p>
        <ul className="text-sm text-gray-700 leading-relaxed list-disc pl-6 space-y-2">
          <li>
            <strong>Public-origin delegations on that topic are auto-revoked.</strong> If someone
            found you through the browse page and delegated to you on this topic, their delegation
            is cancelled when you revert to private. They&apos;re notified that the delegation
            ended because you stopped publicly accepting on that topic.
          </li>
          <li>
            <strong>Private-origin (follow-based) delegations are preserved.</strong> If someone
            delegated to you because they followed you (the trust-based delegation flow you
            approved person-by-person), that delegation is unaffected by your topic going private.
            Those delegations were never tied to your public-delegate status; they were tied to a
            specific approved follow relationship.
          </li>
          <li>
            <strong>Past rationale becomes invisible.</strong> Any rationale you wrote on past
            votes for this topic is hidden from the public delegate page. The data isn&apos;t
            deleted; if you raise the topic back to public, the rationale reappears. It&apos;s
            visibility-gated, not destroyed.
          </li>
        </ul>
        <p className="text-sm text-gray-700 leading-relaxed">
          The revert action is presented with a confirmation dialog that surfaces the named list of
          public-origin delegators who&apos;ll lose their delegation, so the consequence is visible
          before you commit.
        </p>
        <p className="text-sm text-gray-700 leading-relaxed">
          If you only want to stop accepting <em>new</em> public delegations without affecting
          existing ones, the soft-revert option is to go from
          <code className="text-xs bg-amber-100 px-1 py-0.5 rounded">public_accepting</code> back to
          <code className="text-xs bg-amber-100 px-1 py-0.5 rounded">public</code>. Existing
          public-origin delegations remain; the &ldquo;Delegate to me on this topic&rdquo; button is
          just removed from your page.
        </p>
      </section>

    </div>
  );
}

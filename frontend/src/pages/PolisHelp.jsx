import HelpBackLink from '../components/HelpBackLink';

/**
 * Phase 9 Session 4 — public help page for Polis (Decision 4 + spec).
 *
 * Route: /help/polis (public — no `ProtectedRoute` wrapping; mirrors
 * /help/voting-methods and /help/sustained-majority).
 *
 * Content covers:
 *   1. What Polis is (deliberation, distinct from voting).
 *   2. When to use it.
 *   3. The privacy framing (votes/statements visible to others; per-org
 *      pseudonym; platform can deanonymize for moderation).
 *   4. How linked Polises work.
 *   5. The 10:1 voter-to-commenter framing — most members only vote.
 */
export default function PolisHelp() {
  return (
    <div className="max-w-3xl mx-auto px-4 py-8 space-y-8">
      <div>
        {/* Phase 11 — help pages are public/non-org-scoped.
            Phase 15 G1 — back-link uses history.back() with /orgs fallback. */}
        <HelpBackLink />
        <h1 className="text-2xl font-bold text-[var(--brand-primary)]">About Polis Deliberations</h1>
        <p className="text-sm text-gray-500 mt-1">
          A structured way to surface where your group agrees and disagrees —
          before (or alongside) putting a question to a vote.
        </p>
      </div>

      {/* What it is */}
      <section className="bg-white border border-gray-200 rounded-xl p-6 space-y-3">
        <h2 className="text-lg font-semibold text-[var(--brand-primary)]">What is a Polis?</h2>
        <p className="text-sm text-gray-700 leading-relaxed">
          A Polis is an open conversation where members write short statements
          and vote agree / disagree / pass on the statements other members
          wrote. The Polis tool clusters participants by their voting patterns
          and surfaces statements that bridge the clusters — the ideas most
          people across different perspectives can support.
        </p>
        <p className="text-sm text-gray-700 leading-relaxed">
          It&apos;s a deliberation tool, not a voting method. A Polis doesn&apos;t
          decide anything on its own; it surfaces the shape of agreement so
          your org can write better proposals (or skip the proposal entirely
          when the conversation makes the answer obvious).
        </p>
      </section>

      {/* When to use */}
      <section className="bg-blue-50 border border-blue-200 rounded-xl p-6 space-y-3">
        <h2 className="text-lg font-semibold text-[var(--brand-primary)]">When should we use it?</h2>
        <p className="text-sm text-gray-700 leading-relaxed">
          For proposals where the org would benefit from gathering input or
          exploring consensus before voting. Some examples where it helps:
        </p>
        <ul className="text-sm text-gray-700 space-y-2 leading-relaxed list-disc pl-5">
          <li>
            <strong>Sense-making for big decisions</strong> — strategic
            direction, charter changes, hiring philosophy. Polises let
            you see <em>why</em> people are leaning the way they are.
          </li>
          <li>
            <strong>Many possible options</strong> — when there are dozens
            of plausible answers and you don&apos;t want to write a 12-option
            ranked-choice ballot. Members can suggest answers organically.
          </li>
          <li>
            <strong>Surfacing minority viewpoints</strong> — Polis weighs
            statements by how well they cross clusters, so good ideas held
            by small minorities have a path to visibility.
          </li>
        </ul>
        <p className="text-sm text-gray-500 leading-relaxed">
          You probably <em>don&apos;t</em> need a Polis to pick a meeting time or
          confirm a routine motion. Most decisions don&apos;t need structured
          deliberation.
        </p>
      </section>

      {/* Privacy framing */}
      <section className="bg-white border border-gray-200 rounded-xl p-6 space-y-3">
        <h2 className="text-lg font-semibold text-[var(--brand-primary)]">Privacy &amp; identity</h2>
        <p className="text-sm text-gray-700 leading-relaxed">
          Polises are different from proposal votes. <strong>Your votes and
          statements in a Polis are visible to other participants.</strong>
          They&apos;re tied to a per-org pseudonym, not your real name. When
          you participate, the platform creates an opaque random ID for you
          (your <code className="text-xs bg-gray-100 px-1 rounded">data-xid</code>);
          pol.is sees only that ID, not your username or email.
        </p>
        <p className="text-sm text-gray-700 leading-relaxed">
          The platform itself <strong>can</strong> identify who said what when
          needed for moderation — the mapping between your platform identity
          and your Polis pseudonym is stored on the platform side and used
          only when an admin needs to act on a moderation issue. Your
          participation is recorded for cross-session continuity (so the
          same dot keeps moving as you vote across visits).
        </p>
        <p className="text-sm text-gray-700 leading-relaxed">
          This is a different model from <strong>voting on proposals</strong>,
          which stays private by default — your individual proposal votes are
          not shown to other members, only the aggregate tallies and (when
          available) the anonymized vote-flow graph.
        </p>
      </section>

      {/* How linked Polises work */}
      <section className="bg-white border border-gray-200 rounded-xl p-6 space-y-3">
        <h2 className="text-lg font-semibold text-[var(--brand-primary)]">How linked Polises work</h2>
        <p className="text-sm text-gray-700 leading-relaxed">
          Proposals can reference Polises in two ways: pasting a pol.is URL
          into the proposal body, or attaching the Polis structurally via the
          proposal&apos;s create form. Either way, the proposal renders a
          card-style link card so voters notice the deliberation alongside
          the ballot.
        </p>
        <p className="text-sm text-gray-700 leading-relaxed">
          Polises live independently of any proposal lifecycle. A Polis can
          run for weeks before a proposal references it, stay open during
          voting, and continue gathering input after a proposal closes. The
          link is editorial — the proposal&apos;s tally is not influenced by
          Polis state.
        </p>
        <p className="text-sm text-gray-700 leading-relaxed">
          Some orgs require a linked Polis on every new proposal (an opt-in
          org setting). Most don&apos;t — the default is &quot;optional&quot;
          and individual proposal authors decide whether their proposal
          benefits from the structured deliberation.
        </p>
      </section>

      {/* What to do here */}
      <section className="bg-blue-50 border border-blue-200 rounded-xl p-6 space-y-3">
        <h2 className="text-lg font-semibold text-[var(--brand-primary)]">What should I do as a participant?</h2>
        <p className="text-sm text-gray-700 leading-relaxed">
          <strong>Most participants only vote on existing statements — you
          don&apos;t have to write your own.</strong> Successful Polises run
          at roughly a 10:1 voter-to-commenter ratio: ten people read and
          react for every one person who composes a new statement.
        </p>
        <ul className="text-sm text-gray-700 space-y-2 leading-relaxed list-disc pl-5">
          <li>Click <strong>Agree</strong> if you broadly agree with the statement.</li>
          <li>Click <strong>Disagree</strong> if you broadly disagree.</li>
          <li>Click <strong>Pass</strong> if the statement is unclear, off-topic, or you don&apos;t feel strongly.</li>
        </ul>
        <p className="text-sm text-gray-700 leading-relaxed">
          If a statement you&apos;d like to express isn&apos;t already there,
          you can add one — but only do this if the statement is novel and
          adds something the existing set doesn&apos;t already cover. Quality
          beats quantity for the clustering to surface useful patterns.
        </p>
      </section>
    </div>
  );
}

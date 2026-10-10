import HelpBackLink from '../components/HelpBackLink';
import { MajorityJudgmentExplanation } from '../components/VotingMethodSettings';
import { VOTING_METHOD_DESCRIPTIONS, METHOD_AVAILABILITY_FOOTER, SINGLE_WINNER_ELIGIBILITY, VOTER_WEIGHT_EXPLANATION } from '../utils/votingMethodDescriptions';

export default function VotingMethodsHelp() {
  return (
    <div className="max-w-3xl mx-auto px-4 py-8 space-y-8">
      <div>
        {/* Phase 11 — help pages are public/non-org-scoped.
            Phase 15 G1 — back-link uses history.back() with /orgs fallback. */}
        <HelpBackLink />
        <h1 className="text-2xl font-bold text-[var(--brand-primary)]">Voting Methods</h1>
        <p className="text-sm text-gray-500 mt-1">
          Understanding the different ways your organization can make decisions.
        </p>
      </div>

      <section className="bg-white border border-gray-200 rounded-xl p-5 space-y-5" aria-label="Voting method descriptions">
        {Object.entries(VOTING_METHOD_DESCRIPTIONS).map(([method, text]) => <div key={method} className="space-y-2">
          <h2 className="text-lg font-semibold text-[var(--brand-primary)]">{text.name}</h2>
          <p className="text-sm text-gray-700 leading-relaxed">{text.description}</p>
          {method === 'majority_judgment' && <MajorityJudgmentExplanation />}
        </div>)}
        <p className="text-sm text-gray-700">{VOTER_WEIGHT_EXPLANATION}</p>
        <p className="text-sm text-gray-700">{METHOD_AVAILABILITY_FOOTER}</p>
        <p className="text-sm text-gray-700">{SINGLE_WINNER_ELIGIBILITY}</p>
        <p className="text-sm text-gray-700">Design background: <a href="https://www.rangevoting.org/BalinskiLarakiPNASpdf.pdf" className="underline" target="_blank" rel="noreferrer">Balinski and Laraki</a>.</p>
      </section>

      <section id="majority-judgment" className="bg-white border border-gray-200 rounded-xl p-6 space-y-3">
        <h2 className="text-lg font-semibold">Majority Judgment — optional, single winner</h2>
        <p className="text-sm">Give each option one verbal grade: Reject, Poor, Acceptable, Good, Very good, or Excellent. You may give equal grades. These are ordered descriptions, not numeric points to total or average.</p>
        <p className="text-sm">The highest majority grade leads: the weighted median, using the lower middle grade when voting weight is even. If options tie, repeatedly remove one unit of their current median grades and compare again. The original grade distributions stay intact. Identical distributions use the committed draw order.</p>
        <p className="text-sm">Ungraded options receive Reject, including write-ins added later. Selecting a grade does not submit your ballot. Explicitly submit, change or retract while voting is permitted. An all-Reject or empty grade ballot counts as participation and overrides delegation; abstention also overrides delegation but contributes no grades to any distribution.</p>
        <p className="text-sm">No winner is produced if every grade is Reject, and quorum must be met. A live result requiring the draw cannot satisfy Stable Result Required. The final result reveals the seed used for any draw.</p>
        <p className="text-sm">Majority Judgment is off by default and requires organization opt-in. It applies to single-winner proposals and single-winner officeholder elections.</p>
      </section>
      <section id="ranked-pairs" className="bg-white border border-gray-200 rounded-xl p-6 space-y-3">
        <h2 className="text-lg font-semibold">Ranked Pairs — optional, single winner</h2>
        <p className="text-sm">Assign options to rank groups, with group 1 most preferred. Options in the same group are tied. Unranked options tie below all ranked options, including write-ins added after your vote. Use group menus and Move up/Move down buttons without dragging, then submit explicitly.</p>
        <p className="text-sm">Each pair of options is compared head to head using represented voting weight. A tied ranking favors neither option. Victories are considered by descending winning margin, then winning support, then committed option priority. Each victory is locked unless it would form a cycle. The winner has no incoming locked defeat; multiple such options use the committed draw order.</p>
        <p className="text-sm">This is the platform's fixed margins variant. Equal-strength edges may use the committed draw order, making live results provisional for Stable Result Required. The final result reveals the seed and records locked and skipped edges.</p>
        <p className="text-sm">An entirely unranked ballot counts as participation and overrides delegation. Explicit abstention also overrides delegation but contributes no preferences. Retracting restores normal delegation fallback. If no strict preference is expressed, there is no winner; quorum must also be met.</p>
        <p className="text-sm">Ranked Pairs is off by default and requires organization opt-in. It applies to single-winner proposals and single-winner officeholder elections. It does not use first-choice totals or IRV elimination.</p>
      </section>
      <section id="score" className="bg-white border border-gray-200 rounded-xl p-6 space-y-3">
        <h2 className="text-lg font-semibold">Score — optional, one or multiple winners</h2>
        <p className="text-sm">Rate each option from 0 to 5 points. Equal ratings are allowed. The option with the highest weighted total points wins. There is no runoff or five-star tiebreak.</p>
        <p className="text-sm">Unrated options receive zero, including later write-ins. Selecting a rating does not submit your ballot. Submit it explicitly; you may change or retract it while voting is permitted.</p>
        <p className="text-sm">A neutral all-zero ballot counts as participation and overrides delegation. Explicit abstention also overrides delegation but contributes no points. Retracting restores ordinary delegation fallback.</p>
        <p className="text-sm">Equal highest totals use the committed draw order, revealed at close. Live results relying on the draw cannot satisfy Stable Result Required. All-zero ballots produce no winner; quorum must also be met.</p>
        <p className="text-sm">Total points are not approval percentages. Score requires organization opt-in. Multiple winners require a separate permission: supported options with the highest total scores fill up to the requested places. Every ballot keeps its full influence for every selection; this does not provide proportional representation. Exact boundary ties use the committed priority, and zero total scores leave unfilled places. For elections, the entire selected set must pass installation checks before any office or bound-role access is granted.</p>
      </section>
      <section id="star" className="bg-white border border-gray-200 rounded-xl p-6 space-y-3">
        <h2 className="text-lg font-semibold">STAR — optional, single winner or Bloc STAR</h2>
        <p className="text-sm">Rate each option from 0 to 5 stars, allowing equal ratings. The two highest total scores reach an automatic runoff. Your ballot supports the finalist you rated higher; equal ratings support neither. A rating click is not a submitted vote.</p>
        <p className="text-sm">Unrated options receive zero, including write-ins added later. Organizations control early voting and write-ins. You can change a submitted ballot while voting is permitted. Delegation transfers one whole ballot, with each represented member’s own weight applied in both rounds.</p>
        <p className="text-sm">Abstention overrides delegation and counts for participation but contributes no ratings. An all-zero ballot is also participation; if every rating is zero, no winner is selected. Quorum applies, but the binary yes/no pass threshold does not.</p>
        <p className="text-sm">Score ties affecting finalists use preferences within the tied group, then five-star counts. Runoff ties use original total scores, then five-star counts. Remaining ties use a committed draw order, revealed with the final result. Live draw-dependent results cannot satisfy Stable Result Required.</p>
        <p className="text-sm">STAR is off by default and must be enabled in organization settings. For multiple winners, a separate Bloc STAR permission enables repeated scoring and automatic runoffs. The selected winner is removed, and every ballot retains its original full weight for the next round. This does not provide proportional representation. A single remaining supported option is selected without a competitive runoff; zero-score options leave vacancies. Each round is preserved in results.</p>
      </section>

      {/* Binary */}
      <section className="bg-white border border-gray-200 rounded-xl p-6 space-y-3">
        <h2 className="text-lg font-semibold text-[var(--brand-primary)]">Binary Voting (Yes / No / Abstain)</h2>
        <p className="text-sm text-gray-700 leading-relaxed">
          The simplest form of voting. Each member votes Yes, No, or Abstain on a single question.
          A proposal passes if it meets both the quorum threshold (enough people voted) and the pass
          threshold (enough Yes votes among those who voted Yes or No).
        </p>
        <p className="text-sm text-gray-500">
          <strong>Best for:</strong> Simple decisions with a clear accept/reject framing. Policy approvals,
          budget sign-offs, membership decisions.
        </p>
      </section>

      {/* Approval */}
      <section className="bg-white border border-gray-200 rounded-xl p-6 space-y-3">
        <h2 className="text-lg font-semibold text-[var(--brand-primary)]">Approval Voting</h2>
        <p className="text-sm text-gray-700 leading-relaxed">
          Each member can approve as many options as they like. The option with the most approvals wins.
          This is great for picking from a list of alternatives where voters might genuinely support
          more than one choice.
        </p>

        <div className="bg-gray-50 rounded-lg p-4 space-y-2">
          <p className="text-sm font-medium text-gray-700">How it works:</p>
          <ol className="text-sm text-gray-600 list-decimal list-inside space-y-1">
            <li>A proposal is created with 2 or more options.</li>
            <li>Each voter checks the boxes next to every option they support.</li>
            <li>Submitting with no boxes checked counts as an abstention (you'll be asked to confirm).</li>
            <li>The option with the most approvals wins.</li>
            <li>If two or more options tie for the most approvals, the org&apos;s configured tie-resolution method runs automatically (see Tie Resolution below).</li>
          </ol>
        </div>

        <div className="bg-blue-50 rounded-lg p-4">
          <p className="text-sm text-blue-800">
            <strong>Delegation:</strong> If you've delegated your vote, your delegate's entire approval
            set becomes your vote. If your delegate approved Options A and C, that's your ballot too.
            If your delegate hasn't voted yet, your chain behavior setting (accept sub-delegate, revert
            to direct, or abstain) kicks in &mdash; just like binary voting.
          </p>
        </div>

        <p className="text-sm text-gray-500">
          <strong>Best for:</strong> Choosing from a list of alternatives. Picking event venues, selecting
          committee members, naming decisions, choosing among multiple policy options.
        </p>
      </section>

      {/* Ranked-Choice */}
      <section className="bg-white border border-gray-200 rounded-xl p-6 space-y-3">
        <h2 className="text-lg font-semibold text-[var(--brand-primary)]">Ranked-Choice Voting (IRV)</h2>
        <p className="text-sm text-gray-700 leading-relaxed">
          Voters rank the options in order of preference. The system runs an instant runoff: if no option
          has a majority of first-place votes, the option with the fewest first-place votes is eliminated,
          and ballots that ranked it first transfer to their next preference. This repeats until one option
          has a majority.
        </p>

        <div className="bg-gray-50 rounded-lg p-4 space-y-2">
          <p className="text-sm font-medium text-gray-700">How elimination works:</p>
          <ol className="text-sm text-gray-600 list-decimal list-inside space-y-1">
            <li>Each voter ranks options. They can rank some, all, or none.</li>
            <li>Round 1: count first-place votes only. If anything has a majority, that option wins.</li>
            <li>If not, the option with the fewest votes is eliminated.</li>
            <li>Ballots that ranked the eliminated option first move to their next-ranked option.</li>
            <li>Repeat until one option has more than half of the still-counted ballots.</li>
            <li>If a voter's ranked options all get eliminated, their ballot is exhausted &mdash; it stops counting in subsequent rounds.</li>
          </ol>
        </div>

        <h3 className="text-base font-semibold text-[var(--brand-primary)] mt-2">Single Transferable Vote (STV)</h3>
        <p className="text-sm text-gray-700 leading-relaxed">
          STV is the multi-winner extension of ranked-choice. When a proposal needs to elect more than
          one option (e.g., picking 3 board members from 7 candidates), STV uses the same ranked ballot
          but adds <em>surplus transfer</em>: when an option clears the win threshold by more votes than
          it needs, the excess transfers proportionally to those voters' next preferences. This gives
          minority preference groups a fair share of the seats &mdash; that's the proportional
          representation effect.
        </p>
        <p className="text-sm text-gray-500">
          <strong>When to use STV:</strong> Multi-seat elections where you want different preference
          groups represented (committee elections, multi-winner endorsements, slate selection).
        </p>

        <div className="bg-blue-50 rounded-lg p-4 space-y-2">
          <p className="text-sm text-blue-800">
            <strong>Delegation for ranked ballots:</strong> If you've delegated your vote, you inherit
            your delegate's full ranking. If your delegate ranked options B → D → A, that becomes your
            ballot too. If your delegate ranked only some options (a partial ranking), you inherit it
            as-is &mdash; not ranking C and E was a deliberate choice on their part.
          </p>
          <p className="text-sm text-blue-800 mt-1">
            Ranked-choice currently supports only <strong>strict-precedence</strong> delegation. If
            you've configured a different strategy (majority-of-delegates, weighted-majority), it falls
            back to strict-precedence for ranked-choice proposals: your highest-priority matching topic's
            delegate wins.
          </p>
        </div>

        <div className="bg-gray-50 rounded-lg p-4 space-y-2">
          <p className="text-sm font-medium text-gray-700">Partial rankings &amp; abstentions:</p>
          <ul className="text-sm text-gray-600 list-disc list-inside space-y-1">
            <li><strong>Partial ranking:</strong> ranking only some options is a deliberate choice. The unranked options never get any of your support, even after eliminations.</li>
            <li><strong>Empty ranking:</strong> ranking nothing counts as an abstention. You'll be asked to confirm before submitting.</li>
            <li><strong>Ballot exhaustion:</strong> if all your ranked options are eliminated, your ballot stops counting in later rounds.</li>
          </ul>
        </div>

        <div className="bg-amber-50 rounded-lg p-4">
          <p className="text-sm text-amber-800">
            <strong>Tied final round:</strong> if elimination ends with two or more options tied for the
            last winner slot, the org&apos;s configured tie-resolution method runs automatically (see
            Tie Resolution below). The chosen method, the tied set, and the resolved winner are all
            recorded with the proposal as a verifiable audit trail.
          </p>
        </div>

        <div className="bg-gray-50 rounded-lg p-4 space-y-2">
          <p className="text-sm font-medium text-gray-700">Reading the Elimination Flow chart:</p>
          <p className="text-sm text-gray-600 leading-relaxed">
            The Sankey chart on RCV/STV proposals visualizes round-by-round elimination as flowing
            slabs. Each column is one round; each option's slab is sized by its current vote count.
            Solid links between columns show votes carried forward to the same option; dashed links
            show transfers from an eliminated option to others. Hover any slab or flow to see exact
            counts. STV winners are highlighted in the final column.
          </p>
          <p className="text-sm text-gray-600 leading-relaxed">
            STV transfers can be surpluses (a winner's overflow ballots redistributing fractionally)
            or eliminations (a losing option's ballots redistributing whole). Hover any flow line to
            see which.
          </p>
        </div>

        <p className="text-sm text-gray-500">
          <strong>Best for IRV:</strong> Single-winner choices where preference matters &mdash;
          picking a venue, choosing a chair, settling between competing proposals.{' '}
          <strong>Best for STV:</strong> Multi-winner elections where proportional representation is
          desirable &mdash; committees, boards, multi-seat slates.
        </p>
      </section>

      {/* Budget voting */}
      <section className="bg-white border border-gray-200 rounded-xl p-6 space-y-3">
        <h2 className="text-lg font-semibold text-[var(--brand-primary)]">Budget Voting</h2>
        <p className="text-sm text-gray-700 leading-relaxed">
          Budget voting decides how to spend a fixed pot of money. In
          allocation mode, each voter distributes the budget across
          continuously-fundable buckets, and the group result is the per-bucket
          median of what everyone allocated. In project mode, each voter ranks
          the projects they want funded, and the group funds them in priority
          order up to its chosen spend level.
        </p>

        <div className="bg-blue-50 rounded-lg p-4">
          <p className="text-sm text-blue-800">
            <strong>Delegation:</strong> Delegation works for budget votes the
            same way it does for every other method. If you've delegated the
            proposal's topic, your delegate's allocation or project ranking
            becomes your ballot, counted once for you. If your delegate hasn't
            voted, your chain behavior setting applies. You can always override
            by allocating or ranking directly.
          </p>
        </div>

        <p className="text-sm text-gray-700 leading-relaxed">
          In a weighted-voting organization, budget votes aggregate by weighted
          median instead of a plain one: each voter's allocation or ranking
          counts for their number of shares, so the result sits where half the
          shares fall rather than half the voters. Delegation carries shares into
          budget votes just as it does for other methods &mdash; a delegate's
          budget influence is their own shares plus their delegators'.
        </p>

        <p className="text-sm text-gray-500">
          <strong>Best for:</strong> Participatory budgeting &mdash; dividing an
          operating budget across programs, choosing which capital projects to
          fund, prioritizing spending among competing needs.
        </p>
      </section>

      {/* Phase 17 F3 — Tie Resolution help section.
          Ties are auto-resolved at advance-to-passed time using the org's
          configured method. Each method has a different tradeoff; this
          section documents the four options stewards can pick from in
          Org Settings. */}
      <section className="bg-white border border-gray-200 rounded-xl p-6 space-y-3">
        <h2 className="text-lg font-semibold text-[var(--brand-primary)]">Tie Resolution</h2>
        <p className="text-sm text-gray-700 leading-relaxed">
          Ties are uncomfortable to resolve in the moment. Declaring how
          you&apos;ll handle them up-front makes the result less controversial
          and removes the appearance of admin discretion. Each organization
          picks one method per voting method (Approval, Ranked-Choice / STV);
          when a proposal closes with a tie, the configured method runs
          automatically and the resolution is recorded as part of the result.
        </p>

        <div className="bg-gray-50 rounded-lg p-4 space-y-3">
          <p className="text-sm font-medium text-gray-700">The four methods:</p>

          <div>
            <p className="text-sm font-semibold text-gray-700">Broader approval base <span className="text-xs font-normal text-gray-500">(approval voting only)</span></p>
            <p className="text-sm text-gray-600 leading-relaxed mt-0.5">
              Among the tied options, the one co-approved alongside the most
              other options across all ballots wins. Use this when &ldquo;most
              broadly acceptable option&rdquo; is the right tiebreaker &mdash;
              the result is the option voters were most willing to support
              alongside other choices, not just the option with the most
              standalone support.
            </p>
          </div>

          <div>
            <p className="text-sm font-semibold text-gray-700">Expand winners</p>
            <p className="text-sm text-gray-600 leading-relaxed mt-0.5">
              All tied options become winners. Choose this when your org would
              rather have a bigger winner set than force a single choice. Note:
              with <code>num_winners=1</code> IRV proposals, this can produce
              multiple winners &mdash; pick a different method if you need
              exactly one.
            </p>
          </div>

          <div>
            <p className="text-sm font-semibold text-gray-700">Earliest decisive vote</p>
            <p className="text-sm text-gray-600 leading-relaxed mt-0.5">
              The tied option whose support reached its final count earliest
              wins. Rewards momentum without rewarding &ldquo;voted first
              overall&rdquo; &mdash; what matters is when each tied option
              <em> last </em>incremented to its tied total, not when the first
              ballot was cast.
            </p>
          </div>

          <div>
            <p className="text-sm font-semibold text-gray-700">Random with seed</p>
            <p className="text-sm text-gray-600 leading-relaxed mt-0.5">
              A deterministic random selection seeded by the proposal&apos;s ID
              and end time. Anyone can compute the hash and confirm the result
              independently. The seed and the tied set are recorded with the
              proposal so the choice is verifiable after the fact.
            </p>
          </div>
        </div>

        <div className="bg-blue-50 rounded-lg p-4">
          <p className="text-sm text-blue-800">
            <strong>How to configure:</strong> stewards and admins with
            &ldquo;Edit organization settings&rdquo; permission set the
            tie-resolution method per voting method in{' '}
            <span className="font-medium">Org Settings &rarr; Tie Resolution</span>.
            Sub-orgs inherit the parent org&apos;s setting.
          </p>
        </div>
      </section>
    </div>
  );
}

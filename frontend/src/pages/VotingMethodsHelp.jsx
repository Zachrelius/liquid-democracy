import { Link } from 'react-router-dom';

export default function VotingMethodsHelp() {
  return (
    <div className="max-w-3xl mx-auto px-4 py-8 space-y-8">
      <div>
        <Link to="/proposals" className="text-sm text-[#2E75B6] hover:underline mb-4 inline-block">
          ← Back to Proposals
        </Link>
        <h1 className="text-2xl font-bold text-[#1B3A5C]">Voting Methods</h1>
        <p className="text-sm text-gray-500 mt-1">
          Understanding the different ways your organization can make decisions.
        </p>
      </div>

      {/* Decision guide */}
      <section className="bg-blue-50 border border-blue-200 rounded-xl p-6 space-y-3">
        <h2 className="text-lg font-semibold text-[#1B3A5C]">Which method should I pick?</h2>
        <ul className="text-sm text-gray-700 space-y-2 leading-relaxed">
          <li>
            <strong>Simple yes/no question</strong> &mdash; use{' '}
            <span className="font-medium text-[#1B3A5C]">Binary</span>. Policy approvals, charter changes,
            anything with a clean accept/reject framing.
          </li>
          <li>
            <strong>Multiple options where any combination could be acceptable</strong> &mdash; use{' '}
            <span className="font-medium text-[#1B3A5C]">Approval</span>. Voters tick every option they
            could live with; the most-approved option wins.
          </li>
          <li>
            <strong>One winner from a slate, want majority preference</strong> &mdash; use{' '}
            <span className="font-medium text-[#1B3A5C]">Ranked-Choice (IRV)</span>. Voters rank options
            in order; lowest-ranked options are eliminated until one has majority support.
          </li>
          <li>
            <strong>Multiple winners from a slate, want proportional representation</strong> &mdash; use{' '}
            <span className="font-medium text-[#1B3A5C]">Single Transferable Vote (STV)</span>. Picks N
            winners while reflecting different preference groups in the body.
          </li>
        </ul>
      </section>

      {/* Binary */}
      <section className="bg-white border border-gray-200 rounded-xl p-6 space-y-3">
        <h2 className="text-lg font-semibold text-[#1B3A5C]">Binary Voting (Yes / No / Abstain)</h2>
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
        <h2 className="text-lg font-semibold text-[#1B3A5C]">Approval Voting</h2>
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
            <li>If two or more options tie for the most approvals, an admin resolves the tie.</li>
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
        <h2 className="text-lg font-semibold text-[#1B3A5C]">Ranked-Choice Voting (IRV)</h2>
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

        <h3 className="text-base font-semibold text-[#1B3A5C] mt-2">Single Transferable Vote (STV)</h3>
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
            last winner slot, the result is flagged as <em>tied</em>. An admin can then pick one of the
            tied finalists to break the tie. The selection is recorded with an audit trail.
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
        </div>

        <p className="text-sm text-gray-500">
          <strong>Best for IRV:</strong> Single-winner choices where preference matters &mdash;
          picking a venue, choosing a chair, settling between competing proposals.{' '}
          <strong>Best for STV:</strong> Multi-winner elections where proportional representation is
          desirable &mdash; committees, boards, multi-seat slates.
        </p>
      </section>
    </div>
  );
}

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
            to direct, or abstain) kicks in — just like binary voting.
          </p>
        </div>

        <p className="text-sm text-gray-500">
          <strong>Best for:</strong> Choosing from a list of alternatives. Picking event venues, selecting
          committee members, naming decisions, choosing among multiple policy options.
        </p>
      </section>

      {/* Ranked Choice (coming soon) */}
      <section className="bg-white border border-gray-200 rounded-xl p-6 space-y-3 opacity-75">
        <h2 className="text-lg font-semibold text-gray-400">Ranked Choice Voting (Coming Soon)</h2>
        <p className="text-sm text-gray-500 leading-relaxed">
          Voters rank the options in order of preference. Options are eliminated in rounds
          until one has a majority. This method will be available in a future update.
        </p>
      </section>
    </div>
  );
}

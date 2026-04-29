const STYLES = {
  draft:        'bg-gray-100 text-gray-600',
  deliberation: 'bg-blue-100 text-blue-700',
  voting:       'bg-amber-100 text-amber-700',
  passed:       'bg-green-100 text-green-700',
  failed:       'bg-red-100 text-red-700',
  withdrawn:    'bg-gray-100 text-gray-500',
  unresolved:   'bg-yellow-100 text-yellow-800 border border-yellow-300',
};

const LABELS = {
  draft:        'Draft',
  deliberation: 'Deliberation',
  voting:       'Voting',
  passed:       'Passed',
  failed:       'Failed',
  withdrawn:    'Withdrawn',
  unresolved:   'Awaiting Review',
};

// Phase 7D — multi-option closed proposals (approval / RCV / STV) show a
// neutral "Decided" badge instead of "Passed"/"Failed" because the binary
// pass/fail framing doesn't describe the outcome (the winner name carries
// the decision content on the card body).
const DECIDED_STYLE = 'bg-blue-100 text-blue-700';

export default function StatusBadge({ status, votingMethod }) {
  const isMultiOption =
    votingMethod && votingMethod !== 'binary' &&
    (status === 'passed' || status === 'failed');

  if (isMultiOption) {
    return (
      <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${DECIDED_STYLE}`}>
        Decided
      </span>
    );
  }

  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${STYLES[status] || STYLES.draft}`}>
      {LABELS[status] || status}
    </span>
  );
}

const STYLES = {
  draft:        'bg-gray-100 text-gray-600',
  deliberation: 'bg-blue-100 text-blue-700',
  voting:       'bg-amber-100 text-amber-700',
  passed:       'bg-green-100 text-green-700',
  failed:       'bg-red-100 text-red-700',
  withdrawn:    'bg-gray-100 text-gray-500',
};

const LABELS = {
  draft:        'Draft',
  deliberation: 'Deliberation',
  voting:       'Voting',
  passed:       'Passed',
  failed:       'Failed',
  withdrawn:    'Withdrawn',
};

export default function StatusBadge({ status }) {
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${STYLES[status] || STYLES.draft}`}>
      {LABELS[status] || status}
    </span>
  );
}

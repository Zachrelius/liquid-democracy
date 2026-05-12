export default function TopicBadge({ topic, relevance }) {
  const color = topic?.color || '#6366f1';
  const displayName = topic?.description?.trim() || topic?.name;
  const label = relevance != null && relevance < 1.0
    ? `${displayName} (${Math.round(relevance * 100)}%)`
    : displayName;

  return (
    <span
      className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium text-white"
      style={{ backgroundColor: color }}
    >
      {label}
    </span>
  );
}

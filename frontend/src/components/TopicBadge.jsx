import { contrastTextColor } from '../utils/colorContrast';

export default function TopicBadge({ topic, relevance }) {
  const color = topic?.color || '#6366f1';
  // Phase 30.1 B5 — Topic.name is now scoped per-org and display-safe;
  // the legacy description?.trim() fallback is no longer needed.
  const displayName = topic?.name;
  const label = relevance != null && relevance < 1.0
    ? `${displayName} (${Math.round(relevance * 100)}%)`
    : displayName;

  return (
    <span
      className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium"
      style={{ backgroundColor: color, color: contrastTextColor(color) }}
    >
      {label}
    </span>
  );
}

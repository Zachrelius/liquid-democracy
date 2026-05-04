// Phase 12.8 audit Tier 1, Item 4 — consolidated relative-time helper
// previously duplicated in Comment.jsx, FollowRequests.jsx, DelegateModal.jsx.
// The Comment.jsx variant was the most complete (just-now + 30d-fallback)
// and is preserved as the canonical shape; the other two now use this.

export function timeAgo(dateStr) {
  if (!dateStr) return '';
  const ms = Date.now() - new Date(dateStr).getTime();
  if (ms < 60_000) return 'just now';
  const mins = Math.floor(ms / 60_000);
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days}d ago`;
  // Older than ~a month — show the date instead of "60d ago"
  return new Date(dateStr).toLocaleDateString();
}

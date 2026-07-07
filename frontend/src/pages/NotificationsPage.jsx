import { useState, useEffect, useCallback, useMemo } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import api from '../api';
import { timeAgo } from '../utils/timeAgo';
import { formatNotification, notificationHref } from '../utils/formatNotification';
import { useToast } from '../components/Toast';

/**
 * Phase 13 F2 — full notifications page at /notifications.
 *
 * Account-scoped (NOT org-scoped — registered as a top-level route in
 * App.jsx, wrapped in OrgProvider+Layout but not OrgScopedLayout, mirroring
 * /settings).
 *
 * Layout:
 * - Header: title + "Mark all as read" + a link to preferences.
 * - Filter chips: All / Unread / and one chip per category mapped to the
 *   five backend EVENT_REGISTRY categories. Filters are applied
 *   client-side; the backend feed endpoint doesn't support category
 *   filtering at v1 (the per-user volume is small enough that client-side
 *   suffices).
 * - List grouped by date (Today / Yesterday / This week / Older). Each row
 *   shows the formatted text, relative time, an icon for read state, and a
 *   "Mark unread" toggle when read.
 * - Pagination via offset; "Load more" button at the bottom uses
 *   ?limit=20&offset=N.
 *
 * Routing per Item 22: clicking a row uses notificationHref(notif), which
 * uses notif.org_slug exclusively. No first-parent-org fallback.
 */

const FILTERS = [
  { key: 'all', label: 'All' },
  { key: 'unread', label: 'Unread' },
  { key: 'Comments', label: 'Comments' },
  { key: 'Proposals', label: 'Proposals' },
  { key: 'Membership', label: 'Membership' },
  { key: 'Delegation', label: 'Delegation' },
  { key: 'Polis', label: 'Polis' },
];

// Mirror of the backend EVENT_REGISTRY category mapping. Kept here so the
// filter chips can group events without an extra fetch (the registry is
// also fetched on the preferences page; the client carries 12 entries).
const EVENT_TYPE_CATEGORY = {
  'comment.replied': 'Comments',
  'comment.posted_on_your_proposal': 'Comments',
  'proposal.entered_voting': 'Proposals',
  'proposal.closed': 'Proposals',
  // Phase 20 — replaces the retired sustained_majority.floor_approached.
  'proposal.extended_by_stability': 'Proposals',
  'member.join_request': 'Membership',
  'invitation.accepted': 'Membership',
  'shares.received': 'Membership',
  'delegate.applied': 'Delegation',
  'delegate.application_decided': 'Delegation',
  'follow.requested': 'Delegation',
  'follow.approved': 'Delegation',
  'polis.created': 'Polis',
};

const PAGE_SIZE = 20;

function startOfDay(d) {
  const x = new Date(d);
  x.setHours(0, 0, 0, 0);
  return x;
}

/**
 * Group notifications into date buckets relative to "now."
 *  - Today: same calendar date as now
 *  - Yesterday: one day prior
 *  - This week: within the last 7 days (and not today/yesterday)
 *  - Older: anything beyond
 *
 * Buckets are returned in display order; empty buckets are omitted.
 */
function groupByDate(notifs) {
  const now = new Date();
  const todayStart = startOfDay(now);
  const yesterdayStart = new Date(todayStart);
  yesterdayStart.setDate(yesterdayStart.getDate() - 1);
  const weekStart = new Date(todayStart);
  weekStart.setDate(weekStart.getDate() - 7);

  const buckets = { Today: [], Yesterday: [], 'This week': [], Older: [] };
  for (const n of notifs) {
    const ts = new Date(n.created_at);
    if (ts >= todayStart) buckets.Today.push(n);
    else if (ts >= yesterdayStart) buckets.Yesterday.push(n);
    else if (ts >= weekStart) buckets['This week'].push(n);
    else buckets.Older.push(n);
  }
  return ['Today', 'Yesterday', 'This week', 'Older']
    .map(label => ({ label, items: buckets[label] }))
    .filter(b => b.items.length > 0);
}

export default function NotificationsPage() {
  const navigate = useNavigate();
  const toast = useToast();
  const [items, setItems] = useState([]);
  const [hasMore, setHasMore] = useState(false);
  const [offset, setOffset] = useState(0);
  const [filter, setFilter] = useState('all');
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);

  const loadFirstPage = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.get(`/api/notifications?limit=${PAGE_SIZE}&offset=0`);
      setItems(Array.isArray(res?.items) ? res.items : []);
      setHasMore(!!res?.has_more);
      setOffset(PAGE_SIZE);
    } catch (e) {
      toast.error(e.message || 'Could not load notifications');
      setItems([]);
      setHasMore(false);
    } finally {
      setLoading(false);
    }
  }, [toast]);

  useEffect(() => { loadFirstPage(); }, [loadFirstPage]);

  async function handleLoadMore() {
    if (loadingMore || !hasMore) return;
    setLoadingMore(true);
    try {
      const res = await api.get(`/api/notifications?limit=${PAGE_SIZE}&offset=${offset}`);
      const more = Array.isArray(res?.items) ? res.items : [];
      setItems(prev => [...prev, ...more]);
      setHasMore(!!res?.has_more);
      setOffset(o => o + PAGE_SIZE);
    } catch (e) {
      toast.error(e.message || 'Could not load more notifications');
    } finally {
      setLoadingMore(false);
    }
  }

  async function handleMarkAllRead() {
    try {
      const res = await api.post('/api/notifications/mark-all-read', {});
      const now = new Date().toISOString();
      setItems(prev => prev.map(n => n.read_at ? n : { ...n, read_at: now }));
      toast.success(`Marked ${res?.marked ?? 0} as read`);
    } catch (e) {
      toast.error(e.message || 'Could not mark all as read');
    }
  }

  async function handleRowClick(notif) {
    const href = notificationHref(notif);
    if (!notif.read_at) {
      // Optimistically mark read so the visual state updates instantly.
      setItems(prev =>
        prev.map(n => n.id === notif.id ? { ...n, read_at: new Date().toISOString() } : n)
      );
      try { await api.post(`/api/notifications/${notif.id}/read`); } catch { /* soft-fail */ }
    }
    navigate(href);
  }

  async function handleToggleRead(notif, e) {
    e.stopPropagation();
    if (notif.read_at) {
      // Currently no backend "mark unread" endpoint; the spec lists the
      // toggle in the UI but we can only clear it client-side until/unless
      // the backend grows the endpoint. Keep the surface consistent: clear
      // the local read_at and warn via toast.
      setItems(prev =>
        prev.map(n => n.id === notif.id ? { ...n, read_at: null } : n)
      );
      toast.info('Marked unread on this device');
      return;
    }
    setItems(prev =>
      prev.map(n => n.id === notif.id ? { ...n, read_at: new Date().toISOString() } : n)
    );
    try { await api.post(`/api/notifications/${notif.id}/read`); } catch { /* soft-fail */ }
  }

  const filtered = useMemo(() => {
    if (filter === 'all') return items;
    if (filter === 'unread') return items.filter(n => !n.read_at);
    return items.filter(n => EVENT_TYPE_CATEGORY[n.event_type] === filter);
  }, [items, filter]);

  const grouped = useMemo(() => groupByDate(filtered), [filtered]);

  return (
    <div className="max-w-3xl mx-auto px-4 py-8 space-y-6">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <h1 className="text-2xl font-semibold text-[var(--brand-primary)]">Notifications</h1>
        <div className="flex items-center gap-3">
          <Link
            to="/settings/notifications"
            className="text-xs text-[var(--brand-accent)] hover:underline"
          >
            Preferences
          </Link>
          <button
            onClick={handleMarkAllRead}
            className="text-sm px-3 py-1.5 border border-gray-300 text-gray-700 rounded-lg hover:bg-gray-50 transition-colors"
          >
            Mark all as read
          </button>
        </div>
      </div>

      {/* Filter chips */}
      <div className="flex items-center gap-2 flex-wrap">
        {FILTERS.map(f => (
          <button
            key={f.key}
            onClick={() => setFilter(f.key)}
            className={`text-xs px-3 py-1.5 rounded-full border transition-colors ${
              filter === f.key
                ? 'bg-[var(--brand-primary)] text-white border-[var(--brand-primary)]'
                : 'bg-white text-gray-700 border-gray-300 hover:bg-gray-50'
            }`}
          >
            {f.label}
          </button>
        ))}
      </div>

      {loading ? (
        <div className="flex justify-center py-12">
          <div className="animate-spin w-6 h-6 border-2 border-[var(--brand-accent)] border-t-transparent rounded-full" />
        </div>
      ) : grouped.length === 0 ? (
        <div className="bg-white border border-gray-200 rounded-xl p-8 text-center text-sm text-gray-400">
          {filter === 'all'
            ? 'No notifications yet. Visit '
            : 'Nothing to show for this filter. Try '}
          <Link to="/settings/notifications" className="text-[var(--brand-accent)] hover:underline">
            preferences
          </Link>
          {filter === 'all' ? ' to choose what you want to be notified about.' : ' a different filter.'}
        </div>
      ) : (
        <div className="space-y-6">
          {grouped.map(bucket => (
            <section key={bucket.label} className="space-y-2">
              <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-wide">
                {bucket.label}
              </h2>
              <ul className="bg-white border border-gray-200 rounded-xl divide-y divide-gray-100">
                {bucket.items.map(notif => {
                  const isRead = !!notif.read_at;
                  return (
                    <li key={notif.id}>
                      <div
                        onClick={() => handleRowClick(notif)}
                        className={`flex items-start justify-between gap-3 px-4 py-3 cursor-pointer hover:bg-gray-50 transition-colors ${
                          isRead ? 'opacity-60' : ''
                        }`}
                      >
                        <div className="flex-1 min-w-0">
                          <p className={`text-sm ${isRead ? 'text-gray-500' : 'text-gray-800 font-medium'}`}>
                            {formatNotification(notif)}
                          </p>
                          <p className="text-xs text-gray-400 mt-0.5">
                            {timeAgo(notif.created_at)}
                          </p>
                        </div>
                        <button
                          onClick={(e) => handleToggleRead(notif, e)}
                          className="text-xs text-[var(--brand-accent)] hover:underline shrink-0"
                        >
                          {isRead ? 'Mark unread' : 'Mark read'}
                        </button>
                      </div>
                    </li>
                  );
                })}
              </ul>
            </section>
          ))}

          {hasMore && (
            <div className="flex justify-center">
              <button
                onClick={handleLoadMore}
                disabled={loadingMore}
                className="text-sm px-4 py-2 border border-gray-300 text-gray-700 rounded-lg hover:bg-gray-50 transition-colors disabled:opacity-50"
              >
                {loadingMore ? 'Loading…' : 'Load more'}
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

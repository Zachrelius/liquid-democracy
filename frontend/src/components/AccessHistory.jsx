import { useState, useEffect, useCallback } from 'react';
import api from '../api';

/**
 * AccessHistory — Phase 7.5 user-facing data access log.
 *
 * Renders entries returned by GET /api/users/me/access-log, which lists times
 * other users, organization admins, or platform admins have viewed the current
 * user's data (e.g., elevated audit-ballot views, system-wide delegation graph
 * views, user list views, profile views).
 *
 * Entry shape (from backend AccessLogEntry):
 *   {
 *     timestamp: ISO8601 string,
 *     accessor_id: string | null,
 *     accessor_display_name: string,
 *     accessor_role: string,    // "Platform admin" | "Org admin of {Name}" | "User"
 *     action_type: string,      // human-readable, e.g., "Viewed your ballot"
 *     reason: string | null,
 *     ip_address: string | null,
 *   }
 *
 * Note: ip_address is intentionally not rendered (per spec, hidden in display by
 * default). A future polish pass may add an "expand for details" UX.
 */

const PAGE_SIZE = 20;

function AccessLogRow({ entry }) {
  const ts = entry.timestamp ? new Date(entry.timestamp) : null;
  // Use locale string for full timestamp (date + time) — matches the
  // user expectation of "when did this happen?" rather than just date.
  const tsLabel = ts ? ts.toLocaleString() : '';

  return (
    <li className="py-3 first:pt-0 last:pb-0">
      <div className="flex items-baseline justify-between gap-3 flex-wrap">
        <p className="text-sm text-gray-700">
          <span className="font-medium">{entry.accessor_display_name}</span>
          {entry.accessor_role && (
            <span className="ml-1.5 text-xs text-gray-400">
              ({entry.accessor_role})
            </span>
          )}
        </p>
        <span className="text-xs text-gray-400 whitespace-nowrap">{tsLabel}</span>
      </div>
      <p className="text-sm text-gray-600 mt-0.5">{entry.action_type}</p>
      {entry.reason && (
        <p className="text-xs text-gray-400 mt-0.5 italic">
          Reason: {entry.reason}
        </p>
      )}
    </li>
  );
}

export default function AccessHistory() {
  const [entries, setEntries] = useState([]);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState(null);
  const [hasMore, setHasMore] = useState(false);
  const [offset, setOffset] = useState(0);

  const fetchPage = useCallback(async (nextOffset, append) => {
    if (append) {
      setLoadingMore(true);
    } else {
      setLoading(true);
    }
    setError(null);
    try {
      const data = await api.get(
        `/api/users/me/access-log?limit=${PAGE_SIZE}&offset=${nextOffset}`,
      );
      const list = Array.isArray(data) ? data : [];
      setEntries(prev => (append ? [...prev, ...list] : list));
      // If we received a full page, assume there might be more.
      setHasMore(list.length === PAGE_SIZE);
      setOffset(nextOffset + list.length);
    } catch (e) {
      setError(e?.message || 'Failed to load access history');
    } finally {
      setLoading(false);
      setLoadingMore(false);
    }
  }, []);

  useEffect(() => {
    fetchPage(0, false);
  }, [fetchPage]);

  function handleRetry() {
    setOffset(0);
    fetchPage(0, false);
  }

  function handleLoadMore() {
    fetchPage(offset, true);
  }

  return (
    <div className="bg-white border border-gray-200 rounded-xl p-5 space-y-3">
      <p className="text-xs text-gray-500">
        Times your data has been viewed by other users, organization admins,
        or platform admins.
      </p>

      {loading && (
        <p className="text-sm text-gray-400 py-4">Loading…</p>
      )}

      {!loading && error && (
        <div className="py-4 space-y-2">
          <p className="text-sm text-red-500">
            Couldn't load your access history. Try again later.
          </p>
          <button
            onClick={handleRetry}
            className="text-xs px-3 py-1.5 border border-gray-300 text-gray-600 rounded-lg hover:bg-gray-50 transition-colors"
          >
            Retry
          </button>
        </div>
      )}

      {!loading && !error && entries.length === 0 && (
        <p className="text-sm text-gray-500 py-2">
          No access events recorded. When other users, organization admins, or
          platform admins view your data, those events will appear here.
        </p>
      )}

      {!loading && !error && entries.length > 0 && (
        <ul className="divide-y divide-gray-100">
          {entries.map((e, i) => (
            <AccessLogRow
              key={`${e.timestamp}-${e.accessor_id ?? 'anon'}-${i}`}
              entry={e}
            />
          ))}
        </ul>
      )}

      {!loading && !error && hasMore && (
        <div className="pt-2">
          <button
            onClick={handleLoadMore}
            disabled={loadingMore}
            className="text-xs px-3 py-1.5 border border-gray-300 text-gray-600 rounded-lg hover:bg-gray-50 transition-colors disabled:opacity-50"
          >
            {loadingMore ? 'Loading…' : 'Load more'}
          </button>
        </div>
      )}
    </div>
  );
}

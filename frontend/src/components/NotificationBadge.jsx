import { useState, useEffect, useRef, useCallback } from 'react';
import { Link, useNavigate, useLocation } from 'react-router-dom';
import api from '../api';
import { timeAgo } from '../utils/timeAgo';
import { formatNotification, notificationHref } from '../utils/formatNotification';

/**
 * Phase 13 F1 — notification center.
 *
 * Replaces the legacy listings-polled badge (Phase 9 NotificationBadge) with
 * a real, server-backed feed. The component name is preserved so Nav.jsx's
 * existing import keeps working; the implementation is a full rewrite.
 *
 * Behavior:
 * - Bell icon in nav.
 * - On mount + on every route change, fetches the unread feed
 *   (`GET /api/notifications?unread=true&limit=20`). The response's
 *   `items.length` drives the badge count; if `has_more` is true, the
 *   badge renders "20+".
 * - Click bell → dropdown opens. Dropdown shows up to 5 most recent unread
 *   rows. Each row click POSTs /read and navigates to the routing target
 *   computed by `notificationHref` (Item 22: uses notification.org_slug,
 *   never falls back to first-parent-org).
 * - "Mark all as read" button at top of dropdown.
 * - "View all" link at bottom of dropdown → /notifications.
 * - First-time banner (F5): when the user has zero notifications AND
 *   `notification_intro_dismissed === false`, the dropdown shows a banner
 *   pointing at /settings/notifications instead of "All caught up."
 *
 * F6 — localStorage cleanup. On mount, removes legacy keys written by the
 * old polling badge (`polis_last_seen_*`). Idempotent.
 *
 * Item 22 / 30 audit notes:
 *   - Item 22: routing path is computed by notificationHref(notif), which
 *     uses notif.org_slug (resolved server-side from notif.org_id). There
 *     is no "default org" or "first parent org" fallback anywhere in this
 *     file.
 *   - Item 30: this surface is account-scoped. There is no role-tier check
 *     gating visibility — every authenticated user gets their own bell.
 */

// Phase 13 F6 — keys written by the legacy NotificationBadge polling logic.
// Run-once cleanup on first mount post-deploy. Idempotent: once the keys
// are gone, subsequent runs are no-ops.
const LEGACY_LOCALSTORAGE_PREFIXES = ['polis_last_seen_'];

function cleanupLegacyLocalStorage() {
  try {
    const toRemove = [];
    for (let i = 0; i < window.localStorage.length; i += 1) {
      const key = window.localStorage.key(i);
      if (!key) continue;
      if (LEGACY_LOCALSTORAGE_PREFIXES.some(p => key.startsWith(p))) {
        toRemove.push(key);
      }
    }
    toRemove.forEach(k => window.localStorage.removeItem(k));
  } catch {
    // localStorage may be unavailable (private mode, quota); ignore.
  }
}

export default function NotificationBadge() {
  const navigate = useNavigate();
  const location = useLocation();
  const [items, setItems] = useState([]);
  const [hasMore, setHasMore] = useState(false);
  const [open, setOpen] = useState(false);
  const [introDismissed, setIntroDismissed] = useState(true);
  const ref = useRef(null);

  const load = useCallback(async () => {
    try {
      // The unread feed drives both the badge count and the dropdown rows.
      // We pull up to 20 to power the count; the dropdown shows the first
      // 5 and links to /notifications for "View all."
      const res = await api.get('/api/notifications?unread=true&limit=20');
      setItems(Array.isArray(res?.items) ? res.items : []);
      setHasMore(!!res?.has_more);
    } catch {
      // Soft-fail — a notification fetch failure shouldn't break the page.
      setItems([]);
      setHasMore(false);
    }
  }, []);

  // Mount: cleanup + initial fetch + intro-dismissed lookup. Then refetch on
  // every route change so the badge stays roughly fresh as the user navigates.
  useEffect(() => {
    cleanupLegacyLocalStorage();
  }, []);

  useEffect(() => {
    load();
  }, [load, location.pathname]);

  // Pull the intro-dismissed flag once on mount. Cheap; the preferences
  // GET also returns this and the F3 page will refresh it locally.
  useEffect(() => {
    let mounted = true;
    (async () => {
      try {
        const prefs = await api.get('/api/notifications/preferences');
        if (mounted) setIntroDismissed(!!prefs?.notification_intro_dismissed);
      } catch {
        // If the prefs lookup fails, fall back to "dismissed" so we don't
        // accidentally show the banner everywhere. The F3 page is the
        // canonical place to discover the banner.
        if (mounted) setIntroDismissed(true);
      }
    })();
    return () => { mounted = false; };
  }, []);

  // Outside-click closes dropdown.
  useEffect(() => {
    function handleClick(e) {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false);
    }
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, []);

  const count = items.length;
  const badgeText = count === 0 ? null : (hasMore ? '20+' : (count > 9 ? '9+' : String(count)));

  async function handleRowClick(notif) {
    setOpen(false);
    const href = notificationHref(notif);
    // Optimistically remove from local list so the badge updates immediately.
    setItems(prev => prev.filter(n => n.id !== notif.id));
    try {
      await api.post(`/api/notifications/${notif.id}/read`);
    } catch {
      // Best-effort; if the read POST fails the row will reappear on next
      // refetch and the user can click again.
    }
    navigate(href);
  }

  async function handleMarkAllRead() {
    try {
      await api.post('/api/notifications/mark-all-read', {});
      setItems([]);
      setHasMore(false);
    } catch {
      // Soft-fail.
    }
  }

  // Show the dropdown's 5 most recent unread.
  const dropdownItems = items.slice(0, 5);

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen(!open)}
        className="relative text-blue-200 hover:text-white transition-colors p-1"
        aria-label="Notifications"
      >
        <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
            d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9"
          />
        </svg>
        {badgeText && (
          <span className="absolute -top-1 -right-1 bg-red-500 text-white text-[10px] font-bold min-w-[1rem] h-4 px-1 rounded-full flex items-center justify-center">
            {badgeText}
          </span>
        )}
      </button>

      {open && (
        <div className="absolute right-0 top-full mt-2 w-80 bg-white border border-gray-200 rounded-xl shadow-lg z-50 overflow-hidden">
          {dropdownItems.length > 0 && (
            <div className="px-4 py-2 border-b border-gray-100 flex items-center justify-between bg-gray-50">
              <span className="text-xs font-semibold text-gray-500 uppercase tracking-wide">
                Notifications
              </span>
              <button
                onClick={handleMarkAllRead}
                className="text-xs text-[var(--brand-accent)] hover:underline"
              >
                Mark all as read
              </button>
            </div>
          )}

          {dropdownItems.length === 0 ? (
            // F5: when the user hasn't dismissed the intro, surface the
            // opt-in banner instead of the empty state.
            !introDismissed ? (
              <div className="p-4 space-y-2 text-center">
                <p className="text-sm text-gray-700">
                  Notifications are off by default.
                </p>
                <p className="text-xs text-gray-500">
                  Choose what you want to be notified about, then save.
                </p>
                <Link
                  to="/settings/notifications"
                  onClick={() => setOpen(false)}
                  className="inline-block mt-2 px-4 py-1.5 text-xs bg-[var(--brand-primary)] text-white rounded-lg hover:bg-[var(--brand-accent)] transition-colors"
                >
                  Manage preferences
                </Link>
              </div>
            ) : (
              <div className="p-4 text-sm text-gray-400 text-center">
                All caught up
              </div>
            )
          ) : (
            <ul className="divide-y divide-gray-100 max-h-80 overflow-y-auto">
              {dropdownItems.map(notif => (
                <li key={notif.id}>
                  <button
                    onClick={() => handleRowClick(notif)}
                    className="block w-full text-left px-4 py-3 text-sm text-gray-700 hover:bg-gray-50 transition-colors"
                  >
                    <p className="line-clamp-2">{formatNotification(notif)}</p>
                    <p className="text-xs text-gray-400 mt-0.5">{timeAgo(notif.created_at)}</p>
                  </button>
                </li>
              ))}
            </ul>
          )}

          <div className="border-t border-gray-100 bg-gray-50">
            <Link
              to="/notifications"
              onClick={() => setOpen(false)}
              className="block px-4 py-2 text-xs text-center text-[var(--brand-accent)] hover:underline"
            >
              View all
            </Link>
          </div>
        </div>
      )}
    </div>
  );
}

import { useState, useEffect, useMemo, useCallback } from 'react';
import { Link } from 'react-router-dom';
import api from '../api';
import { useToast } from '../components/Toast';

/**
 * Phase 13.3 F1-F5 — notification preferences page at /settings/notifications.
 *
 * Account-scoped (top-level route in App.jsx, NOT wrapped in
 * OrgScopedLayout). Renders the registry-driven event matrix with a
 * 4-column labeled layout (In-App | Weekly Digest | Daily Digest |
 * Immediate Email — ascending intrusiveness). Email options are NOT
 * mutually exclusive — a user can opt into multiple email channels per
 * event for belt-and-suspenders coverage.
 *
 * Phase 13.3 changes vs Phase 13:
 * - F1: 4-column matrix (was 2-column: in_app, email + global cadence).
 * - F2: global Email Cadence radio buttons section REMOVED. Per-event
 *       cadence in the matrix replaces it. `digest_cadence` is gone from
 *       both state and the PATCH payload.
 * - F3: quiet hours adjustable time pickers (HTML <input type="time">),
 *       defaults 21:00 / 09:00, hidden when toggle is off.
 * - F4: registry-driven matrix automatically renders the two new
 *       voting-opened events; floor_approached is gone from registry.
 * - F5: PATCH payload uses {in_app, email_immediate, email_daily,
 *       email_weekly} per event + {quiet_hours_start, quiet_hours_end}
 *       as HH:MM strings.
 *
 * F5 — first-time banner. When the user has not yet dismissed the intro,
 * a banner sits at the top with a Dismiss button.
 *
 * Item 30 audit: NO role-tier gating. Every authenticated user can manage
 * their own preferences regardless of org role.
 */

// 4 channel columns in ascending-intrusiveness order. The order is the
// visual left-to-right order in the matrix and is intentional (gentle →
// loud, so users opt in from the gentle end first).
const CHANNELS = [
  { key: 'in_app', label: 'In-App' },
  { key: 'email_weekly', label: 'Weekly Digest' },
  { key: 'email_daily', label: 'Daily Digest' },
  { key: 'email_immediate', label: 'Immediate Email' },
];

const DEFAULT_QUIET_START = '21:00';
const DEFAULT_QUIET_END = '09:00';

// Common IANA timezones, used as a fallback when
// Intl.supportedValuesOf isn't available (older browsers). Order: continents
// alphabetical, key population centers per continent. Not exhaustive but
// covers >95% of likely users — the backend stores whatever string we send.
const FALLBACK_TIMEZONES = [
  'UTC',
  'America/Los_Angeles',
  'America/Denver',
  'America/Chicago',
  'America/New_York',
  'America/Toronto',
  'America/Mexico_City',
  'America/Sao_Paulo',
  'Europe/London',
  'Europe/Paris',
  'Europe/Berlin',
  'Europe/Madrid',
  'Europe/Rome',
  'Europe/Athens',
  'Europe/Moscow',
  'Africa/Cairo',
  'Africa/Johannesburg',
  'Asia/Dubai',
  'Asia/Karachi',
  'Asia/Kolkata',
  'Asia/Bangkok',
  'Asia/Shanghai',
  'Asia/Hong_Kong',
  'Asia/Tokyo',
  'Asia/Seoul',
  'Australia/Perth',
  'Australia/Sydney',
  'Pacific/Auckland',
];

function listTimezones() {
  try {
    if (typeof Intl?.supportedValuesOf === 'function') {
      const all = Intl.supportedValuesOf('timeZone');
      if (Array.isArray(all) && all.length > 0) return all;
    }
  } catch { /* fall through */ }
  return FALLBACK_TIMEZONES;
}

function detectBrowserTimezone() {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || null;
  } catch {
    return null;
  }
}

// Normalize a HH:MM string from the server. Backend may send "21:00",
// "21:00:00", or null. We always render an HH:MM string in state (that's
// what <input type="time"> wants and what we PATCH back).
function normalizeTime(value, fallback) {
  if (typeof value !== 'string' || value.length < 4) return fallback;
  // Accept "HH:MM" or "HH:MM:SS" — slice to HH:MM.
  const match = value.match(/^(\d{2}):(\d{2})/);
  return match ? `${match[1]}:${match[2]}` : fallback;
}

export default function NotificationsPreferences() {
  const toast = useToast();
  const [registry, setRegistry] = useState({ events: [], categories: [] });
  // event_type -> {in_app, email_immediate, email_daily, email_weekly}
  const [prefs, setPrefs] = useState({});
  const [quietHours, setQuietHours] = useState(false);
  const [quietStart, setQuietStart] = useState(DEFAULT_QUIET_START);
  const [quietEnd, setQuietEnd] = useState(DEFAULT_QUIET_END);
  const [timezone, setTimezone] = useState('');
  const [introDismissed, setIntroDismissed] = useState(true);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  const tzOptions = useMemo(() => listTimezones(), []);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [reg, p] = await Promise.all([
        api.get('/api/notifications/registry'),
        api.get('/api/notifications/preferences'),
      ]);
      setRegistry({
        events: Array.isArray(reg?.events) ? reg.events : [],
        categories: Array.isArray(reg?.categories) ? reg.categories : [],
      });
      setPrefs(p?.preferences || {});
      setQuietHours(!!p?.quiet_hours_enabled);
      setQuietStart(normalizeTime(p?.quiet_hours_start, DEFAULT_QUIET_START));
      setQuietEnd(normalizeTime(p?.quiet_hours_end, DEFAULT_QUIET_END));
      setIntroDismissed(!!p?.notification_intro_dismissed);
      // Pre-populate timezone from server, falling back to browser detection
      // ONLY if the user hasn't set one yet. We don't quietly overwrite the
      // server value with the browser's idea — only suggest a default the
      // user can save.
      if (p?.timezone) {
        setTimezone(p.timezone);
      } else {
        const detected = detectBrowserTimezone();
        setTimezone(detected || 'UTC');
      }
    } catch (e) {
      toast.error(e.message || 'Could not load notification preferences');
    } finally {
      setLoading(false);
    }
  }, [toast]);

  useEffect(() => { load(); }, [load]);

  function toggleChannel(eventKey, channel) {
    setPrefs(prev => {
      const cur = prev[eventKey] || {
        in_app: false,
        email_immediate: false,
        email_daily: false,
        email_weekly: false,
      };
      // No XOR enforcement — email channels are independent booleans.
      return { ...prev, [eventKey]: { ...cur, [channel]: !cur[channel] } };
    });
  }

  function toggleQuietHours() {
    setQuietHours(v => {
      const next = !v;
      // When flipping ON without prior values, ensure defaults are visible
      // immediately. (load() already pre-populates, but if the user has
      // never enabled quiet hours, the times may match the defaults.)
      if (next) {
        if (!quietStart) setQuietStart(DEFAULT_QUIET_START);
        if (!quietEnd) setQuietEnd(DEFAULT_QUIET_END);
      }
      return next;
    });
  }

  async function handleSave() {
    setSaving(true);
    try {
      const body = {
        preferences: prefs,
        quiet_hours_enabled: quietHours,
        quiet_hours_start: quietStart || DEFAULT_QUIET_START,
        quiet_hours_end: quietEnd || DEFAULT_QUIET_END,
        timezone: timezone || null,
      };
      await api.patch('/api/notifications/preferences', body);
      toast.success('Preferences saved');
    } catch (e) {
      toast.error(e.message || 'Could not save preferences');
    } finally {
      setSaving(false);
    }
  }

  async function handleDismissIntro() {
    // Optimistic: hide the banner immediately, persist in the background.
    setIntroDismissed(true);
    try {
      await api.patch('/api/notifications/preferences', {
        notification_intro_dismissed: true,
      });
    } catch (e) {
      // If persistence fails, the banner will reappear on next load — fine.
      toast.error(e.message || 'Could not dismiss the intro');
    }
  }

  // Group events by category, preserving the registry's display order.
  const eventsByCategory = useMemo(() => {
    const buckets = {};
    for (const cat of registry.categories) buckets[cat] = [];
    for (const ev of registry.events) {
      if (!buckets[ev.category]) buckets[ev.category] = [];
      buckets[ev.category].push(ev);
    }
    return buckets;
  }, [registry]);

  if (loading) {
    return (
      <div className="flex justify-center items-center py-20">
        <div className="animate-spin w-8 h-8 border-4 border-[var(--brand-accent)] border-t-transparent rounded-full" />
      </div>
    );
  }

  // Grid template: event-description column flexes; 4 fixed-width channel
  // columns. Each channel column is 88px wide — narrow enough that all 4
  // fit on most viewports, wide enough that the labels (Weekly Digest /
  // Immediate Email) wrap predictably to two lines on narrow screens.
  const gridCols = 'grid-cols-[1fr,88px,88px,88px,88px]';

  return (
    <div className="max-w-3xl mx-auto px-4 py-8 space-y-8">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-[var(--brand-primary)]">Notification Preferences</h1>
          <p className="text-xs text-gray-500 mt-1">
            Account-level settings — apply across every organization you belong to.
          </p>
        </div>
        <Link
          to="/notifications"
          className="text-xs text-[var(--brand-accent)] hover:underline"
        >
          View notifications
        </Link>
      </div>

      {!introDismissed && (
        <div className="bg-blue-50 border border-blue-200 rounded-xl p-4 flex items-start justify-between gap-3">
          <div className="flex-1 min-w-0">
            <p className="text-sm font-medium text-blue-900">
              Notifications are off by default.
            </p>
            <p className="text-xs text-blue-800 mt-1">
              Choose what you want to be notified about, then save.
            </p>
          </div>
          <button
            onClick={handleDismissIntro}
            className="text-xs text-blue-700 hover:underline shrink-0"
          >
            Dismiss
          </button>
        </div>
      )}

      {/* Matrix */}
      <section className="space-y-3">
        <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide">
          What to notify me about
        </h2>
        <p className="text-xs text-gray-500">
          Pick any combination of channels per event. Email channels can be combined —
          for example, an immediate email AND inclusion in the weekly digest.
        </p>
        <div className="bg-white border border-gray-200 rounded-xl overflow-hidden">
          {/* Sticky header row — stays visible while scrolling the matrix. */}
          <div
            className={`grid ${gridCols} gap-2 px-4 py-2 border-b border-gray-200 bg-gray-50 text-[11px] font-semibold text-gray-500 uppercase tracking-wide sticky top-0 z-10`}
          >
            <span>Event</span>
            {CHANNELS.map(ch => (
              <span key={ch.key} className="text-center leading-tight">
                {ch.label}
              </span>
            ))}
          </div>

          {registry.categories.map(cat => {
            const events = eventsByCategory[cat] || [];
            if (events.length === 0) return null;
            return (
              <div key={cat} className="border-b border-gray-100 last:border-0">
                {/* Category header spans full width above its event group. */}
                <div className="px-4 pt-3 pb-1 text-xs font-semibold text-[var(--brand-primary)] uppercase tracking-wide bg-white">
                  {cat}
                </div>
                {events.map(ev => {
                  const cur = prefs[ev.key] || {
                    in_app: false,
                    email_immediate: false,
                    email_daily: false,
                    email_weekly: false,
                  };
                  return (
                    <div
                      key={ev.key}
                      className={`grid ${gridCols} gap-2 items-center px-4 py-3`}
                    >
                      <div className="min-w-0 pr-2">
                        <p className="text-sm text-gray-800">{ev.label}</p>
                        <p className="text-xs text-gray-500 mt-0.5">{ev.description}</p>
                      </div>
                      {CHANNELS.map(ch => (
                        <label
                          key={ch.key}
                          className="flex items-center justify-center cursor-pointer"
                        >
                          <input
                            type="checkbox"
                            checked={!!cur[ch.key]}
                            onChange={() => toggleChannel(ev.key, ch.key)}
                            className="w-4 h-4 accent-[var(--brand-accent)]"
                            aria-label={`${ev.label} — ${ch.label}`}
                          />
                        </label>
                      ))}
                    </div>
                  );
                })}
              </div>
            );
          })}
        </div>
      </section>

      {/* Quiet hours */}
      <section className="space-y-3">
        <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide">
          Quiet Hours
        </h2>
        <div className="bg-white border border-gray-200 rounded-xl p-5 space-y-3">
          <label className="flex items-start gap-3 cursor-pointer">
            <input
              type="checkbox"
              checked={quietHours}
              onChange={toggleQuietHours}
              className="mt-0.5 w-4 h-4 accent-[var(--brand-accent)]"
            />
            <div>
              <p className="text-sm text-gray-800">
                Don't email me during quiet hours.
              </p>
              <p className="text-xs text-gray-500">
                In-app notifications are unaffected — only email delivery is delayed
                until quiet hours end.
              </p>
            </div>
          </label>

          {quietHours && (
            <div className="pl-7 flex flex-wrap items-center gap-4">
              <label className="flex items-center gap-2 text-sm text-gray-700">
                <span>Start</span>
                <input
                  type="time"
                  value={quietStart}
                  onChange={e => setQuietStart(e.target.value)}
                  className="px-2 py-1 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[var(--brand-accent)]"
                  aria-label="Quiet hours start"
                />
              </label>
              <label className="flex items-center gap-2 text-sm text-gray-700">
                <span>End</span>
                <input
                  type="time"
                  value={quietEnd}
                  onChange={e => setQuietEnd(e.target.value)}
                  className="px-2 py-1 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[var(--brand-accent)]"
                  aria-label="Quiet hours end"
                />
              </label>
              <span className="text-xs text-gray-500">(in your timezone)</span>
            </div>
          )}
        </div>
      </section>

      {/* Timezone */}
      <section className="space-y-3">
        <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide">
          Timezone
        </h2>
        <div className="bg-white border border-gray-200 rounded-xl p-5 space-y-2">
          <p className="text-xs text-gray-500">
            Used for daily and weekly digest delivery and for quiet-hours boundaries.
          </p>
          <select
            value={timezone || ''}
            onChange={e => setTimezone(e.target.value)}
            className="w-full max-w-md px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[var(--brand-accent)]"
          >
            {tzOptions.map(tz => (
              <option key={tz} value={tz}>{tz}</option>
            ))}
          </select>
        </div>
      </section>

      {/* Save */}
      <div className="flex items-center gap-3 pt-2">
        <button
          onClick={handleSave}
          disabled={saving}
          className="text-sm px-5 py-2 bg-[var(--brand-primary)] text-white rounded-lg hover:bg-[var(--brand-accent)] transition-colors disabled:opacity-50"
        >
          {saving ? 'Saving…' : 'Save preferences'}
        </button>
      </div>
    </div>
  );
}

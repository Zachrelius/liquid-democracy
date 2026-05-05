import { useState, useEffect, useMemo, useCallback } from 'react';
import { Link } from 'react-router-dom';
import api from '../api';
import { useToast } from '../components/Toast';

/**
 * Phase 13 F3 — notification preferences page at /settings/notifications.
 *
 * Account-scoped (top-level route in App.jsx, NOT wrapped in
 * OrgScopedLayout). Renders the 12-event matrix from the backend
 * registry, plus account-level controls (digest cadence, quiet hours,
 * timezone).
 *
 * F5 — first-time banner. When the user has not yet dismissed the intro,
 * a banner sits at the top with a Dismiss button. Dismiss flips
 * `notification_intro_dismissed` to true via PATCH.
 *
 * Item 30 audit: NO role-tier gating. Every authenticated user can manage
 * their own preferences regardless of org role.
 */

const DIGEST_CADENCES = [
  { value: 'real_time', label: 'Real-time', desc: 'Send each email immediately when the event happens.' },
  { value: 'daily', label: 'Daily (9am local)', desc: 'One digest per day grouping the events from the previous 24 hours.' },
  { value: 'weekly', label: 'Weekly (Monday 9am local)', desc: 'One digest per week grouping the events from the previous 7 days.' },
  { value: 'off', label: 'Off', desc: "Don't send me any emails about notifications." },
];

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

export default function NotificationsPreferences() {
  const toast = useToast();
  const [registry, setRegistry] = useState({ events: [], categories: [] });
  const [prefs, setPrefs] = useState({});           // event_type -> {in_app, email}
  const [digestCadence, setDigestCadence] = useState('real_time');
  const [quietHours, setQuietHours] = useState(false);
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
      setDigestCadence(p?.digest_cadence || 'real_time');
      setQuietHours(!!p?.quiet_hours_enabled);
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
      const cur = prev[eventKey] || { in_app: false, email: false };
      return { ...prev, [eventKey]: { ...cur, [channel]: !cur[channel] } };
    });
  }

  async function handleSave() {
    setSaving(true);
    try {
      const body = {
        preferences: prefs,
        digest_cadence: digestCadence,
        quiet_hours_enabled: quietHours,
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
        <div className="bg-white border border-gray-200 rounded-xl overflow-hidden">
          {/* Header row */}
          <div className="grid grid-cols-[1fr,auto,auto] gap-4 px-4 py-2 border-b border-gray-200 bg-gray-50 text-xs font-semibold text-gray-500 uppercase tracking-wide">
            <span>Event</span>
            <span className="text-center w-16">In-App</span>
            <span className="text-center w-16">Email</span>
          </div>

          {registry.categories.map(cat => {
            const events = eventsByCategory[cat] || [];
            if (events.length === 0) return null;
            return (
              <div key={cat} className="border-b border-gray-100 last:border-0">
                <div className="px-4 pt-3 pb-1 text-xs font-semibold text-[var(--brand-primary)] uppercase tracking-wide">
                  {cat}
                </div>
                {events.map(ev => {
                  const cur = prefs[ev.key] || { in_app: false, email: false };
                  return (
                    <div
                      key={ev.key}
                      className="grid grid-cols-[1fr,auto,auto] gap-4 items-center px-4 py-3"
                    >
                      <div className="min-w-0">
                        <p className="text-sm text-gray-800">{ev.label}</p>
                        <p className="text-xs text-gray-500 mt-0.5">{ev.description}</p>
                      </div>
                      <label className="flex items-center justify-center w-16 cursor-pointer">
                        <input
                          type="checkbox"
                          checked={!!cur.in_app}
                          onChange={() => toggleChannel(ev.key, 'in_app')}
                          className="w-4 h-4 accent-[var(--brand-accent)]"
                          aria-label={`${ev.label} — in-app`}
                        />
                      </label>
                      <label className="flex items-center justify-center w-16 cursor-pointer">
                        <input
                          type="checkbox"
                          checked={!!cur.email}
                          onChange={() => toggleChannel(ev.key, 'email')}
                          className="w-4 h-4 accent-[var(--brand-accent)]"
                          aria-label={`${ev.label} — email`}
                        />
                      </label>
                    </div>
                  );
                })}
              </div>
            );
          })}
        </div>
      </section>

      {/* Email digest cadence */}
      <section className="space-y-3">
        <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide">
          Email Digest
        </h2>
        <div className="bg-white border border-gray-200 rounded-xl p-5 space-y-3">
          {DIGEST_CADENCES.map(opt => (
            <label key={opt.value} className="flex items-start gap-3 cursor-pointer">
              <input
                type="radio"
                name="digest_cadence"
                value={opt.value}
                checked={digestCadence === opt.value}
                onChange={() => setDigestCadence(opt.value)}
                className="mt-0.5 accent-[var(--brand-accent)]"
              />
              <div>
                <p className="text-sm text-gray-800">{opt.label}</p>
                <p className="text-xs text-gray-500">{opt.desc}</p>
              </div>
            </label>
          ))}
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
              onChange={() => setQuietHours(v => !v)}
              className="mt-0.5 w-4 h-4 accent-[var(--brand-accent)]"
            />
            <div>
              <p className="text-sm text-gray-800">
                Don't email me between 9pm and 9am in my timezone.
              </p>
              <p className="text-xs text-gray-500">
                In-app notifications are unaffected — only email delivery is delayed.
              </p>
            </div>
          </label>
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

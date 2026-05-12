import { useEffect, useState, useCallback, useRef } from 'react';
import { Link } from 'react-router-dom';
import api from '../api';

/**
 * Phase 23 F1 — Demo-org disclosure banner + refreshing overlay.
 *
 * Renders nothing for non-demo orgs (org.is_demo falsy). For demo orgs:
 *   - Normal state: light-amber banner with daily-reset disclosure +
 *     client-side countdown to next reset (recomputed every minute).
 *     Dismissable per session via sessionStorage key per org slug.
 *   - Reset-in-progress state (org.is_demo_resetting === true): a fixed
 *     overlay over the page with a spinner + "Demo refreshing..." copy.
 *     Polls GET /api/orgs/{slug} every 5s until the flag flips back to
 *     false; on flip either fires `onResetComplete` (caller-supplied) or
 *     reloads the page to pick up the fresh seeded state.
 *
 * Visual style mirrors the existing EmailVerificationBanner (amber-50
 * background, full-width bar, max-w-6xl content row).
 */
export default function DemoOrgBanner({
  org,
  resetTimePacific: resetTimePacificProp,
  nextResetAt: nextResetAtProp,
  onResetComplete,
}) {
  // Hooks must run unconditionally; the "no banner for non-demo orgs"
  // gate is handled inside the render path below.
  const dismissKey = org?.slug ? `demo_banner_dismissed_${org.slug}` : null;

  // If the parent didn't pass reset timing, lazily fetch from the demo
  // directory endpoint (public, cached 60s server-side). Keeps the wiring
  // point simple — OrgScopedLayout can just mount <DemoOrgBanner org=... />
  // without needing to know about /api/orgs/demo.
  const [fetchedResetTimePacific, setFetchedResetTimePacific] = useState(null);
  const [fetchedNextResetAt, setFetchedNextResetAt] = useState(null);
  useEffect(() => {
    if (!org?.is_demo) return;
    if (resetTimePacificProp && nextResetAtProp) return;
    let cancelled = false;
    (async () => {
      try {
        const data = await api.get('/api/orgs/demo');
        if (cancelled) return;
        setFetchedResetTimePacific(data?.reset_time_pacific || null);
        setFetchedNextResetAt(data?.next_reset_at || null);
      } catch {
        // Non-fatal — banner still renders without countdown.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [org?.is_demo, resetTimePacificProp, nextResetAtProp]);

  const resetTimePacific = resetTimePacificProp || fetchedResetTimePacific;
  const nextResetAt = nextResetAtProp || fetchedNextResetAt;

  const initialDismissed = (() => {
    if (!dismissKey) return false;
    try {
      return sessionStorage.getItem(dismissKey) === 'true';
    } catch {
      return false;
    }
  })();

  const [dismissed, setDismissed] = useState(initialDismissed);
  const [countdown, setCountdown] = useState(() => computeCountdown(nextResetAt));
  // While the org is resetting we poll until the flag clears. Local copy
  // of the most-recent is_demo_resetting we observed lets the overlay
  // dismiss client-side as soon as the poll sees the flip without waiting
  // on the caller to re-render with a fresh org prop.
  const [pollResetting, setPollResetting] = useState(null);
  const pollTimerRef = useRef(null);

  // Recompute the countdown each time the nextResetAt prop changes
  // (e.g., parent refetched the directory) and then once per minute.
  useEffect(() => {
    setCountdown(computeCountdown(nextResetAt));
    const id = setInterval(() => {
      setCountdown(computeCountdown(nextResetAt));
    }, 60_000);
    return () => clearInterval(id);
  }, [nextResetAt]);

  // Reset the dismissed-state if the org switches (different slug).
  useEffect(() => {
    if (!dismissKey) return;
    try {
      setDismissed(sessionStorage.getItem(dismissKey) === 'true');
    } catch {
      setDismissed(false);
    }
  }, [dismissKey]);

  // Sync the poll-local resetting flag with the latest prop value.
  useEffect(() => {
    setPollResetting(org?.is_demo_resetting ?? false);
  }, [org?.is_demo_resetting]);

  const stopPolling = useCallback(() => {
    if (pollTimerRef.current) {
      clearTimeout(pollTimerRef.current);
      pollTimerRef.current = null;
    }
  }, []);

  // While resetting, poll the org metadata every 5s.
  useEffect(() => {
    if (!org?.slug) return undefined;
    const resetting = pollResetting ?? org?.is_demo_resetting;
    if (!resetting) {
      stopPolling();
      return undefined;
    }

    let cancelled = false;
    async function tick() {
      try {
        const fresh = await api.get(`/api/orgs/${org.slug}`);
        if (cancelled) return;
        if (!fresh?.is_demo_resetting) {
          setPollResetting(false);
          stopPolling();
          if (typeof onResetComplete === 'function') {
            onResetComplete(fresh);
          } else {
            // No caller-provided refresh hook — reload to pick up the
            // freshly-seeded state across all org-scoped surfaces.
            window.location.reload();
          }
          return;
        }
      } catch {
        // Swallow; we'll retry on the next tick.
      }
      if (!cancelled) {
        pollTimerRef.current = setTimeout(tick, 5000);
      }
    }
    pollTimerRef.current = setTimeout(tick, 5000);
    return () => {
      cancelled = true;
      stopPolling();
    };
  }, [org?.slug, pollResetting, org?.is_demo_resetting, onResetComplete, stopPolling]);

  // ----- Render gates -----
  if (!org || !org.is_demo) return null;

  // Reset-in-progress overlay takes precedence over the normal banner.
  const isResetting = pollResetting ?? org.is_demo_resetting;
  if (isResetting) {
    return (
      <div
        className="fixed inset-0 z-50 bg-white/90 backdrop-blur-sm flex items-center justify-center px-4"
        role="alert"
        aria-live="polite"
      >
        <div className="max-w-sm w-full bg-white rounded-xl border border-gray-200 shadow-lg p-6 text-center">
          <div className="flex justify-center mb-4">
            <svg
              className="w-8 h-8 text-[var(--brand-accent)] animate-spin"
              xmlns="http://www.w3.org/2000/svg"
              fill="none"
              viewBox="0 0 24 24"
            >
              <circle
                className="opacity-25"
                cx="12"
                cy="12"
                r="10"
                stroke="currentColor"
                strokeWidth="4"
              />
              <path
                className="opacity-75"
                fill="currentColor"
                d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z"
              />
            </svg>
          </div>
          <h2 className="text-base font-semibold text-[var(--brand-primary)] mb-1">
            Demo refreshing, please wait a moment
          </h2>
          <p className="text-sm text-gray-600 leading-relaxed">
            We're re-seeding the demo organization with its curated state.
            This usually takes under a minute.
          </p>
        </div>
      </div>
    );
  }

  if (dismissed) return null;

  function handleDismiss() {
    if (!dismissKey) return;
    try {
      sessionStorage.setItem(dismissKey, 'true');
    } catch {
      // Best-effort; if storage is unavailable, just hide for this render.
    }
    setDismissed(true);
  }

  const resetTimeLabel = resetTimePacific || '00:00';

  return (
    <div className="bg-amber-50 border-b border-amber-200 px-4 py-3">
      <div className="max-w-6xl mx-auto flex items-center justify-between flex-wrap gap-2">
        <div className="text-sm text-amber-900 leading-snug">
          <span className="font-semibold">Demo organization.</span>{' '}
          State resets daily at {resetTimeLabel} Pacific. Your account
          persists across resets.{' '}
          <Link
            to="/demo"
            className="underline hover:text-amber-950"
          >
            Learn more
          </Link>
          {countdown ? (
            <span className="ml-2 text-amber-800">
              · Next reset in {countdown}
            </span>
          ) : null}
        </div>
        <button
          onClick={handleDismiss}
          className="text-xs text-amber-800 underline hover:text-amber-950"
          aria-label="Dismiss demo banner for this session"
        >
          Dismiss
        </button>
      </div>
    </div>
  );
}

/**
 * Compute a "Xh Ym" countdown string from an ISO 8601 next-reset timestamp.
 * Returns null if the timestamp is missing or already in the past
 * (during the brief reset window the overlay takes over anyway).
 */
function computeCountdown(nextResetAt) {
  if (!nextResetAt) return null;
  const next = new Date(nextResetAt).getTime();
  if (!Number.isFinite(next)) return null;
  const now = Date.now();
  const diffMs = next - now;
  if (diffMs <= 0) return null;
  const totalMinutes = Math.floor(diffMs / 60_000);
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  if (hours <= 0) return `${minutes}m`;
  return `${hours}h ${minutes}m`;
}

import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '../AuthContext';
import { useOrg } from '../OrgContext';

/**
 * Phase 43 Cluster C — Post-creation orientation pointer.
 *
 * Mounted on `OrgSettings.jsx` as a continuing orientation fallback after
 * the Phase 93 guided create/topics/invite path. Shows a small dismissible
 * banner linking to the steward getting-started help page. Persists dismissal
 * per (user, org_slug) via
 * sessionStorage — matches the existing pattern used by `DemoOrgBanner`
 * for per-org dismissable banners (do NOT switch to localStorage per
 * Phase 43 spec Cluster C).
 *
 * Crude visibility heuristic: show only when the viewer is a steward or
 * admin on the current org (the audience the pointer serves). If they
 * already dismissed it, stay dismissed for the session.
 */
export default function NewStewardPointer() {
  const { user } = useAuth();
  const { currentOrg } = useOrg();
  const slug = currentOrg?.slug;
  const role = currentOrg?.user_role;
  const isAdmin = role === 'steward' || role === 'admin';

  const dismissKey =
    user?.id && slug ? `new_steward_pointer_dismissed_${user.id}_${slug}` : null;

  const initialDismissed = (() => {
    if (!dismissKey) return false;
    try {
      return sessionStorage.getItem(dismissKey) === 'true';
    } catch {
      return false;
    }
  })();
  const [dismissed, setDismissed] = useState(initialDismissed);

  if (!isAdmin) return null;
  if (!dismissKey) return null;
  if (dismissed) return null;

  function handleDismiss() {
    setDismissed(true);
    try {
      sessionStorage.setItem(dismissKey, 'true');
    } catch {
      // sessionStorage unavailable (private window) — banner just stays
      // hidden for the rest of this render-tree life.
    }
  }

  return (
    <div className="mb-6 p-4 bg-blue-50 border border-blue-200 rounded-lg flex items-start gap-3">
      <div className="flex-1">
        <h3 className="text-sm font-semibold text-[var(--brand-primary)] mb-1">
          New here? Start with the steward guide.
        </h3>
        <p className="text-sm text-gray-700">
          Quick walkthrough of the handful of steps to turn this org into a
          place your members can actually deliberate and decide.{' '}
          <Link
            to="/help/getting-started-steward"
            className="text-[var(--brand-accent)] font-medium hover:underline"
          >
            Read the steward guide →
          </Link>
        </p>
      </div>
      <button
        type="button"
        onClick={handleDismiss}
        className="shrink-0 text-gray-400 hover:text-gray-600 text-sm px-2 py-1 -mr-1 -mt-1"
        aria-label="Dismiss"
      >
        ✕
      </button>
    </div>
  );
}

import { useEffect, useState, useCallback } from 'react';
import { Link } from 'react-router-dom';
import PublicLayout from '../components/PublicLayout';
import { useToast } from '../components/Toast';
import Avatar from '../components/Avatar';
import api, { setTokens } from '../api';

// Phase 43 Cluster X — count-aware copy helper. Renders English number
// words for the small counts the demo directory plausibly returns; falls
// back to the digits for unexpected values.
function numberWord(n) {
  const words = ['zero', 'one', 'two', 'three', 'four', 'five', 'six'];
  return words[n] || String(n);
}

/**
 * Phase 23 F2 — three-org directory rewrite.
 *
 * The legacy /demo page rendered a flat 6-persona grid against a single
 * `demo` org. Phase 23 reshapes the demo deployment into three curated
 * orgs (HOA, union, activist coalition), each with its own persona set.
 * This page fetches GET /api/orgs/demo and renders a vertical stack of
 * one card per demo org, each containing:
 *   - org header (name, governance type label, charter summary)
 *   - stats row (member / proposal counts)
 *   - per-org persona grid (clickable quick-login)
 *   - "Browse {org_name}" link to the existing OrgPublicLanding at /{slug}
 *   - daily-reset footnote
 *
 * Spec: phase23_demo_daily_reset_spec.md (F2, D21, D22, D23, D25).
 */

const GOVERNANCE_TYPE_STYLES = {
  "Homeowners' Association": 'bg-emerald-100 text-emerald-800 border-emerald-200',
  'Labor Union Local': 'bg-sky-100 text-sky-800 border-sky-200',
  'Civic Advocacy Group': 'bg-violet-100 text-violet-800 border-violet-200',
};

export default function Demo() {
  const toast = useToast();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [directory, setDirectory] = useState(null);
  // Loading key is `${orgSlug}:${username}` so two personas with the
  // same display name across orgs don't collide.
  const [loadingUser, setLoadingUser] = useState(null);

  const fetchDirectory = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.get('/api/orgs/demo');
      setDirectory(data || { orgs: [], reset_time_pacific: '00:00', next_reset_at: null });
    } catch (err) {
      setError(err?.message || 'Could not load demo orgs.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchDirectory();
  }, [fetchDirectory]);

  async function handlePersonaLogin(username, orgSlug, displayName, orgName) {
    const key = `${orgSlug}:${username}`;
    setLoadingUser(key);
    try {
      const data = await api.post('/api/auth/demo-login', {
        username,
        org_slug: orgSlug,
      });
      if (!data?.access_token) {
        throw new Error('Demo login did not return an access token.');
      }
      // Mirror AuthContext.login() — persist tokens to sessionStorage and
      // sync into the api module. Full-page nav to /orgs lets OrgSelector
      // auto-redirect single-org demo personas into their org.
      setTokens(data.access_token, data.refresh_token || null);
      sessionStorage.setItem('token', data.access_token);
      if (data.refresh_token) {
        sessionStorage.setItem('refreshToken', data.refresh_token);
      }
      window.location.assign('/orgs');
    } catch (err) {
      if (err?.status === 404) {
        toast.error(`Demo login as ${displayName} in ${orgName} is unavailable.`);
      } else {
        toast.error(err?.message || 'Demo login failed.');
      }
      setLoadingUser(null);
    }
  }

  const resetTime = directory?.reset_time_pacific || '00:00';
  const orgs = directory?.orgs || [];
  // Phase 43 Cluster X — count-aware copy. Backend currently exposes 1 of
  // the 3 seeded demo orgs publicly via /api/orgs/demo; the prior "three
  // demo organizations" / "all three orgs" prose was stale. Derive from
  // the fetched list so the copy is correct regardless of how many orgs
  // the directory ends up serving.
  const orgCount = orgs.length;
  const orgsPhrase = orgCount === 1
    ? 'the demo organization'
    : orgCount > 1
      ? `${numberWord(orgCount)} demo organizations`
      : 'the demo organizations';
  const orgsResetPhrase = orgCount === 1
    ? 'this org'
    : orgCount > 1
      ? `all ${numberWord(orgCount)} orgs`
      : 'all orgs';

  return (
    <PublicLayout>
      <div className="max-w-6xl mx-auto px-6 py-16">
        {/* Intro */}
        <div className="max-w-3xl">
          <p className="text-sm font-medium text-[var(--brand-accent)] uppercase tracking-wider">
            Demo
          </p>
          <h1 className="mt-2 text-3xl sm:text-4xl font-semibold text-[var(--brand-primary)] tracking-tight">
            Try the platform
          </h1>
          <p className="mt-4 text-base text-[#2C3E50] leading-relaxed">
            This is a working demo of the Liquid Democracy platform. Sign
            in as one of the pre-built personas in {orgsPhrase} to
            vote, delegate, and explore — or register your own account
            to try the full onboarding flow.
          </p>
        </div>

        {/* Persistent-data notice */}
        <div className="mt-6 max-w-3xl p-4 rounded-lg border border-amber-200 bg-amber-50 text-sm text-amber-900">
          <strong className="font-semibold">Heads up:</strong> {orgCount === 1 ? 'this is a' : 'these are'}{' '}
          shared demo {orgCount === 1 ? 'organization' : 'organizations'}.
          Anything you create — proposals, delegations, votes — is visible
          to other visitors. Demo state resets daily at {resetTime} Pacific
          across {orgsResetPhrase}.
        </div>

        {/* Org cards */}
        <section className="mt-12 space-y-6">
          <h2 className="text-xl font-semibold text-[var(--brand-primary)]">
            Pick a demo organization
          </h2>

          {loading && (
            <div className="p-8 rounded-xl border border-gray-200 bg-white text-center">
              <p className="text-sm text-gray-500">Loading demo organizations…</p>
            </div>
          )}

          {!loading && error && (
            <div className="p-6 rounded-xl border border-red-200 bg-red-50">
              <p className="text-sm text-red-800 mb-3">
                Couldn't load demo orgs: {error}
              </p>
              <button
                onClick={fetchDirectory}
                className="px-4 py-2 bg-red-700 text-white text-sm font-medium rounded-lg hover:bg-red-800 transition-colors"
              >
                Retry
              </button>
            </div>
          )}

          {!loading && !error && orgs.length === 0 && (
            <div className="p-8 rounded-xl border border-gray-200 bg-white text-center">
              <p className="text-sm text-[#2C3E50]">
                Demo is refreshing, please check back in a moment.
              </p>
            </div>
          )}

          {!loading && !error && orgs.length > 0 && orgs.map((org) => (
            <DemoOrgCard
              key={org.slug}
              org={org}
              resetTime={resetTime}
              loadingUser={loadingUser}
              onPersonaLogin={handlePersonaLogin}
            />
          ))}
        </section>

        {/* Register-your-own */}
        <section className="mt-14 p-6 rounded-xl border border-gray-200 bg-white shadow-sm max-w-3xl">
          <h2 className="text-lg font-semibold text-[var(--brand-primary)] mb-2">
            Prefer a clean slate?
          </h2>
          <p className="text-sm text-[#2C3E50] leading-relaxed">
            <Link
              to="/register"
              className="text-[var(--brand-accent)] font-medium hover:underline"
            >
              Register an account
            </Link>{' '}
            — you'll go through the real onboarding flow including email
            verification, then can create your own organization.
          </p>
        </section>
      </div>
    </PublicLayout>
  );
}

function DemoOrgCard({ org, resetTime, loadingUser, onPersonaLogin }) {
  const personas = Array.isArray(org.personas) ? org.personas : [];
  const govStyle =
    GOVERNANCE_TYPE_STYLES[org.governance_type] ||
    'bg-gray-100 text-gray-700 border-gray-200';
  const stats = [
    typeof org.member_count === 'number' ? `${org.member_count} members` : null,
    typeof org.active_proposal_count === 'number'
      ? `${org.active_proposal_count} active proposal${org.active_proposal_count === 1 ? '' : 's'}`
      : null,
    typeof org.deliberation_proposal_count === 'number'
      ? `${org.deliberation_proposal_count} in deliberation`
      : null,
  ].filter(Boolean);

  const refreshing = !!org.is_demo_resetting;

  return (
    <div
      className={`relative rounded-xl border border-gray-200 bg-white shadow-sm overflow-hidden ${
        refreshing ? 'opacity-60' : ''
      }`}
    >
      {refreshing && (
        <div className="absolute inset-0 z-10 flex items-center justify-center bg-white/70 backdrop-blur-sm pointer-events-none">
          <span className="text-sm font-medium text-[var(--brand-primary)]">
            Refreshing demo state…
          </span>
        </div>
      )}

      {/* Header */}
      <div className="p-6 border-b border-gray-100">
        <div className="flex items-start justify-between gap-3 flex-wrap">
          <div className="flex-1 min-w-0">
            <h3 className="text-xl font-semibold text-[var(--brand-primary)]">
              {org.name}
            </h3>
            {org.governance_type && (
              <span
                className={`inline-block mt-2 px-2.5 py-1 text-xs font-medium rounded-full border ${govStyle}`}
              >
                {org.governance_type}
              </span>
            )}
          </div>
        </div>
        {org.charter_summary && (
          <p className="mt-3 text-sm text-[#2C3E50] leading-relaxed">
            {org.charter_summary}
          </p>
        )}
        {stats.length > 0 && (
          <p className="mt-3 text-xs text-gray-500">{stats.join(' · ')}</p>
        )}
      </div>

      {/* Personas */}
      <div className="p-6">
        {personas.length === 0 ? (
          <p className="text-sm text-gray-500 italic">
            No personas available for this org yet.
          </p>
        ) : (
          <>
            <p className="text-xs font-medium text-gray-600 uppercase tracking-wider mb-3">
              Sign in as
            </p>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
              {personas.map((p) => {
                const key = `${org.slug}:${p.username}`;
                const isLoading = loadingUser === key;
                const isDisabled =
                  refreshing || (loadingUser !== null && loadingUser !== key);
                return (
                  <DemoPersonaTile
                    key={p.username}
                    persona={p}
                    orgName={org.name}
                    loading={isLoading}
                    disabled={isDisabled}
                    onClick={() =>
                      onPersonaLogin(p.username, org.slug, p.display_name, org.name)
                    }
                  />
                );
              })}
            </div>
          </>
        )}

        {/* Browse link */}
        <div className="mt-5 pt-4 border-t border-gray-100">
          <Link
            to={`/${org.slug}`}
            className="text-sm text-[var(--brand-accent)] font-medium hover:underline"
          >
            Browse {org.name} →
          </Link>
        </div>
      </div>

      {/* Footer */}
      <div className="px-6 py-3 bg-gray-50 border-t border-gray-100 text-xs text-gray-500">
        Demo state resets daily at {resetTime} Pacific.
      </div>
    </div>
  );
}

function DemoPersonaTile({ persona, orgName, loading, disabled, onClick }) {
  const displayName = persona.display_name || persona.username;
  const role = persona.role || '';
  const description = persona.description || role || '';
  return (
    <button
      onClick={onClick}
      disabled={disabled || loading}
      aria-label={`Sign in as ${displayName} in ${orgName}`}
      className="flex flex-col items-start text-left p-4 bg-white rounded-lg border border-gray-200 hover:border-[var(--brand-accent)] hover:shadow-sm transition-all disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:border-gray-200 disabled:hover:shadow-none"
    >
      <div className="flex items-center gap-3 mb-2 w-full">
        {/* Phase 30 B3 — render the AI-illustration portrait when present
            (personas.avatar_url is wired by seed_pipeline.py from
            User.avatar_url). Avatar falls back to a deterministic
            initials circle when avatar_url is missing or 404s. */}
        <div className="shrink-0">
          <Avatar
            user={{
              display_name: displayName,
              avatar_url: persona.avatar_url,
              username: persona.username,
            }}
            size="md"
          />
        </div>
        <div className="min-w-0 flex-1">
          <div className="text-sm font-semibold text-[var(--brand-primary)] truncate">
            {displayName}
          </div>
          {role && (
            <div className="text-xs text-gray-500 truncate">{role}</div>
          )}
        </div>
      </div>
      {description && (
        <p className="text-xs text-[#2C3E50] leading-relaxed">
          {description}
        </p>
      )}
      <span className="mt-3 text-xs text-[var(--brand-accent)] font-medium">
        {loading ? 'Signing in…' : 'Sign in →'}
      </span>
    </button>
  );
}

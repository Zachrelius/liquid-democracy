import { useEffect, useState, useCallback, useRef, useMemo } from 'react';
import { Link } from 'react-router-dom';
import PublicLayout from '../components/PublicLayout';
import api from '../api';

/**
 * Phase 55 — /explore: public org discovery.
 *
 * Lists discoverable public orgs (open, approval_required, and
 * invite_only_public — not invite_only_secret), excluding demo orgs and
 * sub-orgs. Search across name + description, sort by activity (default)
 * or member count. The card's primary action is a "View" link to the
 * Phase 14 splash at /{slug}, which owns all join logic; this page is
 * intentionally thin.
 *
 * Spec: phase55_public_org_discovery_spec_2026-06-05.md (F2, F3).
 */

// Generic governance-type badge styles. The three demo-org labels keep
// their distinct colors (so /demo and /explore feel visually coherent
// when a viewer flips between them), but real orgs can carry arbitrary
// governance_type strings — those fall through to a neutral default.
const GOVERNANCE_TYPE_STYLES = {
  "Homeowners' Association": 'bg-emerald-100 text-emerald-800 border-emerald-200',
  'Labor Union Local': 'bg-sky-100 text-sky-800 border-sky-200',
  'Civic Advocacy Group': 'bg-violet-100 text-violet-800 border-violet-200',
};
const DEFAULT_GOVERNANCE_STYLE = 'bg-gray-100 text-gray-700 border-gray-200';

// Phase 55 D5 — onboarding scaffolding copy. Captured as a named constant
// so a future pass can swap or retire the block in one edit.
const ONBOARDING_HEADER = {
  eyebrow: 'Explore',
  title: 'Public organizations',
  body: (
    "These are real organizations using Liquid Democracy to make decisions "
    + "together. Browse the list, click any org for its public landing page, "
    + "and request to join (or watch from the outside) if it interests you. "
    + "Looking for a feel of the platform first? The "
  ),
  demoLinkText: 'demo organizations',
  bodyTail: ' carry sample personas and pre-built proposals you can try.',
};

export default function OrgDiscovery() {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [data, setData] = useState({ orgs: [], count: 0 });
  const [searchInput, setSearchInput] = useState('');
  const [searchQuery, setSearchQuery] = useState('');
  const [sort, setSort] = useState('activity');

  // Debounce the search input (~300ms) so each keystroke doesn't hit the
  // endpoint. Empty input clears the filter immediately on next tick.
  const debounceRef = useRef(null);
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      setSearchQuery(searchInput.trim());
    }, 300);
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [searchInput]);

  const fetchOrgs = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams();
      if (searchQuery) params.set('q', searchQuery);
      if (sort) params.set('sort', sort);
      const qs = params.toString();
      const path = qs ? `/api/orgs/explore?${qs}` : '/api/orgs/explore';
      const result = await api.get(path);
      setData(result || { orgs: [], count: 0 });
    } catch (err) {
      setError(err?.message || 'Could not load organizations.');
    } finally {
      setLoading(false);
    }
  }, [searchQuery, sort]);

  useEffect(() => {
    fetchOrgs();
  }, [fetchOrgs]);

  const orgs = data?.orgs || [];
  const hasResults = orgs.length > 0;
  const isSearchActive = searchQuery.length > 0;

  // useMemo here is overkill but keeps the empty-state derivation tidy.
  const emptyStateNode = useMemo(() => {
    if (loading || error || hasResults) return null;
    if (isSearchActive) {
      return (
        <div className="p-8 rounded-xl border border-gray-200 bg-white text-center space-y-3">
          <p className="text-sm text-[#2C3E50]">
            No organizations match &ldquo;{searchQuery}&rdquo;.
          </p>
          <button
            onClick={() => setSearchInput('')}
            className="text-sm text-[var(--brand-accent)] font-medium hover:underline"
          >
            Clear search
          </button>
        </div>
      );
    }
    return (
      <div className="p-8 rounded-xl border border-gray-200 bg-white text-center">
        <p className="text-sm text-[#2C3E50]">
          No public organizations yet.
        </p>
      </div>
    );
  }, [loading, error, hasResults, isSearchActive, searchQuery]);

  return (
    <PublicLayout>
      <div className="max-w-6xl mx-auto px-6 py-16">

        {/* Phase 55 onboarding scaffolding — removable once public org count
            is high. Single block, safe to delete wholesale. */}
        <div className="max-w-3xl">
          <p className="text-sm font-medium text-[var(--brand-accent)] uppercase tracking-wider">
            {ONBOARDING_HEADER.eyebrow}
          </p>
          <h1 className="mt-2 text-3xl sm:text-4xl font-semibold text-[var(--brand-primary)] tracking-tight">
            {ONBOARDING_HEADER.title}
          </h1>
          <p className="mt-4 text-base text-[#2C3E50] leading-relaxed">
            {ONBOARDING_HEADER.body}
            <Link
              to="/demo"
              className="text-[var(--brand-accent)] font-medium hover:underline"
            >
              {ONBOARDING_HEADER.demoLinkText}
            </Link>
            {ONBOARDING_HEADER.bodyTail}
          </p>
        </div>
        {/* End onboarding scaffolding */}

        {/* Search + sort controls */}
        <div className="mt-10 flex flex-col sm:flex-row gap-3 sm:items-center sm:justify-between">
          <div className="flex-1 max-w-md">
            <label htmlFor="explore-search" className="sr-only">
              Search organizations
            </label>
            <input
              id="explore-search"
              type="search"
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
              placeholder="Search by name or description…"
              className="w-full px-4 py-2 bg-white border border-gray-300 rounded-lg text-sm placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-[var(--brand-accent)] focus:border-transparent"
            />
          </div>
          <SortControl value={sort} onChange={setSort} />
        </div>

        {/* Results section */}
        <section className="mt-8 space-y-6">
          {loading && (
            <div className="p-8 rounded-xl border border-gray-200 bg-white text-center">
              <p className="text-sm text-gray-500">Loading organizations…</p>
            </div>
          )}

          {!loading && error && (
            <div className="p-6 rounded-xl border border-red-200 bg-red-50">
              <p className="text-sm text-red-800 mb-3">
                Couldn&apos;t load organizations: {error}
              </p>
              <button
                onClick={fetchOrgs}
                className="px-4 py-2 bg-red-700 text-white text-sm font-medium rounded-lg hover:bg-red-800 transition-colors"
              >
                Retry
              </button>
            </div>
          )}

          {emptyStateNode}

          {!loading && !error && hasResults && (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
              {orgs.map((org) => (
                <ExploreOrgCard key={org.slug} org={org} />
              ))}
            </div>
          )}
        </section>

      </div>
    </PublicLayout>
  );
}


function SortControl({ value, onChange }) {
  const options = [
    { value: 'activity', label: 'Most active' },
    { value: 'members', label: 'Most members' },
  ];
  return (
    <div
      role="radiogroup"
      aria-label="Sort organizations"
      className="inline-flex rounded-lg border border-gray-300 bg-white p-0.5 self-start"
    >
      {options.map((opt) => {
        const selected = value === opt.value;
        return (
          <button
            key={opt.value}
            type="button"
            role="radio"
            aria-checked={selected}
            onClick={() => onChange(opt.value)}
            className={`px-3 py-1.5 text-xs font-medium rounded-md transition-colors ${
              selected
                ? 'bg-[var(--brand-primary)] text-white shadow-sm'
                : 'text-[#2C3E50] hover:text-[var(--brand-primary)]'
            }`}
          >
            {opt.label}
          </button>
        );
      })}
    </div>
  );
}


// Phase 14 splash explains the per-policy join state on the org's page;
// here we just hint at the policy on the card so a visitor knows what
// they're walking into.
const JOIN_POLICY_HINTS = {
  open: 'Open to join',
  // Phase 57 — three-value vocabulary (open / approval / invite); the
  // legacy four-value keys are retained for back-compat against a
  // stale cache that returns OrgOut still using them.
  approval: 'Approval required',
  invite: 'Invitation only',
  approval_required: 'Approval required',
  invite_only_public: 'Invitation only',
};


function ExploreOrgCard({ org }) {
  const govStyle =
    GOVERNANCE_TYPE_STYLES[org.governance_type] || DEFAULT_GOVERNANCE_STYLE;
  const branding = org.branding || {};
  const cardPrimary = branding.primary_color || null;
  // 4px left-accent border in the org's primary color when set; subtle
  // visual cue without overriding global CSS vars on a multi-org page.
  const cardStyle = cardPrimary
    ? { borderLeft: `4px solid ${cardPrimary}` }
    : {};

  const policyHint = JOIN_POLICY_HINTS[org.join_policy] || null;
  const memberLabel = org.member_count === 1 ? 'member' : 'members';

  return (
    <Link
      to={`/${org.slug}`}
      style={cardStyle}
      className="group flex flex-col p-5 bg-white border border-gray-200 rounded-xl hover:border-[var(--brand-accent)] hover:shadow-sm transition-all"
    >
      <div className="flex items-start gap-3">
        {org.logo_url ? (
          <img
            src={org.logo_url}
            alt=""
            className="h-10 w-10 object-contain rounded-md bg-gray-50 border border-gray-100 shrink-0"
          />
        ) : (
          <div className="h-10 w-10 rounded-md bg-gray-100 border border-gray-200 flex items-center justify-center shrink-0 text-sm font-semibold text-gray-400">
            {(org.name || '?').charAt(0).toUpperCase()}
          </div>
        )}
        <div className="min-w-0 flex-1">
          <h3
            className={`text-lg font-semibold truncate ${cardPrimary ? '' : 'text-[var(--brand-primary)]'}`}
            style={cardPrimary ? { color: cardPrimary } : undefined}
          >
            {org.name}
          </h3>
          {org.governance_type && (
            <span
              className={`inline-block mt-1 px-2 py-0.5 text-[11px] font-medium rounded-full border ${govStyle}`}
            >
              {org.governance_type}
            </span>
          )}
        </div>
      </div>

      {org.description && (
        <p className="mt-3 text-sm text-[#2C3E50] leading-relaxed line-clamp-3">
          {org.description}
        </p>
      )}

      <div className="mt-4 pt-3 border-t border-gray-100 flex items-center justify-between gap-3 text-xs text-gray-500">
        <div className="flex items-center gap-2">
          <span>{org.member_count ?? 0} {memberLabel}</span>
          {policyHint && (
            <>
              <span className="text-gray-300">·</span>
              <span>{policyHint}</span>
            </>
          )}
        </div>
        <span className="text-[var(--brand-accent)] font-medium group-hover:underline">
          View →
        </span>
      </div>
    </Link>
  );
}

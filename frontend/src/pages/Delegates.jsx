/**
 * Phase 19 F4 — Browse page for an org's public delegates.
 *
 * Route: ``/{slug}/delegates``.
 *
 * Calls ``GET /api/orgs/{slug}/delegates`` (offset-based pagination per spec
 * line 207, ``limit`` defaults to 20). The endpoint already enforces the
 * "user has at least one ``public_accepting`` topic in this org" filter and
 * the cross-org delegation-count scope; we only render and provide UI
 * filtering / sorting on top of the response.
 *
 * Filters mirror the backend query params:
 *   - topic_id              -> topic dropdown (org topics list)
 *   - active_within_days=30 -> "show only delegates active in last 30 days"
 *
 * Sort: backend default is ``delegation_count DESC, recent_rationale_ratio
 * DESC``. Spec line 282 also asks for ``recent activity`` and
 * ``alphabetical``; since the endpoint is offset-paginated and doesn't
 * accept a sort key, we apply secondary client-side sort to the current
 * page (a known-suboptimal v1 — fine for the 20-item page size). If
 * server-side sort becomes load-bearing we can add a ?sort= query param.
 *
 * Each card links to ``/{slug}/delegates/{handle_or_username}`` (F2).
 */
import { useState, useEffect, useCallback } from 'react';
import { useParams, Link } from 'react-router-dom';
import api from '../api';
import { useOrg } from '../OrgContext';
import Avatar from '../components/Avatar';

const PAGE_SIZE = 20;

function rationaleColor(ratio) {
  // D11: "rationale ratio" indicator — green ≥0.5, yellow ≥0.2, none <0.2.
  if (ratio >= 0.5) return { dot: 'bg-green-500', label: 'High rationale rate' };
  if (ratio >= 0.2) return { dot: 'bg-amber-400', label: 'Some rationales' };
  return null;
}

function DelegateCard({ delegate, slug }) {
  const handle = delegate.delegate_handle || delegate.username;
  const intro = (delegate.intro || '').slice(0, 150);
  const truncated = (delegate.intro || '').length > 150;
  const rc = rationaleColor(delegate.recent_rationale_ratio || 0);

  return (
    <Link
      to={`/${slug}/delegates/${handle}`}
      className="block bg-white border border-gray-200 rounded-xl p-4 hover:border-[var(--brand-accent)] transition-colors"
    >
      <div className="flex items-start gap-3">
        <Avatar user={delegate} size="md" />
        <div className="flex-1 min-w-0">
          <div className="flex items-center justify-between gap-2 flex-wrap">
            <div>
              <p className="text-sm font-semibold text-[var(--brand-primary)]">
                {delegate.display_name || delegate.username}
              </p>
              <p className="text-xs text-gray-400">
                @{delegate.delegate_handle || delegate.username}
              </p>
            </div>
            <div className="flex items-center gap-2 flex-shrink-0">
              <span className="text-xs text-gray-500">
                {delegate.delegation_count} delegation{delegate.delegation_count === 1 ? '' : 's'}
              </span>
              {rc && (
                <span
                  className="inline-flex items-center gap-1 text-xs text-gray-500"
                  title={`${rc.label} (${Math.round((delegate.recent_rationale_ratio || 0) * 100)}% of recent votes have rationale)`}
                >
                  <span className={`inline-block w-2 h-2 rounded-full ${rc.dot}`} />
                </span>
              )}
            </div>
          </div>
          {intro && (
            <p className="text-sm text-gray-600 mt-1.5">
              {intro}{truncated ? '…' : ''}
            </p>
          )}
          {delegate.public_topics && delegate.public_topics.length > 0 && (
            <div className="flex gap-1 flex-wrap mt-2">
              {delegate.public_topics
                .filter(t => t.visibility === 'public_accepting')
                .slice(0, 6)
                .map(t => (
                  <span
                    key={t.topic_id}
                    className="text-xs px-2 py-0.5 rounded-full bg-blue-50 text-blue-700"
                  >
                    {/* Phase 26 D1 — description || name. */}
                    {t.name}
                  </span>
                ))}
              {delegate.public_topics.filter(t => t.visibility === 'public_accepting').length > 6 && (
                <span className="text-xs text-gray-400">
                  +{delegate.public_topics.filter(t => t.visibility === 'public_accepting').length - 6} more
                </span>
              )}
            </div>
          )}
        </div>
      </div>
    </Link>
  );
}

export default function Delegates() {
  const { org_slug } = useParams();
  const { currentOrg } = useOrg();

  const [delegates, setDelegates] = useState([]);
  const [topics, setTopics] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [topicFilter, setTopicFilter] = useState('');
  const [activeOnly, setActiveOnly] = useState(false);
  const [sort, setSort] = useState('default'); // 'default' | 'recent' | 'alpha'
  const [offset, setOffset] = useState(0);
  const [hasMore, setHasMore] = useState(false);

  // Phase 34.3 G1 — prefer currentOrg.slug over the URL's org_slug param.
  // Under the Phase 34.2 nested URL pattern (`/:org_slug/sub-orgs/:sub_slug/
  // delegates`), useParams().org_slug is the PARENT slug, not the sub-org's.
  // OrgContext correctly resolves currentOrg to the sub-org when sub_slug is
  // in the URL, so currentOrg.slug is the right value for the API target.
  // Pre-fix the slug fell through to org_slug (parent), causing the sub-org
  // Delegates page to render the parent's 14-delegate list instead of the
  // sub-org's 2-delegate list.
  const slug = currentOrg?.slug || org_slug || null;

  const load = useCallback(async () => {
    if (!slug) return;
    setLoading(true);
    setError('');
    try {
      const params = new URLSearchParams({
        limit: String(PAGE_SIZE),
        offset: String(offset),
      });
      if (topicFilter) params.set('topic_id', topicFilter);
      if (activeOnly) params.set('active_within_days', '30');
      const data = await api.get(`/api/orgs/${slug}/delegates?${params.toString()}`);
      setDelegates(data || []);
      // Offset-based: hasMore if we filled the page.
      setHasMore((data || []).length >= PAGE_SIZE);
    } catch (e) {
      setError(e.message || 'Failed to load delegates');
    } finally {
      setLoading(false);
    }
  }, [slug, offset, topicFilter, activeOnly]);

  useEffect(() => { load(); }, [load]);

  // Topics dropdown: load once for the org.
  useEffect(() => {
    if (!slug) return;
    (async () => {
      try {
        const tops = await api.get(`/api/orgs/${slug}/topics`);
        setTopics(tops || []);
      } catch { /* ignore — topic filter just won't populate */ }
    })();
  }, [slug]);

  // Reset offset when filters change.
  useEffect(() => { setOffset(0); }, [topicFilter, activeOnly]);

  // Client-side secondary sort over the current page.
  const sorted = [...delegates];
  if (sort === 'alpha') {
    sorted.sort((a, b) =>
      (a.display_name || a.username || '').localeCompare(b.display_name || b.username || '')
    );
  }
  // 'recent' would require a per-row last-vote timestamp on the response;
  // the endpoint doesn't ship that. We treat it as an alias for the
  // active_within_days filter for now and surface a note.

  if (!slug) {
    return (
      <div className="max-w-4xl mx-auto px-4 py-8">
        <p className="text-gray-500 text-sm">No organization selected.</p>
      </div>
    );
  }

  return (
    <div className="max-w-4xl mx-auto px-4 py-8 space-y-6">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl font-semibold text-[var(--brand-primary)]">
            Delegates
          </h1>
          <p className="text-sm text-gray-500 mt-1">
            Public delegates accepting delegation in {currentOrg?.name || slug}.
          </p>
        </div>
        <Link
          to={`/${slug}/delegate-profile`}
          className="text-sm px-3 py-1.5 border border-[var(--brand-accent)] text-[var(--brand-accent)] rounded-lg hover:bg-[var(--brand-accent)] hover:text-white transition-colors"
        >
          My Delegate Page
        </Link>
      </div>

      {/* Filters / sort row */}
      <div className="bg-white border border-gray-200 rounded-xl p-4 flex flex-wrap items-end gap-4">
        <div className="flex flex-col">
          <label className="text-xs text-gray-500 mb-1">Topic</label>
          <select
            value={topicFilter}
            onChange={e => setTopicFilter(e.target.value)}
            className="text-sm border border-gray-300 rounded-lg px-2 py-1.5 focus:outline-none focus:ring-2 focus:ring-[var(--brand-accent)]"
          >
            <option value="">All topics</option>
            {topics.map(t => (
              // Phase 26 D1 — option label reads description || name.
              <option key={t.id} value={t.id}>{t.name}</option>
            ))}
          </select>
        </div>
        <div className="flex flex-col">
          <label className="text-xs text-gray-500 mb-1">Sort</label>
          <select
            value={sort}
            onChange={e => setSort(e.target.value)}
            className="text-sm border border-gray-300 rounded-lg px-2 py-1.5 focus:outline-none focus:ring-2 focus:ring-[var(--brand-accent)]"
          >
            <option value="default">Most delegated + most transparent</option>
            <option value="alpha">Alphabetical</option>
          </select>
        </div>
        <label className="flex items-center gap-2 text-sm text-gray-700 ml-auto">
          <input
            type="checkbox"
            checked={activeOnly}
            onChange={e => setActiveOnly(e.target.checked)}
            className="rounded"
          />
          Active in last 30 days
        </label>
      </div>

      {/* Body */}
      {loading ? (
        <div className="flex justify-center items-center py-20">
          <div className="animate-spin w-8 h-8 border-4 border-[var(--brand-accent)] border-t-transparent rounded-full"></div>
        </div>
      ) : error ? (
        <div className="bg-red-50 border border-red-200 text-red-700 p-4 rounded-lg text-sm">
          {error}
        </div>
      ) : sorted.length === 0 ? (
        <div className="bg-white border border-gray-200 rounded-xl p-8 text-center text-sm text-gray-500">
          {topicFilter || activeOnly
            ? 'No delegates match these filters yet.'
            : 'No public delegates in this organization yet. Be the first — set up your delegate page.'}
        </div>
      ) : (
        <div className="space-y-3">
          {sorted.map(d => (
            <DelegateCard key={d.user_id} delegate={d} slug={slug} />
          ))}
        </div>
      )}

      {/* Pagination */}
      {!loading && (offset > 0 || hasMore) && (
        <div className="flex items-center justify-between pt-2">
          <button
            onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
            disabled={offset === 0}
            className="text-sm px-4 py-1.5 border border-gray-300 text-gray-600 rounded-lg hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            ← Previous
          </button>
          <span className="text-xs text-gray-400">
            Showing {offset + 1}–{offset + sorted.length}
          </span>
          <button
            onClick={() => setOffset(offset + PAGE_SIZE)}
            disabled={!hasMore}
            className="text-sm px-4 py-1.5 border border-gray-300 text-gray-600 rounded-lg hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            Next →
          </button>
        </div>
      )}
    </div>
  );
}

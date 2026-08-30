import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import api, { isAbortError } from '../api';
import { useOrg } from '../OrgContext';
import { urlFor } from '../utils/urls';
import {
  createProposalFeedLoader,
  emptyProposalFeedState,
  formatViewerVote,
  PROPOSAL_FEED_PAGE_SIZE,
  votingMethodLabel,
} from '../utils/proposalFeed';
import StatusBadge from '../components/StatusBadge';
import CountModeBadge from '../components/CountModeBadge';
import TopicBadge from '../components/TopicBadge';
import Spinner from '../components/Spinner';
import ErrorMessage from '../components/ErrorMessage';

const STATUS_FILTERS = ['all', 'deliberation', 'voting', 'unvoted', 'passed', 'failed', 'archived'];
const FILTER_LABELS = { unvoted: 'To vote' };
const filtersKey = slug => `proposalsFilters:${slug || 'global'}`;

function timeRemaining(votingEnd) {
  if (!votingEnd) return null;
  const milliseconds = new Date(votingEnd) - Date.now();
  if (milliseconds <= 0) return 'Closed';
  const days = Math.floor(milliseconds / 86400000);
  const hours = Math.floor((milliseconds % 86400000) / 3600000);
  if (days > 0) return `${days}d ${hours}h remaining`;
  const minutes = Math.floor((milliseconds % 3600000) / 60000);
  return `${hours}h ${minutes}m remaining`;
}

function ProposalCard({ item, subOrgsById, isReadOnly, linkOrg }) {
  const { proposal, viewer_vote: viewerVote } = item;
  const subOrg = proposal.sub_org_id ? subOrgsById?.[proposal.sub_org_id] : null;
  const isVoting = proposal.status === 'voting';
  const deadline = isVoting ? timeRemaining(proposal.voting_end) : null;

  return (
    <Link
      to={linkOrg ? urlFor(linkOrg, 'proposal-detail', proposal.id) : '#'}
      className="block bg-white border border-gray-200 rounded-xl p-4 sm:p-5 hover:border-[var(--brand-accent)] hover:shadow-sm transition-all focus:outline-none focus:ring-2 focus:ring-[var(--brand-accent)]"
    >
      <div className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-2 mb-3">
        <span className="text-[var(--brand-primary)] font-semibold text-lg leading-snug min-w-0">
          {proposal.title}
        </span>
        <div className="flex flex-wrap items-center gap-2 shrink-0">
          <StatusBadge status={proposal.status} votingMethod={proposal.voting_method} />
          <CountModeBadge countMode={proposal.count_mode} />
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2 mb-3 text-xs text-gray-500">
        <span className="bg-gray-100 text-gray-700 px-2 py-0.5 rounded-full">
          {votingMethodLabel(proposal.voting_method)}
        </span>
        {proposal.option_count > 0 && proposal.voting_method !== 'binary' && (
          <span>{proposal.option_count} options</span>
        )}
        {proposal.stable_result_required && (
          <span
            title="The result must remain stable across the closing portion of the voting window"
            className="bg-blue-50 text-[var(--brand-accent)] border border-blue-200 px-2 py-0.5 rounded-full"
          >
            Stable result required
          </span>
        )}
      </div>

      {subOrg && (
        <div className="flex flex-wrap items-center gap-2 mb-3">
          <span className="text-xs bg-cyan-50 text-cyan-700 border border-cyan-200 px-2 py-0.5 rounded-full font-medium">
            {subOrg.name}
          </span>
          {isReadOnly && (
            <span className="text-xs text-gray-500 italic">View only — you&apos;re not a member</span>
          )}
        </div>
      )}

      {proposal.topics?.length > 0 && (
        <div className="flex flex-wrap gap-1.5 mb-3">
          {proposal.topics.map(topicLink => (
            <TopicBadge
              key={topicLink.topic_id || topicLink.id}
              topic={topicLink.topic || topicLink}
              relevance={topicLink.relevance}
            />
          ))}
        </div>
      )}

      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 text-xs">
        <p className="text-gray-400">
          by {proposal.author?.display_name || 'Unknown author'}
          {proposal.created_at && ` · ${new Date(proposal.created_at).toLocaleDateString()}`}
        </p>
        {deadline && <p className="text-amber-700 font-medium">{deadline}</p>}
      </div>

      {proposal.status === 'deliberation' && (
        <p className="text-xs text-blue-600 mt-2">
          Deliberation period
          {proposal.voting_start
            ? ` · Opens for voting ${new Date(proposal.voting_start).toLocaleDateString()}`
            : ''}
        </p>
      )}

      {!isReadOnly && isVoting && (
        <p className={`text-xs mt-2 ${viewerVote?.has_effective_vote ? 'text-[var(--brand-accent)]' : 'text-gray-500'}`}>
          {formatViewerVote(proposal, viewerVote)}
        </p>
      )}
    </Link>
  );
}

export default function Proposals() {
  const { currentOrg, userOrgs, isMember } = useOrg();
  const readOnly = currentOrg ? !isMember : false;
  const scopeKey = currentOrg?.slug || 'global';
  const linkOrg = (() => {
    if (!currentOrg) return null;
    if (currentOrg.parent_org_id) {
      return userOrgs.find(org => org.id === currentOrg.parent_org_id) || null;
    }
    return currentOrg;
  })();

  const [topics, setTopics] = useState([]);
  const [subOrgsById, setSubOrgsById] = useState({});
  const [statusFilter, setStatusFilter] = useState('all');
  const [topicFilter, setTopicFilter] = useState('');
  const [filtersReadyFor, setFiltersReadyFor] = useState(null);
  const [retryGeneration, setRetryGeneration] = useState(0);
  const [feedState, setFeedState] = useState(() => emptyProposalFeedState());
  const [feedLoader] = useState(() => createProposalFeedLoader({
    get: (path, options) => api.get(path, options),
    isAbort: isAbortError,
    onChange: setFeedState,
  }));
  const { items, hasMore, loading, loadingMore, error, loadMoreError } = feedState;

  // The loader owns both initial and Load-more controllers, so cancellation
  // aborts whichever request is active at unmount. cancel() is reusable so
  // React development StrictMode's setup-cleanup-setup cycle remains valid.
  useEffect(() => () => feedLoader.cancel(), [feedLoader]);

  useEffect(() => {
    let savedStatus = 'all';
    let savedTopic = '';
    try {
      const raw = sessionStorage.getItem(filtersKey(scopeKey));
      if (raw) {
        const saved = JSON.parse(raw);
        if (STATUS_FILTERS.includes(saved.statusFilter)) savedStatus = saved.statusFilter;
        if (typeof saved.topicFilter === 'string') savedTopic = saved.topicFilter;
      }
    } catch {
      // Disabled or malformed session storage should not block browsing.
    }
    if (readOnly && savedStatus === 'unvoted') savedStatus = 'all';
    // Restoring an org-keyed external-storage snapshot requires one batched
    // state transition when the route scope changes.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setStatusFilter(savedStatus);
    setTopicFilter(savedTopic);
    setFiltersReadyFor(scopeKey);
  }, [scopeKey, readOnly]);

  useEffect(() => {
    if (filtersReadyFor !== scopeKey) return;
    try {
      sessionStorage.setItem(
        filtersKey(scopeKey),
        JSON.stringify({ statusFilter, topicFilter }),
      );
    } catch {
      // Browsing remains functional when storage is unavailable.
    }
  }, [filtersReadyFor, scopeKey, statusFilter, topicFilter]);

  useEffect(() => {
    const controller = new AbortController();
    if (readOnly) {
      return () => controller.abort();
    }
    const url = currentOrg ? `/api/orgs/${currentOrg.slug}/topics` : '/api/topics';
    api.get(url, { signal: controller.signal })
      .then(data => setTopics(Array.isArray(data) ? data : []))
      .catch(err => { if (!isAbortError(err)) setTopics([]); });
    return () => controller.abort();
  }, [currentOrg, readOnly]);

  useEffect(() => {
    const controller = new AbortController();
    if (!currentOrg || readOnly) {
      return () => controller.abort();
    }
    const parentSlug = currentOrg.parent_org_id
      ? userOrgs.find(org => org.id === currentOrg.parent_org_id)?.slug
      : currentOrg.slug;
    if (!parentSlug) return () => controller.abort();
    api.get(`/api/orgs/${parentSlug}/sub-orgs`, { signal: controller.signal })
      .then(list => {
        const next = {};
        for (const subOrg of list || []) next[subOrg.id] = subOrg;
        setSubOrgsById(next);
      })
      .catch(err => { if (!isAbortError(err)) setSubOrgsById({}); });
    return () => controller.abort();
  }, [currentOrg, readOnly, userOrgs]);

  useEffect(() => {
    if (filtersReadyFor !== scopeKey) return undefined;
    void feedLoader.reset({
      slug: currentOrg?.slug,
      readOnly,
      status: statusFilter,
      topicId: topicFilter,
    });
    return undefined;
  }, [currentOrg?.slug, feedLoader, filtersReadyFor, readOnly, retryGeneration, scopeKey, statusFilter, topicFilter]);

  const loadMore = () => {
    void feedLoader.loadMore({
      slug: currentOrg?.slug,
      readOnly,
      status: statusFilter,
      topicId: topicFilter,
      limit: PROPOSAL_FEED_PAGE_SIZE,
    });
  };

  const canCreateProposal = Array.isArray(currentOrg?.user_permissions)
    && currentOrg.user_permissions.includes('proposal.create');
  const adminProposalsHref = linkOrg ? urlFor(linkOrg, 'admin-proposals') : null;

  return (
    <div className="max-w-4xl mx-auto px-4 py-8">
      <div className="flex items-center justify-between gap-4 mb-6">
        <h1 className="text-2xl font-semibold text-[var(--brand-primary)]">Proposals</h1>
        {canCreateProposal && adminProposalsHref && (
          <Link
            to={`${adminProposalsHref}?create=1`}
            className="text-sm px-4 py-2 bg-[var(--brand-primary)] text-white rounded-lg hover:bg-[var(--brand-accent)] transition-colors"
          >
            Create proposal
          </Link>
        )}
      </div>

      <div className="flex flex-wrap gap-3 mb-6">
        <div
          role="group"
          aria-label="Filter proposals by status"
          className="grid grid-cols-4 w-full sm:flex sm:w-auto bg-white border border-gray-200 rounded-lg overflow-hidden"
        >
          {STATUS_FILTERS.filter(s => !(readOnly && s === 'unvoted')).map(s => (
            <button
              key={s}
              type="button"
              aria-pressed={statusFilter === s}
              onClick={() => setStatusFilter(s)}
              title={s === 'unvoted' ? "Voting proposals you haven't voted on yet" : undefined}
              className={`px-2 sm:px-3 py-1.5 text-sm capitalize transition-colors ${
                statusFilter === s
                  ? 'bg-[var(--brand-primary)] text-white'
                  : 'text-gray-600 hover:bg-gray-50'
              }`}
            >
              {FILTER_LABELS[s] || s}
            </button>
          ))}
        </div>

        {!readOnly && topics.length > 0 && (
          <select
            aria-label="Filter proposals by topic"
            value={topicFilter}
            onChange={event => setTopicFilter(event.target.value)}
            className="bg-white border border-gray-200 rounded-lg px-3 py-1.5 text-sm text-gray-600 focus:outline-none focus:ring-1 focus:ring-[var(--brand-accent)]"
          >
            <option value="">All Topics</option>
            {topics.map(topic => <option key={topic.id} value={topic.id}>{topic.name}</option>)}
          </select>
        )}
      </div>

      {loading ? (
        <div aria-live="polite" aria-busy="true"><Spinner /></div>
      ) : error ? (
        <ErrorMessage error={error} onRetry={() => setRetryGeneration(value => value + 1)} />
      ) : items.length === 0 ? (
        <div className="text-center py-16 text-gray-400">
          {statusFilter === 'unvoted' ? (
            <>
              <p className="text-lg mb-2">You&apos;re all caught up</p>
              <p className="text-sm">
                {topicFilter
                  ? 'No open votes left for you in this topic.'
                  : "There are no open votes you haven't cast yet."}
              </p>
            </>
          ) : statusFilter === 'all' && !topicFilter ? (
            <>
              <p className="text-lg mb-2">No proposals yet</p>
              {canCreateProposal && adminProposalsHref ? (
                <>
                  <p className="text-sm mb-4">Start with a real, low-stakes decision for your members.</p>
                  <Link
                    to={`${adminProposalsHref}?create=1`}
                    className="inline-flex text-sm px-4 py-2 bg-[var(--brand-primary)] text-white rounded-lg hover:bg-[var(--brand-accent)] transition-colors"
                  >
                    Create your first proposal
                  </Link>
                </>
              ) : (
                <p className="text-sm">A steward hasn&apos;t opened the organization&apos;s first proposal yet.</p>
              )}
            </>
          ) : (
            <>
              <p className="text-lg mb-2">No proposals found</p>
              <p className="text-sm">
                Try a different filter, or{' '}
                <button
                  type="button"
                  onClick={() => { setStatusFilter('all'); setTopicFilter(''); }}
                  className="text-[var(--brand-accent)] hover:underline"
                >
                  clear all filters
                </button>
              </p>
            </>
          )}
        </div>
      ) : (
        <>
          <div className="space-y-4">
            {items.map(item => {
              const subOrg = item.proposal.sub_org_id
                ? subOrgsById[item.proposal.sub_org_id]
                : null;
              return (
                <ProposalCard
                  key={item.proposal.id}
                  item={item}
                  subOrgsById={subOrgsById}
                  isReadOnly={readOnly || (!!subOrg && !subOrg.user_role)}
                  linkOrg={linkOrg}
                />
              );
            })}
          </div>

          <div className="mt-8 text-center" aria-live="polite">
            {loadMoreError && <p className="text-sm text-red-700 mb-3">{loadMoreError}</p>}
            {hasMore ? (
              <button
                type="button"
                onClick={loadMore}
                disabled={loadingMore}
                aria-busy={loadingMore}
                className="px-5 py-2.5 bg-white border border-gray-300 rounded-lg text-sm font-medium text-[var(--brand-primary)] hover:border-[var(--brand-accent)] disabled:opacity-60 disabled:cursor-wait focus:outline-none focus:ring-2 focus:ring-[var(--brand-accent)]"
              >
                {loadingMore ? 'Loading more proposals…' : 'Load more proposals'}
              </button>
            ) : (
              <p className="text-sm text-gray-400">All proposals loaded</p>
            )}
          </div>
        </>
      )}
    </div>
  );
}

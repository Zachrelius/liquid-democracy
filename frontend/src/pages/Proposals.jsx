import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import api from '../api';
import { useOrg } from '../OrgContext';
import StatusBadge from '../components/StatusBadge';
import TopicBadge from '../components/TopicBadge';
import VoteBar from '../components/VoteBar';
import Spinner from '../components/Spinner';
import ErrorMessage from '../components/ErrorMessage';

const STATUS_FILTERS = ['all', 'deliberation', 'voting', 'passed', 'failed'];

function timeRemaining(votingEnd) {
  if (!votingEnd) return null;
  const ms = new Date(votingEnd) - Date.now();
  if (ms <= 0) return 'Closed';
  const days = Math.floor(ms / 86400000);
  const hours = Math.floor((ms % 86400000) / 3600000);
  if (days > 0) return `${days}d ${hours}h remaining`;
  const mins = Math.floor((ms % 3600000) / 60000);
  return `${hours}h ${mins}m remaining`;
}

function ProposalCard({ proposal, myVote, tally, subOrgsById, isReadOnly }) {
  const subOrg = proposal.sub_org_id ? subOrgsById?.[proposal.sub_org_id] : null;
  return (
    <Link
      to={`/proposals/${proposal.id}`}
      className="block bg-white border border-gray-200 rounded-xl p-5 hover:border-[#2E75B6] hover:shadow-sm transition-all"
    >
      <div className="flex items-start justify-between gap-3 mb-3">
        <span className="text-[#1B3A5C] font-semibold text-lg leading-snug">
          {proposal.title}
          {/* Phase 8 — sustained-majority indicator. Shown when the proposal
              has it explicitly enabled OR when results call back active=true. */}
          {(proposal.sustained_majority_enabled === true ||
            tally?.sustained_majority?.active) && (
            <span
              title="Sustained-majority voting: support must hold throughout the window"
              className="ml-2 inline-flex items-center text-xs bg-blue-50 text-[#2E75B6] border border-blue-200 px-1.5 py-0.5 rounded"
            >
              ⏳ Sustained
            </span>
          )}
        </span>
        <StatusBadge status={proposal.status} />
      </div>

      {/* Phase 8.5 — sub-org badge + Decision 7 read-only hint */}
      {subOrg && (
        <div className="flex flex-wrap items-center gap-2 mb-3">
          <span className="text-xs bg-cyan-50 text-cyan-700 border border-cyan-200 px-2 py-0.5 rounded-full font-medium">
            {subOrg.name}
          </span>
          {isReadOnly && (
            <span className="text-xs text-gray-500 italic">
              View only — you&apos;re not a member
            </span>
          )}
        </div>
      )}

      {/* Topic badges */}
      {proposal.topics?.length > 0 && (
        <div className="flex flex-wrap gap-1.5 mb-3">
          {proposal.topics.map(pt => (
            <TopicBadge key={pt.topic_id} topic={pt.topic} relevance={pt.relevance} />
          ))}
        </div>
      )}

      {/* Author */}
      <p className="text-xs text-gray-400 mb-3">
        by {proposal.author?.display_name}
        {proposal.created_at && ` · ${new Date(proposal.created_at).toLocaleDateString()}`}
      </p>

      {/* Voting status */}
      {proposal.status === 'voting' && tally && (
        <div className="space-y-2">
          <VoteBar yes={tally.yes} no={tally.no} abstain={tally.abstain} />
          <div className="flex items-center justify-between text-xs text-gray-500">
            <span>{tally.votes_cast ?? (tally.yes + tally.no + tally.abstain)} of {tally.total_eligible} votes cast</span>
            {proposal.voting_end && <span>{timeRemaining(proposal.voting_end)}</span>}
          </div>
          {myVote && (
            <p className="text-xs text-[#2E75B6]">
              Your vote: {myVote.vote_value?.toUpperCase() ?? 'Not cast'}
              {myVote.cast_by && !myVote.is_direct ? ` via ${myVote.cast_by.display_name}` : ''}
            </p>
          )}
        </div>
      )}

      {proposal.status === 'deliberation' && (
        <p className="text-xs text-blue-500">
          Deliberation period
          {proposal.voting_start ? ` · Opens for voting ${new Date(proposal.voting_start).toLocaleDateString()}` : ''}
        </p>
      )}

      {(proposal.status === 'passed' || proposal.status === 'failed') && tally && (
        <div className="space-y-1">
          <VoteBar yes={tally.yes} no={tally.no} abstain={tally.abstain} />
          <p className="text-xs text-gray-500">Final result</p>
        </div>
      )}
    </Link>
  );
}

export default function Proposals() {
  const { currentOrg, userOrgs } = useOrg();
  const [proposals, setProposals] = useState([]);
  const [topics, setTopics] = useState([]);
  const [tallies, setTallies] = useState({});
  const [myVotes, setMyVotes] = useState({});
  const [statusFilter, setStatusFilter] = useState('all');
  const [topicFilter, setTopicFilter] = useState('');
  // Phase 8.5 — UI-only scope filter. 'all' (default) keeps the existing
  // server payload as-is; 'current' narrows to proposals whose sub_org_id
  // matches currentOrg when currentOrg is itself a sub-org.
  const [scopeFilter, setScopeFilter] = useState('all');
  const [subOrgsById, setSubOrgsById] = useState({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    const topicsUrl = currentOrg
      ? `/api/orgs/${currentOrg.slug}/topics`
      : '/api/topics';
    api.get(topicsUrl).then(setTopics).catch(() => {});
  }, [currentOrg]);

  // Phase 8.5 — fetch the parent's sub-orgs so we can render scope badges
  // and the Decision-7 read-only hint on cards. Resolves the parent slug
  // from currentOrg (walking up if currentOrg is itself a sub-org).
  useEffect(() => {
    if (!currentOrg) return;
    let parentSlug;
    if (currentOrg.parent_org_id) {
      const parent = userOrgs.find(o => o.id === currentOrg.parent_org_id);
      parentSlug = parent?.slug;
    } else {
      parentSlug = currentOrg.slug;
    }
    if (!parentSlug) return;
    api.get(`/api/orgs/${parentSlug}/sub-orgs`)
      .then(list => {
        const map = {};
        for (const s of list || []) map[s.id] = s;
        setSubOrgsById(map);
      })
      .catch(() => setSubOrgsById({}));
  }, [currentOrg, userOrgs]);

  useEffect(() => {
    setLoading(true);
    setError('');
    const params = new URLSearchParams();
    if (statusFilter !== 'all') params.set('status', statusFilter);
    if (topicFilter) params.set('topic_id', topicFilter);
    const qs = params.toString() ? `?${params}` : '';

    const proposalsUrl = currentOrg
      ? `/api/orgs/${currentOrg.slug}/proposals${qs}`
      : `/api/proposals${qs}`;

    api.get(proposalsUrl)
      .then(async (data) => {
        setProposals(data);

        // Fetch tallies for voting/passed/failed proposals
        const votingProposals = data.filter(p =>
          ['voting', 'passed', 'failed'].includes(p.status)
        );
        const [tallyResults, myVoteResults] = await Promise.all([
          Promise.allSettled(votingProposals.map(p =>
            api.get(`/api/proposals/${p.id}/results`)
          )),
          Promise.allSettled(votingProposals.map(p =>
            api.get(`/api/proposals/${p.id}/my-vote`)
          )),
        ]);

        const newTallies = {};
        const newMyVotes = {};
        votingProposals.forEach((p, i) => {
          if (tallyResults[i].status === 'fulfilled') newTallies[p.id] = tallyResults[i].value;
          if (myVoteResults[i].status === 'fulfilled') newMyVotes[p.id] = myVoteResults[i].value;
        });
        setTallies(newTallies);
        setMyVotes(newMyVotes);
      })
      .catch(err => setError(err.message || 'Failed to load proposals'))
      .finally(() => setLoading(false));
  }, [statusFilter, topicFilter, currentOrg]);

  return (
    <div className="max-w-4xl mx-auto px-4 py-8">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-semibold text-[#1B3A5C]">Proposals</h1>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap gap-3 mb-6">
        {/* Status filter */}
        <div className="flex bg-white border border-gray-200 rounded-lg overflow-hidden">
          {STATUS_FILTERS.map(s => (
            <button
              key={s}
              onClick={() => setStatusFilter(s)}
              className={`px-3 py-1.5 text-sm capitalize transition-colors ${
                statusFilter === s
                  ? 'bg-[#1B3A5C] text-white'
                  : 'text-gray-600 hover:bg-gray-50'
              }`}
            >
              {s}
            </button>
          ))}
        </div>

        {/* Topic filter */}
        {topics.length > 0 && (
          <select
            value={topicFilter}
            onChange={e => setTopicFilter(e.target.value)}
            className="bg-white border border-gray-200 rounded-lg px-3 py-1.5 text-sm text-gray-600 focus:outline-none focus:ring-1 focus:ring-[#2E75B6]"
          >
            <option value="">All Topics</option>
            {topics.map(t => (
              <option key={t.id} value={t.id}>{t.name}</option>
            ))}
          </select>
        )}

        {/* Phase 8.5 — scope filter. Only meaningful when currentOrg is a
            sub-org (server already returns the right payload; this is a
            UI narrow). */}
        {currentOrg?.parent_org_id && (
          <div className="flex bg-white border border-gray-200 rounded-lg overflow-hidden">
            <button
              onClick={() => setScopeFilter('all')}
              className={`px-3 py-1.5 text-sm transition-colors ${
                scopeFilter === 'all'
                  ? 'bg-[#1B3A5C] text-white'
                  : 'text-gray-600 hover:bg-gray-50'
              }`}
            >
              Everything I&apos;m eligible for
            </button>
            <button
              onClick={() => setScopeFilter('current')}
              className={`px-3 py-1.5 text-sm transition-colors ${
                scopeFilter === 'current'
                  ? 'bg-[#1B3A5C] text-white'
                  : 'text-gray-600 hover:bg-gray-50'
              }`}
            >
              {currentOrg.name} only
            </button>
          </div>
        )}
      </div>

      {/* Content */}
      {loading ? (
        <Spinner />
      ) : error ? (
        <ErrorMessage error={error} onRetry={() => { setStatusFilter('all'); setTopicFilter(''); }} />
      ) : proposals.length === 0 ? (
        <div className="text-center py-16 text-gray-400">
          {statusFilter === 'all' && !topicFilter ? (
            <>
              <p className="text-lg mb-2">No proposals yet</p>
              <p className="text-sm">Create one from the admin panel to get started.</p>
            </>
          ) : (
            <>
              <p className="text-lg mb-2">No proposals found</p>
              <p className="text-sm">
                Try a different filter, or{' '}
                <button
                  onClick={() => { setStatusFilter('all'); setTopicFilter(''); }}
                  className="text-[#2E75B6] hover:underline"
                >
                  clear all filters
                </button>
              </p>
            </>
          )}
        </div>
      ) : (
        <div className="space-y-4">
          {proposals
            .filter(p => {
              if (scopeFilter !== 'current') return true;
              // 'current' narrows to the current sub-org. Only meaningful when
              // currentOrg is a sub-org; the toggle isn't shown otherwise.
              return p.sub_org_id === currentOrg?.id;
            })
            .map(p => {
              const subOrg = p.sub_org_id ? subOrgsById[p.sub_org_id] : null;
              // Decision 7 — non-member viewers see read-only treatment. The
              // sub-org's user_role is null when the viewer isn't an active
              // member; non-null when they are.
              const isReadOnly = !!subOrg && !subOrg.user_role;
              return (
                <ProposalCard
                  key={p.id}
                  proposal={p}
                  tally={tallies[p.id]}
                  myVote={myVotes[p.id]}
                  subOrgsById={subOrgsById}
                  isReadOnly={isReadOnly}
                />
              );
            })}
        </div>
      )}
    </div>
  );
}

import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import api from '../api';
import { useOrg } from '../OrgContext';
import { urlFor } from '../utils/urls';
import StatusBadge from '../components/StatusBadge';
import TopicBadge from '../components/TopicBadge';
import VoteBar from '../components/VoteBar';
import MultiOptionResultBar from '../components/MultiOptionResultBar';
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

// Phase 7D helpers — pure shape transforms for the proposals list card.
//
// Approval: build per-option bars from `tally.option_approvals` keyed by
// option id, sorted approval-count-descending. Bars are independent —
// percentage = approvals / votes_cast, NOT normalized across options.
function buildApprovalBars(proposal, tally) {
  const counts = tally?.option_approvals || {};
  const winners = new Set(tally?.winners || []);
  const total = tally?.votes_cast || tally?.total_ballots_cast || 0;
  const optsByLabel = (proposal.options || []).map(o => ({
    id: o.id,
    label: o.label,
    count: counts[o.id] ?? 0,
  }));
  optsByLabel.sort((a, b) => b.count - a.count);
  return optsByLabel.map(o => ({
    label: o.label,
    percentage: total > 0 ? (o.count / total) * 100 : 0,
    isWinner: winners.has(o.id),
  }));
}

// RCV/STV: first-choice share comes from `tally.rounds[0].option_counts`.
// Sorted first-choice-count-descending. Winners come from `tally.winners`
// (the eventual elimination/STV winners — which may differ from
// first-choice leader). Denominator is `tally.votes_cast` so bar widths
// reflect ballots-cast share, not within-round share.
function buildRankedChoiceBars(proposal, tally) {
  const round0 = Array.isArray(tally?.rounds) && tally.rounds.length > 0
    ? tally.rounds[0]
    : null;
  const counts = round0?.option_counts || {};
  const winners = new Set(tally?.winners || []);
  const total = tally?.votes_cast || tally?.total_ballots_cast || 0;
  const items = (proposal.options || []).map(o => ({
    id: o.id,
    label: o.label,
    count: counts[o.id] ?? 0,
  }));
  items.sort((a, b) => b.count - a.count);
  return items.map(o => ({
    label: o.label,
    percentage: total > 0 ? (o.count / total) * 100 : 0,
    isWinner: winners.has(o.id),
  }));
}

function lookupLabel(proposal, optionId) {
  const opt = (proposal.options || []).find(o => o.id === optionId);
  return opt?.label || optionId;
}

// Heading text for closed multi-option proposals: "Winner: X" / "Winners: X, Y"
// / "Tied: X, Y" depending on tally.winners and tally.tied. tied=true wins
// over the winner-count framing per spec — when the backend hasn't resolved a
// tie, render "Tied: ..." rather than picking arbitrarily.
function closedHeading(proposal, tally) {
  const winnerIds = Array.isArray(tally?.winners) ? tally.winners : [];
  if (winnerIds.length === 0) return null;
  const labels = winnerIds.map(id => lookupLabel(proposal, id));
  if (tally?.tied === true && !tally?.tie_resolution) {
    return `Tied: ${labels.join(', ')}`;
  }
  if (winnerIds.length === 1) return `Winner: ${labels[0]}`;
  return `Winners: ${labels.join(', ')}`;
}

// "Your vote" line per ballot type. Returns null when no vote info available
// (parent renders "Not cast" itself). For multi-option: tied winners get
// isWinner styling on bars, but the "Your vote" line is always plain blue.
function yourVoteLine(proposal, myVote) {
  if (!myVote) return 'Your vote: Not cast';
  const viaSuffix = (myVote.cast_by && !myVote.is_direct)
    ? ` via ${myVote.cast_by.display_name}`
    : '';
  if (proposal.voting_method === 'binary') {
    if (!myVote.vote_value) return 'Your vote: Not cast';
    return `Your vote: ${myVote.vote_value.toUpperCase()}${viaSuffix}`;
  }
  if (proposal.voting_method === 'approval') {
    const n = Array.isArray(myVote.approvals) ? myVote.approvals.length : 0;
    if (n === 0 && !myVote.cast_by) return 'Your vote: Not cast';
    return `Your vote: ${n} option${n === 1 ? '' : 's'} approved${viaSuffix}`;
  }
  if (proposal.voting_method === 'ranked_choice') {
    const n = Array.isArray(myVote.ranking) ? myVote.ranking.length : 0;
    const m = (proposal.options || []).length;
    if (n === 0 && !myVote.cast_by) return 'Your vote: Not cast';
    return `Your vote: ranked ${n} of ${m} option${m === 1 ? '' : 's'}${viaSuffix}`;
  }
  return 'Your vote: Not cast';
}

function ProposalCard({ proposal, myVote, tally, subOrgsById, isReadOnly, linkOrg }) {
  const subOrg = proposal.sub_org_id ? subOrgsById?.[proposal.sub_org_id] : null;
  const method = proposal.voting_method;
  const isClosed = proposal.status === 'passed' || proposal.status === 'failed';
  const isVoting = proposal.status === 'voting';

  // Per-method body content — bar block + "Your vote" line + meta line.
  let bodyBlock = null;
  if (tally && (isVoting || isClosed)) {
    const metaLine = (
      <div className="flex items-center justify-between text-xs text-gray-500">
        <span>
          {tally.votes_cast ?? ((tally.yes ?? 0) + (tally.no ?? 0) + (tally.abstain ?? 0))} of {tally.total_eligible} votes cast
        </span>
        {isVoting && proposal.voting_end && <span>{timeRemaining(proposal.voting_end)}</span>}
      </div>
    );
    const voteLine = (
      <p className="text-xs text-[var(--brand-accent)]">{yourVoteLine(proposal, myVote)}</p>
    );

    if (method === 'binary') {
      // Binary preserved bit-for-bit from pre-7D: voting state shows the bar,
      // the meta line, and "Your vote" if cast; closed shows the bar and
      // "Final result". The status badge ("Passed"/"Failed") carries the
      // outcome on closed binary cards.
      bodyBlock = isClosed ? (
        <div className="space-y-1">
          <VoteBar yes={tally.yes} no={tally.no} abstain={tally.abstain} />
          <p className="text-xs text-gray-500">Final result</p>
        </div>
      ) : (
        <div className="space-y-2">
          <VoteBar yes={tally.yes} no={tally.no} abstain={tally.abstain} />
          {metaLine}
          {myVote && voteLine}
        </div>
      );
    } else if (method === 'approval' || method === 'ranked_choice') {
      const bars = method === 'approval'
        ? buildApprovalBars(proposal, tally)
        : buildRankedChoiceBars(proposal, tally);
      const heading = isClosed ? closedHeading(proposal, tally) : null;
      bodyBlock = (
        <div className="space-y-2">
          {heading && (
            <p className="text-sm font-semibold text-[var(--brand-primary)]">{heading}</p>
          )}
          <MultiOptionResultBar options={bars} />
          {metaLine}
          {isVoting && voteLine}
        </div>
      );
    }
  }

  return (
    <Link
      to={linkOrg ? urlFor(linkOrg, 'proposal-detail', proposal.id) : '#'}
      className="block bg-white border border-gray-200 rounded-xl p-5 hover:border-[var(--brand-accent)] hover:shadow-sm transition-all"
    >
      <div className="flex items-start justify-between gap-3 mb-3">
        <span className="text-[var(--brand-primary)] font-semibold text-lg leading-snug">
          {proposal.title}
          {/* Phase 20 — Stable Result Required indicator. Shown when the
              proposal has it explicitly enabled OR when results call back
              active=true. The backend preserves the JSON key `sustained_majority`
              on the results payload for one pass for backwards compat. */}
          {(proposal.stable_result_required === true ||
            tally?.sustained_majority?.active) && (
            <span
              title="Stable Result Required: the result must be stable across the closing portion of the voting window"
              className="ml-2 inline-flex items-center text-xs bg-blue-50 text-[var(--brand-accent)] border border-blue-200 px-1.5 py-0.5 rounded"
            >
              ⏳ Stable Result
            </span>
          )}
        </span>
        <StatusBadge status={proposal.status} votingMethod={method} />
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

      {bodyBlock}

      {proposal.status === 'deliberation' && (
        <p className="text-xs text-blue-500">
          Deliberation period
          {proposal.voting_start ? ` · Opens for voting ${new Date(proposal.voting_start).toLocaleDateString()}` : ''}
        </p>
      )}
    </Link>
  );
}

export default function Proposals() {
  const { currentOrg, userOrgs } = useOrg();
  // Phase 11 — proposal-detail routes are parent-org-rooted. If currentOrg
  // is itself a sub-org, walk up to the parent for link construction.
  const linkOrg = (() => {
    if (!currentOrg) return null;
    if (currentOrg.parent_org_id) {
      return userOrgs.find(o => o.id === currentOrg.parent_org_id) || null;
    }
    return currentOrg;
  })();
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

  // Phase 16 F2 — surface a "Create proposal" button to any user with the
  // `proposal.create` permission. Routes to the existing creation form on
  // /{slug}/admin/proposals (Option B in spec §F2): the AdminRoute wrapper
  // already accepts the `proposals` subsection permission set — which
  // includes `proposal.create` — so a Member granted just that one key can
  // reach the form. No new route added; the form is structurally tied to
  // the management page (proposals table + create button + advance/withdraw
  // actions live together) so duplicating the route under a non-admin path
  // would only re-render the same component.
  const canCreateProposal = Array.isArray(currentOrg?.user_permissions)
    && currentOrg.user_permissions.includes('proposal.create');
  // Resolve the parent slug for the admin link the same way as the
  // proposal-detail link above (sub-org scope walks up to the parent
  // because the admin/proposals page lives under the parent's slug).
  const adminProposalsHref = linkOrg ? urlFor(linkOrg, 'admin-proposals') : null;

  return (
    <div className="max-w-4xl mx-auto px-4 py-8">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-semibold text-[var(--brand-primary)]">Proposals</h1>
        {canCreateProposal && adminProposalsHref && (
          <Link
            // Phase 25 F1 — append ?create=1 so the admin page opens
            // directly on the create form instead of dropping the user
            // on the proposals list with a second "Create" button to click.
            to={`${adminProposalsHref}?create=1`}
            className="text-sm px-4 py-2 bg-[var(--brand-primary)] text-white rounded-lg hover:bg-[var(--brand-accent)] transition-colors"
          >
            Create proposal
          </Link>
        )}
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
                  ? 'bg-[var(--brand-primary)] text-white'
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
            className="bg-white border border-gray-200 rounded-lg px-3 py-1.5 text-sm text-gray-600 focus:outline-none focus:ring-1 focus:ring-[var(--brand-accent)]"
          >
            <option value="">All Topics</option>
            {topics.map(t => (
              // Phase 26 D1 — option label reads description || name.
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
                  ? 'bg-[var(--brand-primary)] text-white'
                  : 'text-gray-600 hover:bg-gray-50'
              }`}
            >
              Everything I&apos;m eligible for
            </button>
            <button
              onClick={() => setScopeFilter('current')}
              className={`px-3 py-1.5 text-sm transition-colors ${
                scopeFilter === 'current'
                  ? 'bg-[var(--brand-primary)] text-white'
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
                  className="text-[var(--brand-accent)] hover:underline"
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
                  linkOrg={linkOrg}
                />
              );
            })}
        </div>
      )}
    </div>
  );
}

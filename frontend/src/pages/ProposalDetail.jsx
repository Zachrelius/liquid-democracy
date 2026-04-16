import { useState, useEffect, useCallback } from 'react';
import { useParams, Link } from 'react-router-dom';
import api from '../api';
import StatusBadge from '../components/StatusBadge';
import TopicBadge from '../components/TopicBadge';
import VoteBar from '../components/VoteBar';
import VoteFlowGraph from '../components/VoteFlowGraph';
import UserLink from '../components/UserLink';
import Spinner from '../components/Spinner';
import ErrorMessage from '../components/ErrorMessage';

// Simple markdown renderer (no external dep needed for basics)
function renderMarkdown(text) {
  if (!text) return '';
  return text
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/^### (.+)$/gm, '<h3>$1</h3>')
    .replace(/^## (.+)$/gm, '<h2>$1</h2>')
    .replace(/^# (.+)$/gm, '<h1>$1</h1>')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.+?)\*/g, '<em>$1</em>')
    .replace(/`(.+?)`/g, '<code>$1</code>')
    .replace(/^[-*] (.+)$/gm, '<li>$1</li>')
    .replace(/(<li>.*<\/li>)/s, '<ul>$1</ul>')
    .replace(/\n\n/g, '</p><p>')
    .replace(/^(?!<[hul])(.+)$/gm, (m) => m.startsWith('<') ? m : m);
}

const VOTE_COLORS = {
  yes: { bg: 'bg-[#2D8A56]', border: 'border-[#2D8A56]', text: 'text-[#2D8A56]', hover: 'hover:bg-[#2D8A56] hover:text-white' },
  no: { bg: 'bg-[#C0392B]', border: 'border-[#C0392B]', text: 'text-[#C0392B]', hover: 'hover:bg-[#C0392B] hover:text-white' },
  abstain: { bg: 'bg-[#7F8C8D]', border: 'border-[#7F8C8D]', text: 'text-[#7F8C8D]', hover: 'hover:bg-[#7F8C8D] hover:text-white' },
};

function VoteButtons({ onVote, casting, currentValue }) {
  return (
    <div className="flex gap-2">
      {['yes', 'no', 'abstain'].map(v => {
        const c = VOTE_COLORS[v];
        const active = currentValue === v;
        return (
          <button
            key={v}
            onClick={() => onVote(v)}
            disabled={casting}
            className={`flex-1 py-2.5 rounded-lg border-2 text-sm font-semibold capitalize transition-colors disabled:opacity-50
              ${active
                ? `${c.bg} ${c.border} text-white`
                : `bg-white ${c.border} ${c.text} ${c.hover}`
              }`}
          >
            {v}
          </button>
        );
      })}
    </div>
  );
}

function VoteStatusBox({ myVote, proposalId, onVoteChange }) {
  const [showButtons, setShowButtons] = useState(false);
  const [casting, setCasting] = useState(false);
  const [err, setErr] = useState('');

  const hasVote = myVote?.vote_value != null;
  const isDirect = myVote?.is_direct;

  async function castVote(value) {
    setCasting(true);
    setErr('');
    try {
      await api.post(`/api/proposals/${proposalId}/vote`, { vote_value: value });
      setShowButtons(false);
      onVoteChange();
    } catch (e) {
      setErr(e.message);
    } finally {
      setCasting(false);
    }
  }

  async function retractVote() {
    setCasting(true);
    setErr('');
    try {
      await api.delete(`/api/proposals/${proposalId}/vote`);
      setShowButtons(false);
      onVoteChange();
    } catch (e) {
      setErr(e.message);
    } finally {
      setCasting(false);
    }
  }

  const voteColor = hasVote ? VOTE_COLORS[myVote.vote_value]?.text : '';

  return (
    <div className="bg-gray-50 border border-gray-200 rounded-xl p-4 space-y-3">
      <h3 className="text-sm font-semibold text-gray-700 uppercase tracking-wide">Your Vote</h3>

      {hasVote ? (
        <div>
          <div className={`text-2xl font-bold mb-0.5 ${voteColor}`}>
            {myVote.vote_value.toUpperCase()}
          </div>
          <p className="text-sm text-gray-500">
            {isDirect
              ? 'You voted directly'
              : myVote.cast_by
                ? <>Via <UserLink user={myVote.cast_by} className="text-sm" />{myVote.delegate_chain?.length > 1 ? ' (chain)' : ''}</>
                : myVote.message}
          </p>

          {!showButtons && (
            <div className="flex gap-2 mt-3">
              <button
                onClick={() => setShowButtons(true)}
                className="text-xs px-3 py-1.5 border border-[#2E75B6] text-[#2E75B6] rounded-lg hover:bg-[#2E75B6] hover:text-white transition-colors"
              >
                {isDirect ? 'Change Vote' : 'Override — Vote Directly'}
              </button>
              {isDirect && (
                <button
                  onClick={retractVote}
                  disabled={casting}
                  className="text-xs px-3 py-1.5 border border-gray-300 text-gray-500 rounded-lg hover:bg-gray-100 transition-colors disabled:opacity-50"
                >
                  Retract
                </button>
              )}
            </div>
          )}
        </div>
      ) : (
        <div>
          <p className="text-gray-500 text-sm mb-3">
            {myVote?.message || 'No vote cast'}
          </p>
          {!showButtons && (
            <button
              onClick={() => setShowButtons(true)}
              className="text-sm px-3 py-1.5 bg-[#1B3A5C] text-white rounded-lg hover:bg-[#2E75B6] transition-colors"
            >
              Vote Now
            </button>
          )}
        </div>
      )}

      {showButtons && (
        <div className="space-y-2">
          <VoteButtons
            onVote={castVote}
            casting={casting}
            currentValue={isDirect ? myVote?.vote_value : null}
          />
          <button
            onClick={() => setShowButtons(false)}
            className="w-full text-xs text-gray-400 hover:text-gray-600"
          >
            Cancel
          </button>
        </div>
      )}

      {err && <p className="text-xs text-red-600">{err}</p>}
    </div>
  );
}

function ResultsPanel({ tally, proposal }) {
  if (!tally) return null;
  const cast = tally.yes + tally.no + tally.abstain;
  const quorumMet = tally.quorum_met;
  const thresholdMet = tally.threshold_met;

  return (
    <div className="space-y-4">
      <h3 className="text-sm font-semibold text-gray-700 uppercase tracking-wide">Current Results</h3>
      <VoteBar yes={tally.yes} no={tally.no} abstain={tally.abstain} showLabels={false} />

      <div className="grid grid-cols-3 gap-2 text-center">
        {[
          { label: 'Yes', val: tally.yes, pct: tally.yes_pct, color: 'text-[#2D8A56]' },
          { label: 'No', val: tally.no, pct: tally.no_pct, color: 'text-[#C0392B]' },
          { label: 'Abstain', val: tally.abstain, pct: tally.abstain_pct, color: 'text-gray-500' },
        ].map(({ label, val, pct, color }) => (
          <div key={label} className="bg-gray-50 rounded-lg p-2">
            <div className={`text-lg font-bold ${color}`}>{val}</div>
            <div className="text-xs text-gray-400">{label}</div>
            <div className="text-xs text-gray-500">{(pct * 100).toFixed(1)}%</div>
          </div>
        ))}
      </div>

      <div className="text-sm text-gray-500 space-y-1">
        <p>{cast} of {tally.total_eligible} eligible votes cast
          {tally.total_eligible > 0
            ? ` (${((cast / tally.total_eligible) * 100).toFixed(1)}%)`
            : ''
          }
        </p>
        <p>
          Quorum{' '}
          <span className={quorumMet ? 'text-[#2D8A56] font-medium' : 'text-[#C0392B]'}>
            {quorumMet ? '✓ met' : '✗ not met'}
          </span>
          {' '}(need {Math.round(proposal.quorum_threshold * 100)}%)
        </p>
        <p>
          Threshold{' '}
          <span className={thresholdMet ? 'text-[#2D8A56] font-medium' : 'text-[#C0392B]'}>
            {thresholdMet ? '✓ met' : '✗ not met'}
          </span>
          {' '}(need {Math.round(proposal.pass_threshold * 100)}% Yes)
        </p>
      </div>
    </div>
  );
}

export default function ProposalDetail() {
  const { id } = useParams();
  const [proposal, setProposal] = useState(null);
  const [tally, setTally] = useState(null);
  const [myVote, setMyVote] = useState(null);
  const [voteGraph, setVoteGraph] = useState(null);
  const [graphOpen, setGraphOpen] = useState(window.innerWidth >= 768);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const fetchData = useCallback(async () => {
    try {
      const [p, t, mv] = await Promise.allSettled([
        api.get(`/api/proposals/${id}`),
        api.get(`/api/proposals/${id}/results`),
        api.get(`/api/proposals/${id}/my-vote`),
      ]);
      if (p.status === 'fulfilled') setProposal(p.value);
      else throw p.reason;
      if (t.status === 'fulfilled') setTally(t.value);
      if (mv.status === 'fulfilled') setMyVote(mv.value);

      // Fetch vote graph for voting/passed/failed
      const prop = p.status === 'fulfilled' ? p.value : null;
      if (prop && ['voting', 'passed', 'failed'].includes(prop.status)) {
        try {
          const graph = await api.get(`/api/proposals/${id}/vote-graph`);
          setVoteGraph(graph);
        } catch {/* graph is optional — don't fail the page */}
      }
    } catch (e) {
      setError(e.message || 'Failed to load proposal');
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const refreshVote = useCallback(async () => {
    try {
      const [t, mv] = await Promise.all([
        api.get(`/api/proposals/${id}/results`),
        api.get(`/api/proposals/${id}/my-vote`),
      ]);
      setTally(t);
      setMyVote(mv);
      // Also refresh vote graph
      try {
        const graph = await api.get(`/api/proposals/${id}/vote-graph`);
        setVoteGraph(graph);
      } catch {/* ignore */}
    } catch {/* ignore */}
  }, [id]);

  if (loading) return <Spinner />;
  if (error) return (
    <div className="max-w-4xl mx-auto px-4 py-8">
      <ErrorMessage error={error} onRetry={fetchData} />
    </div>
  );
  if (!proposal) return null;

  const isVoting = proposal.status === 'voting';
  const isClosed = ['passed', 'failed', 'withdrawn'].includes(proposal.status);

  return (
    <div className="max-w-6xl mx-auto px-4 py-8">
      {/* Back link */}
      <Link to="/proposals" className="text-sm text-[#2E75B6] hover:underline mb-4 inline-block">
        ← Back to Proposals
      </Link>

      <div className="lg:grid lg:grid-cols-3 lg:gap-8">
        {/* Main content — 2/3 width */}
        <div className="lg:col-span-2 space-y-6">
          {/* Header */}
          <div>
            <div className="flex flex-wrap items-center gap-2 mb-3">
              <StatusBadge status={proposal.status} />
              {proposal.topics?.map(pt => (
                <TopicBadge key={pt.topic_id} topic={pt.topic} relevance={pt.relevance} />
              ))}
            </div>
            <h1 className="text-2xl font-bold text-[#1B3A5C] leading-tight mb-2">
              {proposal.title}
            </h1>
            <p className="text-sm text-gray-400">
              Proposed by {proposal.author?.display_name}
              {proposal.created_at && ` · ${new Date(proposal.created_at).toLocaleDateString()}`}
              {proposal.voting_end && isVoting && ` · Closes ${new Date(proposal.voting_end).toLocaleDateString()}`}
              {isClosed && proposal.voting_end && ` · Closed ${new Date(proposal.voting_end).toLocaleDateString()}`}
            </p>
          </div>

          {/* Body */}
          {proposal.body ? (
            <div
              className="prose text-[#2C3E50] text-sm leading-relaxed"
              dangerouslySetInnerHTML={{ __html: `<p>${renderMarkdown(proposal.body)}</p>` }}
            />
          ) : (
            <p className="text-gray-400 italic text-sm">No description provided.</p>
          )}

          {/* Results (desktop: shown inline; mobile: shown below vote panel) */}
          {(isVoting || isClosed) && tally && (
            <div className="lg:hidden bg-white border border-gray-200 rounded-xl p-5">
              <ResultsPanel tally={tally} proposal={proposal} />
            </div>
          )}

          {/* Vote Network Graph */}
          {(isVoting || isClosed) && voteGraph && (
            <section className="bg-white border border-gray-200 rounded-xl overflow-hidden">
              <button
                onClick={() => setGraphOpen(v => !v)}
                className="w-full flex items-center justify-between px-5 py-3 text-sm font-semibold text-gray-700 uppercase tracking-wide hover:bg-gray-50 transition-colors"
              >
                <span>Vote Network</span>
                <span className="text-gray-400 text-xs font-normal">
                  {graphOpen ? 'Hide' : 'Show'}
                </span>
              </button>
              {graphOpen && (
                <div className="px-4 pb-4 space-y-3">
                  {/* Legend */}
                  <div className="flex flex-wrap gap-x-4 gap-y-1 text-[10px] text-gray-500">
                    <span><span className="inline-block w-2.5 h-2.5 rounded-full bg-[#2D8A56] mr-1 align-middle" />Yes</span>
                    <span><span className="inline-block w-2.5 h-2.5 rounded-full bg-[#C0392B] mr-1 align-middle" />No</span>
                    <span><span className="inline-block w-2.5 h-2.5 rounded-full bg-[#7F8C8D] mr-1 align-middle" />Abstain</span>
                    <span><span className="inline-block w-2.5 h-2.5 rounded-full border border-gray-300 mr-1 align-middle" style={{ borderStyle: 'dashed' }} />Not voted</span>
                    <span className="text-gray-400">→ Delegation</span>
                    <span><svg className="inline-block mr-1 align-middle" width="14" height="14" viewBox="0 0 14 14"><circle cx="7" cy="7" r="4" fill="none" stroke="#2D8A56" strokeWidth="1.5" /><circle cx="7" cy="7" r="6.5" fill="none" stroke="#2D8A56" strokeWidth="0.8" strokeDasharray="2,1.5" opacity="0.6" /></svg>Public delegate</span>
                    <span><span className="inline-block w-2.5 h-2.5 rounded-full border-2 border-[#F39C12] mr-1 align-middle" />You</span>
                  </div>

                  {/* Cluster summary */}
                  <div className="flex gap-3 text-xs text-gray-500">
                    <span className="text-[#2D8A56] font-medium">
                      {voteGraph.clusters.yes?.count || 0} Yes
                      <span className="text-gray-400 font-normal"> ({voteGraph.clusters.yes?.direct || 0}d + {voteGraph.clusters.yes?.delegated || 0}del)</span>
                    </span>
                    <span className="text-[#C0392B] font-medium">
                      {voteGraph.clusters.no?.count || 0} No
                      <span className="text-gray-400 font-normal"> ({voteGraph.clusters.no?.direct || 0}d + {voteGraph.clusters.no?.delegated || 0}del)</span>
                    </span>
                    <span className="text-gray-500 font-medium">
                      {voteGraph.clusters.abstain?.count || 0} Abstain
                    </span>
                    <span className="text-gray-400">
                      {voteGraph.clusters.not_cast?.count || 0} Not cast
                    </span>
                  </div>

                  <VoteFlowGraph data={voteGraph} />
                </div>
              )}
            </section>
          )}
        </div>

        {/* Sidebar — 1/3 width */}
        <div className="mt-8 lg:mt-0 space-y-4">
          {/* Vote panel */}
          {isVoting && (
            <div className="bg-white border border-gray-200 rounded-xl p-5">
              <VoteStatusBox
                myVote={myVote}
                proposalId={id}
                onVoteChange={refreshVote}
              />
            </div>
          )}

          {proposal.status === 'deliberation' && (
            <div className="bg-blue-50 border border-blue-200 rounded-xl p-5">
              <h3 className="text-sm font-semibold text-blue-700 mb-1">Deliberation Period</h3>
              <p className="text-sm text-blue-600">
                {proposal.voting_start
                  ? `Voting opens ${new Date(proposal.voting_start).toLocaleDateString()}`
                  : 'Voting has not yet been scheduled.'}
              </p>
            </div>
          )}

          {/* Results (desktop sidebar) */}
          {(isVoting || isClosed) && tally && (
            <div className="hidden lg:block bg-white border border-gray-200 rounded-xl p-5">
              <ResultsPanel tally={tally} proposal={proposal} />
            </div>
          )}

          {isClosed && (
            <div className={`rounded-xl p-4 text-center font-semibold ${
              proposal.status === 'passed'
                ? 'bg-green-50 border border-green-200 text-green-700'
                : 'bg-red-50 border border-red-200 text-red-700'
            }`}>
              {proposal.status === 'passed' ? 'Proposal Passed' : 'Proposal Failed'}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

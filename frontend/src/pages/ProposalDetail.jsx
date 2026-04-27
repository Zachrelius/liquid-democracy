import { useState, useEffect, useCallback } from 'react';
import { useParams, Link } from 'react-router-dom';
import api from '../api';
import { useAuth } from '../AuthContext';
import { useOrg } from '../OrgContext';
import { useToast } from '../components/Toast';
import { useConfirm } from '../components/ConfirmDialog';
import StatusBadge from '../components/StatusBadge';
import TopicBadge from '../components/TopicBadge';
import VoteBar from '../components/VoteBar';
import VoteFlowGraph from '../components/VoteFlowGraph';
import UserLink from '../components/UserLink';
import Spinner from '../components/Spinner';
import ErrorMessage from '../components/ErrorMessage';
import RankedBallot from '../components/RankedBallot';
import RCVResultsPanel from '../components/RCVResultsPanel';
import RCVSankeyChart from '../components/RCVSankeyChart';
import { colorForOption } from '../components/voteFlowGraphUtils';

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

function VoteButtons({ onVote, casting, currentValue, disabled }) {
  return (
    <div className="flex gap-2">
      {['yes', 'no', 'abstain'].map(v => {
        const c = VOTE_COLORS[v];
        const active = currentValue === v;
        return (
          <button
            key={v}
            onClick={() => onVote(v)}
            disabled={casting || disabled}
            className={`flex-1 py-2.5 rounded-lg border-2 text-sm font-semibold capitalize transition-colors disabled:opacity-50
              ${active
                ? `${c.bg} ${c.border} text-white`
                : `bg-white ${c.border} ${c.text} ${disabled ? '' : c.hover}`
              }`}
          >
            {v}
          </button>
        );
      })}
    </div>
  );
}

function ApprovalBallot({ proposal, myVote, proposalId, onVoteChange, emailVerified }) {
  const confirm = useConfirm();
  const toast = useToast();
  const [selected, setSelected] = useState([]);
  const [showBallot, setShowBallot] = useState(false);
  const [casting, setCasting] = useState(false);
  const [err, setErr] = useState('');

  const hasVote = myVote?.approvals != null;
  const isDirect = myVote?.is_direct;
  const unverified = !emailVerified;
  const options = proposal.options || [];

  function toggleOption(optionId) {
    setSelected(prev =>
      prev.includes(optionId)
        ? prev.filter(id => id !== optionId)
        : [...prev, optionId]
    );
  }

  async function submitBallot() {
    if (selected.length === 0) {
      const ok = await confirm({
        title: 'Submit Empty Ballot?',
        message: "You haven't approved any options. Submitting now counts as an abstention \u2014 you're saying you don't support any of them. This is different from not voting at all. Continue?",
        destructive: false,
      });
      if (!ok) return;
    }
    setCasting(true);
    setErr('');
    try {
      await api.post(`/api/proposals/${proposalId}/vote`, { approvals: selected });
      toast.success(selected.length > 0 ? 'Ballot submitted' : 'Abstention recorded');
      setShowBallot(false);
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
      toast.success('Vote retracted');
      setShowBallot(false);
      onVoteChange();
    } catch (e) {
      setErr(e.message);
    } finally {
      setCasting(false);
    }
  }

  // Build label lookup
  const optionMap = {};
  options.forEach(o => { optionMap[o.id] = o; });

  return (
    <div className="bg-gray-50 border border-gray-200 rounded-xl p-4 space-y-3">
      <h3 className="text-sm font-semibold text-gray-700 uppercase tracking-wide">Your Ballot</h3>

      {unverified && (
        <p className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2">
          Verify your email to vote.
        </p>
      )}

      {hasVote && !showBallot ? (
        <div>
          {isDirect ? (
            myVote.approvals.length > 0 ? (
              <div>
                <p className="text-sm font-medium text-[#2D8A56] mb-1">You approved:</p>
                <ul className="text-sm text-gray-700 list-disc list-inside">
                  {myVote.approvals.map(oid => (
                    <li key={oid}>{optionMap[oid]?.label || oid}</li>
                  ))}
                </ul>
              </div>
            ) : (
              <p className="text-sm text-gray-500">You abstained (approved no options)</p>
            )
          ) : (
            <div>
              <p className="text-sm text-gray-500 mb-1">
                Via {myVote.cast_by ? <UserLink user={myVote.cast_by} className="text-sm" /> : 'delegate'}
                {myVote.delegate_chain?.length > 1 ? ' (chain)' : ''}
              </p>
              {myVote.approvals.length > 0 ? (
                <div>
                  <p className="text-xs text-gray-400 mb-1">Delegate approved:</p>
                  <ul className="text-sm text-gray-700 list-disc list-inside">
                    {myVote.approvals.map(oid => (
                      <li key={oid}>{optionMap[oid]?.label || oid}</li>
                    ))}
                  </ul>
                </div>
              ) : (
                <p className="text-xs text-gray-400">Delegate abstained (approved no options)</p>
              )}
            </div>
          )}

          <div className="flex gap-2 mt-3">
            <button
              onClick={() => { setSelected(isDirect ? [...myVote.approvals] : []); setShowBallot(true); }}
              disabled={unverified}
              className="text-xs px-3 py-1.5 border border-[#2E75B6] text-[#2E75B6] rounded-lg hover:bg-[#2E75B6] hover:text-white transition-colors disabled:opacity-50"
            >
              {isDirect ? 'Change Ballot' : 'Override \u2014 Vote Directly'}
            </button>
            {isDirect && (
              <button onClick={retractVote} disabled={casting || unverified}
                className="text-xs px-3 py-1.5 border border-gray-300 text-gray-500 rounded-lg hover:bg-gray-100 transition-colors disabled:opacity-50">
                Retract
              </button>
            )}
          </div>
        </div>
      ) : !hasVote && !showBallot ? (
        <div>
          <p className="text-gray-500 text-sm mb-3">
            {myVote?.message || 'No ballot cast'}
          </p>
          <button
            onClick={() => { setSelected([]); setShowBallot(true); }}
            disabled={unverified}
            className="text-sm px-3 py-1.5 bg-[#1B3A5C] text-white rounded-lg hover:bg-[#2E75B6] transition-colors disabled:opacity-50"
          >
            Cast Ballot
          </button>
        </div>
      ) : null}

      {showBallot && (
        <div className="space-y-2">
          <p className="text-xs text-gray-500">Select all options you approve of:</p>
          {options.map(opt => (
            <label key={opt.id} className="flex items-start gap-3 p-2 rounded-lg hover:bg-gray-100 cursor-pointer transition-colors">
              <input
                type="checkbox"
                checked={selected.includes(opt.id)}
                onChange={() => toggleOption(opt.id)}
                disabled={unverified}
                className="mt-0.5 accent-[#2E75B6]"
              />
              <div>
                <span className="text-sm font-medium text-gray-800">{opt.label}</span>
                {opt.description && <p className="text-xs text-gray-500 mt-0.5">{opt.description}</p>}
              </div>
            </label>
          ))}
          <div className="flex gap-2 pt-2">
            <button
              onClick={submitBallot}
              disabled={casting || unverified}
              className="text-sm px-4 py-2 bg-[#1B3A5C] text-white rounded-lg hover:bg-[#2E75B6] transition-colors disabled:opacity-50"
            >
              {casting ? 'Submitting...' : `Submit Ballot${selected.length > 0 ? ` (${selected.length} selected)` : ''}`}
            </button>
            <button
              onClick={() => setShowBallot(false)}
              className="text-xs text-gray-400 hover:text-gray-600 px-2"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {err && <p className="text-xs text-red-600">{err}</p>}
    </div>
  );
}

function ApprovalResultsPanel({ tally, proposal }) {
  const { currentOrg, isAdmin } = useOrg();
  const toast = useToast();
  const confirm = useConfirm();
  const [resolving, setResolving] = useState(false);

  if (!tally || !tally.option_approvals) return null;

  const options = proposal.options || [];
  const optionLabels = tally.option_labels || {};
  const optionApprovals = tally.option_approvals || {};
  const maxApprovals = Math.max(1, ...Object.values(optionApprovals));
  const winners = tally.winners || [];
  const tied = tally.tied;
  const tieResolution = tally.tie_resolution || proposal.tie_resolution;

  async function handleResolveTie(optionId) {
    const label = optionLabels[optionId] || optionId;
    const ok = await confirm({
      title: 'Resolve Tie',
      message: `Select "${label}" as the winning option? This cannot be undone.`,
      destructive: false,
    });
    if (!ok) return;
    setResolving(true);
    try {
      await api.post(`/api/orgs/${currentOrg.slug}/proposals/${proposal.id}/resolve-tie`, {
        selected_option_id: optionId,
      });
      toast.success('Tie resolved');
      window.location.reload();
    } catch (e) {
      toast.error(e.message);
    } finally {
      setResolving(false);
    }
  }

  // Item 5: when proposal is in voting, the winner(s) shown are provisional.
  // Surface a tense-aware callout. Closed proposals keep the existing
  // strong-winner UI via the per-option checkmark + tieResolution banner.
  const inProgress = proposal?.status === 'voting';
  const topApproval = winners[0];
  const topLabel = topApproval ? (optionLabels[topApproval] || topApproval) : null;
  const topCount = topApproval ? (optionApprovals[topApproval] || 0) : 0;

  return (
    <div className="space-y-4">
      <h3 className="text-sm font-semibold text-gray-700 uppercase tracking-wide">
        {inProgress ? 'Approval Results (in progress)' : 'Approval Results'}
      </h3>

      {/* Provisional leader callout while voting is open */}
      {inProgress && !tied && winners.length === 1 && topLabel && (
        <div className="bg-blue-50 border border-blue-200 rounded-lg p-3">
          <p className="text-xs font-medium text-blue-700 uppercase tracking-wide mb-1">
            Top option (currently)
          </p>
          <p className="text-base font-bold text-blue-800">
            {topLabel} <span className="text-sm font-normal text-blue-600">({topCount} approval{topCount === 1 ? '' : 's'})</span>
          </p>
        </div>
      )}

      {/* Tie banners */}
      {tied && !tieResolution && (
        <div className="bg-amber-50 border border-amber-200 rounded-lg p-3">
          <p className="text-sm font-medium text-amber-800">
            Tied result \u2014 {winners.length} options received {optionApprovals[winners[0]]} approvals each
          </p>
          {isAdmin && (
            <div className="mt-2 space-y-1">
              <p className="text-xs text-amber-700">As admin, select the winning option:</p>
              <div className="flex flex-wrap gap-2">
                {winners.map(wid => (
                  <button key={wid} onClick={() => handleResolveTie(wid)} disabled={resolving}
                    className="text-xs px-3 py-1 bg-amber-600 text-white rounded-lg hover:bg-amber-700 disabled:opacity-50">
                    {optionLabels[wid] || wid}
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
      {tieResolution && (
        <div className="bg-blue-50 border border-blue-200 rounded-lg p-3">
          <p className="text-sm text-blue-800">
            Tie resolved. Selected winner: <strong>{optionLabels[tieResolution.selected_option_id] || tieResolution.selected_option_id}</strong>
            {tieResolution.resolved_at && <span className="text-xs text-blue-600 ml-1">on {new Date(tieResolution.resolved_at).toLocaleDateString()}</span>}
          </p>
        </div>
      )}

      {/* Horizontal bar chart */}
      <div className="space-y-2">
        {options.map(opt => {
          const count = optionApprovals[opt.id] || 0;
          const pct = maxApprovals > 0 ? (count / maxApprovals) * 100 : 0;
          const isWinner = winners.includes(opt.id);
          const isSelectedWinner = tieResolution?.selected_option_id === opt.id;
          return (
            <div key={opt.id}>
              <div className="flex items-center justify-between text-sm mb-0.5">
                <span className={`font-medium ${isWinner || isSelectedWinner ? 'text-[#2D8A56]' : 'text-gray-700'}`}>
                  {opt.label}
                  {isSelectedWinner && ' \u2605'}
                  {isWinner && !tieResolution && ' \u2713'}
                </span>
                <span className="text-xs text-gray-500">{count} approval{count !== 1 ? 's' : ''}</span>
              </div>
              <div className="w-full bg-gray-200 rounded-full h-4">
                <div
                  className={`h-4 rounded-full transition-all ${isWinner || isSelectedWinner ? 'bg-[#2D8A56]' : 'bg-[#2E75B6]'}`}
                  style={{ width: `${pct}%`, minWidth: count > 0 ? '4px' : '0' }}
                />
              </div>
            </div>
          );
        })}
      </div>

      {/* Summary stats */}
      <div className="text-sm text-gray-500 space-y-1">
        <p>{tally.total_ballots_cast ?? 0} ballot{(tally.total_ballots_cast ?? 0) !== 1 ? 's' : ''} cast
          {tally.total_eligible > 0 && ` of ${tally.total_eligible} eligible (${((tally.total_ballots_cast / tally.total_eligible) * 100).toFixed(1)}%)`}
        </p>
        {(tally.total_abstain ?? 0) > 0 && (
          <p>{tally.total_abstain} empty ballot{tally.total_abstain !== 1 ? 's' : ''} (abstain)</p>
        )}
      </div>
    </div>
  );
}

function VoteStatusBox({ myVote, proposalId, onVoteChange, emailVerified }) {
  const toast = useToast();
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
      toast.success(`Voted ${value}`);
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
      toast.success('Vote retracted');
      setShowButtons(false);
      onVoteChange();
    } catch (e) {
      setErr(e.message);
    } finally {
      setCasting(false);
    }
  }

  const voteColor = hasVote ? VOTE_COLORS[myVote.vote_value]?.text : '';

  const unverified = !emailVerified;

  return (
    <div className="bg-gray-50 border border-gray-200 rounded-xl p-4 space-y-3">
      <h3 className="text-sm font-semibold text-gray-700 uppercase tracking-wide">Your Vote</h3>

      {unverified && (
        <p className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2">
          Verify your email to vote.
        </p>
      )}

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
                disabled={unverified}
                className="text-xs px-3 py-1.5 border border-[#2E75B6] text-[#2E75B6] rounded-lg hover:bg-[#2E75B6] hover:text-white transition-colors disabled:opacity-50"
              >
                {isDirect ? 'Change Vote' : 'Override — Vote Directly'}
              </button>
              {isDirect && (
                <button
                  onClick={retractVote}
                  disabled={casting || unverified}
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
              disabled={unverified}
              className="text-sm px-3 py-1.5 bg-[#1B3A5C] text-white rounded-lg hover:bg-[#2E75B6] transition-colors disabled:opacity-50"
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
            disabled={unverified}
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
  // Item 5: tense-aware in-progress callout. "Currently passing" if both
  // quorum and threshold are met, else "Currently failing". Closed proposals
  // get their pass/fail summary from the existing isClosed banner above.
  const inProgress = proposal?.status === 'voting';
  const currentlyPassing = quorumMet && thresholdMet;

  return (
    <div className="space-y-4">
      <h3 className="text-sm font-semibold text-gray-700 uppercase tracking-wide">Current Results</h3>
      {inProgress && (
        <div className={`rounded-lg p-2 text-sm font-medium border ${
          currentlyPassing
            ? 'bg-blue-50 border-blue-200 text-blue-800'
            : 'bg-gray-50 border-gray-200 text-gray-700'
        }`}>
          {currentlyPassing ? 'Currently passing' : 'Currently failing'}
        </div>
      )}
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

// Phase 7B.2 Polish Item B: method-aware legend for the vote network graph.
// Binary keeps the original Yes/No/Abstain content; approval and RCV swap
// in per-option swatches (using colorForOption so colors match the network
// graph and Sankey). Layout/styling is unchanged from the original inline
// block so the legend continues to flex-wrap on overflow.
function VoteGraphLegend({ proposal, voteGraph }) {
  const method = proposal?.voting_method;
  const options = proposal?.options || [];

  // Detect anonymous voters that render distinctly: ballot is null AND not a
  // non_voter AND not a delegation-recipient (those have ballot via inheritance).
  const hasAnonymous = !!voteGraph?.nodes?.some(
    (n) => n.ballot === null && n.type !== 'non_voter' && n.vote_source !== 'delegation'
  );

  if (method === 'approval' || method === 'ranked_choice') {
    return (
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-[10px] text-gray-500">
        {options.map((opt) => {
          const lbl = opt.label || opt.id;
          const truncated = lbl.length > 14 ? lbl.slice(0, 13) + '…' : lbl;
          return (
            <span key={opt.id} title={lbl}>
              <span
                className="inline-block w-2.5 h-2.5 rounded-full mr-1 align-middle"
                style={{ backgroundColor: colorForOption(opt) }}
              />
              {truncated}
            </span>
          );
        })}
        <span>
          <span
            className="inline-block w-2.5 h-2.5 rounded-full border border-gray-300 mr-1 align-middle"
            style={{ borderStyle: 'dashed' }}
          />
          Abstain (empty ballot)
        </span>
        <span className="text-gray-400">→ Delegation</span>
        <span>
          <svg className="inline-block mr-1 align-middle" width="14" height="14" viewBox="0 0 14 14">
            <circle cx="7" cy="7" r="4" fill="none" stroke="#2D8A56" strokeWidth="1.5" />
            <circle cx="7" cy="7" r="6.5" fill="none" stroke="#2D8A56" strokeWidth="0.8" strokeDasharray="2,1.5" opacity="0.6" />
          </svg>
          Public delegate
        </span>
        <span>
          <span className="inline-block w-2.5 h-2.5 rounded-full border-2 border-[#F39C12] mr-1 align-middle" />
          You
        </span>
        {hasAnonymous && (
          <span>
            <span className="inline-block w-2.5 h-2.5 rounded-full bg-gray-300 mr-1 align-middle" />
            Anonymous voter
          </span>
        )}
      </div>
    );
  }

  // Binary — preserved exactly as-is.
  return (
    <div className="flex flex-wrap gap-x-4 gap-y-1 text-[10px] text-gray-500">
      <span><span className="inline-block w-2.5 h-2.5 rounded-full bg-[#2D8A56] mr-1 align-middle" />Yes</span>
      <span><span className="inline-block w-2.5 h-2.5 rounded-full bg-[#C0392B] mr-1 align-middle" />No</span>
      <span><span className="inline-block w-2.5 h-2.5 rounded-full bg-[#7F8C8D] mr-1 align-middle" />Abstain</span>
      <span><span className="inline-block w-2.5 h-2.5 rounded-full border border-gray-300 mr-1 align-middle" style={{ borderStyle: 'dashed' }} />Not voted</span>
      <span className="text-gray-400">→ Delegation</span>
      <span><svg className="inline-block mr-1 align-middle" width="14" height="14" viewBox="0 0 14 14"><circle cx="7" cy="7" r="4" fill="none" stroke="#2D8A56" strokeWidth="1.5" /><circle cx="7" cy="7" r="6.5" fill="none" stroke="#2D8A56" strokeWidth="0.8" strokeDasharray="2,1.5" opacity="0.6" /></svg>Public delegate</span>
      <span><span className="inline-block w-2.5 h-2.5 rounded-full border-2 border-[#F39C12] mr-1 align-middle" />You</span>
    </div>
  );
}

export default function ProposalDetail() {
  const { id } = useParams();
  const { user } = useAuth();
  const [proposal, setProposal] = useState(null);
  const [tally, setTally] = useState(null);
  const [myVote, setMyVote] = useState(null);
  const [voteGraph, setVoteGraph] = useState(null);
  const [graphOpen, setGraphOpen] = useState(window.innerWidth >= 768);
  const [sankeyOpen, setSankeyOpen] = useState(window.innerWidth >= 768);
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
              {proposal.voting_method === 'approval' && (
                <span className="text-xs bg-purple-100 text-purple-700 px-2 py-0.5 rounded-full font-medium">Approval Vote</span>
              )}
              {proposal.voting_method === 'ranked_choice' && (
                <span className="text-xs bg-indigo-100 text-indigo-700 px-2 py-0.5 rounded-full font-medium">
                  {(proposal.num_winners ?? 1) > 1 ? `STV · ${proposal.num_winners} winners` : 'Ranked-Choice (IRV)'}
                </span>
              )}
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

          {/* Options list for multi-option proposals (visible when not actively voting) */}
          {(proposal.voting_method === 'approval' || proposal.voting_method === 'ranked_choice') && proposal.options?.length > 0 && !isVoting && (
            <div className="bg-white border border-gray-200 rounded-xl p-5">
              <h3 className="text-sm font-semibold text-gray-700 uppercase tracking-wide mb-3">Options</h3>
              <div className="space-y-2">
                {proposal.options.map((opt, idx) => (
                  <div key={opt.id} className="flex items-start gap-3 p-2 bg-gray-50 rounded-lg">
                    <span className="text-xs text-gray-400 mt-0.5">{idx + 1}.</span>
                    <div>
                      <span className="text-sm font-medium text-gray-800">{opt.label}</span>
                      {opt.description && <p className="text-xs text-gray-500 mt-0.5">{opt.description}</p>}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Results (desktop: shown inline; mobile: shown below vote panel) */}
          {(isVoting || isClosed) && tally && (
            <div className="lg:hidden bg-white border border-gray-200 rounded-xl p-5">
              {proposal.voting_method === 'approval' ? (
                <ApprovalResultsPanel tally={tally} proposal={proposal} />
              ) : proposal.voting_method === 'ranked_choice' ? (
                <RCVResultsPanel tally={tally} proposal={proposal} />
              ) : (
                <ResultsPanel tally={tally} proposal={proposal} />
              )}
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
                  {/* Legend — Phase 7B.2 method-aware (Polish Item B) */}
                  <VoteGraphLegend proposal={proposal} voteGraph={voteGraph} />

                  {/* Method-aware tally summary + graph (Phase 7B dispatcher) */}
                  <VoteFlowGraph data={voteGraph} proposal={proposal} tally={tally} />
                </div>
              )}
            </section>
          )}

          {/* Elimination Flow Sankey — Phase 7C, RCV/STV only.
              The component itself short-circuits for non-RCV proposals,
              but we also gate the wrapping section to avoid rendering an
              empty collapsible chrome on binary/approval. */}
          {(isVoting || isClosed) && tally && proposal.voting_method === 'ranked_choice' && (
            <section className="bg-white border border-gray-200 rounded-xl overflow-hidden">
              <button
                onClick={() => setSankeyOpen(v => !v)}
                className="w-full flex items-center justify-between px-5 py-3 text-sm font-semibold text-gray-700 uppercase tracking-wide hover:bg-gray-50 transition-colors"
              >
                <span>Elimination Flow</span>
                <span className="text-gray-400 text-xs font-normal">
                  {sankeyOpen ? 'Hide' : 'Show'}
                </span>
              </button>
              {sankeyOpen && (
                <div className="px-2 pb-2">
                  <RCVSankeyChart tally={tally} proposal={proposal} />
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
              {proposal.voting_method === 'approval' ? (
                <ApprovalBallot
                  proposal={proposal}
                  myVote={myVote}
                  proposalId={id}
                  onVoteChange={refreshVote}
                  emailVerified={user?.email_verified}
                />
              ) : proposal.voting_method === 'ranked_choice' ? (
                <RankedBallot
                  proposal={proposal}
                  myVote={myVote}
                  proposalId={id}
                  onVoteChange={refreshVote}
                  emailVerified={user?.email_verified}
                />
              ) : (
                <VoteStatusBox
                  myVote={myVote}
                  proposalId={id}
                  onVoteChange={refreshVote}
                  emailVerified={user?.email_verified}
                />
              )}
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
              {proposal.voting_method === 'approval' ? (
                <ApprovalResultsPanel tally={tally} proposal={proposal} />
              ) : proposal.voting_method === 'ranked_choice' ? (
                <RCVResultsPanel tally={tally} proposal={proposal} />
              ) : (
                <ResultsPanel tally={tally} proposal={proposal} />
              )}
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

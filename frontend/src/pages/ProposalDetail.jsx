import { useState, useEffect, useCallback } from 'react';
import { useParams, Link } from 'react-router-dom';
import api from '../api';
import { useAuth } from '../AuthContext';
import { useOrg } from '../OrgContext';
// Phase 12.5 F2 — per-control permission gating.
// Phase 32.2 E4 — re-imported for the F2.3 Edit-author button gate.
// Phase 32.2 M2 registers `org.edit_proposal` in the permission
// registry and seeds it onto admin + steward by default; B2 restores
// the spec'd backend gate so the FE check resolves against
// currentOrg.user_permissions. Hotfix #4's platform-admin-only gate
// is reverted to match the original Phase 32 D14 intent.
import { useHasPermission } from '../hooks/useHasPermission';
import { useToast } from '../components/Toast';
import { useConfirm } from '../components/ConfirmDialog';
import VerifyEmailInlineNote from '../components/VerifyEmailInlineNote';
import StatusBadge from '../components/StatusBadge';
import ElectionBadge from '../components/ElectionBadge';
import TopicBadge from '../components/TopicBadge';
import VoteBar from '../components/VoteBar';
import VoteFlowGraph from '../components/VoteFlowGraph';
import UserLink from '../components/UserLink';
import Spinner from '../components/Spinner';
import ErrorMessage from '../components/ErrorMessage';
import RankedBallot from '../components/RankedBallot';
import RCVResultsPanel from '../components/RCVResultsPanel';
import RCVSankeyChart from '../components/RCVSankeyChart';
import SupportTrajectoryChart from '../components/SupportTrajectoryChart';
// Phase 17 F2 — auto-resolved tie banner shared across approval + RCV panels.
import TieResolutionBanner from '../components/TieResolutionBanner';
import StableResultPanel from '../components/StableResultPanel';
import LinkedPolisCard from '../components/LinkedPolisCard';
import CommentThread from '../components/CommentThread';
// Phase 19 F3 — inline rationale composer for the user's own vote.
import MyVoteRationaleBox from '../components/MyVoteRationaleBox';
import { colorForOption } from '../components/voteFlowGraphUtils';
import renderMarkdown from '../utils/renderMarkdown';
import { urlFor } from '../utils/urls';

/**
 * Phase 9 Session 4 — pol.is URL detection in proposal bodies.
 *
 * Detects pol.is conversation URLs in two forms:
 *   - Raw URL:           https://pol.is/<6-10-char-id>
 *   - Markdown link:     [text](https://pol.is/<id>)
 *
 * The conversation ID is the 6-10-char lowercase alphanumeric token
 * documented in `phase9_polis_api_findings.md`. We deliberately accept
 * up to 12 chars to allow for occasional longer slugs without false
 * negatives, and stop at common URL terminators (whitespace, ), ],
 * punctuation followed by space, etc.).
 *
 * Returns an array of { conversationId, originalUrl } unique by
 * conversationId in first-seen order.
 *
 * Implementation choice: client-side, post-markdown-render. The proposal
 * body markdown rendering is a tiny inline helper (`renderMarkdown`) that
 * doesn't expose a plugin point; intercepting at server-side would mean
 * touching the markdown sanitizer in ``backend/schemas.py``. Client-side
 * walking of the rendered HTML is simpler and keeps the URL-detection
 * logic colocated with the link-card UI it feeds.
 */
const POLIS_URL_RE = /https?:\/\/(?:www\.)?pol\.is\/([a-z0-9]{6,12})\b/gi;

function detectPolisUrlsInBody(body) {
  if (!body) return [];
  const found = [];
  const seen = new Set();
  let m;
  POLIS_URL_RE.lastIndex = 0;
  while ((m = POLIS_URL_RE.exec(body)) !== null) {
    const id = (m[1] || '').toLowerCase();
    if (!id || seen.has(id)) continue;
    seen.add(id);
    found.push({ conversationId: id, originalUrl: m[0] });
  }
  return found;
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
        <div className="bg-amber-50 border border-amber-200 rounded-lg px-3 py-2">
          <VerifyEmailInlineNote action="vote" />
        </div>
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
              className="text-xs px-3 py-1.5 border border-[var(--brand-accent)] text-[var(--brand-accent)] rounded-lg hover:bg-[var(--brand-accent)] hover:text-white transition-colors disabled:opacity-50"
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
            className="text-sm px-3 py-1.5 bg-[var(--brand-primary)] text-white rounded-lg hover:bg-[var(--brand-accent)] transition-colors disabled:opacity-50"
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
                className="mt-0.5 accent-[var(--brand-accent)]"
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
              className="text-sm px-4 py-2 bg-[var(--brand-primary)] text-white rounded-lg hover:bg-[var(--brand-accent)] transition-colors disabled:opacity-50"
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
  // Phase 17 F2 + B6 frontend cleanup — the manual admin "resolve tie" UI
  // (handler + button row) was removed in this pass. Ties now auto-resolve
  // at advance-to-passed time via the org's configured tie-resolution
  // method (see backend tie_resolution.py + advance_proposal). The
  // resolution surfaces here as a TieResolutionBanner above the bar
  // chart. The `proposal.resolve_tie` permission key remains in the
  // registry but is no longer consumed anywhere in the frontend; backend
  // dropped its own consumer in B6.
  if (!tally || !tally.option_approvals) return null;

  const options = proposal.options || [];
  const optionLabels = tally.option_labels || {};
  const optionApprovals = tally.option_approvals || {};
  const maxApprovals = Math.max(1, ...Object.values(optionApprovals));
  const winners = tally.winners || [];
  const tied = tally.tied;
  const tieResolution = tally.tie_resolution || proposal.tie_resolution;
  const labelOf = (id) => optionLabels[id] || id;

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

      {/* Phase 17 F2 — auto-resolved tie banner (replaces the manual
          admin "select the winning option" callout — B6 frontend cleanup).
          tieResolution is the audit record persisted at advance-to-passed
          time; its absence on a tied proposal means the proposal closed
          before this pass shipped (D7: no backfill) and we surface a
          plain "tied" note instead. */}
      {tieResolution && (
        <TieResolutionBanner
          tieResolution={tieResolution}
          labelOf={labelOf}
        />
      )}
      {tied && !tieResolution && (
        <div className="bg-amber-50 border border-amber-200 rounded-lg p-3">
          <p className="text-sm font-medium text-amber-800">
            Tied result &mdash; {winners.length} option{winners.length !== 1 ? 's' : ''} received {optionApprovals[winners[0]]} approval{optionApprovals[winners[0]] !== 1 ? 's' : ''} each.
          </p>
        </div>
      )}

      {/* Horizontal bar chart.
          Phase 17 F2: post-tie-resolution `tally.winners` is already
          mutated to the chosen-winners set by the backend (see
          routes/proposals.py::_maybe_resolve_tie). isWinner therefore
          reflects the resolved truth. isSelectedWinner is kept as a
          legacy-shape compatibility hook so old admin-resolved
          proposals (selected_option_id) and new auto-resolved proposals
          (chosen_winners) both render the gold-star marker. */}
      <div className="space-y-2">
        {options.map(opt => {
          const count = optionApprovals[opt.id] || 0;
          const pct = maxApprovals > 0 ? (count / maxApprovals) * 100 : 0;
          const isWinner = winners.includes(opt.id);
          const isSelectedWinner = tieResolution
            ? (
                tieResolution.selected_option_id === opt.id
                || (Array.isArray(tieResolution.chosen_winners)
                  && tieResolution.chosen_winners.includes(opt.id))
              )
            : false;
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
                  className={`h-4 rounded-full transition-all ${isWinner || isSelectedWinner ? 'bg-[#2D8A56]' : 'bg-[var(--brand-accent)]'}`}
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
        <div className="bg-amber-50 border border-amber-200 rounded-lg px-3 py-2">
          <VerifyEmailInlineNote action="vote" />
        </div>
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
                className="text-xs px-3 py-1.5 border border-[var(--brand-accent)] text-[var(--brand-accent)] rounded-lg hover:bg-[var(--brand-accent)] hover:text-white transition-colors disabled:opacity-50"
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
              className="text-sm px-3 py-1.5 bg-[var(--brand-primary)] text-white rounded-lg hover:bg-[var(--brand-accent)] transition-colors disabled:opacity-50"
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

/**
 * Phase 32 W2 — Add an option (write-in) button + inline form.
 *
 * Rendered below the options list on multi-option proposal detail
 * pages. Visible during deliberation OR voting when the proposal
 * flags allow write-ins. Backend resolves the gate per-proposal-
 * override-or-org-default; the frontend optimistically renders the
 * button when the proposal-out has the flag set non-null OR true.
 *
 * Posts to ``POST /api/proposals/{id}/options``. On success, reloads
 * the page to surface the new option in every consumer (vote panel,
 * results panel, etc.).
 */
function WriteInOptionAdder({ proposal, onAdded }) {
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const [label, setLabel] = useState('');
  const [description, setDescription] = useState('');
  const [submitting, setSubmitting] = useState(false);

  // Phase 32.2 E2 + E3 — gate on resolved-effective values from the
  // 4-option resolver (now surfaced on ProposalOut). Render only when:
  //   - status is deliberation OR voting, AND
  //   - effective_allow_write_in_options is True, AND
  //   - if voting: effective_allow_write_ins_during_voting is True too.
  // Previously the gate hid only on explicit `false` per-proposal
  // override, leaving the button surfaced on proposals where the org
  // mode disabled write-ins entirely — every click would 403. Resolver-
  // backed effective values close that gap.
  const status = proposal.status;
  if (status !== 'deliberation' && status !== 'voting') return null;
  if (!proposal.effective_allow_write_in_options) return null;
  if (
    status === 'voting'
    && !proposal.effective_allow_write_ins_during_voting
  ) {
    return null;
  }

  async function handleSubmit(e) {
    e.preventDefault();
    if (!label.trim()) return;
    setSubmitting(true);
    try {
      await api.post(`/api/proposals/${proposal.id}/options`, {
        label: label.trim(),
        description: description.trim(),
      });
      toast.success(`Added "${label.trim()}" as a write-in option`);
      setLabel('');
      setDescription('');
      setOpen(false);
      onAdded?.();
    } catch (err) {
      toast.error(err?.message || 'Could not add option');
    } finally {
      setSubmitting(false);
    }
  }

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="mt-3 inline-flex items-center gap-1.5 text-xs font-medium text-[var(--brand-accent)] hover:underline"
      >
        + Add an option
      </button>
    );
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="mt-3 p-3 bg-gray-50 border border-gray-200 rounded-lg space-y-2"
    >
      <input
        type="text"
        value={label}
        onChange={(e) => setLabel(e.target.value)}
        placeholder="Option label"
        maxLength={200}
        required
        autoFocus
        className="w-full px-2 py-1.5 text-sm border border-gray-300 rounded focus:outline-none focus:border-[var(--brand-accent)]"
      />
      <textarea
        value={description}
        onChange={(e) => setDescription(e.target.value)}
        placeholder="Optional description"
        maxLength={2000}
        rows={2}
        className="w-full px-2 py-1.5 text-sm border border-gray-300 rounded focus:outline-none focus:border-[var(--brand-accent)] resize-y"
      />
      <div className="flex gap-2">
        <button
          type="submit"
          disabled={submitting || !label.trim()}
          className="px-3 py-1 text-xs font-medium text-white bg-[var(--brand-accent)] rounded hover:opacity-90 disabled:opacity-50"
        >
          {submitting ? 'Adding…' : 'Add option'}
        </button>
        <button
          type="button"
          onClick={() => { setOpen(false); setLabel(''); setDescription(''); }}
          className="px-3 py-1 text-xs text-gray-600 hover:text-gray-800"
        >
          Cancel
        </button>
      </div>
    </form>
  );
}


/**
 * Phase 32.1 W3.fe — per-option row with conditional delete button.
 *
 * Original options (is_write_in=False) render unchanged. Write-ins
 * gain a small "Remove" button visible to the adder OR users with
 * admin permission. Click opens an inline confirmation, then calls
 * the existing DELETE endpoint. On success, parent re-fetches.
 *
 * Server-side authoritative on permission (Phase 32 W3); this is the
 * pre-check render. Users without permission see no button.
 */
function OptionRow({ option, index, proposal, currentUser, onDeleted }) {
  const toast = useToast();
  const [confirming, setConfirming] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const isWriteIn = !!option.is_write_in;
  const isAdder = !!currentUser && option.added_by_user_id === currentUser.id;
  const isAdmin = !!currentUser && !!currentUser.is_admin;
  const canDelete = isWriteIn && (isAdder || isAdmin);

  async function handleDelete() {
    setSubmitting(true);
    try {
      await api.delete(
        `/api/proposals/${proposal.id}/options/${option.id}`
      );
      toast.success(`Removed "${option.label}"`);
      setConfirming(false);
      onDeleted?.();
    } catch (err) {
      toast.error(err?.message || 'Could not remove option');
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="flex items-start gap-3 p-2 bg-gray-50 rounded-lg">
      <span className="text-xs text-gray-400 mt-0.5">{index + 1}.</span>
      <div className="flex-1">
        <span className="text-sm font-medium text-gray-800">{option.label}</span>
        {isWriteIn && (
          <span className="ml-2 text-[10px] uppercase tracking-wide text-violet-600 bg-violet-50 px-1.5 py-0.5 rounded">
            write-in
          </span>
        )}
        {option.description && (
          <p className="text-xs text-gray-500 mt-0.5">{option.description}</p>
        )}
        {confirming && (
          <div className="mt-2 p-2 bg-red-50 border border-red-200 rounded text-xs">
            <p className="text-red-700 mb-2">
              Remove this option? Any votes for it will be adjusted. This
              cannot be undone.
            </p>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={handleDelete}
                disabled={submitting}
                className="px-2 py-1 text-xs font-medium text-white bg-red-600 rounded hover:opacity-90 disabled:opacity-50"
              >
                {submitting ? 'Removing…' : 'Remove'}
              </button>
              <button
                type="button"
                onClick={() => setConfirming(false)}
                className="px-2 py-1 text-xs text-gray-600 hover:text-gray-800"
              >
                Cancel
              </button>
            </div>
          </div>
        )}
      </div>
      {canDelete && !confirming && (
        <button
          type="button"
          onClick={() => setConfirming(true)}
          className="text-xs text-gray-400 hover:text-red-600"
          title="Remove this write-in option"
        >
          ✕
        </button>
      )}
    </div>
  );
}


/**
 * Phase 32.1 F2.4 — change-log accordion.
 *
 * Fetches GET /api/proposals/{id}/revisions on first expand and renders
 * a chronological list of edits with a lightweight diff view for title
 * and body. Structured before/after for options/topics/override flags.
 *
 * Hidden entirely when no revisions exist (no empty accordion). Visible
 * to any org member per Phase 32 E4 transparency-first decision; the
 * endpoint enforces org-membership gating.
 */
function ProposalChangeLog({ proposalId }) {
  const [open, setOpen] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [revisions, setRevisions] = useState([]);
  const [count, setCount] = useState(null);
  const [error, setError] = useState(null);

  // Lightweight first-fetch on mount to know whether to render at all
  // (revision count drives the "X revisions" pill).
  useEffect(() => {
    let cancelled = false;
    api.get(`/api/proposals/${proposalId}/revisions`)
      .then((rows) => {
        if (cancelled) return;
        setRevisions(rows || []);
        setCount((rows || []).length);
      })
      .catch(() => { /* silent — accordion stays hidden */ });
    return () => { cancelled = true; };
  }, [proposalId]);

  async function expand() {
    setOpen(true);
    if (loaded) return;
    try {
      const rows = await api.get(`/api/proposals/${proposalId}/revisions`);
      setRevisions(rows || []);
      setCount((rows || []).length);
      setLoaded(true);
    } catch (err) {
      setError(err?.message || 'Could not load change log');
    }
  }

  if (count === null) return null;
  if (count === 0) return null;

  return (
    <section className="bg-white border border-gray-200 rounded-xl overflow-hidden">
      <button
        type="button"
        onClick={() => (open ? setOpen(false) : expand())}
        className="w-full flex items-center justify-between px-5 py-3 text-sm font-semibold text-gray-700 uppercase tracking-wide hover:bg-gray-50 transition-colors"
        aria-expanded={open}
      >
        <span>Change log ({count} {count === 1 ? 'revision' : 'revisions'})</span>
        <span className="text-gray-400 text-xs font-normal">
          {open ? 'Hide' : 'Show'}
        </span>
      </button>
      {open && (
        <div className="px-5 pb-4 space-y-4 border-t border-gray-100">
          {error && (
            <div className="bg-red-50 border border-red-200 text-red-700 p-3 rounded text-sm">
              {error}
            </div>
          )}
          {revisions.map((rev, i) => (
            <ChangeLogEntry key={rev.id || i} revision={rev} />
          ))}
        </div>
      )}
    </section>
  );
}


function ChangeLogEntry({ revision }) {
  const editor = revision.editor;
  const editedAt = new Date(revision.edited_at).toLocaleString();
  const changedFields = Array.isArray(revision.changed_fields)
    ? revision.changed_fields : [];
  return (
    <div className="pt-4 first:pt-2">
      <div className="text-xs text-gray-500 mb-2">
        <span className="font-medium text-gray-700">
          {editor?.display_name || editor?.username || 'Author'}
        </span>{' '}
        edited {editedAt}
      </div>
      <div className="text-xs text-gray-400 mb-3">
        Changed: {changedFields.join(', ')}
      </div>
      <div className="space-y-3">
        {changedFields.map((field) => (
          <FieldDiff
            key={field}
            field={field}
            before={revision.snapshot_before?.[field]}
            after={revision.snapshot_after?.[field]}
          />
        ))}
      </div>
    </div>
  );
}


function FieldDiff({ field, before, after }) {
  const isTextField = field === 'title' || field === 'body';
  const beforeStr = before === undefined || before === null
    ? '(empty)'
    : (typeof before === 'string' ? before : JSON.stringify(before, null, 2));
  const afterStr = after === undefined || after === null
    ? '(empty)'
    : (typeof after === 'string' ? after : JSON.stringify(after, null, 2));
  return (
    <div className="border border-gray-100 rounded-lg overflow-hidden text-xs">
      <div className="px-3 py-1.5 bg-gray-50 text-gray-600 font-medium uppercase tracking-wide">
        {field}
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 divide-y md:divide-y-0 md:divide-x divide-gray-100">
        <div className="px-3 py-2 bg-red-50/40">
          <div className="text-[10px] text-red-700 mb-1 uppercase">Before</div>
          <div className={`whitespace-pre-wrap ${isTextField ? '' : 'font-mono'} text-gray-800`}>
            {beforeStr}
          </div>
        </div>
        <div className="px-3 py-2 bg-green-50/40">
          <div className="text-[10px] text-green-700 mb-1 uppercase">After</div>
          <div className={`whitespace-pre-wrap ${isTextField ? '' : 'font-mono'} text-gray-800`}>
            {afterStr}
          </div>
        </div>
      </div>
    </div>
  );
}


/**
 * Phase 32.1 F2.3 — Edit proposal button + inline form.
 *
 * Visible to the proposal's author OR an org admin while the proposal
 * is in deliberation AND the edit lockout fraction hasn't been
 * reached. Server enforces lockout authoritatively via Phase 32 E3;
 * the frontend pre-checks to avoid rendering a button that 403s.
 *
 * Minimum-viable surface: title + body editing. Per the spec D15 the
 * PATCH endpoint accepts a much wider editable-fields set; this pass
 * ships the most common case (title + body) and defers the full edit
 * form (options/topics/timestamps/overrides) to a later polish pass.
 * Authors can still edit those fields via the existing proposal-
 * editing surface in admin views; the inline form here is the
 * deliberation-phase convenience for fast text edits.
 */
function EditProposalButton({ proposal, onSaved }) {
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState(proposal.title);
  const [body, setBody] = useState(proposal.body || '');
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    setTitle(proposal.title);
    setBody(proposal.body || '');
  }, [proposal.title, proposal.body]);

  async function handleSubmit(e) {
    e.preventDefault();
    if (!title.trim()) return;
    setSubmitting(true);
    try {
      await api.patch(`/api/proposals/${proposal.id}`, {
        title: title.trim(),
        body,
      });
      toast.success('Proposal updated');
      setOpen(false);
      onSaved?.();
    } catch (err) {
      toast.error(err?.message || 'Could not save changes');
    } finally {
      setSubmitting(false);
    }
  }

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="text-xs px-2.5 py-1 border border-[var(--brand-accent)] text-[var(--brand-accent)] rounded hover:bg-[var(--brand-accent)] hover:text-white transition-colors"
      >
        Edit proposal
      </button>
    );
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="mt-2 p-3 bg-gray-50 border border-gray-200 rounded-lg space-y-2 max-w-2xl"
    >
      <div>
        <label className="block text-xs font-medium text-gray-600 mb-1">Title</label>
        <input
          type="text"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          maxLength={500}
          required
          className="w-full px-2 py-1.5 text-sm border border-gray-300 rounded focus:outline-none focus:border-[var(--brand-accent)]"
        />
      </div>
      <div>
        <label className="block text-xs font-medium text-gray-600 mb-1">Description</label>
        <textarea
          value={body}
          onChange={(e) => setBody(e.target.value)}
          rows={6}
          maxLength={50000}
          className="w-full px-2 py-1.5 text-sm border border-gray-300 rounded focus:outline-none focus:border-[var(--brand-accent)] resize-y"
        />
      </div>
      <div className="flex gap-2">
        <button
          type="submit"
          disabled={submitting || !title.trim()}
          className="px-3 py-1 text-xs font-medium text-white bg-[var(--brand-accent)] rounded hover:opacity-90 disabled:opacity-50"
        >
          {submitting ? 'Saving…' : 'Save changes'}
        </button>
        <button
          type="button"
          onClick={() => { setOpen(false); setTitle(proposal.title); setBody(proposal.body || ''); }}
          className="px-3 py-1 text-xs text-gray-600 hover:text-gray-800"
        >
          Cancel
        </button>
      </div>
    </form>
  );
}


/**
 * Phase 31 B6 — full-width always-visible trajectory chart section.
 *
 * Replaces the Phase 22 F3 collapsed-by-default treatment. Rendered in
 * the main content column directly below the Vote Network section; no
 * toggle. Gated to voting + closed proposals (deliberation has no
 * trajectory data).
 *
 * optionLabels: passed through for multi-option legends/tooltips. Parent
 * sources it from tally.option_labels.
 */
function TrajectorySection({ proposalId, proposal, optionLabels }) {
  return (
    <section className="bg-white border border-gray-200 rounded-xl overflow-hidden">
      <div className="px-5 py-3 text-sm font-semibold text-gray-700 uppercase tracking-wide border-b border-gray-100">
        Support Trajectory
      </div>
      <div className="px-4 py-4">
        <SupportTrajectoryChart
          proposalId={proposalId}
          expanded={true}
          optionLabels={optionLabels}
          proposal={proposal}
        />
      </div>
    </section>
  );
}

export default function ProposalDetail() {
  const { id } = useParams();
  const { user } = useAuth();
  const { currentOrg, userOrgs } = useOrg();
  // Phase 11 — proposals/delegations routes are parent-org-rooted. If
  // currentOrg is itself a sub-org, walk up for link construction.
  const linkOrg = (() => {
    if (!currentOrg) return null;
    if (currentOrg.parent_org_id) {
      return userOrgs.find(o => o.id === currentOrg.parent_org_id) || null;
    }
    return currentOrg;
  })();
  const [proposal, setProposal] = useState(null);
  const [tally, setTally] = useState(null);
  const [myVote, setMyVote] = useState(null);
  const [voteGraph, setVoteGraph] = useState(null);
  const [graphOpen, setGraphOpen] = useState(window.innerWidth >= 768);
  const [sankeyOpen, setSankeyOpen] = useState(window.innerWidth >= 768);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  // Phase 8.5 — scope-aware state. subOrg is the proposal's sub-org (or null
  // for parent-org-wide proposals). delegations is fetched lazily so we can
  // detect cross-scope situations (Decision 10 moment 2).
  const [subOrg, setSubOrg] = useState(null);
  const [subOrgMembers, setSubOrgMembers] = useState(null);
  const [delegations, setDelegations] = useState([]);
  // Phase 9 — Polis link card state. `linkedPolises` is the resolved list
  // (structural + URL-detected, deduped). `polisLookup` is a parent-org
  // Polis list keyed by id, used to (a) resolve structural ids when the
  // unscoped proposal endpoint didn't return the rich `linked_polises` and
  // (b) look up URL-detected conversation_ids against the viewer's
  // visibility scope.
  const [linkedPolises, setLinkedPolises] = useState([]);
  // Phase 46 F1 — cosign-gated proposal state. The proposal payload
  // carries is_cosign_gated + cosign_threshold_snapshot + count + the
  // viewer's signed state; the panel renders a counter + Sign/Withdraw.
  const [cosignBusy, setCosignBusy] = useState(false);

  const fetchData = useCallback(async () => {
    // Phase 25 F3 — clear stale error before re-fetch so the Retry
    // button on ErrorMessage actually exits the error UI on a
    // successful refetch (same pattern as Delegations.jsx).
    setError('');
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

      // Phase 8.5 — fetch the user's delegations so we can detect cross-scope
      // delegate situations on sub-org proposals (Decision 10 moment 2). This
      // is independent of the proposal scope; we always need it to render the
      // "your delegate isn't in [Sub-Org]" branch.
      // Phase 18 F1 — delegations are now per-org. linkOrg already resolves
      // to the parent slug whether currentOrg is the parent or a sub-org.
      if (linkOrg?.slug) {
        try {
          const dels = await api.get(`/api/orgs/${linkOrg.slug}/delegations`);
          setDelegations(dels);
        } catch {/* ignore — branch will simply not fire */}
      }
    } catch (e) {
      setError(e.message || 'Failed to load proposal');
    } finally {
      setLoading(false);
    }
  }, [id, linkOrg?.slug]);

  useEffect(() => { fetchData(); }, [fetchData]);

  // Phase 8.5 — when the proposal carries a sub_org_id, look up the sub-org
  // (for name + the viewer's user_role) and the member roster so we can
  // detect membership for both the viewer and any candidate delegate.
  useEffect(() => {
    if (!proposal?.sub_org_id) {
      setSubOrg(null);
      setSubOrgMembers(null);
      return;
    }
    // Resolve the parent slug. If currentOrg is itself a sub-org we walk up
    // via userOrgs; otherwise currentOrg IS the parent. In rare cases where
    // currentOrg isn't loaded yet we bail and re-run when it changes.
    let parentSlug = null;
    if (currentOrg) {
      if (currentOrg.parent_org_id) {
        const parent = userOrgs.find(o => o.id === currentOrg.parent_org_id);
        parentSlug = parent?.slug || null;
      } else {
        parentSlug = currentOrg.slug;
      }
    }
    if (!parentSlug) return;

    let cancelled = false;
    (async () => {
      try {
        const subs = await api.get(`/api/orgs/${parentSlug}/sub-orgs`);
        if (cancelled) return;
        const found = subs.find(s => s.id === proposal.sub_org_id);
        if (found) setSubOrg(found);
        // Roster — only fetchable by sub-org members or parent-org admins;
        // 403 is expected for non-member viewers and is treated as "no
        // roster" so the read-only treatment still renders.
        try {
          const members = await api.get(
            `/api/orgs/${parentSlug}/sub-orgs/${found?.slug || ''}/members`
          );
          if (!cancelled) setSubOrgMembers(members);
        } catch {/* non-member: no roster */}
      } catch {/* ignore — we degrade gracefully */}
    })();
    return () => { cancelled = true; };
  }, [proposal?.sub_org_id, currentOrg, userOrgs]);

  // Phase 9 — resolve linked Polises for the link-card section.
  //
  // Sources, in order of preference:
  //   1. `proposal.linked_polises` (rich, when the org-scoped endpoint was
  //      hit — currently we use the unscoped /api/proposals/{id} which does
  //      NOT pass `db` to `_build_proposal_out`, so this is usually null).
  //   2. `proposal.linked_polis_ids` resolved against the parent-org Polis
  //      list — fetched once for the parent slug and used for both
  //      structural lookups and URL-detected conversation_id matching.
  //   3. URL detection from `proposal.body` — pol.is URLs that resolve to a
  //      visible Polis become cards; URLs that don't resolve fall through
  //      to plain links in the body (we don't render a "missing" card for
  //      URL-detected references — only for structural ids that fail).
  useEffect(() => {
    if (!proposal) {
      setLinkedPolises([]);
      return;
    }
    let cancelled = false;
    let parentSlug = null;
    if (currentOrg) {
      if (currentOrg.parent_org_id) {
        parentSlug = userOrgs.find(o => o.id === currentOrg.parent_org_id)?.slug || null;
      } else {
        parentSlug = currentOrg.slug;
      }
    }
    (async () => {
      // Detected URLs (always client-side, even when structural data is rich
      // — voters who pasted a pol.is URL into the body get the link card too).
      const detected = detectPolisUrlsInBody(proposal.body);

      // Source 1: rich resolved list straight from the proposal payload.
      if (Array.isArray(proposal.linked_polises) && proposal.linked_polises.length > 0) {
        if (!cancelled) {
          // Fold in URL-detected polises that resolve against the rich list.
          const byConvId = new Map();
          proposal.linked_polises.forEach(p => {
            if (p?.polis_conversation_id) byConvId.set(p.polis_conversation_id, p);
          });
          const extras = [];
          detected.forEach(({ conversationId }) => {
            const hit = byConvId.get(conversationId);
            if (hit && !proposal.linked_polises.some(p => p.id === hit.id)) {
              extras.push(hit);
            }
          });
          setLinkedPolises([...proposal.linked_polises, ...extras]);
        }
        return;
      }

      // Source 2/3: need parent-org Polis list. Bail if scope unavailable
      // (viewer has no currentOrg yet) — we'll re-run when it lands.
      if (!parentSlug) return;
      const ids = Array.isArray(proposal.linked_polis_ids)
        ? proposal.linked_polis_ids
        : [];
      if (ids.length === 0 && detected.length === 0) {
        if (!cancelled) setLinkedPolises([]);
        return;
      }
      let polisList = [];
      try {
        polisList = await api.get(`/api/orgs/${parentSlug}/polises`);
      } catch {/* viewer might not have list permission — bail */ return; }
      if (cancelled) return;

      const byId = new Map();
      const byConvId = new Map();
      (polisList || []).forEach(p => {
        if (p?.id) byId.set(p.id, p);
        if (p?.polis_conversation_id) byConvId.set(p.polis_conversation_id, p);
      });

      const out = [];
      const seen = new Set();
      // Structural ids first (ordering preserved); ids that don't resolve
      // become "Polis no longer available" cards so voters see the gap.
      ids.forEach(id => {
        const hit = byId.get(id);
        if (hit) {
          if (!seen.has(hit.id)) { out.push(hit); seen.add(hit.id); }
        } else {
          out.push({ __missing: true, id, originalUrl: null });
          seen.add(id);
        }
      });
      // URL-detected: only include if resolves to a visible Polis (per spec
      // — unresolved URLs fall back to the in-body plain link).
      detected.forEach(({ conversationId }) => {
        const hit = byConvId.get(conversationId);
        if (hit && !seen.has(hit.id)) {
          out.push(hit);
          seen.add(hit.id);
        }
      });
      if (!cancelled) setLinkedPolises(out);
    })();
    return () => { cancelled = true; };
  }, [proposal, currentOrg, userOrgs]);

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

  // Phase 46 F1 — cosign sign / withdraw handlers. The backend returns
  // the updated ProposalOut so we just merge it into our local state.
  async function handleCosignSign() {
    setCosignBusy(true);
    try {
      const updated = await api.post(`/api/proposals/${id}/cosign`);
      setProposal(updated);
      // If the threshold was met, the proposal moved to voting — refresh
      // the tally/my-vote so the voting UI renders correctly.
      if (updated.status === 'voting') await refreshVote();
    } catch (e) {
      setError(e?.message || 'Failed to add signature');
    } finally {
      setCosignBusy(false);
    }
  }

  async function handleCosignWithdraw() {
    setCosignBusy(true);
    try {
      const updated = await api.delete(`/api/proposals/${id}/cosign`);
      setProposal(updated);
    } catch (e) {
      setError(e?.message || 'Failed to withdraw signature');
    } finally {
      setCosignBusy(false);
    }
  }

  if (loading) return <Spinner />;
  if (error) return (
    <div className="max-w-4xl mx-auto px-4 py-8">
      <ErrorMessage error={error} onRetry={fetchData} />
    </div>
  );
  if (!proposal) return null;

  const isVoting = proposal.status === 'voting';
  const isClosed = ['passed', 'failed', 'withdrawn'].includes(proposal.status);
  const isDeliberation = proposal.status === 'deliberation';
  // Phase 32.1 F2.3 — edit-author button gating. Author OR admin can
  // edit; lockout check is server-side authoritative (E3) but the
  // frontend pre-checks to avoid rendering a button that 403s on click.
  const isAuthor = !!user && proposal.author_id === user.id;
  // Phase 32.2 E4 — restored gate: author OR has `org.edit_proposal`
  // permission. The permission key is now registered (M2) + seeded
  // to admin + steward in every org, and the backend PATCH endpoint
  // (B2) enforces it. Platform admin still bypasses via the helper's
  // is_admin short-circuit.
  const canEditViaPermission = useHasPermission('org.edit_proposal');
  const isPlatformAdmin = !!user && !!user.is_admin;
  const canEditAsNonAuthor = isPlatformAdmin || canEditViaPermission;
  let editLockoutReached = false;
  if (isDeliberation && proposal.deliberation_start && proposal.deliberation_days) {
    const startMs = new Date(proposal.deliberation_start).getTime();
    const endMs = startMs + Number(proposal.deliberation_days) * 86400_000;
    const lockoutFrac = (
      proposal.edit_lockout_fraction != null
        ? proposal.edit_lockout_fraction
        : 0.75
    );
    if (endMs > startMs) {
      const elapsedFrac = (Date.now() - startMs) / (endMs - startMs);
      editLockoutReached = elapsedFrac >= lockoutFrac;
    }
  }
  const canEditProposal = isDeliberation && (isAuthor || canEditAsNonAuthor) && !editLockoutReached;

  // ── Phase 8.5 — scope detection (Decisions 7 + 10) ────────────────────────
  // hasSubOrgScope: proposal is sub-org-scoped (sub_org_id is set).
  // isSubOrgMember: the current viewer has an active sub-org membership.
  //   We use SubOrgOut.user_role (non-null = active member) when available;
  //   if for some reason the sub-org fetch was blocked we fall back to the
  //   member roster check.
  // crossScopeDelegate: a delegate, if any, that is NOT in the sub-org's
  //   active member set — used to decide whether to show the new "your
  //   delegate isn't in [Sub-Org]" copy and to surface the delegate's name.
  const hasSubOrgScope = !!proposal.sub_org_id;
  const isSubOrgMember = hasSubOrgScope ? !!subOrg?.user_role : true;
  const memberIdSet = new Set(
    (subOrgMembers || [])
      .filter(m => m.status === 'active')
      .map(m => m.user_id)
  );
  const proposalTopicIds = new Set(
    (proposal.topics || []).map(pt => pt.topic_id)
  );
  // Find a delegation relevant to this proposal: matches a topic id, OR is
  // the global default (topic_id == null). We only flag the cross-scope
  // case when we actually know who the sub-org members are.
  let crossScopeDelegate = null;
  if (
    hasSubOrgScope &&
    isSubOrgMember &&
    subOrgMembers &&
    myVote &&
    !myVote.is_direct &&
    myVote?.vote_value == null
  ) {
    const relevantDels = delegations.filter(d => {
      if (d.topic_id == null) return true; // global default
      return proposalTopicIds.has(d.topic_id);
    });
    for (const d of relevantDels) {
      if (!memberIdSet.has(d.delegate_id)) {
        crossScopeDelegate = d.delegate;
        break;
      }
    }
  }

  return (
    <div className="max-w-6xl mx-auto px-4 py-8">
      {/* Back link */}
      <Link to={linkOrg ? urlFor(linkOrg, 'proposals') : '/orgs'} className="text-sm text-[var(--brand-accent)] hover:underline mb-4 inline-block">
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
              {/* Phase 8.5 — sub-org scope badge (Decision 7 surface) */}
              {hasSubOrgScope && subOrg && (
                <span
                  title={`Scoped to ${subOrg.name}`}
                  className="text-xs bg-cyan-50 text-cyan-700 border border-cyan-200 px-2 py-0.5 rounded-full font-medium"
                >
                  {subOrg.name}
                </span>
              )}
              {proposal.topics?.map(pt => (
                <TopicBadge key={pt.topic_id} topic={pt.topic} relevance={pt.relevance} />
              ))}
            </div>
            <h1 className="text-2xl font-bold text-[var(--brand-primary)] leading-tight mb-2">
              {proposal.title}
            </h1>
            <p className="text-sm text-gray-400">
              Proposed by {proposal.author?.display_name}
              {proposal.created_at && ` · ${new Date(proposal.created_at).toLocaleDateString()}`}
              {proposal.voting_end && isVoting && ` · Closes ${new Date(proposal.voting_end).toLocaleDateString()}`}
              {isClosed && proposal.voting_end && ` · Closed ${new Date(proposal.voting_end).toLocaleDateString()}`}
            </p>
            {/* Phase 32.1 F2.3 — edit-author button. Author or admin
                during deliberation, before lockout. Server-side
                authoritative via E3; this is the pre-check render. */}
            {canEditProposal && (
              <div className="mt-3">
                <EditProposalButton proposal={proposal} onSaved={fetchData} />
              </div>
            )}
            {/* Phase 32.1 F2.3 — lockout tooltip when author/admin but
                editing closed. */}
            {isDeliberation && (isAuthor || canEditAsNonAuthor) && editLockoutReached && (
              <p className="mt-2 text-xs text-gray-400 italic">
                Editing is locked for the final phase of deliberation.
              </p>
            )}
          </div>

          {/* Phase 48 Stage 1 — Election badge + self-nominate
              control. Renders only when proposal.is_election; lists
              the candidates + the action button for the viewer. */}
          {proposal.is_election && currentOrg?.slug && (
            <ElectionBadge
              proposal={proposal}
              orgSlug={currentOrg.slug}
              onChanged={fetchData}
            />
          )}

          {/* Phase 46 F1 / Phase 46a — Cosign gathering panel. Renders
              only when the proposal is in cosign gathering state
              (cosign-gated AND status=='deliberation'). 46a Item 1: the
              advancement bar is WEIGHT, not headcount — a high-weight
              delegate can move the bar substantially. The UI shows
              both numbers so members can see how delegation shifts it.
              46a Item 2: the threshold is a window-end gate, not a
              trigger. The proposal stays in deliberation for its full
              window; the worker decides advance-or-expire at expiry. */}
          {proposal.is_cosign_gated && proposal.status === 'deliberation' && (
            <div className="bg-amber-50 border border-amber-200 rounded-xl p-4 space-y-3">
              <div className="flex items-start justify-between gap-3 flex-wrap">
                <div>
                  <h3 className="text-sm font-semibold text-amber-800 uppercase tracking-wide">Gathering Signatures</h3>
                  <p className="text-sm text-amber-900 mt-1">
                    <strong>
                      Signed by {proposal.cosign_signature_count} member{proposal.cosign_signature_count === 1 ? '' : 's'}
                      {' · '}
                      {proposal.cosign_weight} of {proposal.cosign_threshold_snapshot} weight
                    </strong>
                    {(() => {
                      const need = (proposal.cosign_threshold_snapshot || 0) - (proposal.cosign_weight || 0);
                      return need > 0
                        ? ` — ${need} more weight needed at window-end`
                        : ' — threshold met (the advance happens at window-end)';
                    })()}
                  </p>
                  <p className="text-xs text-amber-800 mt-1">
                    Weight counts each signer plus everyone whose vote on this proposal would resolve to them through delegation. The proposal advances to voting at window-end if weight meets the threshold; otherwise it closes as expired.
                  </p>
                  {proposal.cosign_expires_at && (
                    <p className="text-xs text-amber-700 mt-1">
                      Window closes {new Date(proposal.cosign_expires_at).toLocaleString()}
                    </p>
                  )}
                </div>
                <div>
                  {isAuthor ? (
                    <span className="text-xs italic text-amber-700">
                      Your signature is implicit (you proposed this).
                    </span>
                  ) : proposal.viewer_has_cosigned === true ? (
                    <button
                      onClick={handleCosignWithdraw}
                      disabled={cosignBusy}
                      className="text-sm px-4 py-2 border border-amber-300 text-amber-800 rounded-lg hover:bg-amber-100 transition-colors disabled:opacity-50"
                    >
                      {cosignBusy ? 'Withdrawing…' : 'Withdraw signature'}
                    </button>
                  ) : (
                    <button
                      onClick={handleCosignSign}
                      disabled={cosignBusy}
                      className="text-sm px-4 py-2 bg-amber-600 text-white rounded-lg hover:bg-amber-700 transition-colors disabled:opacity-50"
                    >
                      {cosignBusy ? 'Signing…' : 'Sign this petition'}
                    </button>
                  )}
                </div>
              </div>
            </div>
          )}

          {/* Phase 32.1 F2.4 — change-log accordion. Hidden when no
              revisions exist. Visible to all org members. */}
          <ProposalChangeLog proposalId={proposal.id} />

          {/* Phase 20 F2 — Stable Result Required status panel.
              Renders only when stable-result is active for the proposal.
              The backend backwards-compat alias keeps the JSON key as
              `sustained_majority` on the results payload for one pass. */}
          {(isVoting || isClosed) && tally?.sustained_majority?.active && (
            <StableResultPanel tally={tally} />
          )}

          {/* Body */}
          {proposal.body ? (
            <div
              className="prose text-[#2C3E50] text-sm leading-relaxed"
              dangerouslySetInnerHTML={{ __html: `<p>${renderMarkdown(proposal.body)}</p>` }}
            />
          ) : (
            <p className="text-gray-400 italic text-sm">No description provided.</p>
          )}

          {/* Phase 9 — Linked Deliberations (link cards for structurally-
              attached + URL-detected pol.is references). Renders above the
              vote panel sidebar so voters notice the deliberation alongside
              the ballot. */}
          {linkedPolises.length > 0 && (
            <section className="space-y-2">
              <h3 className="text-sm font-semibold text-gray-700 uppercase tracking-wide">
                Linked Deliberations
              </h3>
              <div className="space-y-3">
                {linkedPolises.map((p, i) => {
                  if (p.__missing) {
                    return (
                      <LinkedPolisCard
                        key={`missing-${p.id || i}`}
                        polis={null}
                        orgSlug={null}
                        missing
                        originalUrl={p.originalUrl}
                      />
                    );
                  }
                  const cardSlug = (() => {
                    if (currentOrg?.parent_org_id) {
                      return userOrgs.find(o => o.id === currentOrg.parent_org_id)?.slug;
                    }
                    return currentOrg?.slug;
                  })();
                  return (
                    <LinkedPolisCard
                      key={p.id || i}
                      polis={p}
                      orgSlug={cardSlug}
                    />
                  );
                })}
              </div>
            </section>
          )}

          {/* Options list for multi-option proposals (visible when not actively voting) */}
          {(proposal.voting_method === 'approval' || proposal.voting_method === 'ranked_choice') && proposal.options?.length > 0 && !isVoting && (
            <div className="bg-white border border-gray-200 rounded-xl p-5">
              <h3 className="text-sm font-semibold text-gray-700 uppercase tracking-wide mb-3">Options</h3>
              <div className="space-y-2">
                {proposal.options.map((opt, idx) => (
                  <OptionRow
                    key={opt.id}
                    option={opt}
                    index={idx}
                    proposal={proposal}
                    currentUser={user}
                    onDeleted={fetchData}
                  />
                ))}
              </div>
              {/* Phase 32 W2 — Add an option button. Visible during
                  deliberation based on proposal flags.
                  Phase 32.1 F2.1 — onAdded re-fetches via fetchData so
                  the new option appears without a full page reload.
                  Voting-phase mount is below (the options-list section
                  hides during voting to avoid duplicating the ballot UI;
                  the Adder still needs to surface). */}
              <WriteInOptionAdder
                proposal={proposal}
                onAdded={fetchData}
              />
            </div>
          )}

          {/* Phase 32.2 hotfix #2 — Write-in adder for voting phase.
              When the options-list section above is hidden (because
              !isVoting gate, since the ballot shows options instead),
              the +Add option button was hidden alongside it. Mount the
              Adder separately during voting so users can still add
              write-ins when `effective_allow_write_ins_during_voting`
              is true. The component self-gates on the resolver flags,
              so this returns null if write-ins-during-voting is off. */}
          {(proposal.voting_method === 'approval' || proposal.voting_method === 'ranked_choice')
            && isVoting
            && proposal.effective_allow_write_in_options
            && proposal.effective_allow_write_ins_during_voting && (
            <div className="bg-white border border-gray-200 rounded-xl p-5">
              <h3 className="text-sm font-semibold text-gray-700 uppercase tracking-wide mb-1">Add a write-in option</h3>
              <p className="text-xs text-gray-500 mb-2">Write-in options added during voting become available immediately on the ballot.</p>
              <WriteInOptionAdder
                proposal={proposal}
                onAdded={fetchData}
              />
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

          {/* Phase 31 B6 — Support Trajectory, full-width below Vote
              Network. Always visible for voting + closed proposals
              (deliberation has no trajectory data). */}
          {/* Phase 32.1 F5 — also render the trajectory section during
              deliberation when the proposal has show_votes_during_
              deliberation=True (which implies the B1 worker is
              capturing snapshots during deliberation per Phase 32.1).
              The chart's x-axis auto-fits to dataMin/dataMax, so it
              extends back to deliberation_start naturally; the
              "Voting opens" phase-transition line renders once
              voting_start falls inside the data range. */}
          {(isVoting || isClosed
            || (isDeliberation && proposal.effective_show_votes_during_deliberation === true)
          ) && (
            <TrajectorySection
              proposalId={proposal.id}
              proposal={proposal}
              optionLabels={tally?.option_labels || {}}
            />
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
          {/* Phase 8.5 — Decision 7 read-only treatment for non-members of a
              sub-org-scoped proposal. Replaces the vote panel with text and
              suppresses the Delegate button (also hidden by virtue of not
              rendering the panel). */}
          {isVoting && hasSubOrgScope && !isSubOrgMember && (
            <div className="bg-gray-50 border border-gray-200 rounded-xl p-5">
              <h3 className="text-sm font-semibold text-gray-700 uppercase tracking-wide mb-2">
                Your Vote
              </h3>
              <p className="text-sm text-gray-600">
                View only — you&apos;re not a member of {subOrg?.name || 'this sub-organization'}.
              </p>
            </div>
          )}

          {/* Phase 8.5 — Decision 10 cross-scope copy. Shown when the viewer
              IS a sub-org member but their delegate is not, and the engine
              produced "not cast" as a result. Two action links: set a more
              specific delegate, or vote directly (jumps to the vote panel). */}
          {isVoting && hasSubOrgScope && isSubOrgMember && crossScopeDelegate && (
            <div className="bg-blue-50 border border-blue-100 rounded-xl p-4 space-y-2">
              <p className="text-sm text-gray-700">
                Your vote: not yet cast — your delegate{' '}
                <span className="font-medium">{crossScopeDelegate.display_name}</span>{' '}
                isn&apos;t in {subOrg?.name || 'this sub-organization'}
              </p>
              <div className="flex gap-3 text-xs">
                <Link
                  to={linkOrg ? urlFor(linkOrg, 'delegations') : '/orgs'}
                  className="text-[var(--brand-accent)] hover:underline"
                >
                  Set a specific delegate
                </Link>
                <button
                  type="button"
                  onClick={() => {
                    const el = document.getElementById('vote-panel');
                    if (el) el.scrollIntoView({ behavior: 'smooth', block: 'center' });
                  }}
                  className="text-[var(--brand-accent)] hover:underline"
                >
                  Vote directly
                </button>
              </div>
            </div>
          )}

          {/* Vote panel — only when the viewer can act (parent-scoped, or sub-
              org member). Non-members see the read-only block above instead. */}
          {/* Phase 32.1 F2.2 — vote panel also renders during deliberation
              when the proposal allows pre-voting. Pre-vote UI reuses the
              existing ballot components; a sentiment label clarifies that
              pre-votes are changeable until voting closes.
              Phase 32.2 — gate on resolved-effective value via the
              4-option resolver instead of the raw per-proposal column;
              `effective_allow_pre_voting=True` covers both explicit
              proposal override AND the org-level `always_on` /
              `default_on` modes. */}
          {(isVoting || (isDeliberation && proposal.effective_allow_pre_voting === true))
            && (!hasSubOrgScope || isSubOrgMember) && (
            <div id="vote-panel" className="bg-white border border-gray-200 rounded-xl p-5">
              {isDeliberation && (
                <div className="mb-3 px-3 py-2 bg-amber-50 border border-amber-200 rounded text-xs text-amber-800">
                  Pre-vote — you can change this anytime before voting closes.
                </div>
              )}
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
              {/* Phase 19 F3 — inline rationale composer. Only renders
                  when the user has a vote on this proposal (the
                  component self-gates on hasVote). Uses linkOrg slug
                  (parent-org rooted) for the deep link. */}
              <MyVoteRationaleBox
                proposalId={id}
                slug={linkOrg?.slug}
                hasVote={!!(myVote?.vote_value || myVote?.approvals?.length || myVote?.ranking?.length)}
              />
            </div>
          )}

          {proposal.status === 'deliberation' && !proposal.effective_allow_pre_voting && (
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

          {/* Phase 8 — Unresolved (escalated) banner. Phase 20 removed
              the floor / escalate mechanic, but historic proposals may
              still carry status=unresolved from before the redesign;
              the banner remains so admins can resolve them. */}
          {proposal.status === 'unresolved' && (
            <div className="rounded-xl p-4 text-center bg-yellow-50 border border-yellow-300 text-yellow-900">
              <p className="font-semibold">Awaiting Admin Review</p>
              <p className="text-xs mt-1">
                This proposal was escalated by the legacy sustained-majority
                feature (now Stable Result Required). An organization admin
                will resolve it: extend the window, fail it, mark it
                passed, or return it to deliberation.
              </p>
            </div>
          )}
        </div>
      </div>

      {/* Phase 10 W3 — Comment thread.
          Position per spec: LinkedDeliberations → VotePanel → CommentThread.
          Renders below the entire 2-column grid so the conversation has the
          full content width and isn't cramped into the sidebar. Collapsed by
          default (chevron toggle); first expand triggers the GET. */}
      <CommentThread proposalId={proposal.id} />
    </div>
  );
}

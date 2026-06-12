/* Phase 48 Stage 1 — minimum-viable election badge + self-nominate
 * control on a Proposal.
 *
 * Renders only when proposal.is_election. Surfaces:
 *   * an "Election" pill with the target title name.
 *   * the candidates list (member-readable).
 *   * a "Self-Nominate / Withdraw" button (active members only,
 *     during the nomination window).
 *
 * Stage 1 visual surface is deliberately minimal — Stage 2 + 3 layer
 * on richer UI (slate config, cosign trigger, etc.).
 */
import { useState, useEffect, useCallback } from 'react';
import api from '../api';
import { useToast } from './Toast';
import { useAuth } from '../AuthContext';
// Phase 67 W1 — winner announcement on closed elections. Winners come
// from the results tally (passed in by ProposalDetail); display names
// come from the option descriptions via the shared W3 helper.
import { effectiveApprovalWinners } from '../utils/approvalWinnerConfig';
import { optionLabelOf } from '../utils/optionDisplay';

export default function ElectionBadge({ proposal, orgSlug, onChanged, tally }) {
  const toast = useToast();
  const { user } = useAuth();
  const [candidates, setCandidates] = useState([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);

  const inNominationWindow = (
    proposal.status === 'deliberation' || proposal.status === 'draft'
  );

  const refresh = useCallback(async () => {
    if (!proposal?.is_election || !proposal?.id || !orgSlug) return;
    setLoading(true);
    try {
      const list = await api.get(
        `/api/orgs/${orgSlug}/elections/${proposal.id}/candidacies`,
      );
      setCandidates(list || []);
    } catch (e) {
      // Quietly tolerate: candidacies endpoint requires org-membership.
    } finally {
      setLoading(false);
    }
  }, [proposal, orgSlug]);

  useEffect(() => { refresh(); }, [refresh]);

  if (!proposal?.is_election) return null;

  const isCandidate = !!user && candidates.some(c => c.user_id === user.id);

  // Phase 67 W1 — banner copy per phase. After a seated (passed) close,
  // announce the winner set (tally winners + candidate display names)
  // instead of the stale "Voting will determine the winner." Quorum
  // gates seat installation: a failed close under an explicit quorum
  // seated nobody and says so honestly.
  const isClosedStatus = ['passed', 'failed', 'withdrawn'].includes(proposal.status);
  const winnerIds = proposal.status === 'passed'
    ? (proposal.voting_method === 'approval'
      ? effectiveApprovalWinners(tally)
      : (Array.isArray(tally?.winners) ? tally.winners : []))
    : [];
  const winnerNames = winnerIds.map(optionLabelOf(proposal, tally?.option_labels));
  let phaseCopy;
  if (inNominationWindow) {
    phaseCopy = 'Nominations are open. Members may self-declare during this window. When voting opens, the candidate set is locked.';
  } else if (!isClosedStatus) {
    phaseCopy = 'Nominations are closed. Voting will determine the winner.';
  } else if (winnerNames.length > 0) {
    phaseCopy = `Elected: ${winnerNames.join(', ')}`;
  } else if (proposal.status === 'withdrawn') {
    phaseCopy = 'This election was withdrawn.';
  } else if (proposal.status === 'failed' && tally?.quorum_met === false) {
    phaseCopy = 'Quorum not met — no seats were changed.';
  } else if (proposal.status === 'passed') {
    // Passed but the results tally hasn't loaded (yet) — don't claim
    // nobody was seated.
    phaseCopy = 'Voting has closed and the winning candidates have been seated.';
  } else {
    phaseCopy = 'This election closed without seating a winner.';
  }

  async function handleDeclare() {
    setBusy(true);
    try {
      await api.post(
        `/api/orgs/${orgSlug}/elections/${proposal.id}/candidacies`,
      );
      toast.success("You're on the ballot.");
      await refresh();
      onChanged?.();
    } catch (e) {
      toast.error(e.message || 'Failed to declare candidacy');
    } finally {
      setBusy(false);
    }
  }

  async function handleWithdraw() {
    setBusy(true);
    try {
      await api.delete(
        `/api/orgs/${orgSlug}/elections/${proposal.id}/candidacies`,
      );
      toast.success('Candidacy withdrawn.');
      await refresh();
      onChanged?.();
    } catch (e) {
      toast.error(e.message || 'Failed to withdraw');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="bg-purple-50 border border-purple-200 rounded-xl p-4 space-y-3">
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <h3 className="text-sm font-semibold text-purple-800 uppercase tracking-wide">
            Election: {proposal.election_title_name || 'a title'}
          </h3>
          <p className={`text-sm text-purple-900 mt-1 ${winnerNames.length > 0 ? 'font-semibold' : ''}`}>
            {phaseCopy}
          </p>
        </div>
        {inNominationWindow && user && (
          <div>
            {isCandidate ? (
              <button
                onClick={handleWithdraw}
                disabled={busy}
                className="text-sm px-4 py-2 border border-purple-300 text-purple-800 rounded-lg hover:bg-purple-100 transition-colors disabled:opacity-50"
              >
                {busy ? 'Withdrawing…' : 'Withdraw my candidacy'}
              </button>
            ) : (
              <button
                onClick={handleDeclare}
                disabled={busy}
                className="text-sm px-4 py-2 bg-purple-600 text-white rounded-lg hover:bg-purple-700 transition-colors disabled:opacity-50"
              >
                {busy ? 'Declaring…' : "I'm running"}
              </button>
            )}
          </div>
        )}
      </div>
      <div>
        <h4 className="text-xs font-semibold text-purple-700 uppercase tracking-wide mb-1">
          Candidates ({candidates.length})
        </h4>
        {loading ? (
          <p className="text-xs text-purple-700">Loading…</p>
        ) : candidates.length === 0 ? (
          <p className="text-xs italic text-purple-700">
            No candidates have declared yet.
          </p>
        ) : (
          <ul className="text-sm text-purple-900 list-disc list-inside space-y-0.5">
            {candidates.map(c => (
              <li key={c.user_id}>
                {c.display_name || c.username}
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

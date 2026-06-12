/* Phase 47 F1 — minimal title management UI.
 *
 * Listed in OrgSettings under the admin surface. Surfaces:
 *   * Existing titles (system + custom) with bound role + cardinality +
 *     holder count.
 *   * Create-custom-title form (name + bound role + cardinality + max).
 *   * Delete (custom titles without holders).
 *   * Assign / revoke holder for each custom title.
 *
 * System titles (Steward, Admin) are listed but uneditable + unassignable
 * via this UI per D6 — the underlying role is managed via the existing
 * transfer-stewardship / change-member-role flows.
 */
import { useState, useEffect, useCallback } from 'react';
import api from '../api';
import { useToast } from './Toast';
import { useHasPermission } from '../hooks/useHasPermission';
// Phase 67 W2 — shared winner-selection helpers (same presets, live
// preview, and validation the proposal creation form uses, so the
// phrasing matches exactly).
import {
  detectApprovalWinnerPreset,
  buildApprovalWinnerConfig,
  validateApprovalWinnerSelection,
  describeApprovalWinnerRule,
  SINGLE_WINNER_SUMMARY,
} from '../utils/approvalWinnerConfig';

/**
 * Phase 67 W2 — Open-election modal form. Replaces the old
 * window.prompt/confirm chain in handleOpenElection with a proper
 * form: voting method picker (ranked choice default / approval),
 * winner-selection control for approval elections, num_winners for
 * RCV multi-holder titles, slate mode, and nomination/voting window
 * lengths. POSTs to the existing /api/orgs/{slug}/elections endpoint.
 *
 * Visual conventions mirror DelegateModal (fixed overlay + white
 * rounded-xl card) and the ProposalManagement winner-selection block.
 */
function OpenElectionModal({ title, orgSlug, onClose }) {
  const toast = useToast();
  const isMulti = title.cardinality_mode === 'multi';
  const isSingleHolder = !isMulti;
  // Default seats for RCV multi-holder = open slots on the title
  // (cap minus current holders), floored at 1; uncapped titles
  // default to 1 like the old prompt did.
  const openSlots = isMulti && title.max_holders
    ? Math.max(1, title.max_holders - (title.holder_count || 0))
    : 1;

  const [votingMethod, setVotingMethod] = useState('ranked_choice');
  const [numWinners, setNumWinners] = useState(openSlots);
  const [winnerSel, setWinnerSel] = useState(() => detectApprovalWinnerPreset(null));
  const [slateMode, setSlateMode] = useState('fill_vacancies');
  const [deliberationDays, setDeliberationDays] = useState(3);
  const [votingDays, setVotingDays] = useState(7);
  // Phase 67 W1 — optional turnout quorum. Elections default to no
  // minimum (0): plurality of those who vote. An explicit quorum gates
  // seat installation — if turnout misses it, the election fails and
  // seats nobody.
  const [quorumPct, setQuorumPct] = useState(0);
  const [submitting, setSubmitting] = useState(false);

  const updateWinnerSel = (patch) => setWinnerSel(prev => ({ ...prev, ...patch }));
  const numOrEmpty = (v) => (v === '' ? '' : Number(v));

  // -- Validation (mirrors the backend rules so submit never 400s) --
  const isApproval = votingMethod === 'approval';
  const presetError = isApproval ? validateApprovalWinnerSelection(winnerSel) : null;
  const winnerConfig = (isApproval && !presetError)
    ? buildApprovalWinnerConfig(winnerSel)
    : null;
  // Backend rule: single-holder titles require max_winners == 1 when a
  // config is set (a rule that can seat more than one winner is
  // incoherent on a single-holder title).
  const singleHolderError = (
    isApproval && !presetError && isSingleHolder
    && winnerConfig && winnerConfig.max_winners !== 1
  )
    ? 'This title has a single holder — the winner rule must seat exactly one winner. Choose "Single winner" (or "Top X" with 1 winner).'
    : null;
  const winnerSelectionError = presetError || singleHolderError;
  const winnerRulePreview = (isApproval && !winnerSelectionError)
    ? (describeApprovalWinnerRule(winnerConfig) || SINGLE_WINNER_SUMMARY)
    : null;

  const numWinnersValid = !isMulti
    || votingMethod !== 'ranked_choice'
    || (Number.isInteger(Number(numWinners)) && Number(numWinners) >= 1);
  const windowsValid =
    deliberationDays !== '' && Number(deliberationDays) > 0
    && votingDays !== '' && Number(votingDays) > 0;
  const quorumValid =
    quorumPct === '' || (Number(quorumPct) >= 0 && Number(quorumPct) <= 100);
  const formValid =
    windowsValid
    && numWinnersValid
    && quorumValid
    && (!isApproval || !winnerSelectionError);

  async function handleSubmit(e) {
    e.preventDefault();
    if (!formValid || submitting) return;
    setSubmitting(true);
    try {
      const payload = {
        title_id: title.id,
        voting_method: votingMethod,
        slate_mode: slateMode,
        deliberation_days: Number(deliberationDays),
        voting_days: Number(votingDays),
      };
      if (votingMethod === 'ranked_choice' && isMulti) {
        payload.num_winners = Number(numWinners);
      } else {
        // Approval elections keep num_winners at 1 — the winner config
        // owns the winner count (backend 400s otherwise). Single-holder
        // RCV is always 1 winner.
        payload.num_winners = 1;
      }
      if (isApproval) {
        payload.approval_winner_config = winnerConfig; // null = single winner
      }
      // Optional turnout quorum — only sent when explicitly set above 0
      // (the backend defaults elections to quorum 0 / no minimum).
      if (quorumPct !== '' && Number(quorumPct) > 0) {
        payload.quorum_threshold = Number(quorumPct) / 100;
      }
      const proposal = await api.post(`/api/orgs/${orgSlug}/elections`, payload);
      toast.success(`Election opened for "${title.name}"`);
      window.location.href = `/${orgSlug}/proposals/${proposal.id}`;
    } catch (e2) {
      toast.error(e2.message || 'Failed to open election');
      setSubmitting(false);
    }
  }

  const inputCls = 'px-2 py-1 border border-gray-300 rounded text-sm focus:outline-none focus:ring-2 focus:ring-[var(--brand-accent)]';

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-xl shadow-lg w-full max-w-md max-h-[85vh] flex flex-col">
        <div className="p-4 border-b border-gray-100">
          <h2 className="font-semibold text-[var(--brand-primary)]">
            Open election for "{title.name}"
          </h2>
          <p className="text-xs text-gray-400 mt-0.5">
            {isMulti
              ? `Multi-holder title${title.max_holders ? ` (cap ${title.max_holders})` : ''} · currently held by ${title.holder_count}`
              : 'Single-holder title'}
          </p>
        </div>
        <form onSubmit={handleSubmit} className="p-4 space-y-4 flex-1 overflow-y-auto">
          {/* Voting method */}
          <div>
            <label className="block text-xs text-gray-500 mb-2">Voting method</label>
            <div className="space-y-1">
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="radio"
                  name="electionVotingMethod"
                  value="ranked_choice"
                  checked={votingMethod === 'ranked_choice'}
                  onChange={() => setVotingMethod('ranked_choice')}
                  className="accent-[var(--brand-accent)]"
                />
                <span className="text-sm text-gray-700">Ranked choice</span>
                <span className="text-xs text-gray-400">(default)</span>
              </label>
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="radio"
                  name="electionVotingMethod"
                  value="approval"
                  checked={votingMethod === 'approval'}
                  onChange={() => setVotingMethod('approval')}
                  className="accent-[var(--brand-accent)]"
                />
                <span className="text-sm text-gray-700">Approval</span>
              </label>
            </div>
          </div>

          {/* Winner selection (approval only) — same four presets as the
              proposal creation form, writing one generalized config. */}
          {isApproval && (
            <div>
              <label className="block text-xs text-gray-500 mb-2">Winner selection</label>
              {isSingleHolder && (
                <p className="text-xs text-gray-400 mb-2">
                  This title has a single holder, so the winner rule must seat exactly one winner.
                </p>
              )}
              <div className="space-y-2">
                <label className="flex items-center gap-2 cursor-pointer">
                  <input type="radio" name="electionWinnerSelection" value="single"
                    checked={winnerSel.mode === 'single'}
                    onChange={() => updateWinnerSel({ mode: 'single' })}
                    className="accent-[var(--brand-accent)]" />
                  <span className="text-sm text-gray-700">Single winner</span>
                  <span className="text-xs text-gray-400">(default)</span>
                </label>

                <div className="flex items-center gap-2 flex-wrap">
                  <label className="flex items-center gap-2 cursor-pointer">
                    <input type="radio" name="electionWinnerSelection" value="top_x"
                      checked={winnerSel.mode === 'top_x'}
                      onChange={() => updateWinnerSel({ mode: 'top_x' })}
                      className="accent-[var(--brand-accent)]" />
                    <span className="text-sm text-gray-700">Top X</span>
                  </label>
                  {winnerSel.mode === 'top_x' && (
                    <label className="flex items-center gap-1 text-xs text-gray-600">
                      winners:
                      <input
                        type="number"
                        min={1}
                        value={winnerSel.topX}
                        onChange={e => updateWinnerSel({ topX: numOrEmpty(e.target.value) })}
                        className={`w-16 ${inputCls}`}
                      />
                    </label>
                  )}
                </div>

                <div className="flex items-center gap-2 flex-wrap">
                  <label className="flex items-center gap-2 cursor-pointer">
                    <input type="radio" name="electionWinnerSelection" value="threshold"
                      checked={winnerSel.mode === 'threshold'}
                      onChange={() => updateWinnerSel({ mode: 'threshold' })}
                      className="accent-[var(--brand-accent)]" />
                    <span className="text-sm text-gray-700">Approval threshold</span>
                  </label>
                  {winnerSel.mode === 'threshold' && (
                    <label className="flex items-center gap-1 text-xs text-gray-600">
                      at least
                      <input
                        type="number"
                        min={1}
                        max={100}
                        value={winnerSel.thresholdPct}
                        onChange={e => updateWinnerSel({ thresholdPct: numOrEmpty(e.target.value) })}
                        className={`w-16 ${inputCls}`}
                      />
                      % of ballots
                    </label>
                  )}
                </div>

                <div className="space-y-1">
                  <label className="flex items-center gap-2 cursor-pointer">
                    <input type="radio" name="electionWinnerSelection" value="floor_extras"
                      checked={winnerSel.mode === 'floor_extras'}
                      onChange={() => updateWinnerSel({ mode: 'floor_extras' })}
                      className="accent-[var(--brand-accent)]" />
                    <span className="text-sm text-gray-700">Floor + extras</span>
                  </label>
                  {winnerSel.mode === 'floor_extras' && (
                    <div className="pl-6 flex items-center gap-2 flex-wrap text-xs text-gray-600">
                      <label className="flex items-center gap-1">
                        at least
                        <input
                          type="number"
                          min={1}
                          value={winnerSel.floorMin}
                          onChange={e => updateWinnerSel({ floorMin: numOrEmpty(e.target.value) })}
                          className={`w-16 ${inputCls}`}
                        />
                        winners
                      </label>
                      <label className="flex items-center gap-1">
                        up to
                        <input
                          type="number"
                          min={1}
                          value={winnerSel.floorMax}
                          placeholder="no cap"
                          onChange={e => updateWinnerSel({ floorMax: numOrEmpty(e.target.value) })}
                          className={`w-20 ${inputCls}`}
                        />
                        total
                      </label>
                      <label className="flex items-center gap-1">
                        extras need
                        <input
                          type="number"
                          min={1}
                          max={100}
                          value={winnerSel.floorPct}
                          onChange={e => updateWinnerSel({ floorPct: numOrEmpty(e.target.value) })}
                          className={`w-16 ${inputCls}`}
                        />
                        % approval
                      </label>
                    </div>
                  )}
                </div>
              </div>
              {winnerRulePreview && (
                <p className="text-xs text-gray-600 mt-2 font-medium">{winnerRulePreview}</p>
              )}
              {winnerSelectionError && (
                <p className="text-xs text-red-500 mt-1">{winnerSelectionError}</p>
              )}
            </div>
          )}

          {/* Seats up for election (ranked choice on multi-holder titles) */}
          {votingMethod === 'ranked_choice' && isMulti && (
            <div>
              <label className="block text-xs text-gray-500 mb-1">Seats up for election</label>
              <input
                type="number"
                min={1}
                value={numWinners}
                onChange={e => setNumWinners(numOrEmpty(e.target.value))}
                className={`w-24 ${inputCls}`}
              />
              <p className="text-xs text-gray-400 mt-1">
                1 seat = ranked-choice voting (IRV). More than 1 seat = single transferable vote (STV).
              </p>
              {!numWinnersValid && (
                <p className="text-xs text-red-500 mt-1">
                  Seats must be a whole number (at least 1).
                </p>
              )}
            </div>
          )}

          {/* Slate mode (multi-holder titles only — single-holder elections
              always replace the holder). */}
          {isMulti && (
            <div>
              <label className="block text-xs text-gray-500 mb-1">Slate mode</label>
              <select
                value={slateMode}
                onChange={e => setSlateMode(e.target.value)}
                className="w-full px-3 py-1.5 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[var(--brand-accent)]"
              >
                <option value="fill_vacancies">Fill vacancies — winners join the current holders</option>
                <option value="refresh_slate">Refresh slate — winners replace all current holders</option>
              </select>
            </div>
          )}

          {/* Windows */}
          <div className="flex flex-wrap gap-4">
            <label className="text-sm space-y-1">
              <span className="block text-xs text-gray-500">Nomination window (days)</span>
              <input
                type="number"
                min={0.5}
                step="any"
                value={deliberationDays}
                onChange={e => setDeliberationDays(numOrEmpty(e.target.value))}
                className={`w-28 ${inputCls}`}
              />
            </label>
            <label className="text-sm space-y-1">
              <span className="block text-xs text-gray-500">Voting window (days)</span>
              <input
                type="number"
                min={0.5}
                step="any"
                value={votingDays}
                onChange={e => setVotingDays(numOrEmpty(e.target.value))}
                className={`w-28 ${inputCls}`}
              />
            </label>
          </div>
          {!windowsValid && (
            <p className="text-xs text-red-500">Both windows must be greater than zero days.</p>
          )}

          {/* Turnout quorum (optional) */}
          <div>
            <label className="block text-xs text-gray-500 mb-1">Turnout quorum (% of eligible members, optional)</label>
            <input
              type="number"
              min={0}
              max={100}
              step="any"
              value={quorumPct}
              onChange={e => setQuorumPct(numOrEmpty(e.target.value))}
              className={`w-24 ${inputCls}`}
            />
            <p className="text-xs text-gray-400 mt-1">
              0 = no minimum (default) — the most-supported candidates win
              regardless of turnout. If you set a quorum and turnout misses
              it, the election fails and no seats are changed.
            </p>
            {!quorumValid && (
              <p className="text-xs text-red-500 mt-1">Quorum must be between 0 and 100 percent.</p>
            )}
          </div>

          <p className="text-xs text-gray-500">
            The election proposal will enter the nomination window. Members can
            self-nominate; voting begins when an admin advances the proposal to
            voting.
          </p>
        </form>
        <div className="p-4 border-t border-gray-100 flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            disabled={submitting}
            className="text-sm px-4 py-2 border border-gray-300 text-gray-600 rounded-lg hover:bg-gray-50 transition-colors disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={handleSubmit}
            disabled={submitting || !formValid}
            className="text-sm px-4 py-2 bg-purple-600 text-white rounded-lg hover:bg-purple-700 transition-colors disabled:opacity-50"
          >
            {submitting ? 'Opening…' : 'Open election'}
          </button>
        </div>
      </div>
    </div>
  );
}

export default function OrgTitlesPanel({ orgSlug }) {
  const toast = useToast();
  const canManageTitles = useHasPermission('title.manage');
  const [titles, setTitles] = useState([]);
  const [members, setMembers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState('');
  const [newBoundRole, setNewBoundRole] = useState('');
  const [newCardinality, setNewCardinality] = useState('single');
  const [newMaxHolders, setNewMaxHolders] = useState('');
  const [assignFor, setAssignFor] = useState(null); // {titleId}
  const [assignTargetId, setAssignTargetId] = useState('');
  // Phase 67 W2 — title whose open-election modal is showing (or null).
  const [electionTitle, setElectionTitle] = useState(null);

  const refresh = useCallback(async () => {
    if (!orgSlug) return;
    setLoading(true);
    try {
      const [t, m] = await Promise.all([
        api.get(`/api/orgs/${orgSlug}/titles`),
        api.get(`/api/orgs/${orgSlug}/members`),
      ]);
      setTitles(t || []);
      setMembers((m || []).filter(x => x.status === 'active'));
    } catch (e) {
      toast.error(e.message || 'Failed to load titles');
    } finally {
      setLoading(false);
    }
  }, [orgSlug, toast]);

  useEffect(() => { refresh(); }, [refresh]);

  async function handleCreate(e) {
    e.preventDefault();
    if (!newName.trim()) return;
    setCreating(true);
    try {
      const payload = {
        name: newName.trim(),
        cardinality_mode: newCardinality,
      };
      if (newBoundRole) payload.bound_role = newBoundRole;
      if (newCardinality === 'multi' && newMaxHolders) {
        payload.max_holders = Number(newMaxHolders);
      }
      await api.post(`/api/orgs/${orgSlug}/titles`, payload);
      toast.success(`Title "${newName.trim()}" created`);
      setNewName('');
      setNewBoundRole('');
      setNewCardinality('single');
      setNewMaxHolders('');
      await refresh();
    } catch (e) {
      toast.error(e.message || 'Failed to create title');
    } finally {
      setCreating(false);
    }
  }

  async function handleDelete(title) {
    if (!confirm(`Delete title "${title.name}"? (must have zero holders)`)) return;
    try {
      await api.delete(`/api/orgs/${orgSlug}/titles/${title.id}`);
      toast.success(`Deleted "${title.name}"`);
      await refresh();
    } catch (e) {
      toast.error(e.message || 'Failed to delete title');
    }
  }

  // Phase 67 W2 — the open-election flow now runs through a proper
  // modal form (OpenElectionModal above) instead of a window.prompt /
  // confirm chain. The button just selects the target title.
  function handleOpenElection(title) {
    setElectionTitle(title);
  }

  async function handleSetFillMethod(title, fillMethod) {
    try {
      await api.patch(`/api/orgs/${orgSlug}/titles/${title.id}`, {
        fill_method: fillMethod,
      });
      toast.success(`Fill method set to "${fillMethod}" for ${title.name}`);
      await refresh();
    } catch (e) {
      toast.error(e.message || 'Failed to update title');
    }
  }

  async function handleSetTerm(title) {
    // Phase 49 — prompt for term length in days. Empty / 0 / cancel
    // clears the term (back to Phase 48 elected-until-challenged).
    const current = title.term_length_days ?? '';
    const raw = window.prompt(
      `Term length for "${title.name}" in days (blank or 0 to clear, e.g. 365 for ~1 year):`,
      current,
    );
    if (raw === null) return; // cancel
    const trimmed = raw.trim();
    let term = 0;
    if (trimmed === '') {
      term = 0;
    } else {
      const n = parseInt(trimmed, 10);
      if (!Number.isFinite(n) || n < 0) {
        toast.error('Term length must be a non-negative integer (days).');
        return;
      }
      term = n;
    }
    let leadTime = title.election_lead_time_days ?? 7;
    if (term > 0) {
      const leadRaw = window.prompt(
        `Lead time in days before term-end to open the election (default 7):`,
        String(title.election_lead_time_days || 7),
      );
      if (leadRaw === null) return;
      const lt = parseInt(leadRaw.trim(), 10);
      if (Number.isFinite(lt) && lt >= 1) leadTime = lt;
    }
    try {
      await api.patch(`/api/orgs/${orgSlug}/titles/${title.id}`, {
        term_length_days: term,
        election_lead_time_days: leadTime,
      });
      toast.success(
        term > 0
          ? `Term set to ${term} days for ${title.name}`
          : `Term cleared for ${title.name}`,
      );
      await refresh();
    } catch (e) {
      toast.error(e.message || 'Failed to update term');
    }
  }

  async function handleAssign(title) {
    if (!assignTargetId) return;
    try {
      await api.post(
        `/api/orgs/${orgSlug}/titles/${title.id}/assignments`,
        { user_id: assignTargetId },
      );
      toast.success(`Assigned "${title.name}"`);
      setAssignFor(null);
      setAssignTargetId('');
      await refresh();
    } catch (e) {
      toast.error(e.message || 'Failed to assign title');
    }
  }

  async function handleRevoke(title, userId) {
    if (!confirm(`Revoke "${title.name}" from this member?`)) return;
    try {
      await api.delete(
        `/api/orgs/${orgSlug}/titles/${title.id}/assignments/${userId}`,
      );
      toast.success(`Revoked "${title.name}"`);
      await refresh();
    } catch (e) {
      toast.error(e.message || 'Failed to revoke title');
    }
  }

  if (!canManageTitles) return null;

  return (
    <section className="space-y-3">
      {/* Phase 67 W2 — open-election modal form */}
      {electionTitle && (
        <OpenElectionModal
          title={electionTitle}
          orgSlug={orgSlug}
          onClose={() => setElectionTitle(null)}
        />
      )}
      <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide">
        Org Titles / Offices
      </h2>
      <div className="bg-white border border-gray-200 rounded-xl p-5 space-y-4">
        <p className="text-sm text-gray-600">
          Define titles members can hold (President, Treasurer, Council Member, ...). Optionally bind a title to a platform role so holding the title grants the role. <strong>Steward</strong> and <strong>Admin</strong> are system titles — their underlying roles are managed via the existing role-change / stewardship-transfer flows.
        </p>

        {loading ? (
          <p className="text-sm text-gray-500">Loading…</p>
        ) : (
          <div className="space-y-2">
            {titles.map(t => (
              <div
                key={t.id}
                className="border border-gray-200 rounded-lg p-3 space-y-2"
              >
                <div className="flex items-start justify-between gap-3 flex-wrap">
                  <div>
                    <span className="font-medium text-gray-800">{t.name}</span>
                    {t.is_system && (
                      <span className="ml-2 text-xs text-gray-500 italic">system</span>
                    )}
                    <div className="text-xs text-gray-500 mt-0.5">
                      {t.bound_role ? `Binds: ${t.bound_role}` : 'No bound role'}
                      {' · '}
                      {t.cardinality_mode === 'single' ? 'Single holder' : `Multi-holder${t.max_holders ? ` (cap ${t.max_holders})` : ''}`}
                      {' · '}
                      Held by {t.holder_count}
                    </div>
                    {/* Phase 49 — surface term + next election when set.
                        Empty when no term — Phase 48 "elected-until-
                        challenged" behavior is preserved silently. */}
                    {t.term_length_days != null && (
                      <div className="text-xs text-purple-700 mt-0.5">
                        Term: {t.term_length_days} days
                        {t.next_election_due_at && (
                          <>
                            {' · '}
                            Next election: {new Date(t.next_election_due_at).toLocaleDateString()}
                          </>
                        )}
                      </div>
                    )}
                  </div>
                  <div className="flex gap-2 flex-wrap">
                    {/* Phase 48 Stage 1 — fill_method selector (admin
                        can flip a title to electable). Available on
                        all titles since fill_method is an org-policy
                        knob, not a structural property. */}
                    <select
                      value={t.fill_method}
                      onChange={e => handleSetFillMethod(t, e.target.value)}
                      title="Fill method"
                      className="text-xs px-2 py-1 border border-gray-300 rounded"
                    >
                      <option value="assigned">assigned</option>
                      <option value="elected">elected</option>
                      <option value="both">both</option>
                    </select>
                    {(t.fill_method === 'elected' || t.fill_method === 'both') && (
                      <button
                        onClick={() => handleOpenElection(t)}
                        className="text-xs px-2 py-1 border border-purple-300 text-purple-700 rounded hover:bg-purple-50"
                      >
                        Open election
                      </button>
                    )}
                    {/* Phase 49 — term config. Available on any
                        electable title (system + custom). System
                        titles can have terms — the resolution path
                        is uniform through finalize_election. */}
                    {(t.fill_method === 'elected' || t.fill_method === 'both') && (
                      <button
                        onClick={() => handleSetTerm(t)}
                        className="text-xs px-2 py-1 border border-purple-300 text-purple-700 rounded hover:bg-purple-50"
                        title="Set fixed term (auto-scheduled re-election)"
                      >
                        Term…
                      </button>
                    )}
                    {!t.is_system && (
                      <>
                        <button
                          onClick={() => setAssignFor(t.id === assignFor ? null : t.id)}
                          className="text-xs px-2 py-1 border border-gray-300 rounded hover:bg-gray-50"
                        >
                          {assignFor === t.id ? 'Cancel' : 'Assign…'}
                        </button>
                        {t.holder_count === 0 && (
                          <button
                            onClick={() => handleDelete(t)}
                            className="text-xs px-2 py-1 border border-red-300 text-red-700 rounded hover:bg-red-50"
                          >
                            Delete
                          </button>
                        )}
                      </>
                    )}
                  </div>
                </div>
                {assignFor === t.id && !t.is_system && (
                  <div className="flex flex-wrap items-center gap-2 pt-2 border-t border-gray-100">
                    <select
                      value={assignTargetId}
                      onChange={e => setAssignTargetId(e.target.value)}
                      className="px-3 py-1.5 border border-gray-300 rounded-lg text-sm"
                    >
                      <option value="">Pick a member…</option>
                      {members.map(m => (
                        <option key={m.user_id} value={m.user_id}>
                          {m.display_name || m.username} ({m.role})
                        </option>
                      ))}
                    </select>
                    <button
                      onClick={() => handleAssign(t)}
                      disabled={!assignTargetId}
                      className="text-xs px-3 py-1.5 bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50"
                    >
                      Assign
                    </button>
                  </div>
                )}
                {/* v2 followup — per-title holders list with inline
                    revoke. v1 surfaces holder_count above; revocation is
                    available via the API but not via this UI yet. */}
              </div>
            ))}
          </div>
        )}

        <form
          onSubmit={handleCreate}
          className="border-t border-gray-200 pt-4 space-y-3"
        >
          <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wide">Create new title</h3>
          <div className="flex flex-wrap gap-3">
            <label className="text-sm space-y-1">
              <span className="block text-xs text-gray-600">Name</span>
              <input
                type="text"
                value={newName}
                onChange={e => setNewName(e.target.value)}
                placeholder="Treasurer"
                className="w-44 px-3 py-1.5 border border-gray-300 rounded-lg text-sm"
              />
            </label>
            <label className="text-sm space-y-1">
              <span className="block text-xs text-gray-600">Bound role</span>
              <select
                value={newBoundRole}
                onChange={e => setNewBoundRole(e.target.value)}
                className="w-40 px-3 py-1.5 border border-gray-300 rounded-lg text-sm"
              >
                <option value="">(none — label only)</option>
                <option value="moderator">moderator</option>
                <option value="admin">admin</option>
                <option value="steward">steward</option>
              </select>
            </label>
            <label className="text-sm space-y-1">
              <span className="block text-xs text-gray-600">Cardinality</span>
              <select
                value={newCardinality}
                onChange={e => setNewCardinality(e.target.value)}
                className="w-32 px-3 py-1.5 border border-gray-300 rounded-lg text-sm"
              >
                <option value="single">single</option>
                <option value="multi">multi</option>
              </select>
            </label>
            {newCardinality === 'multi' && (
              <label className="text-sm space-y-1">
                <span className="block text-xs text-gray-600">Max holders (optional)</span>
                <input
                  type="number"
                  min={1}
                  value={newMaxHolders}
                  onChange={e => setNewMaxHolders(e.target.value)}
                  placeholder="unlimited"
                  className="w-28 px-3 py-1.5 border border-gray-300 rounded-lg text-sm"
                />
              </label>
            )}
            <button
              type="submit"
              disabled={creating || !newName.trim()}
              className="self-end text-sm px-4 py-1.5 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50"
            >
              {creating ? 'Creating…' : 'Create'}
            </button>
          </div>
        </form>
      </div>
    </section>
  );
}



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

  async function handleOpenElection(title) {
    // Phase 48 Stage 2 — multi-holder titles can elect num_winners > 1;
    // single-holder titles are always num_winners=1.
    const isMulti = title.cardinality_mode === 'multi';
    let numWinners = 1;
    if (isMulti) {
      const raw = prompt(
        `Open election for "${title.name}" (multi-holder).\n\n` +
        'How many seats are up for election?',
        '1',
      );
      if (raw == null) return;
      numWinners = parseInt(raw, 10);
      if (!Number.isFinite(numWinners) || numWinners < 1) {
        toast.error('num_winners must be a positive integer');
        return;
      }
    }
    let slateMode = 'fill_vacancies';
    if (isMulti) {
      const slate = prompt(
        'Slate mode: type "refresh" to wipe current holders, ' +
        'or anything else to fill vacancies (add to existing).',
        'fill',
      );
      if (slate == null) return;
      slateMode = slate.toLowerCase().startsWith('refresh')
        ? 'refresh_slate' : 'fill_vacancies';
    }
    if (!confirm(
      `Open an election for "${title.name}"?\n\n` +
      `Seats: ${numWinners}\n` +
      `Slate mode: ${slateMode}\n\n` +
      'The election proposal will enter the nomination window. ' +
      'Members can self-nominate; voting begins when an admin ' +
      'advances the proposal to voting.'
    )) return;
    try {
      const proposal = await api.post(
        `/api/orgs/${orgSlug}/elections`,
        {
          title_id: title.id,
          num_winners: numWinners,
          slate_mode: slateMode,
        },
      );
      toast.success(`Election opened for "${title.name}"`);
      window.location.href = `/${orgSlug}/proposals/${proposal.id}`;
    } catch (e) {
      toast.error(e.message || 'Failed to open election');
    }
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



import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import api from '../api';

/**
 * IssuanceProposeForm — Phase 90e.
 *
 * Under member_vote issuance mode, share issuance happens ONLY through a passed
 * issuance proposal. This compact form lets a holder of member.set_voting_weight
 * draft one for the two most common actions — set a member's weight, or raise the
 * authorized cap — and posts it to POST /orgs/{slug}/issuance-proposals. On
 * success it navigates to the new proposal so the author can open voting.
 *
 * Only rendered by ShareActivity when issuance_mode === 'member_vote' and the
 * viewer can manage issuance; other actions (rules, mode weaken) are authored
 * from their own surfaces in a later pass.
 */
export default function IssuanceProposeForm({ slug, unit }) {
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const [action, setAction] = useState('set_weight');
  const [members, setMembers] = useState([]);
  const [targetId, setTargetId] = useState('');
  const [newWeight, setNewWeight] = useState('');
  const [newCap, setNewCap] = useState('');
  const [title, setTitle] = useState('');
  const [body, setBody] = useState('');
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!open || action !== 'set_weight' || members.length > 0) return;
    api.get(`/api/orgs/${slug}/members`)
      .then(d => setMembers(Array.isArray(d) ? d : (d?.members || [])))
      .catch(() => {});
  }, [open, action, slug, members.length]);

  async function submit(e) {
    e.preventDefault();
    setError('');
    let payload;
    if (action === 'set_weight') {
      if (!targetId || newWeight === '') { setError('Pick a member and a new amount.'); return; }
      payload = { action: 'set_weight', params: { target_user_id: targetId, new_weight: Number(newWeight) } };
    } else {
      if (newCap === '') { setError('Enter a new cap.'); return; }
      payload = { action: 'cap_raise', params: { authorized_total: Number(newCap) } };
    }
    setSaving(true);
    try {
      const created = await api.post(`/api/orgs/${slug}/issuance-proposals`, {
        title: title.trim() || (action === 'set_weight' ? 'Issue shares' : 'Raise authorized cap'),
        body: body.trim(),
        issuance_payload: payload,
      });
      navigate(`/${slug}/proposals/${created.id}`);
    } catch (err) {
      setError(err.message || 'Failed to create issuance proposal');
    } finally {
      setSaving(false);
    }
  }

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="mb-4 px-3 py-1.5 rounded-lg text-sm bg-[var(--brand-primary)] text-white hover:opacity-90"
      >
        Propose share issuance
      </button>
    );
  }

  return (
    <form onSubmit={submit} className="mb-4 bg-white border border-gray-200 rounded-xl p-4 space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-gray-700">Propose share issuance</h3>
        <button type="button" onClick={() => setOpen(false)} className="text-xs text-gray-400 hover:text-gray-600">Cancel</button>
      </div>
      <p className="text-xs text-gray-500">
        This creates a proposal the members vote on. If it passes, the change is applied automatically.
      </p>

      <div className="flex gap-3 text-sm">
        <label className="flex items-center gap-1.5 cursor-pointer">
          <input type="radio" name="issAction" checked={action === 'set_weight'} onChange={() => setAction('set_weight')} />
          Set a member&apos;s {unit}
        </label>
        <label className="flex items-center gap-1.5 cursor-pointer">
          <input type="radio" name="issAction" checked={action === 'cap_raise'} onChange={() => setAction('cap_raise')} />
          Raise authorized cap
        </label>
      </div>

      {action === 'set_weight' ? (
        <div className="flex flex-wrap gap-2">
          <select value={targetId} onChange={e => setTargetId(e.target.value)}
                  className="px-3 py-2 border border-gray-300 rounded-lg text-sm">
            <option value="">Select member…</option>
            {members.map(m => (
              <option key={m.user_id} value={m.user_id}>{m.display_name || m.username || m.user_id}</option>
            ))}
          </select>
          <input type="number" min="0" step="1" value={newWeight} onChange={e => setNewWeight(e.target.value)}
                 placeholder={`New ${unit}`}
                 className="w-32 px-3 py-2 border border-gray-300 rounded-lg text-sm" />
        </div>
      ) : (
        <input type="number" min="0" step="1" value={newCap} onChange={e => setNewCap(e.target.value)}
               placeholder="New authorized total"
               className="w-48 px-3 py-2 border border-gray-300 rounded-lg text-sm" />
      )}

      <input type="text" value={title} onChange={e => setTitle(e.target.value)}
             placeholder="Proposal title (optional)"
             className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm" />
      <textarea value={body} onChange={e => setBody(e.target.value)} rows={2}
                placeholder="Why? (optional)"
                className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm" />

      {error && <p className="text-xs text-red-600">{error}</p>}
      <button type="submit" disabled={saving}
              className="px-3 py-1.5 rounded-lg text-sm bg-[var(--brand-primary)] text-white hover:opacity-90 disabled:opacity-50">
        {saving ? 'Creating…' : 'Create proposal'}
      </button>
    </form>
  );
}

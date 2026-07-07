import { useState, useEffect } from 'react';
import api from '../api';
import { useToast } from './Toast';

/**
 * TransferShares — Phase 90b member-to-member transfer action.
 *
 * Visible only when weighted voting AND transfers are both enabled. Members
 * pick a recipient (from the org member list), enter an amount, and confirm.
 * Transfers move existing shares; they never change the org total.
 */
export default function TransferShares({ slug, unit, onDone }) {
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const [members, setMembers] = useState([]);
  const [toUserId, setToUserId] = useState('');
  const [amount, setAmount] = useState('');
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (open && members.length === 0) {
      api.get(`/api/orgs/${slug}/members`)
        .then(list => setMembers(list.filter(m => m.status === 'active')))
        .catch(() => {});
    }
  }, [open, slug, members.length]);

  async function submit() {
    const n = parseInt(amount, 10);
    if (!toUserId || Number.isNaN(n) || n < 1) {
      toast.error('Pick a recipient and an amount of at least 1.');
      return;
    }
    setSaving(true);
    try {
      const res = await api.post(`/api/orgs/${slug}/shares/transfer`, {
        to_user_id: toUserId, amount: n,
      });
      toast.success(`Transferred ${n} ${unit}. Your balance is now ${res.sender_balance} ${unit}.`);
      setOpen(false);
      setToUserId('');
      setAmount('');
      onDone && onDone();
    } catch (e) {
      toast.error(e.message || 'Transfer failed');
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="mb-4">
      {!open ? (
        <button
          onClick={() => setOpen(true)}
          className="text-xs px-3 py-1.5 border border-[var(--brand-accent)] text-[var(--brand-accent)] rounded-lg hover:bg-[var(--brand-accent)] hover:text-white transition-colors"
        >
          Transfer {unit}
        </button>
      ) : (
        <div className="bg-white border border-gray-200 rounded-xl p-4 space-y-2">
          <div className="text-sm font-semibold text-gray-700">Transfer {unit}</div>
          <div className="flex items-center gap-2 flex-wrap text-sm">
            <span className="text-xs text-gray-600">Send</span>
            <input
              type="number" min="1" value={amount}
              onChange={e => setAmount(e.target.value)}
              className="w-24 border border-gray-300 rounded px-2 py-1"
              placeholder="amount"
            />
            <span className="text-xs text-gray-600">{unit} to</span>
            <select
              value={toUserId}
              onChange={e => setToUserId(e.target.value)}
              className="border border-gray-300 rounded px-2 py-1 text-sm max-w-[220px]"
            >
              <option value="">Choose a member…</option>
              {members.map(m => (
                <option key={m.user_id} value={m.user_id}>{m.display_name}</option>
              ))}
            </select>
          </div>
          <p className="text-xs text-gray-400">
            Transfers move existing {unit} to another member. They never change the
            organization total. Both you and the recipient will see this transfer.
          </p>
          <div className="flex gap-2">
            <button onClick={submit} disabled={saving}
              className="text-xs px-3 py-1.5 bg-[var(--brand-primary)] text-white rounded-lg hover:bg-[var(--brand-accent)] disabled:opacity-50">
              {saving ? 'Sending…' : 'Send transfer'}
            </button>
            <button onClick={() => setOpen(false)} className="text-xs text-gray-400 hover:text-gray-600 px-2">
              Cancel
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

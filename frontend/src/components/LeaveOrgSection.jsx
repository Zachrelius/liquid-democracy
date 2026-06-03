import { useState } from 'react';
import { useToast } from './Toast';
import api from '../api';
import { useOrg } from '../OrgContext';

/**
 * Phase 50 — reusable Leave-organization control.
 *
 * Two stages per spec D2:
 *   * `idle`              — collapsed button.
 *   * `confirm`           — informed-confirm naming what's lost.
 *   * `transfer_required` — backend returned 409; inline transfer
 *                            picker calls the existing
 *                            /transfer-stewardship endpoint, then
 *                            kicks back to `confirm` so the user
 *                            clicks Leave AGAIN to complete (D2's
 *                            "two steps, not atomic" anchor).
 *
 * Used by:
 *   * `pages/admin/OrgSettings.jsx` (admin home for the control).
 *   * `pages/LeaveOrg.jsx` (member-accessible standalone page; the
 *     one a non-admin discovers via the Nav user menu).
 *
 * On success the page redirects to /orgs because the user is no
 * longer a member of the current org — staying on it would 403.
 */
export default function LeaveOrgSection({ onComplete }) {
  const { currentOrg, refreshOrgs } = useOrg();
  const toast = useToast();
  const [stage, setStage] = useState('idle');
  const [transferTargetId, setTransferTargetId] = useState('');
  const [transferMembers, setTransferMembers] = useState([]);
  const [working, setWorking] = useState(false);

  if (!currentOrg) {
    return (
      <p className="text-sm text-gray-500">
        Pick an organization first.
      </p>
    );
  }

  async function loadTransferMembers() {
    try {
      const r = await api.get(`/api/orgs/${currentOrg.slug}/members`);
      const list = Array.isArray(r) ? r : (r?.members || []);
      setTransferMembers(
        list.filter(m => m.status !== 'pending'),
      );
    } catch {
      toast.error('Failed to load members for handoff');
    }
  }

  async function submitLeave() {
    setWorking(true);
    try {
      await api.post(`/api/orgs/${currentOrg.slug}/leave`, {});
      toast.success(`You've left ${currentOrg.name}.`);
      setStage('idle');
      await refreshOrgs();
      if (onComplete) onComplete();
      else window.location.href = '/orgs';
    } catch (e) {
      const status = e?.status || e?.response?.status;
      const detail = e?.detail || e?.response?.data?.detail || {};
      if (status === 409 && detail?.error === 'transfer_required') {
        setStage('transfer_required');
        if (transferMembers.length === 0) await loadTransferMembers();
        toast.error(detail.detail || 'You need to hand off leadership first.');
      } else {
        toast.error(e.message || 'Failed to leave organization');
      }
    } finally {
      setWorking(false);
    }
  }

  async function handleTransferThenRetry() {
    if (!transferTargetId) return;
    const target = transferMembers.find(m => m.user_id === transferTargetId);
    const targetLabel = target ? (target.display_name || target.username) : 'this member';
    setWorking(true);
    try {
      await api.post(`/api/orgs/${currentOrg.slug}/transfer-stewardship`, {
        target_user_id: transferTargetId,
      });
      toast.success(
        `Stewardship transferred to ${targetLabel}. Click Leave again to complete your departure.`,
      );
      await refreshOrgs();
      setStage('confirm');
      setTransferTargetId('');
    } catch (e) {
      toast.error(e.message || 'Failed to transfer stewardship');
    } finally {
      setWorking(false);
    }
  }

  return (
    <div className="bg-white border border-gray-200 rounded-xl p-5 space-y-3">
      {stage === 'idle' && (
        <>
          <p className="text-sm text-gray-700">
            Leaving means losing access to <strong>{currentOrg.name}</strong>'s proposals, members,
            and any role you hold here. If you're the only top leader, you'll be
            asked to hand off first.
          </p>
          <button
            onClick={() => setStage('confirm')}
            className="text-sm px-4 py-2 border border-gray-300 text-gray-700 rounded-lg hover:bg-gray-50 transition-colors"
          >
            Leave organization…
          </button>
        </>
      )}
      {stage === 'confirm' && (
        <>
          <p className="text-sm text-gray-700">
            You're about to leave <strong>{currentOrg.name}</strong>. Here's what happens:
          </p>
          <ul className="text-xs text-gray-600 list-disc pl-5 space-y-1">
            <li>Your membership ends. You lose access to this organization's proposals, members list, and admin surfaces (if any).</li>
            <li>Any titles you hold in this organization (e.g. office or council seat) are revoked.</li>
            <li>Any delegations you've made within this organization are cleaned up.</li>
            <li>Other members who delegate to you in this organization will fall back to direct voting (the engine handles this automatically).</li>
          </ul>
          <p className="text-xs text-gray-500">
            You can rejoin later if the org's join policy allows it.
          </p>
          <div className="flex gap-2">
            <button
              onClick={submitLeave}
              disabled={working}
              className="text-sm px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 transition-colors disabled:opacity-50"
            >
              {working ? 'Leaving…' : 'Confirm and leave'}
            </button>
            <button
              onClick={() => setStage('idle')}
              disabled={working}
              className="text-sm px-4 py-2 border border-gray-300 text-gray-600 rounded-lg hover:bg-gray-50 disabled:opacity-50"
            >
              Cancel
            </button>
          </div>
        </>
      )}
      {stage === 'transfer_required' && (
        <>
          <p className="text-sm text-gray-700">
            You're the only top leader of <strong>{currentOrg.name}</strong>. To leave, hand off
            stewardship to another active member first. Then come back and click
            Leave again to complete your departure.
          </p>
          <p className="text-xs text-gray-500">
            The successor takes the seat as the interim Steward, subject to the
            normal election / handoff processes the organization uses.
          </p>
          <label className="block text-xs text-gray-600">
            New Steward
          </label>
          <select
            value={transferTargetId}
            onChange={e => setTransferTargetId(e.target.value)}
            className="w-full max-w-md px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-400"
          >
            <option value="">Select a member…</option>
            {transferMembers
              .filter(m => m.role !== 'steward')
              .map(m => (
                <option key={m.user_id} value={m.user_id}>
                  {m.display_name || m.username} ({m.role})
                </option>
              ))}
          </select>
          <div className="flex gap-2">
            <button
              onClick={handleTransferThenRetry}
              disabled={!transferTargetId || working}
              className="text-sm px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors disabled:opacity-50"
            >
              {working ? 'Transferring…' : 'Transfer stewardship'}
            </button>
            <button
              onClick={() => { setStage('idle'); setTransferTargetId(''); }}
              disabled={working}
              className="text-sm px-4 py-2 border border-gray-300 text-gray-600 rounded-lg hover:bg-gray-50 disabled:opacity-50"
            >
              Cancel
            </button>
          </div>
        </>
      )}
    </div>
  );
}

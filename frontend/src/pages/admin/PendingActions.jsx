import { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';

import api from '../../api';
import { useOrg } from '../../OrgContext';
import { useToast } from '../../components/Toast';

/**
 * Phase 44 F2 — Pending-actions queue (one per org).
 *
 * Lists every PendingAdminAction for the current org with its rendered
 * change preview, current approvals/threshold, expiry, and inline
 * approve/decline controls. Approver-gated server-side; this page also
 * gates client-side via the orgScopedLayout subsection permissions.
 *
 * F2b discovery surfacing lives elsewhere (the count badge on Nav.jsx
 * and the in-context banners on Members / Topics / RolePermissions /
 * OrgSettings).
 */
export default function PendingActions() {
  const { org_slug } = useParams();
  const { currentOrg } = useOrg();
  const slug = org_slug || currentOrg?.slug;
  const toast = useToast();

  const [loading, setLoading] = useState(true);
  const [items, setItems] = useState([]);
  const [decliningId, setDecliningId] = useState(null);
  const [declineReason, setDeclineReason] = useState('');

  async function load() {
    if (!slug) return;
    setLoading(true);
    try {
      const data = await api.get(`/api/orgs/${slug}/admin/pending-actions`);
      setItems(data.items || []);
    } catch (err) {
      toast.error(err.message || 'Failed to load pending actions');
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(); }, [slug]);

  async function approve(id) {
    try {
      await api.post(`/api/orgs/${slug}/admin/pending-actions/${id}/approve`, {});
      toast.success('Approval recorded');
      await load();
    } catch (err) {
      toast.error(err.message || 'Failed to approve');
    }
  }

  async function decline(id) {
    try {
      await api.post(
        `/api/orgs/${slug}/admin/pending-actions/${id}/decline`,
        { reason: declineReason.trim() || null },
      );
      toast.success('Decline recorded');
      setDecliningId(null);
      setDeclineReason('');
      await load();
    } catch (err) {
      toast.error(err.message || 'Failed to decline');
    }
  }

  if (loading) {
    return (
      <div className="max-w-4xl mx-auto px-4 py-8">
        <h1 className="text-2xl font-bold text-[var(--brand-primary)]">Pending actions</h1>
        <p className="text-sm text-gray-500 mt-2">Loading…</p>
      </div>
    );
  }

  const pendingItems = items.filter(i => i.status === 'pending');
  const resolvedItems = items.filter(i => i.status !== 'pending');

  return (
    <div className="max-w-4xl mx-auto px-4 py-8 space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-[var(--brand-primary)]">Pending actions</h1>
        <p className="text-sm text-gray-500 mt-1">
          Destructive admin actions awaiting N-of-M ratification. One decline vetoes the action.
        </p>
      </div>

      <section>
        <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide mb-2">
          Awaiting your decision ({pendingItems.length})
        </h2>
        {pendingItems.length === 0 ? (
          <div className="bg-white border border-gray-200 rounded-xl p-6 text-sm text-gray-500">
            No pending actions right now.
          </div>
        ) : (
          <div className="space-y-3">
            {pendingItems.map(item => (
              <ActionCard
                key={item.id}
                item={item}
                onApprove={() => approve(item.id)}
                onStartDecline={() => { setDecliningId(item.id); setDeclineReason(''); }}
                isDeclining={decliningId === item.id}
                declineReason={declineReason}
                onDeclineReasonChange={setDeclineReason}
                onConfirmDecline={() => decline(item.id)}
                onCancelDecline={() => { setDecliningId(null); setDeclineReason(''); }}
              />
            ))}
          </div>
        )}
      </section>

      {resolvedItems.length > 0 && (
        <section>
          <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide mb-2">
            Recent ({resolvedItems.length})
          </h2>
          <div className="space-y-3">
            {resolvedItems.map(item => (
              <ResolvedActionCard key={item.id} item={item} />
            ))}
          </div>
        </section>
      )}
    </div>
  );
}

function ActionCard({
  item,
  onApprove, onStartDecline,
  isDeclining, declineReason, onDeclineReasonChange,
  onConfirmDecline, onCancelDecline,
}) {
  const preview = item.preview || {};
  return (
    <div className="bg-white border border-gray-200 rounded-xl p-5 space-y-3">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-[var(--brand-primary)]">{preview.label || item.summary_label}</h3>
          <p className="text-sm text-gray-700 mt-1">{preview.summary || 'Pending action'}</p>
          {preview.reason && (
            <p className="text-xs text-gray-500 mt-1 italic">"{preview.reason}"</p>
          )}
          {preview.impact?.proposals_tagged != null && (
            <p className="text-xs text-gray-500 mt-1">
              Impacts {preview.impact.proposals_tagged} proposal(s) tagged with this topic.
            </p>
          )}
          {preview.destructive === 'high' && (
            <p className="text-xs text-red-600 mt-1 font-medium">
              ⚠ Destructive: all org data will be permanently deleted.
            </p>
          )}
        </div>
        <div className="text-xs text-gray-500 text-right shrink-0">
          <div>{item.approvals_count} / {item.threshold} approvals</div>
          {item.expires_at && (
            <div className="mt-1">expires {new Date(item.expires_at).toLocaleString()}</div>
          )}
        </div>
      </div>

      {preview.diff_by_role && (
        <PermissionDiff diff={preview.diff_by_role} drift={preview.drift} />
      )}

      <div className="text-xs text-gray-500">
        Submitted by <span className="font-medium text-gray-700">{item.initiator?.display_name}</span>
      </div>

      {isDeclining ? (
        <div className="space-y-2 pt-2 border-t border-gray-100">
          <label className="text-xs text-gray-600 block">Reason for declining (optional)</label>
          <textarea
            value={declineReason}
            onChange={e => onDeclineReasonChange(e.target.value)}
            className="w-full border border-gray-300 rounded p-2 text-sm"
            rows={2}
            placeholder="e.g. Re-discuss at next meeting"
          />
          <div className="flex gap-2">
            <button
              type="button"
              onClick={onConfirmDecline}
              className="px-4 py-1.5 bg-red-600 text-white text-sm rounded hover:bg-red-700"
            >Confirm decline (vetoes the action)</button>
            <button
              type="button"
              onClick={onCancelDecline}
              className="px-4 py-1.5 bg-gray-100 text-gray-700 text-sm rounded hover:bg-gray-200"
            >Cancel</button>
          </div>
        </div>
      ) : (
        <div className="flex items-center gap-2 pt-2 border-t border-gray-100">
          {item.viewer_has_decided ? (
            <span className="text-xs text-gray-500 italic">You've already weighed in.</span>
          ) : (
            <>
              <button
                type="button"
                onClick={onApprove}
                className="px-4 py-1.5 bg-[var(--brand-primary)] text-white text-sm rounded hover:bg-[var(--brand-accent)]"
              >Approve</button>
              <button
                type="button"
                onClick={onStartDecline}
                className="px-4 py-1.5 border border-red-300 text-red-700 text-sm rounded hover:bg-red-50"
              >Decline</button>
            </>
          )}
        </div>
      )}
    </div>
  );
}

function ResolvedActionCard({ item }) {
  const preview = item.preview || {};
  const statusColor = {
    executed: 'text-green-700 bg-green-50 border-green-200',
    declined: 'text-red-700 bg-red-50 border-red-200',
    expired: 'text-gray-700 bg-gray-50 border-gray-200',
    failed: 'text-orange-700 bg-orange-50 border-orange-200',
  }[item.status] || 'text-gray-700 bg-gray-50';

  return (
    <div className="bg-white border border-gray-200 rounded-xl p-4 flex items-center justify-between gap-3">
      <div>
        <div className="text-sm font-medium text-gray-700">{preview.summary || item.summary_label}</div>
        <div className="text-xs text-gray-500 mt-0.5">
          by {item.initiator?.display_name}
          {item.resolved_at && ` · ${new Date(item.resolved_at).toLocaleString()}`}
        </div>
      </div>
      <span className={`text-xs px-2 py-1 rounded border font-medium ${statusColor}`}>
        {item.status}
      </span>
    </div>
  );
}

function PermissionDiff({ diff, drift }) {
  return (
    <div className="bg-gray-50 border border-gray-200 rounded p-3 space-y-2">
      {drift && (
        <div className="text-xs text-orange-700 bg-orange-50 border border-orange-200 rounded p-2">
          ⚠ Permissions have changed since this action was proposed. Re-review before approving.
        </div>
      )}
      {Object.entries(diff).map(([role, changes]) => (
        <div key={role} className="text-xs">
          <span className="font-semibold capitalize text-gray-700">{role}:</span>{' '}
          {changes.map((c, i) => (
            <span key={`${c.permission_key}-${i}`} className="ml-1">
              {c.to ? (
                <span className="text-green-700">+ {c.permission_label}</span>
              ) : (
                <span className="text-red-700">− {c.permission_label}</span>
              )}
              {i < changes.length - 1 && <span className="text-gray-400">,</span>}
            </span>
          ))}
        </div>
      ))}
    </div>
  );
}

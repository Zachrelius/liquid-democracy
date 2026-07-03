import { useState, useEffect, useCallback } from 'react';
import { Navigate } from 'react-router-dom';
import api from '../api';
import { useAuth } from '../AuthContext';
import { useToast } from '../components/Toast';

/**
 * Phase 87 (B-10) — minimal platform-admin toolbench.
 *
 * Two tabs: Organizations (takedown: delist / suspend / revert) and Users
 * (read-only). Gated on the current user's is_admin; non-admins are silently
 * redirected. Not org-scoped, so it lives outside the org-context layout.
 * No em dashes in copy.
 */

const RESTRICTION_LABELS = {
  delisted: 'Delisted',
  suspended: 'Suspended',
};

function RestrictionBadge({ value }) {
  if (!value) return <span className="text-xs text-gray-400">Active</span>;
  const color = value === 'suspended'
    ? 'bg-red-50 text-red-700 border-red-200'
    : 'bg-amber-50 text-amber-700 border-amber-200';
  return (
    <span className={`text-xs px-2 py-0.5 rounded border font-medium ${color}`}>
      {RESTRICTION_LABELS[value] || value}
    </span>
  );
}

function RestrictionModal({ org, action, onClose, onDone }) {
  const toast = useToast();
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const reverting = action === 'none';

  const title = reverting
    ? `Revert restriction on ${org.name}?`
    : action === 'suspended'
      ? `Suspend ${org.name}?`
      : `Delist ${org.name}?`;

  const body = reverting
    ? 'This restores the organization to its normal public posture.'
    : action === 'suspended'
      ? 'The organization becomes inaccessible to everyone except platform admins. No data is deleted; reverting restores full access.'
      : 'The organization keeps working for its members but is removed from public discovery (explore and public landing).';

  async function submit() {
    if (!reverting && !reason.trim()) {
      toast.error('A reason is required.');
      return;
    }
    setBusy(true);
    try {
      await api.patch(`/api/admin/orgs/${org.id}/restriction`, {
        restriction: reverting ? 'none' : action,
        reason: reason.trim() || undefined,
      });
      toast.success(reverting ? 'Restriction reverted' : 'Restriction applied');
      onDone();
    } catch (e) {
      toast.error(e?.message || 'Action failed');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="fixed inset-0 z-[10000] flex items-center justify-center">
      <div className="absolute inset-0 bg-black/40" onClick={busy ? undefined : onClose} />
      <div className="relative bg-white rounded-xl shadow-xl max-w-md w-full mx-4 p-6 space-y-4">
        <h3 className="text-lg font-semibold text-gray-800">{title}</h3>
        <p className="text-sm text-gray-600">{body}</p>
        {!reverting && (
          <div>
            <label className="block text-xs text-gray-500 mb-1">Reason (required)</label>
            <textarea
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              rows={3}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm resize-none focus:outline-none focus:ring-1 focus:ring-[var(--brand-accent)]"
              placeholder="Recorded in the audit log"
            />
          </div>
        )}
        <div className="flex justify-end gap-3 pt-1">
          <button
            type="button"
            onClick={onClose}
            disabled={busy}
            className="text-sm px-4 py-2 border border-gray-300 text-gray-600 rounded-lg hover:bg-gray-50 disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={submit}
            disabled={busy}
            className={`text-sm px-4 py-2 rounded-lg text-white disabled:opacity-50 ${
              reverting ? 'bg-[var(--brand-primary)] hover:bg-[var(--brand-accent)]' : 'bg-red-600 hover:bg-red-700'
            }`}
          >
            {busy ? 'Working...' : (reverting ? 'Revert' : 'Confirm')}
          </button>
        </div>
      </div>
    </div>
  );
}

function OrgsTab() {
  const toast = useToast();
  const [orgs, setOrgs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [modal, setModal] = useState(null); // { org, action }

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setOrgs(await api.get('/api/admin/orgs'));
    } catch (e) {
      toast.error(e?.message || 'Failed to load organizations');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  if (loading) {
    return <div className="py-12 text-center text-gray-400">Loading organizations...</div>;
  }

  return (
    <div className="space-y-4">
      <div className="bg-white border border-gray-200 rounded-xl overflow-hidden">
        <div className="grid grid-cols-[1fr_90px_110px_150px] gap-2 px-4 py-2 bg-gray-50 text-xs font-medium text-gray-500 uppercase">
          <span>Organization</span>
          <span>Members</span>
          <span>State</span>
          <span className="text-right">Actions</span>
        </div>
        {orgs.length === 0 ? (
          <div className="px-4 py-8 text-center text-gray-400 text-sm">No organizations</div>
        ) : orgs.map((o) => (
          <div key={o.id} className="grid grid-cols-[1fr_90px_110px_150px] gap-2 items-center px-4 py-3 text-sm border-t border-gray-100">
            <div className="min-w-0">
              <div className="font-medium text-gray-800 truncate">
                {o.name}
                {o.is_demo && <span className="ml-2 text-xs text-gray-400">demo</span>}
                {o.parent_org_id && <span className="ml-2 text-xs text-gray-400">sub-org</span>}
              </div>
              <div className="text-xs text-gray-400 truncate">/{o.slug}</div>
            </div>
            <span className="text-gray-600">{o.member_count}</span>
            <span><RestrictionBadge value={o.platform_restriction} /></span>
            <div className="flex justify-end gap-1.5">
              {o.is_demo ? (
                <span className="text-xs text-gray-300">n/a</span>
              ) : o.platform_restriction ? (
                <button
                  onClick={() => setModal({ org: o, action: 'none' })}
                  className="text-xs px-2.5 py-1 border border-green-400 text-green-700 rounded-lg hover:bg-green-50"
                >
                  Revert
                </button>
              ) : (
                <>
                  <button
                    onClick={() => setModal({ org: o, action: 'delisted' })}
                    className="text-xs px-2.5 py-1 border border-amber-400 text-amber-700 rounded-lg hover:bg-amber-50"
                  >
                    Delist
                  </button>
                  <button
                    onClick={() => setModal({ org: o, action: 'suspended' })}
                    className="text-xs px-2.5 py-1 border border-red-300 text-red-600 rounded-lg hover:bg-red-50"
                  >
                    Suspend
                  </button>
                </>
              )}
            </div>
          </div>
        ))}
      </div>

      {modal && (
        <RestrictionModal
          org={modal.org}
          action={modal.action}
          onClose={() => setModal(null)}
          onDone={() => { setModal(null); load(); }}
        />
      )}
    </div>
  );
}

function UsersTab() {
  const toast = useToast();
  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        setUsers(await api.get('/api/admin/users'));
      } catch (e) {
        toast.error(e?.message || 'Failed to load users');
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  if (loading) {
    return <div className="py-12 text-center text-gray-400">Loading users...</div>;
  }

  return (
    <div className="bg-white border border-gray-200 rounded-xl overflow-hidden">
      <div className="grid grid-cols-[1fr_1fr_80px_80px] gap-2 px-4 py-2 bg-gray-50 text-xs font-medium text-gray-500 uppercase">
        <span>User</span>
        <span>Email</span>
        <span>Verified</span>
        <span>Admin</span>
      </div>
      {users.map((u) => (
        <div key={u.id} className="grid grid-cols-[1fr_1fr_80px_80px] gap-2 items-center px-4 py-2.5 text-sm border-t border-gray-100">
          <span className="font-medium text-gray-800 truncate">
            {u.display_name} <span className="text-gray-400 font-normal">@{u.username}</span>
          </span>
          <span className="text-gray-600 truncate">{u.email}</span>
          <span>{u.email_verified ? 'Yes' : 'No'}</span>
          <span>{u.is_admin ? 'Yes' : ''}</span>
        </div>
      ))}
    </div>
  );
}

export default function PlatformAdmin() {
  const { user, loading } = useAuth();
  const [tab, setTab] = useState('orgs');

  if (loading) {
    return <div className="py-20 text-center text-gray-400">Loading...</div>;
  }
  // Silent redirect for non-admins (no affordance, no error).
  if (!user || !user.is_admin) {
    return <Navigate to="/" replace />;
  }

  return (
    <div className="max-w-4xl mx-auto px-4 py-8 space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-[var(--brand-primary)]">Platform administration</h1>
        <p className="text-sm text-gray-500 mt-1">
          Platform moderation tools. Actions here are recorded in the audit log.
        </p>
      </div>

      <div className="flex gap-2 border-b border-gray-200">
        {[['orgs', 'Organizations'], ['users', 'Users']].map(([key, label]) => (
          <button
            key={key}
            onClick={() => setTab(key)}
            className={`px-4 py-2 text-sm font-medium border-b-2 -mb-px transition-colors ${
              tab === key
                ? 'border-[var(--brand-accent)] text-[var(--brand-primary)]'
                : 'border-transparent text-gray-500 hover:text-gray-700'
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {tab === 'orgs' ? <OrgsTab /> : <UsersTab />}
    </div>
  );
}

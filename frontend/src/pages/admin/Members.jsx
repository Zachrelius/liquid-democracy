import { useState, useEffect, useCallback } from 'react';
import { useOrg } from '../../OrgContext';
import api from '../../api';
import Avatar from '../../components/Avatar';
import ErrorMessage from '../../components/ErrorMessage';
import { useToast } from '../../components/Toast';
import { useConfirm } from '../../components/ConfirmDialog';
// Phase 12.5 F2 — per-control permission gating.
import { useHasPermission } from '../../hooks/useHasPermission';

function MemberRow({ member, onChangeRole, onSuspend, onReactivate, onRemove, perms, confirm }) {
  const { canChangeRole, canSuspend, canRemove } = perms;
  const [expanded, setExpanded] = useState(false);
  const [role, setRole] = useState(member.role);
  const [saving, setSaving] = useState(false);

  // Phase 12 Stage 1: 'owner' renamed to 'steward'. Legacy 'owner' kept
  // for cached-response safety during the deploy cutover.
  const isOwner = member.role === 'steward' || member.role === 'owner';

  return (
    <div className="border-b border-gray-100 last:border-0">
      <div
        onClick={() => !isOwner && setExpanded(!expanded)}
        className={`flex items-center gap-4 px-4 py-3 text-sm ${isOwner ? '' : 'cursor-pointer hover:bg-gray-50'} transition-colors`}
      >
        <span className="flex-1 font-medium text-gray-800 flex items-center gap-2">
          <Avatar user={{ id: member.user_id, display_name: member.display_name, avatar_url: member.avatar_url, avatar_url_small: member.avatar_url_small }} size="sm" />
          {member.display_name}
        </span>
        <span className="w-32 text-gray-500">@{member.username}</span>
        <span className="w-24">
          <span className={`text-xs px-2 py-0.5 rounded font-medium ${
            (member.role === 'steward' || member.role === 'owner') ? 'bg-purple-50 text-purple-700' :
            member.role === 'admin' ? 'bg-blue-50 text-blue-700' :
            member.role === 'moderator' ? 'bg-green-50 text-green-700' :
            'bg-gray-50 text-gray-600'
          }`}>{member.role === 'owner' ? 'steward' : member.role}</span>
        </span>
        <span className="w-24">
          <span className={`text-xs px-2 py-0.5 rounded ${
            member.status === 'active' ? 'bg-green-50 text-green-700' :
            member.status === 'suspended' ? 'bg-red-50 text-red-700' :
            'bg-yellow-50 text-yellow-700'
          }`}>{member.status}</span>
        </span>
        <span className="w-28 text-xs text-gray-400">
          {new Date(member.joined_at).toLocaleDateString()}
        </span>
        {!isOwner && (
          <svg className={`w-4 h-4 text-gray-400 transition-transform ${expanded ? 'rotate-180' : ''}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
          </svg>
        )}
      </div>
      {expanded && !isOwner && (
        <div className="px-4 py-3 bg-gray-50 flex items-center gap-3 flex-wrap">
          {/* Phase 12.5 F2 — Change-role gated on `member.change_role`. */}
          {canChangeRole && (
            <>
              <select
                value={role}
                onChange={e => setRole(e.target.value)}
                className="text-sm border border-gray-300 rounded-lg px-2 py-1 focus:outline-none focus:ring-1 focus:ring-[#2E75B6]"
              >
                <option value="member">Member</option>
                <option value="moderator">Moderator</option>
                <option value="admin">Admin</option>
              </select>
              <button
                onClick={async () => {
                  setSaving(true);
                  await onChangeRole(member.user_id, role);
                  setSaving(false);
                  setExpanded(false);
                }}
                disabled={saving || role === member.role}
                className="text-xs px-3 py-1.5 bg-[#1B3A5C] text-white rounded-lg hover:bg-[#2E75B6] disabled:opacity-50"
              >
                {saving ? 'Saving...' : 'Update Role'}
              </button>
            </>
          )}
          <div className="flex-1" />
          {/* Phase 12.5 F2 — Suspend/Reactivate gated on `member.suspend`. */}
          {canSuspend && member.status === 'active' && (
            <button
              onClick={() => onSuspend(member.user_id)}
              className="text-xs px-3 py-1.5 border border-yellow-400 text-yellow-700 rounded-lg hover:bg-yellow-50"
            >
              Suspend
            </button>
          )}
          {canSuspend && member.status === 'suspended' && (
            <button
              onClick={() => onReactivate(member.user_id)}
              className="text-xs px-3 py-1.5 border border-green-400 text-green-700 rounded-lg hover:bg-green-50"
            >
              Reactivate
            </button>
          )}
          {/* Phase 12.5 F2 — Remove gated on `member.remove`. */}
          {canRemove && (
            <button
              onClick={async () => {
                const ok = await confirm({
                  title: 'Remove Member',
                  message: `Remove ${member.display_name} from the organization?`,
                  destructive: true,
                });
                if (ok) onRemove(member.user_id);
              }}
              className="text-xs px-3 py-1.5 border border-red-300 text-red-600 rounded-lg hover:bg-red-50"
            >
              Remove
            </button>
          )}
        </div>
      )}
    </div>
  );
}

export default function Members() {
  const { currentOrg } = useOrg();
  const toast = useToast();
  const confirm = useConfirm();
  // Phase 12.5 F2 — per-control permission gating. Replaces the prior
  // `isAdmin` role-tier check throughout this page.
  const canApproveJoin = useHasPermission('member.approve_join');
  const canChangeRole = useHasPermission('member.change_role');
  const canRemove = useHasPermission('member.remove');
  const canSuspend = useHasPermission('member.suspend');
  const canInvite = useHasPermission('member.invite');
  const [members, setMembers] = useState([]);
  const [pendingRequests, setPendingRequests] = useState([]);
  const [invitations, setInvitations] = useState([]);
  const [search, setSearch] = useState('');
  const [loading, setLoading] = useState(true);
  const [inviteEmails, setInviteEmails] = useState('');
  const [inviteRole, setInviteRole] = useState('member');
  const [inviteMsg, setInviteMsg] = useState('');
  const [loadError, setLoadError] = useState('');

  const slug = currentOrg?.slug;

  const load = useCallback(async () => {
    if (!slug) return;
    setLoadError('');
    try {
      // Members fetch — required. Moderators have access to this endpoint
      // (require_org_membership), but if it fails for any reason (network
      // hiccup, auth refresh edge case, transient backend error) we surface
      // the error instead of silently rendering an empty list. Phase 9.8 W B1
      // restores this behavior — a previous refactor swallowed the error and
      // left moderators staring at an empty members table.
      const mems = await api.get(`/api/orgs/${slug}/members`);
      const active = mems.filter(m => m.status !== 'pending_approval');
      const pending = mems.filter(m => m.status === 'pending_approval');
      setMembers(active);
      setPendingRequests(pending);
    } catch (e) {
      setLoadError(e.message || 'Failed to load members');
    }
    // Phase 12.5 F2 — invitations endpoint is gated on `member.invite`
    // server-side; only fetch when the viewer holds the permission so users
    // without it don't trigger a known-403 in the network log.
    if (canInvite) {
      try {
        const invs = await api.get(`/api/orgs/${slug}/invitations`);
        setInvitations(invs);
      } catch { /* invite endpoint may 403 — fall through */ }
    } else {
      setInvitations([]);
    }
    setLoading(false);
  }, [slug, canInvite]);

  useEffect(() => { load(); }, [load]);

  if (!currentOrg) return <div className="text-center py-16 text-gray-400">No organization selected</div>;

  async function handleChangeRole(userId, role) {
    try {
      await api.patch(`/api/orgs/${slug}/members/${userId}`, { role });
      toast.success('Role updated');
      load();
    } catch (e) {
      toast.error(e.message);
    }
  }

  async function handleSuspend(userId) {
    try {
      await api.post(`/api/orgs/${slug}/members/${userId}/suspend`);
      toast.success('Member suspended');
      load();
    } catch (e) {
      toast.error(e.message);
    }
  }

  async function handleReactivate(userId) {
    try {
      await api.post(`/api/orgs/${slug}/members/${userId}/reactivate`);
      toast.success('Member reactivated');
      load();
    } catch (e) {
      toast.error(e.message);
    }
  }

  async function handleRemove(userId) {
    try {
      await api.delete(`/api/orgs/${slug}/members/${userId}`);
      toast.success('Member removed');
      load();
    } catch (e) {
      toast.error(e.message);
    }
  }

  async function handleApprove(userId) {
    try {
      await api.post(`/api/orgs/${slug}/join/approve/${userId}`);
      toast.success('Join request approved');
      load();
    } catch (e) {
      toast.error(e.message);
    }
  }

  async function handleDeny(userId) {
    try {
      await api.post(`/api/orgs/${slug}/join/deny/${userId}`);
      toast.success('Join request denied');
      load();
    } catch (e) {
      toast.error(e.message);
    }
  }

  async function handleInvite() {
    setInviteMsg('');
    const emails = inviteEmails.split('\n').map(e => e.trim()).filter(Boolean);
    if (emails.length === 0) return;
    try {
      await api.post(`/api/orgs/${slug}/invitations`, { emails, role: inviteRole });
      toast.success(`${emails.length} invitation(s) sent`);
      setInviteEmails('');
      setInviteMsg(`${emails.length} invitation(s) sent`);
      load();
      setTimeout(() => setInviteMsg(''), 3000);
    } catch (e) {
      setInviteMsg(e.message);
    }
  }

  async function handleResendInvite(invId) {
    try {
      await api.post(`/api/orgs/${slug}/invitations/${invId}/resend`);
      toast.success('Invitation resent');
      load();
    } catch (e) {
      toast.error(e.message);
    }
  }

  async function handleRevokeInvite(invId) {
    try {
      await api.delete(`/api/orgs/${slug}/invitations/${invId}`);
      toast.success('Invitation revoked');
      load();
    } catch (e) {
      toast.error(e.message);
    }
  }

  const filtered = members.filter(m =>
    !search || m.display_name.toLowerCase().includes(search.toLowerCase()) ||
    m.username.toLowerCase().includes(search.toLowerCase())
  );

  if (loading) return (
    <div className="flex justify-center items-center py-20">
      <div className="animate-spin w-8 h-8 border-4 border-[#2E75B6] border-t-transparent rounded-full"></div>
    </div>
  );

  if (loadError) return (
    <div className="max-w-4xl mx-auto px-4 py-8">
      <ErrorMessage error={loadError} onRetry={load} />
    </div>
  );

  return (
    <div className="max-w-4xl mx-auto px-4 py-8 space-y-10">
      <h1 className="text-2xl font-semibold text-[#1B3A5C]">Member Management</h1>

      {/* Pending Join Requests */}
      {pendingRequests.length > 0 && (
        <section className="space-y-3">
          <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide">
            Pending Join Requests ({pendingRequests.length})
          </h2>
          <div className="grid gap-3 sm:grid-cols-2">
            {pendingRequests.map(m => (
              <div key={m.user_id} className="bg-white border border-yellow-200 rounded-xl p-4 flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <Avatar user={{ id: m.user_id, display_name: m.display_name, avatar_url: m.avatar_url, avatar_url_small: m.avatar_url_small }} size="sm" />
                  <div>
                    <p className="text-sm font-medium text-gray-800">{m.display_name}</p>
                    <p className="text-xs text-gray-400">@{m.username} {m.email && `- ${m.email}`}</p>
                    <p className="text-xs text-gray-400">Requested {new Date(m.joined_at).toLocaleDateString()}</p>
                  </div>
                </div>
                <div className="flex gap-2">
                  {/* Phase 12.5 F2 — Approve/Deny gated on `member.approve_join`. */}
                  {canApproveJoin && (
                    <>
                      <button
                        onClick={() => handleApprove(m.user_id)}
                        className="text-xs px-3 py-1.5 bg-green-600 text-white rounded-lg hover:bg-green-700"
                      >
                        Approve
                      </button>
                      <button
                        onClick={() => handleDeny(m.user_id)}
                        className="text-xs px-3 py-1.5 border border-red-300 text-red-600 rounded-lg hover:bg-red-50"
                      >
                        Deny
                      </button>
                    </>
                  )}
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* Members Table */}
      <section className="space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide">
            Members ({members.length})
          </h2>
          <input
            type="text"
            placeholder="Search members..."
            value={search}
            onChange={e => setSearch(e.target.value)}
            className="px-3 py-1.5 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-1 focus:ring-[#2E75B6] w-56"
          />
        </div>
        <div className="bg-white border border-gray-200 rounded-xl overflow-hidden">
          <div className="flex items-center gap-4 px-4 py-2 bg-gray-50 text-xs font-medium text-gray-500 uppercase">
            <span className="flex-1">Name</span>
            <span className="w-32">Username</span>
            <span className="w-24">Role</span>
            <span className="w-24">Status</span>
            <span className="w-28">Joined</span>
            <span className="w-4" />
          </div>
          {filtered.length === 0 ? (
            <div className="px-4 py-8 text-center text-gray-400 text-sm">No members found</div>
          ) : (
            filtered.map(m => (
              <MemberRow
                key={m.user_id}
                member={m}
                onChangeRole={handleChangeRole}
                onSuspend={handleSuspend}
                onReactivate={handleReactivate}
                onRemove={handleRemove}
                perms={{ canChangeRole, canSuspend, canRemove }}
                confirm={confirm}
              />
            ))
          )}
        </div>
      </section>

      {/* Invite Members — gated on `member.invite` (Phase 12.5 F2). */}
      {canInvite && <section className="space-y-3">
        <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide">Invite Members</h2>
        <div className="bg-white border border-gray-200 rounded-xl p-5 space-y-4">
          <div>
            <label className="block text-xs text-gray-500 mb-1">Email addresses (one per line)</label>
            <textarea
              value={inviteEmails}
              onChange={e => setInviteEmails(e.target.value)}
              rows={4}
              placeholder="alice@example.com&#10;bob@example.com"
              className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[#2E75B6] resize-none"
            />
          </div>
          <div className="flex items-center gap-4">
            <div>
              <label className="block text-xs text-gray-500 mb-1">Role</label>
              <select
                value={inviteRole}
                onChange={e => setInviteRole(e.target.value)}
                className="text-sm border border-gray-300 rounded-lg px-3 py-1.5 focus:outline-none focus:ring-1 focus:ring-[#2E75B6]"
              >
                <option value="member">Member</option>
                <option value="admin">Admin</option>
              </select>
            </div>
            <div className="pt-4">
              <button
                onClick={handleInvite}
                disabled={!inviteEmails.trim()}
                className="text-sm px-4 py-2 bg-[#1B3A5C] text-white rounded-lg hover:bg-[#2E75B6] transition-colors disabled:opacity-50"
              >
                Send Invitations
              </button>
            </div>
          </div>
          {inviteMsg && (
            <p className={`text-xs ${inviteMsg.includes('sent') ? 'text-green-600' : 'text-red-600'}`}>{inviteMsg}</p>
          )}
        </div>
      </section>}

      {/* Pending Invitations — gated on `member.invite` (Phase 12.5 F2). */}
      {canInvite && invitations.length > 0 && (
        <section className="space-y-3">
          <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide">
            Invitations ({invitations.length})
          </h2>
          <div className="bg-white border border-gray-200 rounded-xl overflow-hidden">
            <div className="flex items-center gap-4 px-4 py-2 bg-gray-50 text-xs font-medium text-gray-500 uppercase">
              <span className="flex-1">Email</span>
              <span className="w-20">Role</span>
              <span className="w-24">Status</span>
              <span className="w-28">Expires</span>
              <span className="w-28">Sent</span>
              <span className="w-32">Actions</span>
            </div>
            {invitations.map(inv => (
              <div key={inv.id} className="flex items-center gap-4 px-4 py-3 border-t border-gray-100 text-sm">
                <span className="flex-1 text-gray-800 truncate">{inv.email}</span>
                <span className="w-20 text-gray-500">{inv.role}</span>
                <span className="w-24">
                  <span className={`text-xs px-2 py-0.5 rounded ${
                    inv.status === 'pending' ? 'bg-yellow-50 text-yellow-700' :
                    inv.status === 'accepted' ? 'bg-green-50 text-green-700' :
                    'bg-gray-50 text-gray-500'
                  }`}>{inv.status}</span>
                </span>
                <span className="w-28 text-xs text-gray-400">{new Date(inv.expires_at).toLocaleDateString()}</span>
                <span className="w-28 text-xs text-gray-400">{new Date(inv.created_at).toLocaleDateString()}</span>
                <span className="w-32 flex gap-2">
                  {inv.status === 'pending' && (
                    <>
                      <button
                        onClick={() => handleResendInvite(inv.id)}
                        className="text-xs text-[#2E75B6] hover:underline"
                      >
                        Resend
                      </button>
                      <button
                        onClick={() => handleRevokeInvite(inv.id)}
                        className="text-xs text-red-500 hover:underline"
                      >
                        Revoke
                      </button>
                    </>
                  )}
                </span>
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}

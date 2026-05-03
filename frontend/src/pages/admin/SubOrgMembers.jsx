import { useEffect, useState, useCallback, useMemo } from 'react';
import { Link } from 'react-router-dom';
import api from '../../api';
import useSubOrg from '../../useSubOrg';
import Avatar from '../../components/Avatar';
import { useToast } from '../../components/Toast';
import { useConfirm } from '../../components/ConfirmDialog';
import SubOrgErrorState from '../../components/SubOrgErrorState';

/**
 * Phase 8.5 — Sub-Org Members admin page.
 *
 * Mirrors the parent-org Members page but scoped to one sub-org. Adds:
 *   - Invite (admin invites a parent-org member by user_id)
 *   - Approve / deny on pending invites/requests
 *   - Role-change and remove on active rows
 *
 * Per Session-2 spec, only existing parent-org members can be invited; the
 * invite picker queries the parent-org member list to populate a search box.
 */
export default function SubOrgMembers() {
  const { parentSlug, subSlug, subOrg, loading: subLoading, error } = useSubOrg();
  const toast = useToast();
  const confirm = useConfirm();

  const [members, setMembers] = useState([]);
  const [parentMembers, setParentMembers] = useState([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    if (!parentSlug || !subSlug) return;
    setLoading(true);
    try {
      const [m, pm] = await Promise.all([
        api.get(`/api/orgs/${parentSlug}/sub-orgs/${subSlug}/members`),
        api.get(`/api/orgs/${parentSlug}/members`),
      ]);
      setMembers(m);
      setParentMembers(pm);
    } catch { /* friendly fallthrough */ } finally {
      setLoading(false);
    }
  }, [parentSlug, subSlug]);

  useEffect(() => { load(); }, [load]);

  if (subLoading) return (
    <div className="flex justify-center items-center py-20">
      <div className="animate-spin w-8 h-8 border-4 border-[#2E75B6] border-t-transparent rounded-full"></div>
    </div>
  );
  if (error || !subOrg) return <SubOrgErrorState error={error} />;

  const pending = members.filter(m => m.status === 'pending_approval');
  const active = members.filter(m => m.status === 'active');
  const suspended = members.filter(m => m.status === 'suspended');

  async function handleApprove(userId) {
    try {
      await api.post(`/api/orgs/${parentSlug}/sub-orgs/${subSlug}/members/${userId}/approve`);
      toast.success('Approved');
      load();
    } catch (e) { toast.error(e.message); }
  }
  async function handleDeny(userId) {
    try {
      await api.post(`/api/orgs/${parentSlug}/sub-orgs/${subSlug}/members/${userId}/deny`);
      toast.success('Denied');
      load();
    } catch (e) { toast.error(e.message); }
  }
  async function handleRemove(userId, displayName) {
    const ok = await confirm({
      title: 'Remove Member',
      message: `Remove ${displayName} from ${subOrg.name}?`,
      destructive: true,
    });
    if (!ok) return;
    try {
      await api.post(`/api/orgs/${parentSlug}/sub-orgs/${subSlug}/members/${userId}/remove`);
      toast.success('Member removed');
      load();
    } catch (e) { toast.error(e.message); }
  }
  async function handleRoleChange(userId, role) {
    try {
      await api.post(`/api/orgs/${parentSlug}/sub-orgs/${subSlug}/members/${userId}/change-role`, { role });
      toast.success('Role updated');
      load();
    } catch (e) { toast.error(e.message); }
  }
  async function handleInvite(userId, role) {
    try {
      await api.post(`/api/orgs/${parentSlug}/sub-orgs/${subSlug}/members/invite`, { user_id: userId, role });
      toast.success('Invitation sent');
      load();
    } catch (e) { toast.error(e.message); }
  }
  // Phase 9.6 — direct-add (parent-org admin / sub-org admin only).
  // Skips the invitation/approval flow for parent-org members already on
  // the platform. Backend audits this as `sub_org_member.added_directly`.
  async function handleDirectAdd(userId, role) {
    try {
      await api.post(`/api/orgs/${parentSlug}/sub-orgs/${subSlug}/members/add`, { user_id: userId, role });
      toast.success('Member added');
      load();
    } catch (e) { toast.error(e.message || 'Failed to add member'); }
  }

  return (
    <div className="max-w-4xl mx-auto px-4 py-8 space-y-10">
      <div>
        <p className="text-xs text-gray-400 mb-1">
          <Link to="/admin/sub-orgs" className="hover:underline">Sub-organizations</Link>
          {' / '}
          <Link to={`/admin/sub-orgs/${subSlug}/settings`} className="hover:underline">{subOrg.name}</Link>
        </p>
        <h1 className="text-2xl font-semibold text-[#1B3A5C]">{subOrg.name} — Members</h1>
      </div>

      {/* Pending */}
      {pending.length > 0 && (
        <section className="space-y-3">
          <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide">
            Pending ({pending.length})
          </h2>
          <div className="grid gap-3 sm:grid-cols-2">
            {pending.map(m => (
              <div key={m.user_id} className="bg-white border border-yellow-200 rounded-xl p-4 flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <Avatar user={{ id: m.user_id, display_name: m.display_name, avatar_url: m.avatar_url, avatar_url_small: m.avatar_url_small }} size="sm" />
                  <div>
                    <p className="text-sm font-medium text-gray-800">{m.display_name}</p>
                    <p className="text-xs text-gray-400">@{m.username}</p>
                    <p className="text-xs text-gray-400">Requested {new Date(m.joined_at).toLocaleDateString()}</p>
                  </div>
                </div>
                <div className="flex gap-2">
                  <button onClick={() => handleApprove(m.user_id)} className="text-xs px-3 py-1.5 bg-green-600 text-white rounded-lg hover:bg-green-700">
                    Approve
                  </button>
                  <button onClick={() => handleDeny(m.user_id)} className="text-xs px-3 py-1.5 border border-red-300 text-red-600 rounded-lg hover:bg-red-50">
                    Deny
                  </button>
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* Direct add (Phase 9.6) — fast path for parent-org admins.
          Phase 9.7 W6: positioned above Active members so it's visible without
          scrolling on a sub-org with many members. Z reported in the friend
          pilot that the section was hidden below the fold on Gloomhaven. */}
      <DirectAddSection
        parentMembers={parentMembers}
        existingIds={new Set(members.map(m => m.user_id))}
        onAdd={handleDirectAdd}
      />

      {/* Active members */}
      <section className="space-y-3">
        <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide">
          Members ({active.length})
        </h2>
        {loading ? (
          <div className="py-8 text-center text-gray-400 text-sm">Loading…</div>
        ) : active.length === 0 ? (
          <div className="bg-white border border-gray-200 rounded-xl p-6 text-center text-sm text-gray-400">
            No active members yet. Add or invite parent-org members above.
          </div>
        ) : (
          <div className="bg-white border border-gray-200 rounded-xl overflow-hidden">
            <div className="flex items-center gap-4 px-4 py-2 bg-gray-50 text-xs font-medium text-gray-500 uppercase">
              <span className="flex-1">Name</span>
              <span className="w-32">Username</span>
              <span className="w-32">Role</span>
              <span className="w-28">Joined</span>
              <span className="w-32">Actions</span>
            </div>
            {active.map(m => (
              <ActiveRow key={m.user_id} member={m} onRoleChange={handleRoleChange} onRemove={handleRemove} />
            ))}
          </div>
        )}
      </section>

      {suspended.length > 0 && (
        <section className="space-y-3">
          <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide">
            Suspended ({suspended.length})
          </h2>
          <div className="bg-white border border-gray-200 rounded-xl overflow-hidden">
            {suspended.map(m => (
              <div key={m.user_id} className="flex items-center gap-4 px-4 py-3 text-sm border-t border-gray-100 first:border-0">
                <span className="flex-1 text-gray-700">{m.display_name}</span>
                <span className="text-xs text-gray-400">@{m.username}</span>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* Invite */}
      <InviteSection
        parentMembers={parentMembers}
        existingIds={new Set(members.map(m => m.user_id))}
        onInvite={handleInvite}
      />
    </div>
  );
}

function DirectAddSection({ parentMembers, existingIds, onAdd }) {
  const [userId, setUserId] = useState('');
  const [role, setRole] = useState('member');
  const [submitting, setSubmitting] = useState(false);

  const candidates = useMemo(() => {
    return parentMembers.filter(p => !existingIds.has(p.user_id));
  }, [parentMembers, existingIds]);

  async function handleSubmit() {
    if (!userId) return;
    setSubmitting(true);
    try {
      await onAdd(userId, role);
      // Reset form after success (errors surface via toast in parent).
      setUserId('');
      setRole('member');
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <section className="space-y-3">
      <h3 className="text-sm font-semibold text-gray-500 uppercase tracking-wide">Add member directly</h3>
      <div className="bg-white border border-gray-200 rounded-xl p-5 space-y-3">
        <p className="text-xs text-gray-500">
          Skip the invitation flow for parent-org members already on the platform.
        </p>
        <div className="flex items-center gap-2 flex-wrap">
          <select
            value={userId}
            onChange={e => setUserId(e.target.value)}
            disabled={candidates.length === 0}
            className="flex-1 min-w-[16rem] px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[#2E75B6] disabled:bg-gray-50 disabled:text-gray-400"
          >
            <option value="">
              {candidates.length === 0
                ? 'All parent-org members are already in this sub-org'
                : 'Select a parent-org member…'}
            </option>
            {candidates.map(p => (
              <option key={p.user_id} value={p.user_id}>
                {p.display_name} (@{p.username}{p.email ? ` · ${p.email}` : ''})
              </option>
            ))}
          </select>
          <select
            value={role}
            onChange={e => setRole(e.target.value)}
            className="text-sm border border-gray-300 rounded-lg px-3 py-2"
          >
            <option value="member">member</option>
            <option value="moderator">moderator</option>
            <option value="admin">admin</option>
          </select>
          <button
            type="button"
            onClick={handleSubmit}
            disabled={!userId || submitting}
            className="text-sm px-4 py-2 bg-[#1B3A5C] text-white rounded-lg hover:bg-[#2E75B6] disabled:opacity-50"
          >
            {submitting ? 'Adding…' : 'Add'}
          </button>
        </div>
      </div>
    </section>
  );
}

function ActiveRow({ member, onRoleChange, onRemove }) {
  const [role, setRole] = useState(member.role);
  const isOwner = member.role === 'owner';
  return (
    <div className="flex items-center gap-4 px-4 py-3 text-sm border-t border-gray-100 first:border-0">
      <span className="flex-1 font-medium text-gray-800 flex items-center gap-2">
        <Avatar user={{ id: member.user_id, display_name: member.display_name, avatar_url: member.avatar_url, avatar_url_small: member.avatar_url_small }} size="sm" />
        {member.display_name}
      </span>
      <span className="w-32 text-gray-500">@{member.username}</span>
      <span className="w-32">
        {isOwner ? (
          <span className="text-xs px-2 py-0.5 rounded bg-purple-50 text-purple-700">owner</span>
        ) : (
          <select
            value={role}
            onChange={e => setRole(e.target.value)}
            className="text-xs border border-gray-300 rounded px-2 py-1 focus:outline-none"
          >
            <option value="member">member</option>
            <option value="moderator">moderator</option>
            <option value="admin">admin</option>
          </select>
        )}
      </span>
      <span className="w-28 text-xs text-gray-400">{new Date(member.joined_at).toLocaleDateString()}</span>
      <span className="w-32 flex gap-2">
        {!isOwner && role !== member.role && (
          <button
            onClick={() => onRoleChange(member.user_id, role)}
            className="text-xs px-2 py-1 bg-[#1B3A5C] text-white rounded hover:bg-[#2E75B6]"
          >
            Save
          </button>
        )}
        {!isOwner && (
          <button
            onClick={() => onRemove(member.user_id, member.display_name)}
            className="text-xs text-red-500 hover:underline"
          >
            Remove
          </button>
        )}
      </span>
    </div>
  );
}

function InviteSection({ parentMembers, existingIds, onInvite }) {
  const [search, setSearch] = useState('');
  const [role, setRole] = useState('member');

  const candidates = useMemo(() => {
    const q = search.trim().toLowerCase();
    return parentMembers.filter(p => {
      if (existingIds.has(p.user_id)) return false;
      if (!q) return true;
      return (
        p.display_name?.toLowerCase().includes(q) ||
        p.username?.toLowerCase().includes(q) ||
        (p.email || '').toLowerCase().includes(q)
      );
    }).slice(0, 20);
  }, [search, parentMembers, existingIds]);

  return (
    <section className="space-y-3">
      <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide">Invite Member</h2>
      <div className="bg-white border border-gray-200 rounded-xl p-5 space-y-3">
        <p className="text-xs text-gray-500">
          Sub-org members must already be parent-org members. Search the parent-org
          membership list:
        </p>
        <div className="flex items-center gap-2">
          <input
            type="text"
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="Search parent-org members..."
            className="flex-1 px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[#2E75B6]"
          />
          <select
            value={role}
            onChange={e => setRole(e.target.value)}
            className="text-sm border border-gray-300 rounded-lg px-3 py-2"
          >
            <option value="member">member</option>
            <option value="moderator">moderator</option>
            <option value="admin">admin</option>
          </select>
        </div>
        <div className="border border-gray-100 rounded-lg max-h-64 overflow-y-auto">
          {candidates.length === 0 ? (
            <p className="px-3 py-4 text-xs text-gray-400">
              {search ? 'No matches' : 'All parent-org members are already in this sub-org'}
            </p>
          ) : candidates.map(p => (
            <div key={p.user_id} className="flex items-center justify-between px-3 py-2 text-sm border-b border-gray-100 last:border-0">
              <div className="flex items-center gap-2">
                <Avatar user={{ id: p.user_id, display_name: p.display_name, avatar_url: p.avatar_url, avatar_url_small: p.avatar_url_small }} size="sm" />
                <div>
                  <p className="font-medium text-gray-800">{p.display_name}</p>
                  <p className="text-xs text-gray-400">@{p.username}{p.email ? ` · ${p.email}` : ''}</p>
                </div>
              </div>
              <button
                onClick={() => onInvite(p.user_id, role)}
                className="text-xs px-3 py-1 bg-[#1B3A5C] text-white rounded hover:bg-[#2E75B6]"
              >
                Invite
              </button>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

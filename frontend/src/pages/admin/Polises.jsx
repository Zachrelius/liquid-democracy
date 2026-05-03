import { useEffect, useState, useCallback } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useOrg } from '../../OrgContext';
import { urlFor } from '../../utils/urls';
import api from '../../api';

/**
 * Phase 9 Session 3 — Polises list page (parent-org scope).
 *
 * Shows all Polises visible to the viewer under the current parent org.
 * Backend `GET /api/orgs/{slug}/polises` is scope-filtered server-side
 * (Phase 8.5 Decision 7 default-visible-with-opt-out applies for sub-org
 * Polises). Adds a client-side filter for "All / Org-wide / per-sub-org"
 * and a status filter (active / archived).
 *
 * Click row -> Polis detail page (parent-org admin route).
 */
export default function Polises() {
  const navigate = useNavigate();
  const { currentOrg, isModeratorOrAdmin, fetchSubOrgsFor } = useOrg();
  const [polises, setPolises] = useState([]);
  const [subOrgs, setSubOrgs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [scopeFilter, setScopeFilter] = useState('all'); // 'all' | 'orgwide' | sub_org_id
  const [statusFilter, setStatusFilter] = useState('active'); // 'active' | 'archived' | 'all'
  const [users, setUsers] = useState({}); // id -> {display_name, username}

  // Resolve parent slug. Polises are managed at parent scope here; if the
  // user is currently scoped to a sub-org they should use the sub-org admin
  // route family instead — show a redirect breadcrumb the way SubOrgList does.
  const parentSlug = currentOrg?.parent_org_id ? null : currentOrg?.slug;

  const load = useCallback(async () => {
    if (!parentSlug) return;
    setLoading(true);
    try {
      const list = await api.get(`/api/orgs/${parentSlug}/polises`);
      setPolises(list || []);
      // Fetch members so we can resolve creator display names.
      try {
        const members = await api.get(`/api/orgs/${parentSlug}/members`);
        const map = {};
        for (const m of (members || [])) {
          if (m.user_id) {
            map[m.user_id] = {
              display_name: m.display_name,
              username: m.username,
            };
          }
        }
        setUsers(map);
      } catch { /* leave map empty — fall back to user_id */ }
    } finally {
      setLoading(false);
    }
    try {
      const subs = await fetchSubOrgsFor(parentSlug);
      setSubOrgs(subs || []);
    } catch { setSubOrgs([]); }
  }, [parentSlug, fetchSubOrgsFor]);

  useEffect(() => { load(); }, [load]);

  if (currentOrg && currentOrg.parent_org_id) {
    return (
      <div className="max-w-2xl mx-auto px-4 py-16 text-center">
        <h1 className="text-xl font-semibold text-[#1B3A5C] mb-3">Switch to parent org</h1>
        <p className="text-sm text-gray-600 mb-4">
          Polises at the parent-org level are managed here. To manage this
          sub-org's Polises, use the sub-org admin route instead.
        </p>
      </div>
    );
  }

  if (!currentOrg) {
    return <div className="text-center py-16 text-gray-400">No organization selected</div>;
  }

  // Apply filters.
  const filtered = (polises || []).filter(p => {
    if (statusFilter !== 'all' && p.status !== statusFilter) return false;
    if (scopeFilter === 'orgwide' && p.sub_org_id) return false;
    if (scopeFilter !== 'all' && scopeFilter !== 'orgwide' && p.sub_org_id !== scopeFilter) return false;
    return true;
  });

  function subOrgName(id) {
    if (!id) return null;
    const s = subOrgs.find(x => x.id === id);
    return s?.name || 'sub-org';
  }

  function statusBadge(status) {
    const cls = status === 'active'
      ? 'bg-green-100 text-green-700'
      : 'bg-gray-200 text-gray-600';
    return (
      <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${cls}`}>
        {status}
      </span>
    );
  }

  return (
    <div className="max-w-5xl mx-auto px-4 py-8 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-[#1B3A5C]">Polises</h1>
          <p className="text-xs text-gray-500 mt-1">
            Pol.is deliberations linked to <strong>{currentOrg.name}</strong>.
          </p>
        </div>
        {isModeratorOrAdmin && (
          <Link
            to={urlFor(parentSlug, 'admin-polises-create')}
            className="text-sm px-4 py-2 bg-[#1B3A5C] text-white rounded-lg hover:bg-[#2E75B6] transition-colors"
          >
            Create Polis
          </Link>
        )}
      </div>

      {/* Filters */}
      <div className="flex items-center gap-4 flex-wrap">
        <div className="flex items-center gap-2">
          <label className="text-xs text-gray-500">Scope</label>
          <select
            value={scopeFilter}
            onChange={e => setScopeFilter(e.target.value)}
            className="px-2 py-1 border border-gray-300 rounded text-sm focus:outline-none focus:ring-2 focus:ring-[#2E75B6]"
          >
            <option value="all">All</option>
            <option value="orgwide">Org-wide</option>
            {subOrgs.map(s => (
              <option key={s.id} value={s.id}>{s.name}</option>
            ))}
          </select>
        </div>
        <div className="flex items-center gap-2">
          <label className="text-xs text-gray-500">Status</label>
          <select
            value={statusFilter}
            onChange={e => setStatusFilter(e.target.value)}
            className="px-2 py-1 border border-gray-300 rounded text-sm focus:outline-none focus:ring-2 focus:ring-[#2E75B6]"
          >
            <option value="active">Active</option>
            <option value="archived">Archived</option>
            <option value="all">All</option>
          </select>
        </div>
      </div>

      {loading ? (
        <div className="flex justify-center items-center py-20">
          <div className="animate-spin w-8 h-8 border-4 border-[#2E75B6] border-t-transparent rounded-full"></div>
        </div>
      ) : filtered.length === 0 ? (
        <div className="text-center py-12 text-gray-400 text-sm">
          No Polises match this filter.
        </div>
      ) : (
        <div className="bg-white border border-gray-200 rounded-xl overflow-hidden">
          <div className="grid grid-cols-12 gap-3 px-4 py-2 bg-gray-50 text-xs font-medium text-gray-500 uppercase">
            <span className="col-span-4">Title</span>
            <span className="col-span-2">Scope</span>
            <span className="col-span-1">Status</span>
            <span className="col-span-2">Creator</span>
            <span className="col-span-1 text-right">Participants</span>
            <span className="col-span-2">Created</span>
          </div>
          {filtered.map(p => {
            const creator = users[p.created_by];
            return (
              <button
                key={p.id}
                onClick={() => navigate(urlFor(parentSlug, 'admin-polis-detail', p.id))}
                className="w-full text-left grid grid-cols-12 gap-3 px-4 py-3 text-sm border-t border-gray-100 hover:bg-gray-50 transition-colors items-center"
              >
                <span className="col-span-4 font-medium text-gray-800 truncate">{p.title}</span>
                <span className="col-span-2 text-xs text-gray-600">
                  {p.sub_org_id ? (
                    <span className="inline-flex items-center px-1.5 py-0.5 rounded bg-blue-50 text-blue-700 text-[10px] uppercase">
                      {subOrgName(p.sub_org_id)}
                    </span>
                  ) : (
                    <span className="text-gray-500">Org-wide</span>
                  )}
                </span>
                <span className="col-span-1">{statusBadge(p.status)}</span>
                <span className="col-span-2 text-xs text-gray-600 truncate">
                  {creator ? creator.display_name : <span className="text-gray-400">—</span>}
                </span>
                <span className="col-span-1 text-xs text-gray-600 text-right">
                  {/* List endpoint doesn't include participation_stats; the
                      detail page does. Show em-dash here as a deliberate
                      "fetch on detail" placeholder, mirroring the
                      live_stats_unavailable convention. */}
                  —
                </span>
                <span className="col-span-2 text-xs text-gray-400">
                  {new Date(p.created_at).toLocaleDateString()}
                </span>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

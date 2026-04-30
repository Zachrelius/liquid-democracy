import { useEffect, useState, useCallback } from 'react';
import { Link } from 'react-router-dom';
import api from '../../api';
import useSubOrg from '../../useSubOrg';
import SubOrgErrorState from '../../components/SubOrgErrorState';

/**
 * Phase 9 Session 3 — Sub-Org Polises admin page.
 *
 * Mirrors `SubOrgTopics.jsx`: lists Polises scoped to this sub-org (filtered
 * client-side from the parent Polises endpoint, since list responses already
 * include `sub_org_id`). Includes a "Create Polis" button that routes to the
 * shared CreatePolis form with sub-org context locked.
 */
export default function SubOrgPolises() {
  const { parentSlug, subSlug, subOrg, loading: subLoading, error } = useSubOrg();
  const [polises, setPolises] = useState([]);
  const [loading, setLoading] = useState(true);
  const [statusFilter, setStatusFilter] = useState('active');
  const [users, setUsers] = useState({});

  const load = useCallback(async () => {
    if (!parentSlug || !subOrg) return;
    setLoading(true);
    try {
      const list = await api.get(`/api/orgs/${parentSlug}/polises`);
      setPolises((list || []).filter(p => p.sub_org_id === subOrg.id));
      try {
        const members = await api.get(`/api/orgs/${parentSlug}/members`);
        const map = {};
        for (const m of (members || [])) {
          if (m.user_id) map[m.user_id] = { display_name: m.display_name };
        }
        setUsers(map);
      } catch { /* ignore */ }
    } catch { /* ignore */ } finally {
      setLoading(false);
    }
  }, [parentSlug, subOrg]);

  useEffect(() => { load(); }, [load]);

  if (subLoading) return (
    <div className="flex justify-center items-center py-20">
      <div className="animate-spin w-8 h-8 border-4 border-[#2E75B6] border-t-transparent rounded-full"></div>
    </div>
  );
  if (error || !subOrg) return <SubOrgErrorState error={error} />;

  const filtered = polises.filter(p => statusFilter === 'all' || p.status === statusFilter);

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
    <div className="max-w-4xl mx-auto px-4 py-8 space-y-6">
      <div>
        <p className="text-xs text-gray-400 mb-1">
          <Link to="/admin/sub-orgs" className="hover:underline">Sub-organizations</Link>
          {' / '}
          <Link to={`/admin/sub-orgs/${subSlug}/settings`} className="hover:underline">{subOrg.name}</Link>
        </p>
        <div className="flex items-center justify-between">
          <h1 className="text-2xl font-semibold text-[#1B3A5C]">{subOrg.name} — Polises</h1>
          <Link
            to={`/admin/sub-orgs/${subSlug}/polises/create`}
            className="text-sm px-4 py-2 bg-[#1B3A5C] text-white rounded-lg hover:bg-[#2E75B6] transition-colors"
          >
            Create Polis
          </Link>
        </div>
        <p className="text-xs text-gray-500 mt-1">
          Pol.is deliberations scoped to this sub-org.
        </p>
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

      {loading ? (
        <div className="py-8 text-center text-gray-400 text-sm">Loading…</div>
      ) : filtered.length === 0 ? (
        <div className="text-center py-12 text-gray-400 text-sm">
          No Polises in this sub-org. Create one above.
        </div>
      ) : (
        <div className="bg-white border border-gray-200 rounded-xl overflow-hidden">
          <div className="grid grid-cols-12 gap-3 px-4 py-2 bg-gray-50 text-xs font-medium text-gray-500 uppercase">
            <span className="col-span-6">Title</span>
            <span className="col-span-2">Status</span>
            <span className="col-span-2">Creator</span>
            <span className="col-span-2">Created</span>
          </div>
          {filtered.map(p => {
            const creator = users[p.created_by];
            return (
              <Link
                key={p.id}
                to={`/admin/sub-orgs/${subSlug}/polises/${p.id}`}
                className="grid grid-cols-12 gap-3 px-4 py-3 text-sm border-t border-gray-100 hover:bg-gray-50 transition-colors items-center"
              >
                <span className="col-span-6 font-medium text-gray-800 truncate">{p.title}</span>
                <span className="col-span-2">{statusBadge(p.status)}</span>
                <span className="col-span-2 text-xs text-gray-600 truncate">
                  {creator ? creator.display_name : <span className="text-gray-400">—</span>}
                </span>
                <span className="col-span-2 text-xs text-gray-400">
                  {new Date(p.created_at).toLocaleDateString()}
                </span>
              </Link>
            );
          })}
        </div>
      )}
    </div>
  );
}

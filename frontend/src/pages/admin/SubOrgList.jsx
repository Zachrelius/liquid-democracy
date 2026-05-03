import { useState, useEffect, useCallback } from 'react';
import { Link } from 'react-router-dom';
import { useOrg } from '../../OrgContext';
import { urlFor } from '../../utils/urls';
import api from '../../api';
import { useToast } from '../../components/Toast';

/**
 * Phase 8.5 — Sub-Organizations list (parent-org admin entry point).
 *
 * Shows all sub-orgs visible under the current parent org with quick links to
 * the per-sub-org admin pages, plus a Create form for parent-org admins.
 *
 * Routed at `/admin/sub-orgs`. Requires parent-org admin scope (existing
 * AdminOnlyRoute) — Decision-6 implicit power means a parent-org admin can
 * always reach this list and create sub-orgs even without sub-org membership.
 */
export default function SubOrgList() {
  const { currentOrg, isAdmin, fetchSubOrgsFor, invalidateSubOrgs } = useOrg();
  const toast = useToast();
  const [subOrgs, setSubOrgs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [name, setName] = useState('');
  const [slug, setSlug] = useState('');
  const [description, setDescription] = useState('');
  const [creating, setCreating] = useState(false);

  // Resolve parent slug: if currentOrg is itself a sub-org, climb out.
  const parentSlug = currentOrg?.parent_org_id ? null : currentOrg?.slug;

  const load = useCallback(async () => {
    if (!parentSlug) return;
    setLoading(true);
    try {
      const list = await fetchSubOrgsFor(parentSlug, true);
      setSubOrgs(list);
    } finally {
      setLoading(false);
    }
  }, [parentSlug, fetchSubOrgsFor]);

  useEffect(() => { load(); }, [load]);

  // If the user is currently scoped to a sub-org, route them up to the parent
  // org first — sub-org list is a parent-org-admin surface.
  if (currentOrg && currentOrg.parent_org_id) {
    return (
      <div className="max-w-2xl mx-auto px-4 py-16 text-center">
        <h1 className="text-xl font-semibold text-[#1B3A5C] mb-3">Switch to parent org</h1>
        <p className="text-sm text-gray-600 mb-4">
          Sub-organizations are managed at the parent-org level. Use the org
          switcher in the nav to select <strong>the parent organization</strong>
          first.
        </p>
      </div>
    );
  }

  if (!currentOrg) {
    return <div className="text-center py-16 text-gray-400">No organization selected</div>;
  }

  async function handleCreate(e) {
    e.preventDefault();
    setCreating(true);
    try {
      await api.post(`/api/orgs/${parentSlug}/sub-orgs`, { name, slug, description });
      toast.success('Sub-organization created');
      setName(''); setSlug(''); setDescription('');
      setShowCreate(false);
      invalidateSubOrgs(parentSlug);
      load();
    } catch (e) {
      toast.error(e.message || 'Failed to create sub-organization');
    } finally {
      setCreating(false);
    }
  }

  // Auto-derive slug from name as the user types (only when slug is blank or
  // unedited; minor convenience, no validation here — server enforces).
  function onNameChange(v) {
    setName(v);
    if (!slug || slug === slugify(name)) {
      setSlug(slugify(v));
    }
  }

  return (
    <div className="max-w-4xl mx-auto px-4 py-8 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-[#1B3A5C]">Sub-Organizations</h1>
          <p className="text-xs text-gray-500 mt-1">
            Manage scoped governance groups inside <strong>{currentOrg.name}</strong>.
          </p>
        </div>
        {isAdmin && !showCreate && (
          <button
            onClick={() => setShowCreate(true)}
            className="text-sm px-4 py-2 bg-[#1B3A5C] text-white rounded-lg hover:bg-[#2E75B6] transition-colors"
          >
            Create Sub-Organization
          </button>
        )}
      </div>

      {showCreate && (
        <form onSubmit={handleCreate} className="bg-white border border-gray-200 rounded-xl p-5 space-y-3">
          <h3 className="text-sm font-semibold text-gray-700">New Sub-Organization</h3>
          <div>
            <label className="block text-xs text-gray-500 mb-1">Name</label>
            <input
              type="text"
              value={name}
              onChange={e => onNameChange(e.target.value)}
              required
              className="w-full max-w-md px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[#2E75B6]"
            />
          </div>
          <div>
            <label className="block text-xs text-gray-500 mb-1">Slug</label>
            <input
              type="text"
              value={slug}
              onChange={e => setSlug(e.target.value)}
              required
              className="w-full max-w-md px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[#2E75B6]"
            />
            <p className="text-xs text-gray-400 mt-1">
              Lowercase letters, digits, and hyphens. 3-50 characters.
            </p>
          </div>
          <div>
            <label className="block text-xs text-gray-500 mb-1">Description</label>
            <textarea
              value={description}
              onChange={e => setDescription(e.target.value)}
              rows={3}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[#2E75B6] resize-none"
            />
          </div>
          <div className="flex gap-2">
            <button
              type="submit"
              disabled={creating || !name.trim() || !slug.trim()}
              className="text-sm px-4 py-2 bg-[#1B3A5C] text-white rounded-lg hover:bg-[#2E75B6] disabled:opacity-50"
            >
              {creating ? 'Creating...' : 'Create'}
            </button>
            <button
              type="button"
              onClick={() => setShowCreate(false)}
              className="text-sm px-4 py-2 border border-gray-300 text-gray-600 rounded-lg hover:bg-gray-50"
            >
              Cancel
            </button>
          </div>
        </form>
      )}

      {loading ? (
        <div className="flex justify-center items-center py-20">
          <div className="animate-spin w-8 h-8 border-4 border-[#2E75B6] border-t-transparent rounded-full"></div>
        </div>
      ) : subOrgs.length === 0 ? (
        <div className="text-center py-12 text-gray-400 text-sm">
          No sub-organizations yet. Create one to scope topics, proposals, and members to a smaller group.
        </div>
      ) : (
        <div className="space-y-3">
          {subOrgs.map(s => (
            <div key={s.id} className="bg-white border border-gray-200 rounded-xl p-4 flex items-center justify-between">
              <div className="flex-1">
                <div className="flex items-center gap-2">
                  <p className="text-sm font-medium text-gray-800">{s.name}</p>
                  {s.settings?.private && (
                    <span className="text-[10px] px-1.5 py-0.5 rounded bg-gray-100 text-gray-500 uppercase">
                      Private
                    </span>
                  )}
                  {s.user_role && (
                    <span className="text-[10px] px-1.5 py-0.5 rounded bg-blue-50 text-blue-700 uppercase">
                      {s.user_role}
                    </span>
                  )}
                </div>
                <p className="text-xs text-gray-400">{s.slug} · {s.member_count ?? 0} members</p>
                {s.description && (
                  <p className="text-xs text-gray-500 mt-1 line-clamp-2">{s.description}</p>
                )}
              </div>
              <div className="flex gap-3 text-xs">
                <Link to={urlFor(parentSlug, 'admin-sub-org-settings', s.slug)} className="text-[#2E75B6] hover:underline">
                  Settings
                </Link>
                <Link to={urlFor(parentSlug, 'admin-sub-org-members', s.slug)} className="text-[#2E75B6] hover:underline">
                  Members
                </Link>
                <Link to={urlFor(parentSlug, 'admin-sub-org-proposals', s.slug)} className="text-[#2E75B6] hover:underline">
                  Proposals
                </Link>
                <Link to={urlFor(parentSlug, 'admin-sub-org-topics', s.slug)} className="text-[#2E75B6] hover:underline">
                  Topics
                </Link>
                <Link to={urlFor(parentSlug, 'admin-sub-org-polises', s.slug)} className="text-[#2E75B6] hover:underline">
                  Polises
                </Link>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function slugify(s) {
  return (s || '')
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9-]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 50);
}

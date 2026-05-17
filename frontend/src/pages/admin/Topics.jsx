import { useState, useEffect, useCallback } from 'react';
import { useOrg } from '../../OrgContext';
import api from '../../api';
import { useToast } from '../../components/Toast';
import { useConfirm } from '../../components/ConfirmDialog';
// Phase 12.5 F2 — per-control permission gating.
import { useHasPermission } from '../../hooks/useHasPermission';

const PRESET_COLORS = [
  '#6366f1', '#8b5cf6', '#ec4899', '#ef4444', '#f97316',
  '#eab308', '#22c55e', '#14b8a6', '#06b6d4', '#3b82f6',
  'var(--brand-primary)', 'var(--brand-accent)', '#64748b', '#78716c',
];

export default function Topics() {
  const { currentOrg, fetchSubOrgsFor } = useOrg();
  const toast = useToast();
  const confirm = useConfirm();
  // Phase 12.5 F2 — per-control permission gating. Promote-to-org-wide is
  // a structural edit so it gates on `topic.edit`.
  const canCreateTopic = useHasPermission('topic.create');
  const canEditTopic = useHasPermission('topic.edit');
  const canDeleteTopic = useHasPermission('topic.delete');
  const [topics, setTopics] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [editingId, setEditingId] = useState(null);

  // Create form state
  const [newName, setNewName] = useState('');
  const [newDesc, setNewDesc] = useState('');
  const [newColor, setNewColor] = useState('#6366f1');
  // Phase 8.5 — scope selector. '' == parent-org-wide (sub_org_id null).
  const [newScope, setNewScope] = useState('');

  // Edit form state
  const [editName, setEditName] = useState('');
  const [editDesc, setEditDesc] = useState('');
  const [editColor, setEditColor] = useState('#6366f1');

  // Phase 8.5 — sub-orgs available for the scope dropdown.
  const [subOrgs, setSubOrgs] = useState([]);

  const slug = currentOrg?.slug;

  const load = useCallback(async () => {
    if (!slug) return;
    try {
      const data = await api.get(`/api/orgs/${slug}/topics`);
      setTopics(data);
    } catch { /* ignore */ } finally {
      setLoading(false);
    }
    // Sub-org scope dropdown only meaningful at parent-org scope.
    if (currentOrg && !currentOrg.parent_org_id) {
      try {
        const subs = await fetchSubOrgsFor(slug);
        setSubOrgs(subs || []);
      } catch { setSubOrgs([]); }
    }
  }, [slug, currentOrg, fetchSubOrgsFor]);

  useEffect(() => { load(); }, [load]);

  if (!currentOrg) return <div className="text-center py-16 text-gray-400">No organization selected</div>;
  if (loading) return (
    <div className="flex justify-center items-center py-20">
      <div className="animate-spin w-8 h-8 border-4 border-[var(--brand-accent)] border-t-transparent rounded-full"></div>
    </div>
  );

  async function handleCreate(e) {
    e.preventDefault();
    try {
      const payload = { name: newName, description: newDesc, color: newColor };
      if (newScope) payload.sub_org_id = newScope;
      await api.post(`/api/orgs/${slug}/topics`, payload);
      toast.success('Topic created');
      setNewName('');
      setNewDesc('');
      setNewColor('#6366f1');
      setNewScope('');
      setShowCreate(false);
      load();
    } catch (err) {
      toast.error(err.message);
    }
  }

  async function handlePromote(topic) {
    const displayName = topic.name;
    const ok = await confirm({
      title: 'Promote to org-wide?',
      message: `"${displayName}" will become visible to all parent-org members and usable by any proposal. This is IRREVERSIBLE.`,
    });
    if (!ok) return;
    try {
      await api.post(`/api/orgs/${slug}/topics/${topic.id}/promote-to-orgwide`, { confirm: true });
      toast.success(`"${displayName}" promoted to org-wide`);
      load();
    } catch (e) {
      toast.error(e.message || 'Failed to promote');
    }
  }

  async function handleUpdate(topicId) {
    try {
      await api.patch(`/api/orgs/${slug}/topics/${topicId}`, { name: editName, description: editDesc, color: editColor });
      toast.success('Topic updated');
      setEditingId(null);
      load();
    } catch (err) {
      toast.error(err.message);
    }
  }

  async function handleDeactivate(topicId, topicName) {
    const ok = await confirm({
      title: 'Deactivate Topic',
      message: `Deactivate topic "${topicName}"? It will be removed from the organization.`,
      destructive: true,
    });
    if (!ok) return;
    try {
      await api.delete(`/api/orgs/${slug}/topics/${topicId}`);
      toast.success('Topic deactivated');
      load();
    } catch (err) {
      toast.error(err.message);
    }
  }

  function startEdit(topic) {
    setEditingId(topic.id);
    setEditName(topic.name);
    setEditDesc(topic.description || '');
    setEditColor(topic.color);
  }

  function ColorPicker({ value, onChange }) {
    return (
      <div className="flex flex-wrap gap-2">
        {PRESET_COLORS.map(c => (
          <button
            key={c}
            type="button"
            onClick={() => onChange(c)}
            className={`w-7 h-7 rounded-full border-2 transition-all ${
              value === c ? 'border-gray-800 scale-110' : 'border-transparent hover:border-gray-300'
            }`}
            style={{ backgroundColor: c }}
          />
        ))}
      </div>
    );
  }

  return (
    <div className="max-w-3xl mx-auto px-4 py-8 space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold text-[var(--brand-primary)]">Topic Management</h1>
        {/* Phase 12.5 F2 — Create button gated on `topic.create`. */}
        {!showCreate && canCreateTopic && (
          <button
            onClick={() => setShowCreate(true)}
            className="text-sm px-4 py-2 bg-[var(--brand-primary)] text-white rounded-lg hover:bg-[var(--brand-accent)] transition-colors"
          >
            Create Topic
          </button>
        )}
      </div>

      {/* Create Form */}
      {showCreate && (
        <form onSubmit={handleCreate} className="bg-white border border-gray-200 rounded-xl p-5 space-y-4">
          <h3 className="text-sm font-semibold text-gray-700">New Topic</h3>
          <div>
            <label className="block text-xs text-gray-500 mb-1">Name</label>
            <input
              type="text"
              value={newName}
              onChange={e => setNewName(e.target.value)}
              required
              className="w-full max-w-xs px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[var(--brand-accent)]"
            />
          </div>
          <div>
            <label className="block text-xs text-gray-500 mb-1">Description</label>
            <input
              type="text"
              value={newDesc}
              onChange={e => setNewDesc(e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[var(--brand-accent)]"
            />
          </div>
          {subOrgs.length > 0 && (
            <div>
              <label className="block text-xs text-gray-500 mb-1">Scope</label>
              <select
                value={newScope}
                onChange={e => setNewScope(e.target.value)}
                className="w-full max-w-xs px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[var(--brand-accent)]"
              >
                <option value="">Parent-org-wide (default)</option>
                {subOrgs.map(s => (
                  <option key={s.id} value={s.id}>{s.name} only</option>
                ))}
              </select>
              <p className="text-xs text-gray-400 mt-1">
                Sub-org topics are visible only to that sub-org's members and parent-org admins.
              </p>
            </div>
          )}
          <div>
            <label className="block text-xs text-gray-500 mb-1">Color</label>
            <ColorPicker value={newColor} onChange={setNewColor} />
          </div>
          <div className="flex gap-2">
            <button
              type="submit"
              disabled={!newName.trim()}
              className="text-sm px-4 py-2 bg-[var(--brand-primary)] text-white rounded-lg hover:bg-[var(--brand-accent)] disabled:opacity-50"
            >
              Create
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

      {/* Topics List */}
      <div className="space-y-3">
        {topics.length === 0 ? (
          <div className="text-center py-12 text-gray-400 text-sm">No topics yet. Create one to get started.</div>
        ) : (
          topics.map(t => (
            <div key={t.id} className="bg-white border border-gray-200 rounded-xl p-4">
              {editingId === t.id ? (
                <div className="space-y-3">
                  <div>
                    <label className="block text-xs text-gray-500 mb-1">Name</label>
                    <input
                      type="text"
                      value={editName}
                      onChange={e => setEditName(e.target.value)}
                      className="w-full max-w-xs px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[var(--brand-accent)]"
                    />
                  </div>
                  <div>
                    <label className="block text-xs text-gray-500 mb-1">Description</label>
                    <input
                      type="text"
                      value={editDesc}
                      onChange={e => setEditDesc(e.target.value)}
                      className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[var(--brand-accent)]"
                    />
                  </div>
                  <div>
                    <label className="block text-xs text-gray-500 mb-1">Color</label>
                    <ColorPicker value={editColor} onChange={setEditColor} />
                  </div>
                  <div className="flex gap-2">
                    <button
                      onClick={() => handleUpdate(t.id)}
                      className="text-xs px-3 py-1.5 bg-[var(--brand-primary)] text-white rounded-lg hover:bg-[var(--brand-accent)]"
                    >
                      Save
                    </button>
                    <button
                      onClick={() => setEditingId(null)}
                      className="text-xs px-3 py-1.5 border border-gray-300 text-gray-600 rounded-lg hover:bg-gray-50"
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              ) : (
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <span
                      className="w-5 h-5 rounded-full flex-shrink-0"
                      style={{ backgroundColor: t.color }}
                    />
                    <div>
                      <div className="flex items-center gap-2">
                        <p className="text-sm font-medium text-gray-800">{t.name}</p>
                        {t.sub_org_id && (
                          <span className="text-[10px] uppercase px-1.5 py-0.5 rounded bg-blue-50 text-blue-700">
                            {(subOrgs.find(s => s.id === t.sub_org_id)?.name) || 'sub-org'}
                          </span>
                        )}
                      </div>
                      {t.description && <p className="text-xs text-gray-400">{t.description}</p>}
                    </div>
                  </div>
                  <div className="flex gap-2">
                    {/* Phase 12.5 F2 — Promote (structural edit) gated on
                        `topic.edit`; Edit on `topic.edit`; Deactivate on
                        `topic.delete`. */}
                    {t.sub_org_id && canEditTopic && (
                      <button
                        onClick={() => handlePromote(t)}
                        className="text-xs text-[var(--brand-accent)] hover:underline"
                        title="Make this topic visible to the whole parent org"
                      >
                        Promote to org-wide
                      </button>
                    )}
                    {canEditTopic && (
                      <button
                        onClick={() => startEdit(t)}
                        className="text-xs text-[var(--brand-accent)] hover:underline"
                      >
                        Edit
                      </button>
                    )}
                    {canDeleteTopic && (
                      <button
                        // Phase 26 D1 — pass display name (description ||
                        // name) to the confirm dialog so the user sees
                        // the label they recognize.
                        onClick={() => handleDeactivate(t.id, t.name)}
                        className="text-xs text-red-500 hover:underline"
                      >
                        Deactivate
                      </button>
                    )}
                  </div>
                </div>
              )}
            </div>
          ))
        )}
      </div>
    </div>
  );
}

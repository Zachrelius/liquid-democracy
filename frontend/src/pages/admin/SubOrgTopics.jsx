import { useEffect, useState, useCallback } from 'react';
import { Link } from 'react-router-dom';
import api from '../../api';
import useSubOrg from '../../useSubOrg';
import { urlFor } from '../../utils/urls';
import { useToast } from '../../components/Toast';
import { useConfirm } from '../../components/ConfirmDialog';
import SubOrgErrorState from '../../components/SubOrgErrorState';

const PRESET_COLORS = [
  '#6366f1', '#8b5cf6', '#ec4899', '#ef4444', '#f97316',
  '#eab308', '#22c55e', '#14b8a6', '#06b6d4', '#3b82f6',
  'var(--brand-primary)', 'var(--brand-accent)', '#64748b', '#78716c',
];

/**
 * Phase 8.5 — Sub-Org Topics admin page.
 *
 * Lists topics scoped to this sub-org (filtered client-side from the parent
 * topics endpoint). Includes a Create form locked to this sub-org's scope and
 * a Promote-to-org-wide action on each row (Decision 3, irreversible).
 */
export default function SubOrgTopics() {
  const { parentSlug, subSlug, subOrg, loading: subLoading, error } = useSubOrg();
  const toast = useToast();
  const confirm = useConfirm();

  const [topics, setTopics] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [color, setColor] = useState('#6366f1');

  const load = useCallback(async () => {
    if (!parentSlug || !subOrg) return;
    setLoading(true);
    try {
      const all = await api.get(`/api/orgs/${parentSlug}/topics`);
      setTopics((all || []).filter(t => t.sub_org_id === subOrg.id));
    } catch { /* ignore */ } finally {
      setLoading(false);
    }
  }, [parentSlug, subOrg]);

  useEffect(() => { load(); }, [load]);

  if (subLoading) return (
    <div className="flex justify-center items-center py-20">
      <div className="animate-spin w-8 h-8 border-4 border-[var(--brand-accent)] border-t-transparent rounded-full"></div>
    </div>
  );
  if (error || !subOrg) return <SubOrgErrorState error={error} />;

  async function handleCreate(e) {
    e.preventDefault();
    try {
      await api.post(`/api/orgs/${parentSlug}/topics`, {
        name, description, color,
        sub_org_id: subOrg.id,
      });
      toast.success('Topic created');
      setName(''); setDescription(''); setColor('#6366f1');
      setShowCreate(false);
      load();
    } catch (e) {
      toast.error(e.message || 'Failed to create topic');
    }
  }

  async function handlePromote(topic) {
    const displayName = topic.description?.trim() || topic.name;
    const ok = await confirm({
      title: 'Promote to org-wide?',
      message: `"${displayName}" will become visible to all parent-org members and usable by any proposal in the org. This is IRREVERSIBLE.`,
    });
    if (!ok) return;
    try {
      await api.post(`/api/orgs/${parentSlug}/topics/${topic.id}/promote-to-orgwide`, { confirm: true });
      toast.success(`"${displayName}" promoted to org-wide`);
      load();
    } catch (e) {
      toast.error(e.message || 'Failed to promote');
    }
  }

  async function handleDeactivate(topic) {
    const displayName = topic.description?.trim() || topic.name;
    const ok = await confirm({
      title: 'Deactivate Topic',
      message: `Deactivate "${displayName}"?`,
      destructive: true,
    });
    if (!ok) return;
    try {
      await api.delete(`/api/orgs/${parentSlug}/topics/${topic.id}`);
      toast.success('Topic deactivated');
      load();
    } catch (e) {
      toast.error(e.message);
    }
  }

  return (
    <div className="max-w-3xl mx-auto px-4 py-8 space-y-6">
      <div>
        <p className="text-xs text-gray-400 mb-1">
          <Link to={urlFor(parentSlug, 'admin-sub-orgs')} className="hover:underline">Sub-organizations</Link>
          {' / '}
          <Link to={urlFor(parentSlug, 'admin-sub-org-settings', subSlug)} className="hover:underline">{subOrg.name}</Link>
        </p>
        <div className="flex items-center justify-between">
          <h1 className="text-2xl font-semibold text-[var(--brand-primary)]">{subOrg.name} — Topics</h1>
          {!showCreate && (
            <button
              onClick={() => setShowCreate(true)}
              className="text-sm px-4 py-2 bg-[var(--brand-primary)] text-white rounded-lg hover:bg-[var(--brand-accent)] transition-colors"
            >
              Create Topic
            </button>
          )}
        </div>
        <p className="text-xs text-gray-500 mt-1">
          Topics scoped to this sub-org. Promote one to make it visible org-wide.
        </p>
      </div>

      {showCreate && (
        <form onSubmit={handleCreate} className="bg-white border border-gray-200 rounded-xl p-5 space-y-4">
          <h3 className="text-sm font-semibold text-gray-700">New Topic — scope locked to {subOrg.name}</h3>
          <div>
            <label className="block text-xs text-gray-500 mb-1">Name</label>
            <input
              type="text"
              value={name}
              onChange={e => setName(e.target.value)}
              required
              className="w-full max-w-xs px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[var(--brand-accent)]"
            />
          </div>
          <div>
            <label className="block text-xs text-gray-500 mb-1">Description</label>
            <input
              type="text"
              value={description}
              onChange={e => setDescription(e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[var(--brand-accent)]"
            />
          </div>
          <div>
            <label className="block text-xs text-gray-500 mb-1">Color</label>
            <div className="flex flex-wrap gap-2">
              {PRESET_COLORS.map(c => (
                <button
                  key={c}
                  type="button"
                  onClick={() => setColor(c)}
                  className={`w-7 h-7 rounded-full border-2 transition-all ${color === c ? 'border-gray-800 scale-110' : 'border-transparent hover:border-gray-300'}`}
                  style={{ backgroundColor: c }}
                />
              ))}
            </div>
          </div>
          <div className="flex gap-2">
            <button
              type="submit"
              disabled={!name.trim()}
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

      {loading ? (
        <div className="py-8 text-center text-gray-400 text-sm">Loading…</div>
      ) : topics.length === 0 ? (
        <div className="text-center py-12 text-gray-400 text-sm">
          No sub-org topics yet. Create one above, or use parent-org-wide topics for proposals here.
        </div>
      ) : (
        <div className="space-y-3">
          {topics.map(t => (
            <div key={t.id} className="bg-white border border-gray-200 rounded-xl p-4 flex items-center justify-between">
              <div className="flex items-center gap-3">
                <span className="w-5 h-5 rounded-full flex-shrink-0" style={{ backgroundColor: t.color }} />
                <div>
                  <p className="text-sm font-medium text-gray-800">{t.name}</p>
                  {t.description && <p className="text-xs text-gray-400">{t.description}</p>}
                </div>
              </div>
              <div className="flex gap-3 text-xs">
                <button
                  onClick={() => handlePromote(t)}
                  className="text-[var(--brand-accent)] hover:underline"
                  title="Make this topic visible to the whole parent org"
                >
                  Promote to org-wide
                </button>
                <button
                  onClick={() => handleDeactivate(t)}
                  className="text-red-500 hover:underline"
                >
                  Deactivate
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

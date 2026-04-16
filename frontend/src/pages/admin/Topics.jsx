import { useState, useEffect, useCallback } from 'react';
import { useOrg } from '../../OrgContext';
import api from '../../api';

const PRESET_COLORS = [
  '#6366f1', '#8b5cf6', '#ec4899', '#ef4444', '#f97316',
  '#eab308', '#22c55e', '#14b8a6', '#06b6d4', '#3b82f6',
  '#1B3A5C', '#2E75B6', '#64748b', '#78716c',
];

export default function Topics() {
  const { currentOrg } = useOrg();
  const [topics, setTopics] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [editingId, setEditingId] = useState(null);

  // Create form state
  const [newName, setNewName] = useState('');
  const [newDesc, setNewDesc] = useState('');
  const [newColor, setNewColor] = useState('#6366f1');

  // Edit form state
  const [editName, setEditName] = useState('');
  const [editDesc, setEditDesc] = useState('');
  const [editColor, setEditColor] = useState('#6366f1');

  const slug = currentOrg?.slug;

  const load = useCallback(async () => {
    if (!slug) return;
    try {
      const data = await api.get(`/api/orgs/${slug}/topics`);
      setTopics(data);
    } catch { /* ignore */ } finally {
      setLoading(false);
    }
  }, [slug]);

  useEffect(() => { load(); }, [load]);

  if (!currentOrg) return <div className="text-center py-16 text-gray-400">No organization selected</div>;
  if (loading) return (
    <div className="flex justify-center items-center py-20">
      <div className="animate-spin w-8 h-8 border-4 border-[#2E75B6] border-t-transparent rounded-full"></div>
    </div>
  );

  async function handleCreate(e) {
    e.preventDefault();
    try {
      await api.post(`/api/orgs/${slug}/topics`, { name: newName, description: newDesc, color: newColor });
      setNewName('');
      setNewDesc('');
      setNewColor('#6366f1');
      setShowCreate(false);
      load();
    } catch (err) {
      alert(err.message);
    }
  }

  async function handleUpdate(topicId) {
    try {
      await api.patch(`/api/orgs/${slug}/topics/${topicId}`, { name: editName, description: editDesc, color: editColor });
      setEditingId(null);
      load();
    } catch (err) {
      alert(err.message);
    }
  }

  async function handleDeactivate(topicId, topicName) {
    if (!window.confirm(`Deactivate topic "${topicName}"? It will be removed from the organization.`)) return;
    try {
      await api.delete(`/api/orgs/${slug}/topics/${topicId}`);
      load();
    } catch (err) {
      alert(err.message);
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
        <h1 className="text-2xl font-semibold text-[#1B3A5C]">Topic Management</h1>
        {!showCreate && (
          <button
            onClick={() => setShowCreate(true)}
            className="text-sm px-4 py-2 bg-[#1B3A5C] text-white rounded-lg hover:bg-[#2E75B6] transition-colors"
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
              className="w-full max-w-xs px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[#2E75B6]"
            />
          </div>
          <div>
            <label className="block text-xs text-gray-500 mb-1">Description</label>
            <input
              type="text"
              value={newDesc}
              onChange={e => setNewDesc(e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[#2E75B6]"
            />
          </div>
          <div>
            <label className="block text-xs text-gray-500 mb-1">Color</label>
            <ColorPicker value={newColor} onChange={setNewColor} />
          </div>
          <div className="flex gap-2">
            <button
              type="submit"
              disabled={!newName.trim()}
              className="text-sm px-4 py-2 bg-[#1B3A5C] text-white rounded-lg hover:bg-[#2E75B6] disabled:opacity-50"
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
                      className="w-full max-w-xs px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[#2E75B6]"
                    />
                  </div>
                  <div>
                    <label className="block text-xs text-gray-500 mb-1">Description</label>
                    <input
                      type="text"
                      value={editDesc}
                      onChange={e => setEditDesc(e.target.value)}
                      className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[#2E75B6]"
                    />
                  </div>
                  <div>
                    <label className="block text-xs text-gray-500 mb-1">Color</label>
                    <ColorPicker value={editColor} onChange={setEditColor} />
                  </div>
                  <div className="flex gap-2">
                    <button
                      onClick={() => handleUpdate(t.id)}
                      className="text-xs px-3 py-1.5 bg-[#1B3A5C] text-white rounded-lg hover:bg-[#2E75B6]"
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
                      <p className="text-sm font-medium text-gray-800">{t.name}</p>
                      {t.description && <p className="text-xs text-gray-400">{t.description}</p>}
                    </div>
                  </div>
                  <div className="flex gap-2">
                    <button
                      onClick={() => startEdit(t)}
                      className="text-xs text-[#2E75B6] hover:underline"
                    >
                      Edit
                    </button>
                    <button
                      onClick={() => handleDeactivate(t.id, t.name)}
                      className="text-xs text-red-500 hover:underline"
                    >
                      Deactivate
                    </button>
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

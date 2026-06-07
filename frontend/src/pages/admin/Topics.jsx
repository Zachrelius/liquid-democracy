import { useState, useEffect, useCallback, useMemo } from 'react';
import { useOrg } from '../../OrgContext';
import api from '../../api';
import { useToast } from '../../components/Toast';
import { useConfirm } from '../../components/ConfirmDialog';
// Phase 12.5 F2 — per-control permission gating.
import { useHasPermission } from '../../hooks/useHasPermission';
import PendingActionsBanner from '../../components/PendingActionsBanner';
// Phase 56 F3 — render org topic guidance (markdown) at the top of the
// topic-management page. Same renderer used for proposal bodies / intro_text.
import renderMarkdown from '../../utils/renderMarkdown';

// Phase 56 F1 — `var(--brand-primary)` and `var(--brand-accent)` removed.
// The CSS-var swatches rendered fine but POSTed a non-hex value that the
// backend hex-color validator (converged onto the branding regex in B2)
// correctly rejects. The custom-color picker below covers any color a
// steward might have reached for via those swatches.
const PRESET_COLORS = [
  '#6366f1', '#8b5cf6', '#ec4899', '#ef4444', '#f97316',
  '#eab308', '#22c55e', '#14b8a6', '#06b6d4', '#3b82f6',
  '#64748b', '#78716c', '#1B3A5C', '#2E75B6',
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
  const [newColor, setNewColor] = useState('#6366f1');
  // Phase 56 F2 + F4 — optional purpose + category on create + edit.
  const [newPurpose, setNewPurpose] = useState('');
  const [newCategory, setNewCategory] = useState('');
  // Phase 8.5 — scope selector. '' == parent-org-wide (sub_org_id null).
  const [newScope, setNewScope] = useState('');

  // Edit form state
  const [editName, setEditName] = useState('');
  const [editColor, setEditColor] = useState('#6366f1');
  const [editPurpose, setEditPurpose] = useState('');
  const [editCategory, setEditCategory] = useState('');

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

  // Phase 56 F3 / F4 hotfix — derive guidance + categoriesEnabled +
  // groupedTopics BEFORE the early-return guards. The earlier placement
  // (after the `if (!currentOrg)` / `if (loading)` returns) violated the
  // rules of hooks: on the initial render `loading=true` short-circuited
  // before `useMemo` ran, so a later render where `loading=false` called
  // a hook that hadn't existed previously → React #310. Reading from
  // possibly-null `currentOrg` is safe via optional chaining; the empty
  // `topics` array on initial render makes the memo a no-op.
  const topicGuidance =
    typeof currentOrg?.settings?.topic_guidance === 'string'
      ? currentOrg.settings.topic_guidance
      : '';
  const categoriesEnabled = !!currentOrg?.settings?.topic_categories_enabled;
  // Phase 59 B2 — org-defined category list. When the toggle is on, the
  // category control on the topic create/edit form is a dropdown
  // populated from this list (free-text legacy values are kept and
  // shown with a "(not in list)" marker). When the toggle is off the
  // control is hidden entirely (fixing the half-wired Phase 56 surface).
  const orgCategories = Array.isArray(currentOrg?.settings?.topic_categories)
    ? currentOrg.settings.topic_categories
    : [];
  const groupedTopics = useMemo(() => {
    if (!categoriesEnabled) return null;
    const groups = new Map();
    for (const t of topics) {
      const key = (t.category || '').trim();
      const groupKey = key || '__uncategorized__';
      if (!groups.has(groupKey)) groups.set(groupKey, []);
      groups.get(groupKey).push(t);
    }
    const named = [...groups.entries()]
      .filter(([k]) => k !== '__uncategorized__')
      .sort(([a], [b]) => a.toLowerCase().localeCompare(b.toLowerCase()));
    const uncategorized = groups.get('__uncategorized__') || [];
    const result = named.map(([label, items]) => ({
      label,
      items: items
        .slice()
        .sort((a, b) => a.name.toLowerCase().localeCompare(b.name.toLowerCase())),
    }));
    if (uncategorized.length > 0) {
      result.push({
        label: 'Uncategorized',
        items: uncategorized
          .slice()
          .sort((a, b) => a.name.toLowerCase().localeCompare(b.name.toLowerCase())),
        isUncategorized: true,
      });
    }
    return result;
  }, [categoriesEnabled, topics]);

  if (!currentOrg) return <div className="text-center py-16 text-gray-400">No organization selected</div>;
  if (loading) return (
    <div className="flex justify-center items-center py-20">
      <div className="animate-spin w-8 h-8 border-4 border-[var(--brand-accent)] border-t-transparent rounded-full"></div>
    </div>
  );

  async function handleCreate(e) {
    e.preventDefault();
    try {
      const payload = { name: newName, color: newColor };
      // Phase 56 F2 + F4 — only send purpose / category when non-empty so
      // the backend stores NULL rather than an empty literal.
      const trimmedPurpose = newPurpose.trim();
      const trimmedCategory = newCategory.trim();
      if (trimmedPurpose) payload.purpose = trimmedPurpose;
      if (trimmedCategory) payload.category = trimmedCategory;
      if (newScope) payload.sub_org_id = newScope;
      await api.post(`/api/orgs/${slug}/topics`, payload);
      toast.success('Topic created');
      setNewName('');
      setNewColor('#6366f1');
      setNewPurpose('');
      setNewCategory('');
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
      const payload = { name: editName, color: editColor };
      const trimmedPurpose = editPurpose.trim();
      const trimmedCategory = editCategory.trim();
      // Phase 56 — PATCH semantics for purpose/category mirror the
      // backend: send the value (even if empty) so a steward can
      // explicitly clear a field by saving with the input blank.
      payload.purpose = trimmedPurpose;
      payload.category = trimmedCategory;
      await api.patch(`/api/orgs/${slug}/topics/${topicId}`, payload);
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
      const res = await api.delete(`/api/orgs/${slug}/topics/${topicId}`);
      // Phase 44 — approval-on path.
      if (res && res.status === 'submitted_for_approval') {
        const need = res.pending_action?.threshold ?? 2;
        toast.success(`Submitted for approval (${need} approvals needed)`);
      } else {
        toast.success('Topic deactivated');
      }
      load();
    } catch (err) {
      toast.error(err.message);
    }
  }

  function startEdit(topic) {
    setEditingId(topic.id);
    setEditName(topic.name);
    setEditColor(topic.color);
    // Phase 56 F2 + F4 — seed the edit form with the current purpose +
    // category (or empty strings when null) so the inputs are editable.
    setEditPurpose(topic.purpose || '');
    setEditCategory(topic.category || '');
  }

  function ColorPicker({ value, onChange }) {
    // Phase 56 F1 — a native `<input type="color">` sits beside the preset
    // swatches so a steward can pick any hex (covers what the dropped
    // var() swatches loosely gestured at). The native picker always emits
    // `#RRGGBB`, so the backend validator (regex `^#(?:[0-9a-f]{3}|[0-9a-f]{6})$`)
    // accepts the output by construction.
    //
    // Phase 59 C1 — `onMouseDown={preventDefault}` on each swatch keeps
    // the browser's focus on whatever was previously focused (including
    // the system-level color picker dialog if open). Without this guard,
    // clicking a swatch steals focus from the OS color dialog and the
    // browser closes the dialog. The `onClick` still fires (preventDefault
    // on mousedown doesn't suppress click). This is the conservative fix
    // for the "auto-closes on each swatch click" report — the React layer
    // has no popover of its own, but the OS-level picker reacted to focus
    // changes triggered by swatch clicks.
    const isPreset = PRESET_COLORS.includes(value);
    return (
      <div>
        <div className="flex flex-wrap items-center gap-2">
          {PRESET_COLORS.map(c => (
            <button
              key={c}
              type="button"
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => onChange(c)}
              className={`w-7 h-7 rounded-full border-2 transition-all ${
                value === c ? 'border-gray-800 scale-110' : 'border-transparent hover:border-gray-300'
              }`}
              style={{ backgroundColor: c }}
              aria-label={`Use color ${c}`}
            />
          ))}
          <label
            className={`relative inline-flex items-center justify-center w-7 h-7 rounded-full border-2 cursor-pointer transition-all ${
              !isPreset ? 'border-gray-800 scale-110' : 'border-dashed border-gray-300 hover:border-gray-500'
            }`}
            style={!isPreset ? { backgroundColor: value } : { backgroundColor: 'white' }}
            title="Pick a custom color"
          >
            <input
              type="color"
              value={value && /^#[0-9a-fA-F]{6}$/.test(value) ? value : '#6366f1'}
              onChange={e => onChange(e.target.value)}
              className="absolute inset-0 opacity-0 cursor-pointer"
              aria-label="Pick a custom color"
            />
            {isPreset && (
              <span className="text-[10px] text-gray-500 leading-none select-none">+</span>
            )}
          </label>
        </div>
        <p className="mt-2 text-xs text-gray-400">
          Selected: <span className="font-mono">{value || '—'}</span>
        </p>
      </div>
    );
  }

  return (
    <div className="max-w-3xl mx-auto px-4 py-8 space-y-6">
      <PendingActionsBanner orgSlug={slug} actionType="topic.delete" />
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

      {/* Phase 56 F3 — org-level topic guidance. Hidden entirely when
          empty so untouched orgs don't see a placeholder block. Markdown
          renders via the existing sanitizing renderer (same one
          intro_text uses). */}
      {topicGuidance.trim() && (
        <div className="border border-blue-100 bg-blue-50/40 rounded-xl p-4">
          <p className="text-xs font-semibold text-blue-700 uppercase tracking-wide mb-2">
            Topic guidance from your organization
          </p>
          <div
            className="prose text-sm text-[#2C3E50] leading-relaxed"
            dangerouslySetInnerHTML={{ __html: `<p>${renderMarkdown(topicGuidance)}</p>` }}
          />
        </div>
      )}

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
            <label className="block text-xs text-gray-500 mb-1">Purpose (optional)</label>
            <input
              type="text"
              value={newPurpose}
              onChange={e => setNewPurpose(e.target.value)}
              maxLength={500}
              placeholder="A short one-liner explaining what this topic is for."
              className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[var(--brand-accent)]"
            />
          </div>
          {/* Phase 59 B2 — category control hidden when the toggle is
              off (the Phase 56 surface was visible-but-unused).
              When on, dropdown from the org-defined list (B1). */}
          {categoriesEnabled && (
            <div>
              <label className="block text-xs text-gray-500 mb-1">Category (optional)</label>
              {orgCategories.length === 0 ? (
                <p className="text-xs text-gray-500 italic">
                  Your organization hasn&apos;t defined any categories yet.
                  Add some in <strong>Org Settings → Topic categories</strong>.
                </p>
              ) : (
                <select
                  value={newCategory}
                  onChange={e => setNewCategory(e.target.value)}
                  className="w-full max-w-xs px-3 py-2 border border-gray-300 rounded-lg text-sm bg-white focus:outline-none focus:ring-2 focus:ring-[var(--brand-accent)]"
                >
                  <option value="">(no category)</option>
                  {orgCategories.map(cat => (
                    <option key={cat} value={cat}>{cat}</option>
                  ))}
                </select>
              )}
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

      {/* Topics List — flat when categories are disabled, grouped by
          category (with a trailing "Uncategorized" group) when enabled.
          Toggling categories OFF does NOT clear category values on the
          rows; re-enabling restores grouping. */}
      <div className="space-y-3">
        {topics.length === 0 ? (
          <div className="text-center py-12 text-gray-400 text-sm">No topics yet. Create one to get started.</div>
        ) : categoriesEnabled && groupedTopics ? (
          groupedTopics.map(group => (
            <div key={group.label} className="space-y-2">
              <h2
                className={`text-xs font-semibold uppercase tracking-wide ${
                  group.isUncategorized ? 'text-gray-400' : 'text-gray-500'
                }`}
              >
                {group.label}
              </h2>
              {group.items.map(t => renderTopicCard(t))}
            </div>
          ))
        ) : (
          topics.map(t => renderTopicCard(t))
        )}
      </div>
    </div>
  );

  function renderTopicCard(t) {
    return (
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
              <label className="block text-xs text-gray-500 mb-1">Purpose (optional)</label>
              <input
                type="text"
                value={editPurpose}
                onChange={e => setEditPurpose(e.target.value)}
                maxLength={500}
                placeholder="A short one-liner explaining what this topic is for."
                className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[var(--brand-accent)]"
              />
            </div>
            {/* Phase 59 B2 — same hide-on-toggle-off + dropdown pattern
                as the create form. Legacy free-text values not in the
                org list are preserved with a "(not in list)" marker
                so a steward can keep them or pick from the new list. */}
            {categoriesEnabled && (
              <div>
                <label className="block text-xs text-gray-500 mb-1">Category (optional)</label>
                {(() => {
                  const isLegacy =
                    editCategory && !orgCategories.includes(editCategory);
                  if (orgCategories.length === 0 && !isLegacy) {
                    return (
                      <p className="text-xs text-gray-500 italic">
                        Your organization hasn&apos;t defined any
                        categories yet. Add some in{' '}
                        <strong>Org Settings → Topic categories</strong>.
                      </p>
                    );
                  }
                  return (
                    <select
                      value={editCategory}
                      onChange={e => setEditCategory(e.target.value)}
                      className="w-full max-w-xs px-3 py-2 border border-gray-300 rounded-lg text-sm bg-white focus:outline-none focus:ring-2 focus:ring-[var(--brand-accent)]"
                    >
                      <option value="">(no category)</option>
                      {isLegacy && (
                        <option value={editCategory}>
                          {editCategory} (not in list)
                        </option>
                      )}
                      {orgCategories.map(cat => (
                        <option key={cat} value={cat}>{cat}</option>
                      ))}
                    </select>
                  );
                })()}
              </div>
            )}
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
                {/* Phase 56 F2 — was dead `t.description` (column dropped
                    in Phase 33). Now renders the optional `purpose`
                    field as plain text (NOT via the markdown / HTML
                    renderer — XSS-safe by treating as text). */}
                {t.purpose && <p className="text-xs text-gray-400">{t.purpose}</p>}
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
                  // Phase 56 — was an out-of-date Phase 26 comment
                  // referencing `t.description` (Phase 33 dropped
                  // that column); the confirm dialog has always
                  // received `t.name` here, which remains canonical.
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
    );
  }
}

import { useCallback, useEffect, useState } from 'react';
import api from '../api';
import { useToast } from './Toast';

/**
 * Phase 9 Session 4 — Linked Deliberations picker for proposal create form.
 *
 * Renders a "Linked Deliberations" section with:
 *   - Multi-select picker over Polises in the proposal's scope (parent-org-
 *     wide + the selected sub-org's). Filters by status === 'active'.
 *   - "Create new Polis" inline mini-form (subset of the full CreatePolis:
 *     title, prompt, seed statements). On success the new Polis's id is
 *     added to the linked list automatically.
 *   - When `required` is true (org has `require_polis_for_new_proposals`
 *     resolved-true), enforces at-least-one selection via inline error; the
 *     parent form should also block submission via the `value.length === 0`
 *     check it already does for required fields.
 *
 * Props:
 *   - parentSlug: required, parent-org slug for API calls.
 *   - scopeSubOrgId: '' | sub-org id. Filters the picker dropdown to the
 *     proposal's scope (Decision 3 mirror — sub-org proposals see parent-
 *     org-wide Polises + that sub-org's; parent-wide proposals see only
 *     parent-wide Polises).
 *   - value: current `linked_polis_ids` array.
 *   - onChange(ids): called with the new array.
 *   - required: when true, surface "at least one required" validation copy.
 *
 * The "Create new" mini-form re-uses the dual-path UX shape: when
 * polis_token_configured is false it asks for the conversation_id inline.
 * For simplicity we don't render the manual-fallback success panel here —
 * we just reload the picker list and select the new Polis. Operators who
 * want the full success-panel flow (copy seed statements etc.) can use
 * the standalone /admin/polises/create page.
 */
export default function LinkedPolisesPicker({
  parentSlug,
  scopeSubOrgId,
  value,
  onChange,
  required = false,
}) {
  const toast = useToast();
  const [polises, setPolises] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);

  const ids = Array.isArray(value) ? value : [];
  const inScope = (polises || []).filter(p => {
    if (p.status !== 'active') return false;
    if (scopeSubOrgId) {
      // Sub-org-scoped proposals can link parent-wide OR own-sub-org Polises.
      return p.sub_org_id === null || p.sub_org_id === scopeSubOrgId;
    }
    // Parent-wide proposal — only parent-wide Polises.
    return p.sub_org_id === null;
  });

  const load = useCallback(async () => {
    if (!parentSlug) return;
    setLoading(true);
    try {
      const list = await api.get(`/api/orgs/${parentSlug}/polises`);
      setPolises(list || []);
    } catch {
      setPolises([]);
    } finally {
      setLoading(false);
    }
  }, [parentSlug]);

  useEffect(() => { load(); }, [load]);

  // When scope changes, drop any selections that are no longer in scope so
  // the form doesn't submit cross-scope ids the backend will reject.
  useEffect(() => {
    if (!ids.length || loading) return;
    const inScopeIds = new Set(inScope.map(p => p.id));
    const trimmed = ids.filter(id => inScopeIds.has(id));
    if (trimmed.length !== ids.length) {
      onChange(trimmed);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scopeSubOrgId, loading]);

  function toggle(polisId) {
    if (ids.includes(polisId)) {
      onChange(ids.filter(x => x !== polisId));
    } else {
      onChange([...ids, polisId]);
    }
  }

  return (
    <div className="space-y-2">
      <div className="flex items-baseline justify-between">
        <label className="block text-xs text-gray-500">
          Linked Deliberations {required && <span className="text-red-500">*</span>}
        </label>
        {!showCreate && (
          <button
            type="button"
            onClick={() => setShowCreate(true)}
            className="text-xs text-[var(--brand-accent)] hover:underline"
          >+ Create new Polis</button>
        )}
      </div>
      <p className="text-xs text-gray-400">
        Link to a deliberation for proposals where the org would benefit from
        gathering input or exploring consensus before voting.
      </p>

      {loading ? (
        <p className="text-xs text-gray-400">Loading Polises…</p>
      ) : inScope.length === 0 ? (
        <p className="text-xs text-gray-400">
          No active Polises in scope.{' '}
          {!showCreate && (
            <button
              type="button"
              onClick={() => setShowCreate(true)}
              className="text-[var(--brand-accent)] hover:underline"
            >Create one →</button>
          )}
        </p>
      ) : (
        <div className="bg-white border border-gray-200 rounded-lg max-h-48 overflow-y-auto">
          {inScope.map(p => {
            const checked = ids.includes(p.id);
            return (
              <label
                key={p.id}
                className="flex items-start gap-2 px-3 py-2 hover:bg-gray-50 cursor-pointer text-sm"
              >
                <input
                  type="checkbox"
                  checked={checked}
                  onChange={() => toggle(p.id)}
                  className="mt-0.5 accent-[var(--brand-accent)]"
                />
                <div className="flex-1 min-w-0">
                  <p className="font-medium text-gray-800 truncate">{p.title}</p>
                  <p className="text-xs text-gray-500 truncate">{p.prompt}</p>
                </div>
                {p.sub_org_id ? (
                  <span className="text-[10px] uppercase px-1.5 py-0.5 rounded bg-blue-50 text-blue-700 shrink-0">
                    sub-org
                  </span>
                ) : (
                  <span className="text-[10px] uppercase px-1.5 py-0.5 rounded bg-gray-100 text-gray-500 shrink-0">
                    org-wide
                  </span>
                )}
              </label>
            );
          })}
        </div>
      )}

      {required && ids.length === 0 && !showCreate && (
        <p className="text-xs text-red-500">
          At least one linked Polis is required by this org&apos;s settings.
        </p>
      )}

      {showCreate && (
        <InlineCreatePolis
          parentSlug={parentSlug}
          scopeSubOrgId={scopeSubOrgId || null}
          onCancel={() => setShowCreate(false)}
          onCreated={(newPolis) => {
            setShowCreate(false);
            // Add to local list and select.
            setPolises(prev => [newPolis, ...(prev || [])]);
            onChange([...(ids || []), newPolis.id]);
            toast.success('Polis created and linked');
          }}
        />
      )}
    </div>
  );
}

function InlineCreatePolis({ parentSlug, scopeSubOrgId, onCreated, onCancel }) {
  const toast = useToast();
  const [title, setTitle] = useState('');
  const [prompt, setPrompt] = useState('');
  const [seeds, setSeeds] = useState(['', '', '']);
  const [pastedConversationId, setPastedConversationId] = useState('');
  const [submitting, setSubmitting] = useState(false);

  function updateSeed(i, v) {
    setSeeds(prev => prev.map((s, j) => j === i ? v : s));
  }
  function addSeed() { setSeeds(prev => [...prev, '']); }

  async function handleSubmit() {
    if (!title.trim() || !prompt.trim()) {
      toast.error('Title and prompt are required');
      return;
    }
    setSubmitting(true);
    try {
      const trimmed = seeds.map(s => s.trim()).filter(Boolean);
      const payload = {
        title: title.trim(),
        prompt: prompt.trim(),
        seed_statements: trimmed,
      };
      if (scopeSubOrgId) payload.sub_org_id = scopeSubOrgId;
      // Manual-fallback path support: include conversation_id if pasted.
      // We optimistically include it; backend rejects with a clear 400 if
      // the token IS configured and the field is unexpected (no — server
      // ignores polis_conversation_id on the programmatic path per
      // PolisCreate docstring). Either way it's safe.
      if (pastedConversationId.trim()) {
        payload.polis_conversation_id = pastedConversationId.trim();
      }
      const res = await api.post(`/api/orgs/${parentSlug}/polises`, payload);
      if (onCreated) onCreated(res.polis);
    } catch (e) {
      toast.error(e.message || 'Failed to create Polis');
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="bg-gray-50 border border-gray-200 rounded-lg p-4 space-y-3">
      <p className="text-xs font-semibold text-gray-700">Create a new Polis</p>
      <div>
        <input
          type="text"
          value={title}
          onChange={e => setTitle(e.target.value)}
          placeholder="Title"
          className="w-full px-2 py-1.5 border border-gray-300 rounded text-sm focus:outline-none focus:ring-2 focus:ring-[var(--brand-accent)]"
        />
      </div>
      <div>
        <textarea
          value={prompt}
          onChange={e => setPrompt(e.target.value)}
          placeholder="Prompt — the central question this deliberation explores"
          rows={3}
          className="w-full px-2 py-1.5 border border-gray-300 rounded text-sm focus:outline-none focus:ring-2 focus:ring-[var(--brand-accent)] resize-none"
        />
      </div>
      <div className="space-y-1">
        <p className="text-xs text-gray-500">Seed statements (optional — 10–15 recommended for full clustering)</p>
        {seeds.map((s, i) => (
          <input
            key={i}
            type="text"
            value={s}
            onChange={e => updateSeed(i, e.target.value)}
            placeholder={`Statement ${i + 1}`}
            maxLength={997}
            className="w-full px-2 py-1.5 border border-gray-300 rounded text-sm focus:outline-none focus:ring-2 focus:ring-[var(--brand-accent)]"
          />
        ))}
        <button
          type="button"
          onClick={addSeed}
          className="text-xs text-[var(--brand-accent)] hover:underline"
        >+ Add statement</button>
      </div>
      <div>
        <input
          type="text"
          value={pastedConversationId}
          onChange={e => setPastedConversationId(e.target.value)}
          placeholder="conversation_id (manual-fallback only — paste from pol.is/admin)"
          maxLength={300}
          className="w-full px-2 py-1.5 border border-gray-300 rounded text-sm focus:outline-none focus:ring-2 focus:ring-[var(--brand-accent)]"
        />
        <p className="text-[10px] text-gray-400 mt-1">
          Leave empty if your platform has the pol.is API token configured.
        </p>
      </div>
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={handleSubmit}
          disabled={submitting || !title.trim() || !prompt.trim()}
          className="text-xs px-3 py-1.5 bg-[var(--brand-primary)] text-white rounded-lg hover:bg-[var(--brand-accent)] disabled:opacity-50"
        >
          {submitting ? 'Creating…' : 'Create & link'}
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="text-xs px-3 py-1.5 border border-gray-300 text-gray-600 rounded-lg hover:bg-gray-50"
        >
          Cancel
        </button>
      </div>
    </div>
  );
}

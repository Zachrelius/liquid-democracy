import { useState, useEffect, useCallback } from 'react';
import api from '../api';
import { useToast } from './Toast';
import { useConfirm } from './ConfirmDialog';
import { useHasPermission } from '../hooks/useHasPermission';

/**
 * DistributionRules — Phase 90a member-visible + admin-managed rules card.
 *
 * All members see the standing rules (read-only). Holders of
 * member.set_voting_weight get create + pause/resume/delete controls.
 */
function ruleSummary(r, unit) {
  const cadence = r.interval_months % 12 === 0 && r.interval_months >= 12
    ? `every ${r.interval_months / 12} year${r.interval_months === 12 ? '' : 's'}`
    : `every ${r.interval_months} month${r.interval_months === 1 ? '' : 's'}`;
  const target = r.targeting_mode === 'all_members'
    ? 'all members'
    : r.targeting_mode === 'titles_include'
      ? 'members with selected titles'
      : 'all members except selected titles';
  const mode = r.schedule_mode === 'anniversary'
    ? 'on each member\'s own anniversary'
    : 'on a fixed schedule';
  return `${r.amount} ${unit} ${cadence}, ${mode}, to ${target}`;
}

export default function DistributionRules({ slug, unit }) {
  const toast = useToast();
  const confirm = useConfirm();
  const canManage = useHasPermission('member.set_voting_weight');
  const [rules, setRules] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [form, setForm] = useState({
    amount: 10, interval_value: 1, interval_unit: 'years',
    schedule_mode: 'anniversary', targeting_mode: 'all_members',
    title_ids: [],
  });
  const [titles, setTitles] = useState([]);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    if (!slug) return;
    setLoading(true);
    try {
      setRules(await api.get(`/api/orgs/${slug}/share-distribution-rules`));
    } catch {
      /* non-fatal */
    } finally {
      setLoading(false);
    }
  }, [slug]);

  useEffect(() => { load(); }, [load]);

  // Load titles lazily when the admin opens the create form (for targeting).
  useEffect(() => {
    if (showCreate && canManage && titles.length === 0) {
      api.get(`/api/orgs/${slug}/titles`).then(setTitles).catch(() => {});
    }
  }, [showCreate, canManage, slug, titles.length]);

  function toggleTitle(id) {
    setForm(f => ({
      ...f,
      title_ids: f.title_ids.includes(id)
        ? f.title_ids.filter(t => t !== id)
        : [...f.title_ids, id],
    }));
  }

  async function createRule() {
    setSaving(true);
    try {
      const interval_months = form.interval_unit === 'years'
        ? Number(form.interval_value) * 12
        : Number(form.interval_value);
      await api.post(`/api/orgs/${slug}/share-distribution-rules`, {
        amount: Number(form.amount),
        interval_months,
        schedule_mode: form.schedule_mode,
        targeting_mode: form.targeting_mode,
        title_ids: form.targeting_mode === 'all_members' ? [] : form.title_ids,
      });
      toast.success('Distribution rule created');
      setShowCreate(false);
      load();
    } catch (e) {
      toast.error(e.message || 'Failed to create rule');
    } finally {
      setSaving(false);
    }
  }

  async function toggleStatus(r) {
    const action = r.status === 'active' ? 'pause' : 'resume';
    try {
      await api.post(`/api/orgs/${slug}/share-distribution-rules/${r.id}/${action}`);
      load();
    } catch (e) {
      toast.error(e.message);
    }
  }

  async function remove(r) {
    const ok = await confirm({
      title: 'Delete distribution rule?',
      message: 'This stops future grants from this rule. Shares already granted are kept.',
      destructive: true,
    });
    if (!ok) return;
    try {
      await api.delete(`/api/orgs/${slug}/share-distribution-rules/${r.id}`);
      load();
    } catch (e) {
      toast.error(e.message);
    }
  }

  if (loading) return null;
  if (rules.length === 0 && !canManage) return null;

  return (
    <div className="bg-white border border-gray-200 rounded-xl p-4 mb-6">
      <div className="flex items-center justify-between mb-2">
        <h2 className="text-sm font-semibold text-gray-700">Distribution rules</h2>
        {canManage && (
          <button
            onClick={() => setShowCreate(v => !v)}
            className="text-xs px-3 py-1 border border-[var(--brand-accent)] text-[var(--brand-accent)] rounded-lg hover:bg-[var(--brand-accent)] hover:text-white transition-colors"
          >
            {showCreate ? 'Cancel' : 'New rule'}
          </button>
        )}
      </div>

      {rules.length === 0 ? (
        <p className="text-xs text-gray-400">No automatic distribution rules.</p>
      ) : (
        <ul className="space-y-2">
          {rules.map(r => (
            <li key={r.id} className="flex items-start justify-between gap-3 text-sm">
              <span className="text-gray-700">
                {ruleSummary(r, unit)}
                {r.status === 'paused' && <span className="text-xs text-amber-600 ml-1">(paused)</span>}
              </span>
              {canManage && (
                <span className="flex gap-2 shrink-0">
                  <button onClick={() => toggleStatus(r)} className="text-xs text-gray-500 hover:text-gray-800">
                    {r.status === 'active' ? 'Pause' : 'Resume'}
                  </button>
                  <button onClick={() => remove(r)} className="text-xs text-red-500 hover:text-red-700">
                    Delete
                  </button>
                </span>
              )}
            </li>
          ))}
        </ul>
      )}

      {showCreate && canManage && (
        <div className="mt-3 pt-3 border-t border-gray-100 space-y-2 text-sm">
          <div className="flex items-center gap-2 flex-wrap">
            <label className="text-xs text-gray-600">Grant</label>
            <input type="number" min="1" value={form.amount}
              onChange={e => setForm(f => ({ ...f, amount: e.target.value }))}
              className="w-20 border border-gray-300 rounded px-2 py-1" />
            <span className="text-xs text-gray-600">{unit} every</span>
            <input type="number" min="1" value={form.interval_value}
              onChange={e => setForm(f => ({ ...f, interval_value: e.target.value }))}
              className="w-16 border border-gray-300 rounded px-2 py-1" />
            <select value={form.interval_unit}
              onChange={e => setForm(f => ({ ...f, interval_unit: e.target.value }))}
              className="border border-gray-300 rounded px-2 py-1 text-xs">
              <option value="months">months</option>
              <option value="years">years</option>
            </select>
          </div>
          <div className="flex items-center gap-2 flex-wrap">
            <label className="text-xs text-gray-600">Schedule</label>
            <select value={form.schedule_mode}
              onChange={e => setForm(f => ({ ...f, schedule_mode: e.target.value }))}
              className="border border-gray-300 rounded px-2 py-1 text-xs">
              <option value="anniversary">Each member's own anniversary</option>
              <option value="fixed_cadence">Fixed schedule for everyone</option>
            </select>
            <label className="text-xs text-gray-600 ml-2">Who</label>
            <select value={form.targeting_mode}
              onChange={e => setForm(f => ({ ...f, targeting_mode: e.target.value }))}
              className="border border-gray-300 rounded px-2 py-1 text-xs">
              <option value="all_members">All members</option>
              <option value="titles_include">Only these titles</option>
              <option value="titles_exclude">Everyone except these titles</option>
            </select>
          </div>
          {form.targeting_mode !== 'all_members' && (
            <div className="flex flex-wrap gap-2 pl-1">
              {titles.length === 0 && <span className="text-xs text-gray-400">No titles defined.</span>}
              {titles.map(t => (
                <label key={t.id} className="flex items-center gap-1 text-xs text-gray-600">
                  <input type="checkbox" checked={form.title_ids.includes(t.id)}
                    onChange={() => toggleTitle(t.id)} className="accent-[var(--brand-accent)]" />
                  {t.name}
                </label>
              ))}
            </div>
          )}
          <p className="text-xs text-gray-400">
            Anniversary mode grants each member on the anniversary of their share start date.
            Fixed mode grants everyone together on the rule's cadence. Missed periods (from downtime)
            catch up on the next run.
          </p>
          <button onClick={createRule} disabled={saving}
            className="text-xs px-3 py-1.5 bg-[var(--brand-primary)] text-white rounded-lg hover:bg-[var(--brand-accent)] disabled:opacity-50">
            {saving ? 'Creating...' : 'Create rule'}
          </button>
        </div>
      )}
    </div>
  );
}

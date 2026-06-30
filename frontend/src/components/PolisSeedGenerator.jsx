import { useState } from 'react';
import api from '../api';
import { useToast } from './Toast';
import { useConfirm } from './ConfirmDialog';

/**
 * Phase 82 C1 — pol.is seed-statement generator + editable list + CSV download.
 *
 * Stateless w.r.t. the server: generation drafts statements (Sonnet) into an
 * editable list the admin reviews/edits/extends; "Download CSV" serializes the
 * list to pol.is's native import shape (a `comment_text` header + one quoted
 * statement per row) which the admin uploads on pol.is themselves. Nothing is
 * persisted on the platform.
 *
 * The list is usable with zero generations — an admin can add rows and type
 * their own. Generation is an accelerator, not a dependency. The Generate
 * controls hide if the platform reports AI generation is unconfigured (503).
 *
 * Props: { topic, description, slug } — topic/description come from live
 * create-form state OR a saved Polis record (same component, two sources).
 */
export default function PolisSeedGenerator({ topic = '', description = '', slug }) {
  const toast = useToast();
  const confirm = useConfirm();
  const [statements, setStatements] = useState([]);
  const [steer, setSteer] = useState('');
  const [includeOrgDescription, setIncludeOrgDescription] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [warning, setWarning] = useState('');
  const [aiUnavailable, setAiUnavailable] = useState(false);

  const nonEmpty = statements.map(s => s.trim()).filter(Boolean);

  async function callGenerate() {
    setGenerating(true);
    setWarning('');
    try {
      const res = await api.post(
        `/api/orgs/${slug}/polises/seed-statements/generate`,
        {
          topic: topic || '',
          description: description || '',
          steer: steer.trim(),
          include_org_description: includeOrgDescription,
        },
      );
      if (res.warning) setWarning(res.warning);
      return Array.isArray(res.statements) ? res.statements : [];
    } catch (e) {
      if (e.status === 503) {
        setAiUnavailable(true);
        toast.info('AI seed generation isn\'t configured — you can still add statements manually.');
      } else {
        toast.error(e.message || 'Generation failed');
      }
      return null;
    } finally {
      setGenerating(false);
    }
  }

  async function handleGenerate() {
    // Replace the list. Confirm if there are existing statements.
    if (nonEmpty.length > 0) {
      const ok = await confirm({
        title: 'Replace current statements?',
        message: 'Regenerating replaces the current list with a fresh draft.',
      });
      if (!ok) return;
    }
    const out = await callGenerate();
    if (out !== null) setStatements(out);
  }

  async function handleAddMore() {
    const out = await callGenerate();
    if (out !== null && out.length) {
      // Append, skipping exact duplicates already in the list.
      setStatements(prev => {
        const seen = new Set(prev.map(s => s.trim()));
        const fresh = out.filter(s => !seen.has(s.trim()));
        return [...prev, ...fresh];
      });
    }
  }

  function updateRow(i, v) {
    setStatements(prev => prev.map((s, j) => (j === i ? v : s)));
  }
  function removeRow(i) {
    setStatements(prev => prev.filter((_, j) => j !== i));
  }
  function addRow() {
    setStatements(prev => [...prev, '']);
  }

  function downloadCsv() {
    // Trim, drop empties, de-dupe (exact, order-preserving).
    const seen = new Set();
    const rows = [];
    for (const s of statements) {
      const t = s.trim();
      if (!t || seen.has(t)) continue;
      seen.add(t);
      rows.push(t);
    }
    if (rows.length === 0) {
      toast.error('Add at least one statement first.');
      return;
    }
    // pol.is import format: a `comment_text` header, one statement per row,
    // with real CSV quoting for commas / quotes / newlines.
    const esc = (v) => (/[",\n\r]/.test(v) ? `"${v.replace(/"/g, '""')}"` : v);
    const csv = ['comment_text', ...rows.map(esc)].join('\r\n') + '\r\n';
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' });
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'polis_seed_statements.csv';
    document.body.appendChild(a);
    a.click();
    a.remove();
    window.URL.revokeObjectURL(url);
    toast.success(`Downloaded ${rows.length} statement${rows.length === 1 ? '' : 's'}`);
  }

  const hasList = statements.length > 0;

  return (
    <div className="bg-gray-50 border border-gray-200 rounded-xl p-5 space-y-4">
      <div>
        <h3 className="text-sm font-semibold text-gray-700">Seed statements</h3>
        <p className="text-xs text-gray-500 mt-1">
          Draft a set of agree/disagree statements for your pol.is conversation,
          then download them as a CSV to upload on pol.is. You can also add your
          own.
        </p>
      </div>

      {!aiUnavailable && (
        <div className="space-y-2">
          <input
            type="text"
            value={steer}
            onChange={e => setSteer(e.target.value)}
            maxLength={2000}
            placeholder="Optional: steer the statements (e.g. 'make sure pro- and anti-development views are both represented')"
            className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[var(--brand-accent)]"
          />
          <label className="flex items-center gap-2 text-xs text-gray-600 cursor-pointer">
            <input
              type="checkbox"
              checked={includeOrgDescription}
              onChange={e => setIncludeOrgDescription(e.target.checked)}
              className="accent-[var(--brand-accent)]"
            />
            Include our organization&apos;s description for context
          </label>
          <div className="flex flex-wrap gap-2">
            {!hasList ? (
              <button
                type="button"
                onClick={handleGenerate}
                disabled={generating}
                className="text-sm px-4 py-2 bg-[var(--brand-primary)] text-white rounded-lg hover:bg-[var(--brand-accent)] disabled:opacity-50"
              >
                {generating ? 'Generating…' : 'Generate seed statements'}
              </button>
            ) : (
              <>
                <button
                  type="button"
                  onClick={handleAddMore}
                  disabled={generating}
                  className="text-sm px-3 py-1.5 bg-[var(--brand-primary)] text-white rounded-lg hover:bg-[var(--brand-accent)] disabled:opacity-50"
                >
                  {generating ? 'Working…' : 'Add more'}
                </button>
                <button
                  type="button"
                  onClick={handleGenerate}
                  disabled={generating}
                  className="text-sm px-3 py-1.5 border border-gray-300 text-gray-700 rounded-lg hover:bg-gray-50 disabled:opacity-50"
                >
                  Regenerate
                </button>
              </>
            )}
          </div>
        </div>
      )}

      {warning && (
        <p className="text-xs text-amber-600">{warning}</p>
      )}

      {/* Editable list */}
      {hasList && (
        <div className="space-y-2">
          {statements.map((s, i) => (
            <div key={i} className="flex items-start gap-2">
              <span className="text-xs text-gray-400 mt-2 w-6 text-right shrink-0">{i + 1}.</span>
              <input
                type="text"
                value={s}
                onChange={e => updateRow(i, e.target.value)}
                placeholder={`Statement ${i + 1}`}
                className="flex-1 px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[var(--brand-accent)]"
              />
              <button
                type="button"
                onClick={() => removeRow(i)}
                className="text-xs text-red-500 hover:underline mt-2 shrink-0"
                title="Remove this statement"
              >remove</button>
            </div>
          ))}
        </div>
      )}

      <button
        type="button"
        onClick={addRow}
        className="text-xs text-[var(--brand-accent)] hover:underline"
      >+ Add a statement</button>

      <div className="border-t border-gray-200 pt-3 space-y-1">
        <button
          type="button"
          onClick={downloadCsv}
          disabled={nonEmpty.length === 0}
          className="text-sm px-4 py-2 border border-gray-300 text-gray-700 rounded-lg hover:bg-gray-50 disabled:opacity-50"
        >
          Download CSV
        </button>
        <p className="text-xs text-gray-400">
          Upload this CSV in your pol.is conversation&apos;s admin page (Comments → seed).
        </p>
      </div>
    </div>
  );
}

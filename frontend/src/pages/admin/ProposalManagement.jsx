import { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { useOrg } from '../../OrgContext';
import api from '../../api';
import StatusBadge from '../../components/StatusBadge';
import { useToast } from '../../components/Toast';
import { useConfirm } from '../../components/ConfirmDialog';
import LinkedPolisesPicker from '../../components/LinkedPolisesPicker';
// Phase 56 F3 — markdown renderer reused for the topic-guidance hint in
// the proposal-creation topic picker.
import renderMarkdown from '../../utils/renderMarkdown';
import { unitInputSymbol } from '../../utils/budgetFormat';
import {
  aggregateBulkAdvanceResponses,
  bulkAdvanceSummaryMessage,
  chunkProposalIds,
  visibleDraftProposalIds,
} from '../../utils/bulkDeliberation';
import {
  createProposalRowsSequentially,
  proposalImportRateLimitMessage,
  proposalImportSelectionState,
} from '../../utils/proposalImportBatch';
// Phase 12.5 F2 — per-control permission gating.
import { useHasPermission } from '../../hooks/useHasPermission';
// Phase 52 Stage 1 — shared verification state label tables.
import { VERIFICATION_STATE_OPTIONS } from '../../verificationLabels';
// Multi-winner approval selection — shared preset detection, payload
// builder, validation, and plain-language phrasing (also used by the
// results panel so the copy matches end to end).
import {
  SINGLE_WINNER_SUMMARY,
  detectApprovalWinnerPreset,
  buildApprovalWinnerConfig,
  validateApprovalWinnerSelection,
  describeApprovalWinnerRule,
} from '../../utils/approvalWinnerConfig';

// Phase 16 F1 — format a day-count for display. Whole numbers render as
// integers ("3 days"); fractional values keep up to two decimal places so
// 0.05 renders as "0.05" rather than "0.0500" or "5e-2". Trailing zeros
// stripped so 0.50 → "0.5".
function formatDays(value) {
  if (value === null || value === undefined || Number.isNaN(value)) return '?';
  const n = Number(value);
  if (Number.isInteger(n)) return String(n);
  // Two decimal places is enough for the 0.05 floor; trim trailing zeros.
  return n.toFixed(2).replace(/\.?0+$/, '');
}

function pluralizeDays(value) {
  // Spec line 224 example uses "day(s)"; we render "day"/"days" based on
  // the numeric value (1 day, 2 days, 0.5 days, 0 days).
  return Number(value) === 1 ? 'day' : 'days';
}

function OptionsEditor({ options, onChange, budgetCeilings = false, unitSymbol = '$' }) {
  function updateOption(idx, field, value) {
    const updated = options.map((o, i) => i === idx ? { ...o, [field]: value } : o);
    onChange(updated);
  }

  function addOption() {
    if (options.length >= 20) return;
    onChange([...options, { label: '', description: '', budgetMaxAmount: '' }]);
  }

  function removeOption(idx) {
    onChange(options.filter((_, i) => i !== idx));
  }

  function moveOption(idx, direction) {
    const newIdx = idx + direction;
    if (newIdx < 0 || newIdx >= options.length) return;
    const updated = [...options];
    [updated[idx], updated[newIdx]] = [updated[newIdx], updated[idx]];
    onChange(updated);
  }

  // Check for duplicate labels (case-insensitive)
  const labelCounts = {};
  options.forEach(o => {
    const key = o.label.trim().toLowerCase();
    if (key) labelCounts[key] = (labelCounts[key] || 0) + 1;
  });

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <label className="block text-xs text-gray-500">
          {budgetCeilings ? 'Buckets' : 'Options'} ({options.length}/20)
          {options.length < 2 && <span className="text-amber-600 ml-2">Minimum 2 required</span>}
        </label>
        <button
          type="button"
          onClick={addOption}
          disabled={options.length >= 20}
          className="text-xs px-3 py-1 bg-[var(--brand-accent)] text-white rounded-lg hover:bg-[var(--brand-primary)] transition-colors disabled:opacity-50"
        >
          Add Option
        </button>
      </div>
      {options.map((opt, idx) => {
        const isDuplicate = opt.label.trim() && labelCounts[opt.label.trim().toLowerCase()] > 1;
        return (
          <fieldset key={idx} className="bg-gray-50 border border-gray-200 rounded-lg p-3 space-y-2">
            <legend className="sr-only">Option {idx + 1}</legend>
            <div className="flex items-center gap-2">
              <span className="text-xs text-gray-400 w-6">{idx + 1}.</span>
              <label htmlFor={`proposal-option-${idx}-label`} className="sr-only">Option {idx + 1} label</label>
              <input
                id={`proposal-option-${idx}-label`}
                type="text"
                value={opt.label}
                onChange={e => updateOption(idx, 'label', e.target.value)}
                placeholder="Option label (required)"
                maxLength={200}
                aria-invalid={isDuplicate || undefined}
                aria-describedby={isDuplicate ? `proposal-option-${idx}-error` : undefined}
                className={`flex-1 px-2 py-1.5 border rounded text-sm focus:outline-none focus:ring-2 focus:ring-[var(--brand-accent)] ${isDuplicate ? 'border-red-400' : 'border-gray-300'}`}
              />
              <div className="flex gap-1">
                <button type="button" onClick={() => moveOption(idx, -1)} disabled={idx === 0}
                  aria-label={`Move option ${idx + 1} up`}
                  className="min-w-8 min-h-8 text-gray-500 hover:text-gray-700 disabled:opacity-30 text-xs">
                  &#x25b2;
                </button>
                <button type="button" onClick={() => moveOption(idx, 1)} disabled={idx === options.length - 1}
                  aria-label={`Move option ${idx + 1} down`}
                  className="min-w-8 min-h-8 text-gray-500 hover:text-gray-700 disabled:opacity-30 text-xs">
                  &#x25bc;
                </button>
              </div>
              <button type="button" onClick={() => removeOption(idx)}
                aria-label={`Remove option ${idx + 1}`}
                className="min-w-8 min-h-8 text-red-500 hover:text-red-700 text-sm">
                &#x2715;
              </button>
            </div>
            {isDuplicate && <p id={`proposal-option-${idx}-error`} role="alert" className="text-xs text-red-600 ml-8">Duplicate label</p>}
            <label htmlFor={`proposal-option-${idx}-description`} className="sr-only">Option {idx + 1} description (optional)</label>
            <textarea
              id={`proposal-option-${idx}-description`}
              value={opt.description}
              onChange={e => updateOption(idx, 'description', e.target.value)}
              placeholder="Description (optional)"
              maxLength={2000}
              rows={2}
              className="w-full ml-8 px-2 py-1.5 border border-gray-300 rounded text-xs focus:outline-none focus:ring-2 focus:ring-[var(--brand-accent)] resize-none"
              style={{ width: 'calc(100% - 2rem)' }}
            />
            {/* Phase 73 — optional per-bucket ceiling for budget proposals. */}
            {budgetCeilings && (
              <div className="ml-8 flex items-center gap-2 text-xs text-gray-500">
                <label htmlFor={`proposal-option-${idx}-ceiling`}>Ceiling (optional):</label>
                {unitSymbol && <span className="text-gray-400">{unitSymbol}</span>}
                <input
                  id={`proposal-option-${idx}-ceiling`}
                  type="number" min="0" step="1"
                  value={opt.budgetMaxAmount ?? ''}
                  onChange={e => updateOption(idx, 'budgetMaxAmount', e.target.value)}
                  placeholder="no limit"
                  className="w-32 px-2 py-1 border border-gray-300 rounded text-xs focus:outline-none focus:ring-2 focus:ring-[var(--brand-accent)]"
                />
              </div>
            )}
          </fieldset>
        );
      })}
    </div>
  );
}

// Phase 74b — project-budget item editor. Each item has a kind (discrete /
// continuous-as-discrete / tier_parent). Tier parents carry no cost of their
// own; a nested sub-editor adds tier variants (label + cost) + a fallback
// toggle. Emits items in the shape the create payload maps to options.
function ProjectItemsEditor({ items, onChange, unitSymbol = '$' }) {
  function patch(idx, field, value) {
    onChange(items.map((it, i) => (i === idx ? { ...it, [field]: value } : it)));
  }
  function addItem() {
    if (items.length >= 20) return;
    onChange([...items, { label: '', kind: 'discrete', cost: '', tiers: [], fallback: true }]);
  }
  function removeItem(idx) {
    onChange(items.filter((_, i) => i !== idx));
  }
  function patchTier(idx, ti, field, value) {
    const tiers = items[idx].tiers.map((t, j) => (j === ti ? { ...t, [field]: value } : t));
    patch(idx, 'tiers', tiers);
  }
  function addTier(idx) {
    patch(idx, 'tiers', [...(items[idx].tiers || []), { label: '', cost: '' }]);
  }
  function removeTier(idx, ti) {
    patch(idx, 'tiers', items[idx].tiers.filter((_, j) => j !== ti));
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <label className="block text-xs text-gray-500">Projects ({items.length}/20)
          {items.length < 2 && <span className="text-amber-600 ml-2">Minimum 2 required</span>}
        </label>
        <button type="button" onClick={addItem} disabled={items.length >= 20}
          className="text-xs px-3 py-1 bg-[var(--brand-accent)] text-white rounded-lg hover:bg-[var(--brand-primary)] transition-colors disabled:opacity-50">
          Add Project
        </button>
      </div>
      {items.map((it, idx) => (
        <div key={idx} className="bg-gray-50 border border-gray-200 rounded-lg p-3 space-y-2">
          <div className="flex items-center gap-2">
            <span className="text-xs text-gray-400 w-6">{idx + 1}.</span>
            <input type="text" value={it.label}
              onChange={e => patch(idx, 'label', e.target.value)}
              placeholder="Project name (required)" maxLength={200}
              className="flex-1 px-2 py-1.5 border border-gray-300 rounded text-sm focus:outline-none focus:ring-2 focus:ring-[var(--brand-accent)]" />
            <select value={it.kind} onChange={e => patch(idx, 'kind', e.target.value)}
              className="text-xs border border-gray-300 rounded px-1.5 py-1">
              <option value="discrete">Fixed cost</option>
              <option value="continuous-as-discrete">Continuous (fund fully or not at all)</option>
              <option value="tier_parent">Tiered variants</option>
            </select>
            <button type="button" onClick={() => removeItem(idx)}
              className="text-red-400 hover:text-red-600 text-sm px-1">✕</button>
          </div>
          {it.kind === 'tier_parent' ? (
            <div className="ml-8 space-y-1">
              <p className="text-xs text-gray-500">Tier variants (pick at most one when voting):</p>
              {(it.tiers || []).map((t, ti) => (
                <div key={ti} className="flex items-center gap-2">
                  <input type="text" value={t.label}
                    onChange={e => patchTier(idx, ti, 'label', e.target.value)}
                    placeholder="Variant (e.g. 6ft pool)" maxLength={200}
                    className="flex-1 px-2 py-1 border border-gray-300 rounded text-xs" />
                  {unitSymbol && <span className="text-gray-400 text-xs">{unitSymbol}</span>}
                  <input type="number" min="1" value={t.cost}
                    onChange={e => patchTier(idx, ti, 'cost', e.target.value)}
                    placeholder="cost" className="w-28 px-2 py-1 border border-gray-300 rounded text-xs" />
                  <button type="button" onClick={() => removeTier(idx, ti)}
                    className="text-red-400 hover:text-red-600 text-xs px-1">✕</button>
                </div>
              ))}
              <div className="flex items-center gap-3">
                <button type="button" onClick={() => addTier(idx)}
                  className="text-xs text-[var(--brand-accent)] hover:underline">+ Add variant</button>
                <label className="flex items-center gap-1 text-xs text-gray-600">
                  <input type="checkbox" checked={it.fallback !== false}
                    onChange={e => patch(idx, 'fallback', e.target.checked)}
                    className="accent-[var(--brand-accent)]" />
                  Fall back to a cheaper variant if the preferred one doesn’t fit
                </label>
              </div>
            </div>
          ) : (
            <div className="ml-8 flex items-center gap-2 text-xs text-gray-600">
              <span>{it.kind === 'continuous-as-discrete' ? 'Full amount:' : 'Cost:'}</span>
              {unitSymbol && <span className="text-gray-400">{unitSymbol}</span>}
              <input type="number" min="1" value={it.cost}
                onChange={e => patch(idx, 'cost', e.target.value)}
                placeholder="cost when funded"
                className="w-32 px-2 py-1 border border-gray-300 rounded text-xs" />
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

// Phase 56 F3 — collapsible org-guidance hint shown above the
// topic-picker. Hidden entirely when the org hasn't set any guidance,
// so untouched orgs see no change. Default-collapsed to keep the
// already-busy proposal form lean; one click opens the markdown body.
function TopicGuidanceHint({ guidance }) {
  const [open, setOpen] = useState(false);
  const trimmed = (guidance || '').trim();
  if (!trimmed) return null;
  return (
    <div className="mb-3 border border-blue-100 bg-blue-50/40 rounded-lg">
      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        className="w-full px-3 py-2 flex items-center justify-between text-xs font-medium text-blue-800 hover:bg-blue-50/70 rounded-lg"
      >
        <span>Topic guidance from your organization</span>
        <span className="text-blue-500">{open ? '−' : '+'}</span>
      </button>
      {open && (
        <div
          className="prose text-xs text-[#2C3E50] leading-relaxed px-3 pb-3"
          dangerouslySetInnerHTML={{ __html: `<p>${renderMarkdown(trimmed)}</p>` }}
        />
      )}
    </div>
  );
}

// Phase 56 F4 — proposal-creation topic picker, optionally grouped by
// category when the org has `settings.topic_categories_enabled` on.
// When the toggle is off, renders the flat list with the same shape
// as the pre-Phase-56 picker (the spec's "no visible change for orgs
// that don't opt in" guarantee).
function TopicPickerList({
  topics,
  categoriesEnabled,
  selectedTopics,
  onToggle,
  onRelevance,
}) {
  const grouped = useMemo(() => {
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

  function renderTopicRow(t) {
    const sel = selectedTopics.find(s => s.topic_id === t.id);
    return (
      <div key={t.id} className="flex items-center gap-3">
        <label className="flex items-center gap-2 cursor-pointer">
          <input
            type="checkbox"
            checked={!!sel}
            onChange={() => onToggle(t.id)}
            className="accent-[var(--brand-accent)]"
          />
          <span
            className="inline-block w-3 h-3 rounded-full"
            style={{ backgroundColor: t.color }}
          />
          <span className="text-sm text-gray-700">{t.name}</span>
          {t.sub_org_id && (
            <span className="text-[10px] uppercase text-blue-600">scoped</span>
          )}
          {/* Phase 56 F2 — surface the purpose as a small subtitle so
              the picker tells members what a topic is for. Plain text. */}
          {t.purpose && (
            <span className="text-xs text-gray-400">— {t.purpose}</span>
          )}
        </label>
        {sel && (
          <div className="flex items-center gap-2 ml-4">
            <span className="text-xs text-gray-400">Relevance:</span>
            <input
              type="range"
              min={0}
              max={100}
              value={Math.round(sel.relevance * 100)}
              onChange={e => onRelevance(t.id, parseInt(e.target.value) / 100)}
              className="w-24 accent-[var(--brand-accent)]"
            />
            <span className="text-xs text-gray-500 w-8">{Math.round(sel.relevance * 100)}%</span>
          </div>
        )}
      </div>
    );
  }

  if (categoriesEnabled && grouped) {
    return (
      <div className="space-y-3">
        {grouped.map(group => (
          <div key={group.label} className="space-y-1.5">
            <p
              className={`text-[11px] font-semibold uppercase tracking-wide ${
                group.isUncategorized ? 'text-gray-400' : 'text-gray-500'
              }`}
            >
              {group.label}
            </p>
            <div className="space-y-2 pl-1">
              {group.items.map(renderTopicRow)}
            </div>
          </div>
        ))}
      </div>
    );
  }
  return <div className="space-y-2">{topics.map(renderTopicRow)}</div>;
}

// Phase 62 A1 — CreateProposalForm doubles as the draft-edit form when
// `editingProposal` is supplied. In edit mode it prefills every editable
// field from the proposal, PATCHes /api/proposals/{id} on submit, and
// labels the submit button "Save Changes". Create-mode behavior is
// unchanged when `editingProposal` is null/undefined. The full editable
// field set matches the create payload modulo `sub_org_id` and
// `linked_polis_ids` — both are deliberately not editable post-creation
// in this pass (scope is structural; linked Polises are a structural
// link, and changing either has broader implications beyond the draft).
// Phase 76a — optional display unit for budget amounts. Free text stored in
// budget_config.currency; blank means "$" (USD). Purely cosmetic — never
// affects tally math. Shared by the allocation + project budget config blocks.
function BudgetUnitField({ value, onChange }) {
  return (
    <div>
      <label className="block text-xs text-gray-500 mb-1">Unit (optional)</label>
      <input
        type="text"
        value={value}
        onChange={e => onChange(e.target.value)}
        placeholder="$ (default) — e.g. pesos, credits, thousand, €"
        maxLength={24}
        className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[var(--brand-accent)]"
      />
      <p className="text-xs text-gray-400 mt-1">
        How amounts are labeled. Short symbols ($, €) sit before the number;
        words (“pesos”, “credits”) sit after. Display only — doesn’t change any math.
      </p>
    </div>
  );
}

function CreateProposalForm({
  slug,
  orgSettings,
  topics,
  subOrgs,
  onCreated,
  onCancel,
  editingProposal = null,
  // Phase 62 A3 — optional hard-delete callback surfaced in edit mode.
  // When supplied, a "Delete draft" button is rendered alongside Save
  // + Cancel. Caller is responsible for the API DELETE + navigation;
  // see ProposalDetail.jsx for the canonical wiring.
  onDelete = null,
  // Advance-to-next-phase callback surfaced in edit mode alongside Save +
  // Cancel + Delete. When supplied (parent gates on the proposal's
  // can_advance flag), an "Advance to {next}" button is rendered in the
  // footer so an author can move a draft into deliberation without leaving
  // the editor. advanceLabel is the button text; advancing is the in-flight
  // disabled state. The parent owns the confirm dialog + API call; see
  // ProposalDetail.jsx for the canonical wiring.
  onAdvance = null,
  advanceLabel = null,
  advancing = false,
  // Phase 72 — when an import file carries 2+ proposals, the form hands the
  // per-item preview results up to the parent to render the review list
  // instead of prefilling a single proposal. Create-mode only.
  onMultiImport = null,
}) {
  const isEditMode = !!editingProposal;
  const toast = useToast();
  const confirm = useConfirm();
  // Cluster B (49a) — creation-flow awareness. The legacy 3-way
  // proposal_creation_mode collapsed into permission + toggle:
  // members lacking ``proposal.create`` can still file a petition
  // when ``allow_cosign_petition`` is on. Surface advisory copy so
  // those members know their proposal will gather signatures before
  // going to a vote.
  const { currentOrg } = useOrg();
  const cosignPetitionAllowed = !!currentOrg?.allow_cosign_petition;
  const canCreateDirectly = useHasPermission('proposal.create');
  const showCosignAdvisory = cosignPetitionAllowed && !canCreateDirectly;
  const cosignCfg = currentOrg?.settings?.cosign || {};
  const cosignThreshold = cosignCfg.threshold ?? 3;
  const cosignWindowHours = cosignCfg.expiry_hours ?? 168;
  const cosignWindowDays = Math.round(cosignWindowHours / 24);
  // Phase 12.5 F3 — threshold inputs are gated on `proposal.set_thresholds`.
  // Members granted `proposal.create` but not `proposal.set_thresholds` see
  // the form WITHOUT threshold inputs; the backend (Cluster B3) applies
  // org defaults. The form simply omits pass_threshold/quorum_threshold
  // from the POST payload in that case.
  const canSetThresholds = useHasPermission('proposal.set_thresholds');
  // Phase 16 F1 — duration inputs are gated on `proposal.set_durations`.
  // Same shape as Phase 12.5 thresholds: members without the permission see
  // a read-only display of the org defaults; members with it see editable
  // number inputs (deliberation integer days, voting fractional days with
  // a 0.05 floor / 0.05 step for live-poll use cases).
  const canSetDurations = useHasPermission('proposal.set_durations');
  // Phase 62 A1 — prefill from editingProposal when in edit mode. Fall
  // back to create-mode defaults otherwise. Lazy-init so we read the
  // proposal once on mount; subsequent updates to editingProposal would
  // require a key= on the form (we never re-prefill mid-edit).
  const [title, setTitle] = useState(() => (isEditMode ? (editingProposal.title ?? '') : ''));
  const [body, setBody] = useState(() => (isEditMode ? (editingProposal.body ?? '') : ''));
  const [votingMethod, setVotingMethod] = useState(() => (
    isEditMode ? (editingProposal.voting_method ?? 'binary') : 'binary'
  ));
  // Phase 90c — per-proposal count mode. Only meaningful in weighted orgs that
  // allow the per-proposal override. '' = org default (weighted); the toggle
  // sets it to 'one_per_member' when the author wants headcount counting.
  const [countMode, setCountMode] = useState(() => (
    isEditMode ? (editingProposal.count_mode ?? '') : ''
  ));
  const [options, setOptions] = useState(() => {
    if (isEditMode && Array.isArray(editingProposal.options) && editingProposal.options.length > 0) {
      return editingProposal.options.map(o => ({
        label: o.label ?? '',
        description: o.description ?? '',
        // Phase 73 — per-bucket ceiling (budget proposals only).
        budgetMaxAmount: o.budget_max_amount != null ? String(o.budget_max_amount) : '',
      }));
    }
    return [
      { label: '', description: '', budgetMaxAmount: '' },
      { label: '', description: '', budgetMaxAmount: '' },
    ];
  });
  // Phase 73 — allocation-budget config (only used when method is
  // budget_allocation). Envelope is the pool to split; aggregation is the
  // per-bucket central tendency.
  const [budgetEnvelope, setBudgetEnvelope] = useState(() => (
    isEditMode && editingProposal.budget_config?.envelope != null
      ? String(editingProposal.budget_config.envelope) : ''
  ));
  const [budgetAggregation, setBudgetAggregation] = useState(() => (
    isEditMode ? (editingProposal.budget_config?.aggregation ?? 'median') : 'median'
  ));
  // Phase 76a — display unit for budget amounts (allocation + project). Stored
  // in budget_config.currency (any non-empty string). Blank → backend default
  // "USD" → "$". Purely cosmetic; doesn't affect any tally math.
  const [budgetUnit, setBudgetUnit] = useState(() => {
    if (!isEditMode) return '';
    const c = editingProposal.budget_config?.currency;
    return c && c !== 'USD' ? c : '';
  });
  // Phase 74b — project-budget config + items (only when method is
  // budget_project). Envelope reuses budgetEnvelope above.
  const [projectMinSpend, setProjectMinSpend] = useState(() => (
    isEditMode && editingProposal.budget_config?.min_spend != null
      ? String(editingProposal.budget_config.min_spend) : '0'
  ));
  const [projectMaxSpend, setProjectMaxSpend] = useState(() => (
    isEditMode && editingProposal.budget_config?.max_spend != null
      ? String(editingProposal.budget_config.max_spend) : ''
  ));
  const [projectItems, setProjectItems] = useState(() => {
    // Edit-mode reconstruction of project items from flat options is non-
    // trivial (tiers fold under parents); project proposals are draft-edited
    // rarely. Seed empty in edit mode (the create path is the primary surface).
    if (isEditMode && editingProposal.voting_method === 'budget_project') {
      const opts = Array.isArray(editingProposal.options) ? editingProposal.options : [];
      const tops = opts.filter(o => !o.budget_tier_parent_id);
      return tops.map(o => {
        if (o.budget_kind === 'tier_parent') {
          const kids = opts.filter(c => c.budget_tier_parent_id === o.id);
          return { label: o.label ?? '', kind: 'tier_parent',
            cost: '', fallback: o.tier_allow_fallback !== false,
            tiers: kids.map(k => ({ label: k.label ?? '', cost: String(k.budget_floor_amount ?? '') })) };
        }
        const cost = o.budget_kind === 'continuous-as-discrete'
          ? (o.budget_max_amount ?? o.budget_floor_amount) : o.budget_floor_amount;
        return { label: o.label ?? '', kind: o.budget_kind || 'discrete',
          cost: cost != null ? String(cost) : '', tiers: [], fallback: true };
      });
    }
    return [
      { label: '', kind: 'discrete', cost: '', tiers: [], fallback: true },
      { label: '', kind: 'discrete', cost: '', tiers: [], fallback: true },
    ];
  });
  const [numWinners, setNumWinners] = useState(() => (
    isEditMode ? (editingProposal.num_winners ?? 1) : 1
  ));
  // Multi-winner approval selection (approval method only; never for
  // elections — those create through OrgTitles, not this form). One
  // state object holding the active preset + every preset's input
  // values; seeded from the proposal's stored generalized config in
  // edit mode (preset shape detected; non-matching shapes fall back to
  // the floor_extras preset showing the raw generalized values).
  const [winnerSel, setWinnerSel] = useState(() => detectApprovalWinnerPreset(
    isEditMode ? editingProposal.approval_winner_config : null,
  ));
  const isElection = isEditMode && editingProposal.is_election === true;
  const [selectedTopics, setSelectedTopics] = useState(() => {
    if (isEditMode && Array.isArray(editingProposal.topics)) {
      // ProposalOut surfaces topics as [{topic_id, relevance, ...}]; map
      // to the form's {topic_id, relevance} shape (drop extras).
      return editingProposal.topics.map(t => ({
        topic_id: t.topic_id ?? t.id,
        relevance: t.relevance ?? 1.0,
      }));
    }
    return [];
  });
  // Phase 8.5 — scope selector. '' == parent-org-wide. Not editable post-
  // creation (structural choice); we still surface it as read-only in
  // edit mode for context.
  const [scope, setScope] = useState(() => (
    isEditMode ? (editingProposal.sub_org_id ?? '') : ''
  ));
  const [passThreshold, setPassThreshold] = useState(() => (
    isEditMode && editingProposal.pass_threshold != null
      ? editingProposal.pass_threshold
      : (orgSettings?.default_pass_threshold ?? 0.5)
  ));
  const [quorumThreshold, setQuorumThreshold] = useState(() => (
    isEditMode && editingProposal.quorum_threshold != null
      ? editingProposal.quorum_threshold
      : (orgSettings?.default_quorum_threshold ?? 0.4)
  ));
  // Phase 16 F1 — duration state. Pre-populated from org defaults so the
  // visible numbers match what the backend would default to. When the user
  // lacks `proposal.set_durations` we still hold these values but only
  // include them in the payload when the editor is shown. In edit mode,
  // prefill from the proposal's own value if it overrode the default.
  const [deliberationDays, setDeliberationDays] = useState(() => (
    isEditMode && editingProposal.deliberation_days != null
      ? editingProposal.deliberation_days
      : (orgSettings?.default_deliberation_days ?? 7)
  ));
  const [votingDays, setVotingDays] = useState(() => (
    isEditMode && editingProposal.voting_days != null
      ? editingProposal.voting_days
      : (orgSettings?.default_voting_days ?? 3)
  ));
  // Phase 75a — optional absolute voting deadline (datetime-local string).
  // When set, wins over voting_days at advance time. Empty = use voting_days.
  const [votingEndDate, setVotingEndDate] = useState(() => {
    const v = isEditMode ? editingProposal.voting_end_date : null;
    if (!v) return '';
    // ISO -> datetime-local value (YYYY-MM-DDTHH:mm), trimming seconds/zone.
    return String(v).slice(0, 16);
  });

  // Decision 3: sub-org proposals can use parent-org-wide topics + that sub-
  // org's own topics. Parent-org-wide proposals can use ONLY parent-org-wide
  // topics (sub_org_id null).
  const inScopeTopics = scope
    ? topics.filter(t => t.sub_org_id == null || t.sub_org_id === scope)
    : topics.filter(t => t.sub_org_id == null);
  // Phase 20 — per-proposal Stable Result Required override.
  // null = inherit org default; only writable when org allows the override.
  // Backwards-compat: read from the new key first, fall back to the old
  // sustained_majority_* key for orgs whose settings haven't been resaved.
  const smOverrideAllowed = (
    orgSettings?.stable_result_per_proposal_override
    ?? orgSettings?.sustained_majority_per_proposal_override
    ?? true
  ) !== false;
  const orgSmDefault = (
    orgSettings?.stable_result_enabled_default
    ?? orgSettings?.sustained_majority_enabled_default
  ) === true;
  const [smEnabled, setSmEnabled] = useState(() => (
    isEditMode && editingProposal.stable_result_required != null
      ? editingProposal.stable_result_required
      : orgSmDefault
  ));
  // Phase 9 — Linked Polises (Decision 2 + 7). When org config has
  // `require_polis_for_new_proposals` true, at least one link is required;
  // form blocks submission otherwise. The org config walks parent chain
  // server-side via `get_org_config`; for parent-org-wide proposals the
  // value lives on `currentOrg.settings`.
  const requirePolis = orgSettings?.require_polis_for_new_proposals === true;
  const [linkedPolisIds, setLinkedPolisIds] = useState(() => (
    isEditMode && Array.isArray(editingProposal.linked_polis_ids)
      ? editingProposal.linked_polis_ids
      : []
  ));
  // Phase 52 Stage 1 — per-proposal verification floor. Default
  // empty → backend serializes as NULL → ungated (today's behavior).
  const [verificationFloor, setVerificationFloor] = useState(() => (
    isEditMode ? (editingProposal.verification_floor ?? '') : ''
  ));
  const [verificationJurisdiction, setVerificationJurisdiction] = useState(() => (
    isEditMode ? (editingProposal.verification_jurisdiction ?? '') : ''
  ));
  // Phase 32.2 F1 — three new deliberation-engagement override toggles,
  // now mode-aware. The Phase 32.2 migration replaced the four boolean
  // default fields with enum modes (`always_off` / `default_off` /
  // `default_on` / `always_on`). For `default_*` modes the toggle is
  // visible + editable + pre-filled with the mode's default. For
  // `always_*` modes the toggle is hidden (org has locked the feature
  // org-wide); the create form omits the override from the submit
  // payload so the row keeps the null inherit-from-org marker.
  function _modeDefault(mode, fallback) {
    if (mode === 'always_off' || mode === 'default_off') return false;
    if (mode === 'always_on' || mode === 'default_on') return true;
    return !!fallback;
  }
  function _modeOverridable(mode) {
    return mode === 'default_off' || mode === 'default_on';
  }
  const writeInsAllowedMode = orgSettings?.write_ins?.allowed_mode ?? 'default_off';
  const writeInsDuringVotingMode = orgSettings?.write_ins?.during_voting_mode ?? 'default_on';
  const preVotingAllowedMode = orgSettings?.pre_voting?.allowed_mode ?? 'default_off';
  const visibilityMode = orgSettings?.pre_voting?.visibility_mode ?? 'default_off';
  const writeInsOverridable = _modeOverridable(writeInsAllowedMode);
  const writeInsDuringVotingOverridable = _modeOverridable(writeInsDuringVotingMode);
  const preVotingOverridable = _modeOverridable(preVotingAllowedMode);
  const visibilityOverridable = _modeOverridable(visibilityMode);
  const orgWriteInsAllowed = _modeDefault(writeInsAllowedMode, false);
  const orgWriteInsDuringVoting = _modeDefault(writeInsDuringVotingMode, true);
  const orgMaxWriteIns = orgSettings?.write_ins?.max_per_proposal ?? 10;
  const orgPreVotingAllowed = _modeDefault(preVotingAllowedMode, false);
  const orgShowVotesDuringDelib = _modeDefault(visibilityMode, false);
  const orgEditLockoutFrac = orgSettings?.proposal_edits?.lockout_fraction ?? 0.75;
  // Phase 62 A1 — prefill engagement overrides from the proposal's own
  // value when non-null; fall back to org-default otherwise (so "inherit"
  // stays "inherit" unless the user changes it).
  const [allowWriteIns, setAllowWriteIns] = useState(() => (
    isEditMode && editingProposal.allow_write_in_options != null
      ? editingProposal.allow_write_in_options
      : orgWriteInsAllowed
  ));
  const [allowWriteInsDuringVoting, setAllowWriteInsDuringVoting] = useState(() => (
    isEditMode && editingProposal.allow_write_ins_during_voting != null
      ? editingProposal.allow_write_ins_during_voting
      : orgWriteInsDuringVoting
  ));
  const [maxWriteIns, setMaxWriteIns] = useState(() => (
    isEditMode && editingProposal.max_write_ins != null
      ? editingProposal.max_write_ins
      : orgMaxWriteIns
  ));
  const [allowPreVoting, setAllowPreVoting] = useState(() => (
    isEditMode && editingProposal.allow_pre_voting != null
      ? editingProposal.allow_pre_voting
      : orgPreVotingAllowed
  ));
  const [showVotesDuringDelib, setShowVotesDuringDelib] = useState(() => (
    isEditMode && editingProposal.show_votes_during_deliberation != null
      ? editingProposal.show_votes_during_deliberation
      : orgShowVotesDuringDelib
  ));
  const [editLockoutFrac, setEditLockoutFrac] = useState(() => (
    isEditMode && editingProposal.edit_lockout_fraction != null
      ? editingProposal.edit_lockout_fraction
      : orgEditLockoutFrac
  ));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  const allowedMethods = orgSettings?.allowed_voting_methods || ['binary'];
  const approvalAllowed = allowedMethods.includes('approval');
  const rankedChoiceAllowed = allowedMethods.includes('ranked_choice');
  // Phase 73/74 — budget methods are opt-in per org (like ranked_choice).
  const budgetAllowed = allowedMethods.includes('budget_allocation');
  const projectBudgetAllowed = allowedMethods.includes('budget_project');
  const isBudget = votingMethod === 'budget_allocation';
  const isProjectBudget = votingMethod === 'budget_project';
  // Budget-allocation buckets are options too, so they share the multi-option
  // editor. Project budget uses its own ProjectItemsEditor (kind + tiers).
  const isMultiOption = votingMethod === 'approval' || votingMethod === 'ranked_choice' || isBudget;

  // Phase 90c — the per-proposal count-mode toggle is offered only in weighted
  // orgs that allow the override (weighted_voting.allow_per_member_proposals,
  // default true). Editable only while the proposal is in draft (backend locks
  // it after); we hide the control in edit mode once the proposal has left draft.
  const weightedVoting = currentOrg?.weighted_voting;
  const countModeAvailable = !!weightedVoting?.enabled
    && weightedVoting?.allow_per_member_proposals !== false
    && (!isEditMode || editingProposal.status === 'draft');

  function toggleTopic(topicId) {
    setSelectedTopics(prev => {
      const existing = prev.find(t => t.topic_id === topicId);
      if (existing) return prev.filter(t => t.topic_id !== topicId);
      return [...prev, { topic_id: topicId, relevance: 1.0 }];
    });
  }

  function setRelevance(topicId, relevance) {
    setSelectedTopics(prev => prev.map(t =>
      t.topic_id === topicId ? { ...t, relevance } : t
    ));
  }

  // Validation for multi-option proposals (approval and ranked_choice)
  const hasDuplicateLabels = (() => {
    if (!isMultiOption) return false;
    const labels = options.map(o => o.label.trim().toLowerCase()).filter(Boolean);
    return new Set(labels).size !== labels.length;
  })();

  const optionsValid = !isMultiOption || (
    options.length >= 2 &&
    options.every(o => o.label.trim()) &&
    !hasDuplicateLabels
  );

  const numWinnersValid = votingMethod !== 'ranked_choice' || (
    Number.isInteger(numWinners) && numWinners >= 1 && numWinners <= options.length
  );

  // Phase 73 — budget proposals need a positive envelope.
  const budgetValid = !isBudget || (Number(budgetEnvelope) > 0);

  // Phase 74b — project budget validity: positive envelope, >=2 items each
  // with a label + a resolvable cost (tier parents need >=1 tier with a cost).
  const projectBudgetValid = !isProjectBudget || (
    Number(budgetEnvelope) > 0
    && projectItems.length >= 2
    && projectItems.every(it => {
      if (!it.label.trim()) return false;
      if (it.kind === 'tier_parent') {
        return (it.tiers || []).length >= 1
          && it.tiers.every(t => t.label.trim() && Number(t.cost) > 0);
      }
      return Number(it.cost) > 0;
    })
  );

  // Multi-winner approval selection — client-side validation mirrors
  // the backend's approval_winner_config rules; the submit button is
  // disabled with an inline message when invalid.
  const winnerSelectionError = (votingMethod === 'approval' && !isElection)
    ? validateApprovalWinnerSelection(winnerSel)
    : null;
  const winnerSelectionValid = !winnerSelectionError;
  const winnerRulePreview = (votingMethod === 'approval' && !isElection && winnerSelectionValid)
    ? (describeApprovalWinnerRule(buildApprovalWinnerConfig(winnerSel)) || SINGLE_WINNER_SUMMARY)
    : null;

  function updateWinnerSel(patch) {
    setWinnerSel(prev => ({ ...prev, ...patch }));
  }

  // Parse a number-input value: '' stays '' (cleared), otherwise Number.
  function numOrEmpty(raw) {
    return raw === '' ? '' : Number(raw);
  }

  async function handleSubmit(e) {
    e.preventDefault();
    const ok = await saveChanges();
    if (ok) onCreated();
  }

  // Persist the form (create or edit). Returns true on success, false on a
  // validation-cancel or an API failure. Split out from handleSubmit so the
  // edit-mode "Save & advance" button can save and THEN advance without
  // closing the editor (which onCreated does). The advance handler invokes
  // this via the onAdvance(saveChanges) wiring.
  async function saveChanges() {
    // Phase 9 — block submission when require_polis_for_new_proposals is
    // true and the picker is empty. Server enforces this too; we surface
    // it inline so the operator doesn't round-trip a 400.
    if (!isEditMode && requirePolis && (linkedPolisIds || []).length === 0 && scope) {
      setError('At least one linked Polis is required for proposals in this scope.');
      return false;
    }
    // Phase 62 A1 — voting_method change during edit discards existing
    // options (matches the Phase 59 A4 backend's option-reshape behavior).
    // Confirm with the user before submit so the destructive intent is
    // explicit. Only fires when actually changing methods.
    if (
      isEditMode
      && votingMethod !== (editingProposal.voting_method ?? 'binary')
      && Array.isArray(editingProposal.options)
      && editingProposal.options.length > 0
    ) {
      const ok = await confirm({
        title: 'Change voting method?',
        message: (
          'Changing the voting method on this draft will discard the '
          + 'existing options. New options can be added if the new method '
          + 'is approval or ranked-choice. Continue?'
        ),
        destructive: true,
      });
      if (!ok) return false;
    }
    setSaving(true);
    setError('');
    try {
      const payload = {
        title,
        body,
        topics: selectedTopics,
        voting_method: votingMethod,
      };
      // Phase 12.5 F3 — only include thresholds when the user has the
      // `proposal.set_thresholds` permission. Backend (B3) applies org
      // defaults when these fields are omitted; sending them without
      // permission would fail with a 400 if they differ from defaults.
      if (canSetThresholds) {
        payload.pass_threshold = passThreshold;
        payload.quorum_threshold = quorumThreshold;
      }
      // Phase 16 F1/B3 — same pattern for durations. Only include when the
      // user has `proposal.set_durations`; otherwise the backend uses the
      // org defaults. Sending values that differ from defaults without the
      // permission would 400.
      if (canSetDurations) {
        payload.deliberation_days = deliberationDays;
        payload.voting_days = votingDays;
      }
      // Phase 75a — absolute voting deadline. In edit mode always send (incl.
      // null to clear); in create only when set. The backend gates a divergent
      // implied duration on proposal.set_durations, same as voting_days.
      if (isEditMode) {
        payload.voting_end_date = votingEndDate
          ? new Date(votingEndDate).toISOString() : null;
      } else if (votingEndDate) {
        payload.voting_end_date = new Date(votingEndDate).toISOString();
      }
      // Phase 62 A1 — sub_org_id is set only on create. Edit mode keeps
      // the proposal's existing scope; the PATCH endpoint does not accept
      // a scope change.
      if (!isEditMode && scope) payload.sub_org_id = scope;
      if (isMultiOption) {
        payload.options = options.map(o => ({
          label: o.label.trim(),
          description: o.description.trim(),
          // Phase 73 — bucket ceiling for budget proposals; omitted (null)
          // for approval/RCV options.
          ...(isBudget && o.budgetMaxAmount !== '' && o.budgetMaxAmount != null
            ? { budget_max_amount: Number(o.budgetMaxAmount) }
            : {}),
        }));
      }
      if (votingMethod === 'ranked_choice') {
        payload.num_winners = numWinners;
      }
      // Phase 90c — per-proposal count mode (weighted orgs that allow it). Send
      // 'one_per_member' when chosen; otherwise omit so the org default (weighted)
      // applies. In edit mode the backend enforces the draft-only lock.
      if (countModeAvailable && countMode === 'one_per_member') {
        payload.count_mode = 'one_per_member';
      } else if (isEditMode && editingProposal.count_mode && countMode !== 'one_per_member') {
        // Author cleared the override while still in draft → back to weighted.
        payload.count_mode = 'weighted';
      }
      // Phase 73 — allocation-budget config.
      if (isBudget) {
        payload.budget_config = {
          mode: 'allocation',
          envelope: Number(budgetEnvelope),
          aggregation: budgetAggregation,
          currency: budgetUnit.trim() || 'USD',
        };
      }
      // Phase 74b — project-budget config + items (tier parents carry nested
      // tiers; the server expands them into child option rows).
      if (isProjectBudget) {
        const env = Number(budgetEnvelope);
        payload.budget_config = {
          mode: 'project',
          envelope: env,
          min_spend: Number(projectMinSpend) || 0,
          max_spend: projectMaxSpend !== '' ? Number(projectMaxSpend) : env,
          currency: budgetUnit.trim() || 'USD',
        };
        payload.options = projectItems.map(it => {
          const base = { label: it.label.trim(), description: '' };
          if (it.kind === 'tier_parent') {
            return {
              ...base, budget_kind: 'tier_parent',
              tier_allow_fallback: it.fallback !== false,
              tiers: (it.tiers || []).map(t => ({
                label: t.label.trim(), budget_floor_amount: Number(t.cost),
              })),
            };
          }
          if (it.kind === 'continuous-as-discrete') {
            return { ...base, budget_kind: 'continuous-as-discrete', budget_max_amount: Number(it.cost) };
          }
          return { ...base, budget_kind: 'discrete', budget_floor_amount: Number(it.cost) };
        });
      }
      // Multi-winner approval selection — approval method only (the
      // backend 400s on other methods and on elections). Single-winner
      // preset sends null = legacy behavior; in edit mode the explicit
      // null also clears a previously-set config.
      if (votingMethod === 'approval' && !isElection) {
        payload.approval_winner_config = buildApprovalWinnerConfig(winnerSel);
      }
      // Phase 52 Stage 1 + Phase 62 A1 — verification floor + optional
      // jurisdiction. In create mode, only include when explicitly set
      // (unset → backend leaves NULL = ungated default). In edit mode,
      // always send the field (including explicit null) so the user can
      // clear a previously-set gate; the backend reads model_fields_set
      // to distinguish "not editing this" from "editing this to null".
      if (isEditMode) {
        payload.verification_floor = verificationFloor || null;
        payload.verification_jurisdiction = (
          verificationFloor && verificationJurisdiction.trim()
            ? verificationJurisdiction.trim()
            : null
        );
      } else if (verificationFloor) {
        payload.verification_floor = verificationFloor;
        if (verificationJurisdiction.trim()) {
          payload.verification_jurisdiction = verificationJurisdiction.trim();
        }
      }
      // Phase 20 — only send the override when org allows it AND the choice
      // diverges from the org default; otherwise let null inherit. The wire
      // field rename: sustained_majority_enabled -> stable_result_required.
      if (smOverrideAllowed && smEnabled !== orgSmDefault) {
        payload.stable_result_required = smEnabled;
      }
      // Phase 32.2 F1 — per-proposal override fields, mode-aware.
      // Only include when the org mode is overridable AND the user
      // diverged from the mode default. For `always_*` modes the
      // toggle isn't rendered, so we keep the field null to inherit
      // (the backend resolver will return the always-locked value).
      const isMultiOptionM = votingMethod === 'approval' || votingMethod === 'ranked_choice';
      if (isMultiOptionM && writeInsOverridable && allowWriteIns !== orgWriteInsAllowed) {
        payload.allow_write_in_options = allowWriteIns;
      }
      if (isMultiOptionM && allowWriteIns && writeInsDuringVotingOverridable
          && allowWriteInsDuringVoting !== orgWriteInsDuringVoting) {
        payload.allow_write_ins_during_voting = allowWriteInsDuringVoting;
      }
      if (isMultiOptionM && allowWriteIns
          && Number(maxWriteIns) !== Number(orgMaxWriteIns)) {
        payload.max_write_ins = Number(maxWriteIns);
      }
      if (preVotingOverridable && allowPreVoting !== orgPreVotingAllowed) {
        payload.allow_pre_voting = allowPreVoting;
      }
      if (allowPreVoting && visibilityOverridable
          && showVotesDuringDelib !== orgShowVotesDuringDelib) {
        payload.show_votes_during_deliberation = showVotesDuringDelib;
      }
      if (Number(editLockoutFrac) !== Number(orgEditLockoutFrac)) {
        payload.edit_lockout_fraction = Number(editLockoutFrac);
      }
      // Phase 9 — structurally-recorded Polis links (Decision 2). Server
      // rejects this on parent-org-wide proposals (linked_polis_ids only
      // supported on org-scoped proposals); only include when scoped.
      // In edit mode we don't currently surface a polis-picker (scope is
      // immutable; the existing links stay), so this stays create-only.
      if (!isEditMode && scope && (linkedPolisIds || []).length > 0) {
        payload.linked_polis_ids = linkedPolisIds;
      }
      if (isEditMode) {
        await api.patch(`/api/proposals/${editingProposal.id}`, payload);
        toast.success('Proposal updated');
      } else {
        await api.post(`/api/orgs/${slug}/proposals`, payload);
        toast.success('Proposal created');
      }
      return true;
    } catch (err) {
      setError(err.message || (isEditMode ? 'Failed to save changes' : 'Failed to create proposal'));
      return false;
    } finally {
      setSaving(false);
    }
  }

  // ----- Phase 68a — import a proposal from a JSON file -----
  // Posts to the parse+validate endpoint, which NEVER persists; on success
  // we pre-fill this form's fields from the returned ProposalCreate-shaped
  // payload and the user reviews + submits through the normal create path.
  const [importOpen, setImportOpen] = useState(false);
  const [importText, setImportText] = useState('');
  const [importFile, setImportFile] = useState(null);
  const [importBusy, setImportBusy] = useState(false);
  const [importErrors, setImportErrors] = useState(null);
  const [importWarnings, setImportWarnings] = useState([]);
  // Phase 75b — Smart Import (AI agenda → proposals) state.
  const [smartOpen, setSmartOpen] = useState(false);
  const [smartMode, setSmartMode] = useState('text'); // 'text' | 'pdf'
  const [smartText, setSmartText] = useState('');
  const [smartFile, setSmartFile] = useState(null);
  const [smartMeetingDate, setSmartMeetingDate] = useState('');
  const [smartInstructions, setSmartInstructions] = useState('');
  const [smartBusy, setSmartBusy] = useState(false);
  const [smartError, setSmartError] = useState('');

  // Apply an imported payload to the form's fields. Each field is guarded
  // so a partial payload only fills what it carries (the rest keep their
  // defaults). Permission-gated fields (thresholds/durations) are still
  // pre-filled; the submit handler decides whether to include them.
  function applyImport(p) {
    if (!p || typeof p !== 'object') return;
    if (p.title != null) setTitle(String(p.title));
    if (p.body != null) setBody(String(p.body));
    if (p.voting_method) setVotingMethod(p.voting_method);
    if (Array.isArray(p.options)) {
      setOptions(
        p.options.length
          ? p.options.map(o => ({ label: o.label ?? '', description: o.description ?? '' }))
          : [{ label: '', description: '' }, { label: '', description: '' }],
      );
    }
    if (p.num_winners != null) setNumWinners(p.num_winners);
    if (p.approval_winner_config !== undefined) {
      setWinnerSel(detectApprovalWinnerPreset(p.approval_winner_config));
    }
    if (Array.isArray(p.topics)) {
      setSelectedTopics(p.topics.map(t => ({
        topic_id: t.topic_id ?? t.id,
        relevance: t.relevance ?? 1.0,
      })));
    }
    if (p.sub_org_id != null) setScope(p.sub_org_id);
    if (p.pass_threshold != null) setPassThreshold(p.pass_threshold);
    if (p.quorum_threshold != null) setQuorumThreshold(p.quorum_threshold);
    if (p.deliberation_days != null) setDeliberationDays(p.deliberation_days);
    if (p.voting_days != null) setVotingDays(p.voting_days);
    if (p.voting_end_date != null) setVotingEndDate(String(p.voting_end_date).slice(0, 16));
    if (p.stable_result_required != null) setSmEnabled(p.stable_result_required);
    if (Array.isArray(p.linked_polis_ids)) setLinkedPolisIds(p.linked_polis_ids);
    if (p.verification_floor != null) setVerificationFloor(p.verification_floor || '');
    if (p.verification_jurisdiction != null) setVerificationJurisdiction(p.verification_jurisdiction || '');
    if (p.allow_write_in_options != null) setAllowWriteIns(p.allow_write_in_options);
    if (p.allow_write_ins_during_voting != null) setAllowWriteInsDuringVoting(p.allow_write_ins_during_voting);
    if (p.max_write_ins != null) setMaxWriteIns(p.max_write_ins);
    if (p.allow_pre_voting != null) setAllowPreVoting(p.allow_pre_voting);
    if (p.show_votes_during_deliberation != null) setShowVotesDuringDelib(p.show_votes_during_deliberation);
    if (p.edit_lockout_fraction != null) setEditLockoutFrac(p.edit_lockout_fraction);
  }

  async function runImport() {
    setImportBusy(true);
    setImportErrors(null);
    setImportWarnings([]);
    try {
      let result;
      if (importFile) {
        const fd = new FormData();
        fd.append('file', importFile);
        result = await api.postFormData(`/api/orgs/${slug}/proposals/import-preview`, fd);
      } else {
        if (!importText.trim()) {
          setImportErrors({ _file: ['Paste JSON or choose a file first.'] });
          setImportBusy(false);
          return;
        }
        let parsed;
        try {
          parsed = JSON.parse(importText);
        } catch {
          setImportErrors({ _file: ['Could not parse as JSON. Check for typos.'] });
          setImportBusy(false);
          return;
        }
        result = await api.post(`/api/orgs/${slug}/proposals/import-preview`, parsed);
      }
      // The response is either single-shape ({proposal,...}) when the file
      // was a JSON OBJECT, or array-shape ({items, summary}) when it was a
      // JSON ARRAY.
      //
      // Phase 72c — an ARRAY response ALWAYS routes to the multi-proposal
      // review list: for any item count, and even when every item is invalid
      // (summary.valid === 0). We do NOT unwrap an array-of-one into the
      // prefill form and we NEVER show the single-import "review the fields
      // below" copy on the array path. (That was the 72 bug: a 200 {items}
      // response carrying per-item errors showed a success toast and then
      // rendered nothing — the review list never mounted.)
      if (Array.isArray(result.items)) {
        if (onMultiImport) {
          onMultiImport(result.items);
          setImportOpen(false);
          setImportText('');
          setImportFile(null);
        } else {
          setImportErrors({ _file: ['Multi-proposal import is not available here.'] });
        }
        return;
      }
      // Single-object response → prefill the create form (unchanged).
      applyImport(result.proposal);
      setImportWarnings(result.warnings || []);
      setImportOpen(false);
      setImportText('');
      setImportFile(null);
      toast.success('Imported — review the fields below and submit.');
    } catch (e) {
      if (e?.raw?.errors) {
        setImportErrors(e.raw.errors);
        setImportWarnings(e.raw.warnings || []);
      } else {
        setImportErrors({ _file: [e?.message || 'Import failed.'] });
      }
    } finally {
      setImportBusy(false);
    }
  }

  async function runSmartImport() {
    setSmartBusy(true);
    setSmartError('');
    try {
      let result;
      if (smartMode === 'pdf') {
        if (!smartFile) {
          setSmartError('Choose a PDF first.');
          setSmartBusy(false);
          return;
        }
        const fd = new FormData();
        fd.append('file', smartFile);
        if (smartMeetingDate) fd.append('meeting_date', smartMeetingDate);
        if (smartInstructions.trim()) fd.append('instructions', smartInstructions.trim());
        result = await api.postFormData(`/api/orgs/${slug}/proposals/smart-import`, fd);
      } else {
        if (!smartText.trim()) {
          setSmartError('Paste the agenda text first.');
          setSmartBusy(false);
          return;
        }
        result = await api.post(`/api/orgs/${slug}/proposals/smart-import`, {
          content: smartText,
          meeting_date: smartMeetingDate || undefined,
          instructions: smartInstructions.trim() || undefined,
        });
      }
      const items = Array.isArray(result.items) ? result.items : [];
      if (items.length === 0) {
        setSmartError(
          (result.warnings && result.warnings[0])
          || 'No proposals could be extracted from the content.',
        );
        return;
      }
      if (items.length === 1 && items[0].proposal && !Object.keys(items[0].errors || {}).length) {
        applyImport(items[0].proposal);
        setImportWarnings(items[0].warnings || []);
        setSmartOpen(false);
        toast.success('Parsed — review the fields below and submit.');
      } else if (onMultiImport) {
        onMultiImport(items);
        setSmartOpen(false);
      } else {
        setSmartError('Multi-proposal review is not available here.');
      }
    } catch (e) {
      if (e?.raw?.detail) setSmartError(e.raw.detail);
      else setSmartError(e?.message || 'Smart import failed.');
    } finally {
      setSmartBusy(false);
    }
  }

  async function downloadImportTemplate() {
    try {
      const tmpl = await api.get(`/api/orgs/${slug}/proposals/import-template`);
      const blob = new Blob([JSON.stringify(tmpl, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'proposal-import-template.json';
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch {
      toast.error('Could not load the template.');
    }
  }

  return (
    <form onSubmit={handleSubmit} className="bg-white border border-gray-200 rounded-xl p-5 space-y-4">
      <h3 className="text-lg font-semibold text-[var(--brand-primary)]">
        {isEditMode ? 'Edit Draft Proposal' : 'Create Proposal'}
      </h3>

      {/* Phase 68a — import a proposal from a JSON file. Pre-fills the form
          below; the user reviews and submits through the normal flow.
          Create mode only. */}
      {!isEditMode && (
        <div className="border border-gray-200 rounded-lg bg-gray-50">
          <div className="flex items-center justify-between px-3 py-2">
            <button
              type="button"
              onClick={() => setImportOpen(o => !o)}
              className="text-sm font-medium text-[var(--brand-accent)] hover:underline"
            >
              {importOpen ? '▾ ' : '▸ '}Import from file
            </button>
            <button
              type="button"
              onClick={downloadImportTemplate}
              className="text-xs text-gray-500 hover:text-[var(--brand-accent)] hover:underline"
            >
              Download template
            </button>
          </div>
          {importOpen && (
            <div className="px-3 pb-3 space-y-2">
              <p className="text-xs text-gray-500">
                Upload a <code>.json</code> file or paste JSON. Nothing is saved —
                the fields below are pre-filled for you to review and submit.
                Topics can be given by name. Download the template above for the format.
              </p>
              <input
                type="file"
                accept=".json,application/json"
                onChange={e => setImportFile(e.target.files?.[0] || null)}
                className="block w-full text-xs text-gray-600 file:mr-3 file:py-1 file:px-3 file:rounded file:border-0 file:text-xs file:bg-[var(--brand-primary)] file:text-white hover:file:bg-[var(--brand-accent)]"
              />
              <div className="text-xs text-gray-400 text-center">— or paste —</div>
              <textarea
                value={importText}
                onChange={e => setImportText(e.target.value)}
                rows={6}
                placeholder='{"title": "...", "voting_method": "approval", "options": [...]}'
                className="w-full px-3 py-2 border border-gray-300 rounded-lg text-xs font-mono focus:outline-none focus:ring-2 focus:ring-[var(--brand-accent)]"
              />
              {importErrors && (
                <div className="bg-red-50 border border-red-200 rounded-lg p-2 text-xs text-red-700 space-y-1">
                  <div className="font-medium">Import couldn't be applied:</div>
                  <ul className="list-disc ml-4">
                    {Object.entries(importErrors).map(([field, msgs]) => (
                      (Array.isArray(msgs) ? msgs : [msgs]).map((m, i) => (
                        <li key={`${field}-${i}`}>
                          {field !== '_file' && <span className="font-medium">{field}: </span>}{m}
                        </li>
                      ))
                    ))}
                  </ul>
                </div>
              )}
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={runImport}
                  disabled={importBusy}
                  className="text-sm px-4 py-1.5 bg-[var(--brand-primary)] text-white rounded-lg hover:bg-[var(--brand-accent)] transition-colors disabled:opacity-50"
                >
                  {importBusy ? 'Importing…' : 'Preview & fill form'}
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Phase 75b — Smart Import: paste an agenda or upload a PDF and let the
          AI extract proposal drafts. Hands off to the same review list as the
          structured multi-import. Create mode only. */}
      {!isEditMode && (
        <div className="border border-gray-200 rounded-lg bg-gray-50">
          <div className="flex items-center justify-between px-3 py-2">
            <button
              type="button"
              onClick={() => setSmartOpen(o => !o)}
              className="text-sm font-medium text-[var(--brand-accent)] hover:underline"
            >
              {smartOpen ? '▾ ' : '▸ '}Smart Import (AI agenda parser)
            </button>
          </div>
          {smartOpen && (
            <div className="px-3 pb-3 space-y-2">
              <p className="text-xs text-gray-500">
                Paste a meeting agenda or upload a PDF. The assistant extracts
                substantive items as proposal drafts (skipping procedural items)
                and assigns topics. Nothing is saved — you review every draft
                before publishing.
              </p>
              <div className="flex gap-2 text-xs">
                <button
                  type="button"
                  onClick={() => setSmartMode('text')}
                  className={`px-2 py-1 rounded ${smartMode === 'text' ? 'bg-[var(--brand-primary)] text-white' : 'bg-gray-200 text-gray-600'}`}
                >
                  Paste text
                </button>
                <button
                  type="button"
                  onClick={() => setSmartMode('pdf')}
                  className={`px-2 py-1 rounded ${smartMode === 'pdf' ? 'bg-[var(--brand-primary)] text-white' : 'bg-gray-200 text-gray-600'}`}
                >
                  Upload PDF
                </button>
              </div>
              {smartMode === 'text' ? (
                <textarea
                  value={smartText}
                  onChange={e => setSmartText(e.target.value)}
                  rows={6}
                  placeholder="Paste the agenda text here…"
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg text-xs font-mono focus:outline-none focus:ring-2 focus:ring-[var(--brand-accent)]"
                />
              ) : (
                <input
                  type="file"
                  accept=".pdf,application/pdf"
                  onChange={e => setSmartFile(e.target.files?.[0] || null)}
                  className="block w-full text-xs text-gray-600 file:mr-3 file:py-1 file:px-3 file:rounded file:border-0 file:text-xs file:bg-[var(--brand-primary)] file:text-white hover:file:bg-[var(--brand-accent)]"
                />
              )}
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                <div>
                  <label className="block text-xs text-gray-500 mb-1">
                    Meeting date (optional)
                  </label>
                  <input
                    type="date"
                    value={smartMeetingDate}
                    onChange={e => setSmartMeetingDate(e.target.value)}
                    className="w-full px-2 py-1.5 border border-gray-300 rounded text-xs focus:outline-none focus:ring-2 focus:ring-[var(--brand-accent)]"
                  />
                  <p className="text-[11px] text-gray-400 mt-0.5">Voting will close by this date.</p>
                </div>
                <div>
                  <label className="block text-xs text-gray-500 mb-1">
                    Guidance (optional)
                  </label>
                  <input
                    type="text"
                    value={smartInstructions}
                    onChange={e => setSmartInstructions(e.target.value)}
                    placeholder="e.g., focus on zoning items"
                    className="w-full px-2 py-1.5 border border-gray-300 rounded text-xs focus:outline-none focus:ring-2 focus:ring-[var(--brand-accent)]"
                  />
                </div>
              </div>
              {smartError && (
                <div className="bg-red-50 border border-red-200 rounded-lg p-2 text-xs text-red-700">
                  {smartError}
                </div>
              )}
              <button
                type="button"
                onClick={runSmartImport}
                disabled={smartBusy}
                className="text-sm px-4 py-1.5 bg-[var(--brand-primary)] text-white rounded-lg hover:bg-[var(--brand-accent)] transition-colors disabled:opacity-50"
              >
                {smartBusy ? 'Parsing agenda items…' : 'Parse'}
              </button>
            </div>
          )}
        </div>
      )}

      {/* Phase 68a — warnings from a successful import (unknown keys skipped,
          topic names resolved). Dismissible info note. */}
      {!isEditMode && importWarnings.length > 0 && (
        <div className="bg-blue-50 border border-blue-200 rounded-lg p-3 text-xs text-blue-900">
          <div className="flex items-start justify-between gap-2">
            <div>
              <strong>Imported with notes:</strong>
              <ul className="list-disc ml-4 mt-1">
                {importWarnings.map((w, i) => <li key={i}>{w}</li>)}
              </ul>
            </div>
            <button
              type="button"
              onClick={() => setImportWarnings([])}
              className="text-blue-400 hover:text-blue-700 text-sm leading-none"
              aria-label="Dismiss"
            >
              ✕
            </button>
          </div>
        </div>
      )}

      {/* Phase 46 F2 / Phase 46a — cosign-required advisory.
          Members in cosign_required orgs see this so the creation flow
          doesn't silently change behavior. 46a: threshold is measured
          in WEIGHT (delegation-aware) and evaluated at window-end.
          Phase 62 A1: cosign is a create-time gathering mechanic; not
          surfaced in edit mode (an existing draft has already entered
          the cosign pipeline at creation time if applicable). */}
      {!isEditMode && showCosignAdvisory && (
        <div className="bg-amber-50 border border-amber-200 rounded-lg p-3 text-sm text-amber-900">
          <strong>This org gathers signatures first.</strong> Your proposal will need <strong>{cosignThreshold} weight</strong> of cosign support (you count for yourself plus everyone who delegates a relevant topic to you) within roughly <strong>{cosignWindowDays} day{cosignWindowDays === 1 ? '' : 's'}</strong>. The threshold is checked at window-end: if support is met, the proposal advances to voting; otherwise it closes as "expired_unsigned."
        </div>
      )}

      {/* Phase 8.5 — Scope Selector. Phase 62 A1: scope is structural and
          immutable post-creation; in edit mode we render the current
          scope read-only (or omit if parent-org-wide) rather than the
          selector. */}
      {isEditMode && scope && subOrgs && subOrgs.find(s => s.id === scope) && (
        <div>
          <label className="block text-xs text-gray-500 mb-1">Scope</label>
          <div className="px-3 py-2 bg-gray-50 border border-gray-200 rounded-lg text-sm text-gray-600">
            {subOrgs.find(s => s.id === scope).name} only
            <span className="ml-2 text-xs text-gray-400">(scope is not editable)</span>
          </div>
        </div>
      )}
      {!isEditMode && subOrgs && subOrgs.length > 0 && (
        <div>
          <label className="block text-xs text-gray-500 mb-1">Scope</label>
          <select
            value={scope}
            onChange={e => {
              setScope(e.target.value);
              // Trim out-of-scope topic selections when scope changes.
              setSelectedTopics(prev => prev.filter(s => {
                const t = topics.find(x => x.id === s.topic_id);
                if (!t) return false;
                if (e.target.value) return t.sub_org_id == null || t.sub_org_id === e.target.value;
                return t.sub_org_id == null;
              }));
            }}
            className="w-full max-w-md px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[var(--brand-accent)]"
          >
            <option value="">Parent-org-wide (default)</option>
            {subOrgs.map(s => (
              <option key={s.id} value={s.id}>{s.name} only</option>
            ))}
          </select>
          {scope && (
            <p className="text-xs text-amber-600 mt-1">
              Only {subOrgs.find(s => s.id === scope)?.name} members will be able to vote on this proposal.
            </p>
          )}
        </div>
      )}

      {/* Voting Method Selector */}
      <div>
        <label className="block text-xs text-gray-500 mb-2">
          Voting Method
          <Link to="/help/voting-methods" className="ml-2 text-[var(--brand-accent)] hover:underline">Which should I pick?</Link>
        </label>
        <div className="flex gap-3">
          <label className="flex items-center gap-2 cursor-pointer">
            <input type="radio" name="votingMethod" value="binary" checked={votingMethod === 'binary'}
              onChange={() => setVotingMethod('binary')} className="accent-[var(--brand-accent)]" />
            <span className="text-sm text-gray-700">Binary (Yes/No)</span>
          </label>
          <label className={`flex items-center gap-2 ${approvalAllowed ? 'cursor-pointer' : 'opacity-50 cursor-not-allowed'}`}>
            <input type="radio" name="votingMethod" value="approval" checked={votingMethod === 'approval'}
              onChange={() => approvalAllowed && setVotingMethod('approval')}
              disabled={!approvalAllowed} className="accent-[var(--brand-accent)]" />
            <span className="text-sm text-gray-700">Approval</span>
            {!approvalAllowed && <span className="text-xs text-amber-600">(Not enabled for this org)</span>}
          </label>
          <label className={`flex items-center gap-2 ${rankedChoiceAllowed ? 'cursor-pointer' : 'opacity-50 cursor-not-allowed'}`}>
            <input type="radio" name="votingMethod" value="ranked_choice" checked={votingMethod === 'ranked_choice'}
              onChange={() => rankedChoiceAllowed && setVotingMethod('ranked_choice')}
              disabled={!rankedChoiceAllowed} className="accent-[var(--brand-accent)]" />
            <span className="text-sm text-gray-700">Ranked Choice</span>
            {!rankedChoiceAllowed && <span className="text-xs text-amber-600">(Not enabled for this org)</span>}
          </label>
          {/* Phase 73 — allocation budget (opt-in per org). */}
          {budgetAllowed && (
            <label className="flex items-center gap-2 cursor-pointer">
              <input type="radio" name="votingMethod" value="budget_allocation" checked={isBudget}
                onChange={() => setVotingMethod('budget_allocation')} className="accent-[var(--brand-accent)]" />
              <span className="text-sm text-gray-700">Budget (allocate funds across buckets)</span>
            </label>
          )}
          {projectBudgetAllowed && (
            <label className="flex items-center gap-2 cursor-pointer">
              <input type="radio" name="votingMethod" value="budget_project" checked={isProjectBudget}
                onChange={() => setVotingMethod('budget_project')} className="accent-[var(--brand-accent)]" />
              <span className="text-sm text-gray-700">Project budget (fund discrete projects by priority)</span>
            </label>
          )}
        </div>
      </div>

      {/* Phase 90c — per-proposal count mode (weighted orgs that allow it). */}
      {countModeAvailable && (
        <div className="border border-emerald-200 rounded-lg p-3 bg-emerald-50/40">
          <label className="block text-xs text-gray-600 mb-2 font-medium">
            How should votes count?
          </label>
          <div className="flex flex-col gap-2">
            <label className="flex items-start gap-2 cursor-pointer">
              <input
                type="radio" name="countMode" value="weighted"
                checked={countMode !== 'one_per_member'}
                onChange={() => setCountMode('weighted')}
                className="mt-0.5 accent-[var(--brand-accent)]"
              />
              <span className="text-sm text-gray-700">
                By member shares
                <span className="block text-xs text-gray-500">
                  Each member&apos;s vote carries their {weightedVoting?.unit_label || 'shares'} (this organization&apos;s default).
                </span>
              </span>
            </label>
            <label className="flex items-start gap-2 cursor-pointer">
              <input
                type="radio" name="countMode" value="one_per_member"
                checked={countMode === 'one_per_member'}
                onChange={() => setCountMode('one_per_member')}
                className="mt-0.5 accent-emerald-600"
              />
              <span className="text-sm text-gray-700">
                One member, one vote
                <span className="block text-xs text-gray-500">
                  Count by headcount for this proposal — shares don&apos;t apply. Locked once voting opens.
                </span>
              </span>
            </label>
          </div>
        </div>
      )}

      {/* Phase 73 — budget envelope + aggregation. */}
      {isBudget && (
        <div className="border border-gray-200 rounded-lg p-3 space-y-3 bg-gray-50">
          <div>
            <label className="block text-xs text-gray-500 mb-1">Total budget (envelope)</label>
            <div className="flex items-center gap-1">
              {unitInputSymbol(budgetUnit) && (
                <span className="text-gray-400 text-sm">{unitInputSymbol(budgetUnit)}</span>
              )}
              <input
                type="number" min="1" step="1" value={budgetEnvelope}
                onChange={e => setBudgetEnvelope(e.target.value)}
                placeholder="100000"
                className="w-40 px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[var(--brand-accent)]"
              />
            </div>
            {!budgetValid && (
              <p className="text-xs text-red-600 mt-1">Enter a positive budget amount.</p>
            )}
          </div>
          <BudgetUnitField value={budgetUnit} onChange={setBudgetUnit} />
          <div>
            <label className="block text-xs text-gray-500 mb-1">Aggregation</label>
            <select
              value={budgetAggregation}
              onChange={e => setBudgetAggregation(e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[var(--brand-accent)]"
            >
              <option value="median">Median (recommended — strategyproof)</option>
              <option value="trimmed_mean">Trimmed mean (leans toward minority intensity)</option>
            </select>
            <p className="text-xs text-gray-400 mt-1">
              Every bucket with support gets a proportional share; the result always sums to the budget.
            </p>
          </div>
        </div>
      )}

      {/* Phase 74b — project-budget config (envelope + spend band). */}
      {isProjectBudget && (
        <div className="border border-gray-200 rounded-lg p-3 space-y-3 bg-gray-50">
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <div>
              <label className="block text-xs text-gray-500 mb-1">Total budget (envelope)</label>
              <input type="number" min="1" step="1" value={budgetEnvelope}
                onChange={e => setBudgetEnvelope(e.target.value)} placeholder="100000"
                className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[var(--brand-accent)]" />
            </div>
            <div>
              <label className="block text-xs text-gray-500 mb-1">Min spend</label>
              <input type="number" min="0" step="1" value={projectMinSpend}
                onChange={e => setProjectMinSpend(e.target.value)} placeholder="0"
                className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[var(--brand-accent)]" />
            </div>
            <div>
              <label className="block text-xs text-gray-500 mb-1">Max spend</label>
              <input type="number" min="0" step="1" value={projectMaxSpend}
                onChange={e => setProjectMaxSpend(e.target.value)} placeholder="= envelope"
                className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[var(--brand-accent)]" />
            </div>
          </div>
          <p className="text-xs text-gray-400">
            Projects fund in the group’s priority order up to the group’s chosen
            spend level (a median of voters’ desired totals, clamped to the
            min/max band). Min spend 0 lets the group choose to fund little.
          </p>
          <BudgetUnitField value={budgetUnit} onChange={setBudgetUnit} />
          <ProjectItemsEditor items={projectItems} onChange={setProjectItems} unitSymbol={unitInputSymbol(budgetUnit)} />
          {!projectBudgetValid && (
            <p className="text-xs text-red-600">
              Enter a positive envelope and at least 2 projects, each with a name
              and a positive cost (tiered items need at least one priced variant).
            </p>
          )}
        </div>
      )}

      <div>
        <label htmlFor="proposal-title" className="block text-xs text-gray-500 mb-1">Title</label>
        <input
          id="proposal-title"
          type="text"
          value={title}
          onChange={e => setTitle(e.target.value)}
          required
          className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[var(--brand-accent)]"
        />
      </div>

      <div>
        <label htmlFor="proposal-body" className="block text-xs text-gray-500 mb-1">Body (markdown supported)</label>
        <textarea
          id="proposal-body"
          value={body}
          onChange={e => setBody(e.target.value)}
          rows={6}
          className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[var(--brand-accent)] resize-none font-mono"
        />
      </div>

      {/* Options Editor (approval, ranked-choice, and budget buckets) */}
      {isMultiOption && (
        <OptionsEditor options={options} onChange={setOptions} budgetCeilings={isBudget} unitSymbol={unitInputSymbol(budgetUnit)} />
      )}

      {/* Winner selection (approval only). Four presets writing one
          generalized config: single winner (null = legacy behavior),
          Top X, approval threshold, floor + conditional extras. Not
          rendered for elections (those carry their own slate rules). */}
      {votingMethod === 'approval' && !isElection && (
        <div>
          <label className="block text-xs text-gray-500 mb-2">Winner selection</label>
          <div className="space-y-2">
            <label className="flex items-center gap-2 cursor-pointer">
              <input type="radio" name="winnerSelection" value="single"
                checked={winnerSel.mode === 'single'}
                onChange={() => updateWinnerSel({ mode: 'single' })}
                className="accent-[var(--brand-accent)]" />
              <span className="text-sm text-gray-700">Single winner</span>
              <span className="text-xs text-gray-400">(default)</span>
            </label>

            <div className="flex items-center gap-2 flex-wrap">
              <label className="flex items-center gap-2 cursor-pointer">
                <input type="radio" name="winnerSelection" value="top_x"
                  checked={winnerSel.mode === 'top_x'}
                  onChange={() => updateWinnerSel({ mode: 'top_x' })}
                  className="accent-[var(--brand-accent)]" />
                <span className="text-sm text-gray-700">Top X</span>
              </label>
              {winnerSel.mode === 'top_x' && (
                <label className="flex items-center gap-1 text-xs text-gray-600">
                  winners:
                  <input
                    type="number"
                    min={1}
                    value={winnerSel.topX}
                    onChange={e => updateWinnerSel({ topX: numOrEmpty(e.target.value) })}
                    className="w-16 px-2 py-1 border border-gray-300 rounded text-sm focus:outline-none focus:ring-2 focus:ring-[var(--brand-accent)]"
                  />
                </label>
              )}
            </div>

            <div className="flex items-center gap-2 flex-wrap">
              <label className="flex items-center gap-2 cursor-pointer">
                <input type="radio" name="winnerSelection" value="threshold"
                  checked={winnerSel.mode === 'threshold'}
                  onChange={() => updateWinnerSel({ mode: 'threshold' })}
                  className="accent-[var(--brand-accent)]" />
                <span className="text-sm text-gray-700">Approval threshold</span>
              </label>
              {winnerSel.mode === 'threshold' && (
                <label className="flex items-center gap-1 text-xs text-gray-600">
                  at least
                  <input
                    type="number"
                    min={1}
                    max={100}
                    value={winnerSel.thresholdPct}
                    onChange={e => updateWinnerSel({ thresholdPct: numOrEmpty(e.target.value) })}
                    className="w-16 px-2 py-1 border border-gray-300 rounded text-sm focus:outline-none focus:ring-2 focus:ring-[var(--brand-accent)]"
                  />
                  % of ballots
                </label>
              )}
            </div>

            <div className="space-y-1">
              <label className="flex items-center gap-2 cursor-pointer">
                <input type="radio" name="winnerSelection" value="floor_extras"
                  checked={winnerSel.mode === 'floor_extras'}
                  onChange={() => updateWinnerSel({ mode: 'floor_extras' })}
                  className="accent-[var(--brand-accent)]" />
                <span className="text-sm text-gray-700">Floor + extras</span>
              </label>
              {winnerSel.mode === 'floor_extras' && (
                <div className="pl-6 flex items-center gap-2 flex-wrap text-xs text-gray-600">
                  <label className="flex items-center gap-1">
                    at least
                    <input
                      type="number"
                      min={1}
                      value={winnerSel.floorMin}
                      onChange={e => updateWinnerSel({ floorMin: numOrEmpty(e.target.value) })}
                      className="w-16 px-2 py-1 border border-gray-300 rounded text-sm focus:outline-none focus:ring-2 focus:ring-[var(--brand-accent)]"
                    />
                    winners
                  </label>
                  <label className="flex items-center gap-1">
                    up to
                    <input
                      type="number"
                      min={1}
                      value={winnerSel.floorMax}
                      placeholder="no cap"
                      onChange={e => updateWinnerSel({ floorMax: numOrEmpty(e.target.value) })}
                      className="w-20 px-2 py-1 border border-gray-300 rounded text-sm focus:outline-none focus:ring-2 focus:ring-[var(--brand-accent)]"
                    />
                    total
                  </label>
                  <label className="flex items-center gap-1">
                    extras need
                    <input
                      type="number"
                      min={1}
                      max={100}
                      value={winnerSel.floorPct}
                      onChange={e => updateWinnerSel({ floorPct: numOrEmpty(e.target.value) })}
                      className="w-16 px-2 py-1 border border-gray-300 rounded text-sm focus:outline-none focus:ring-2 focus:ring-[var(--brand-accent)]"
                    />
                    % approval
                  </label>
                </div>
              )}
            </div>
          </div>
          {winnerRulePreview && (
            <p className="text-xs text-gray-600 mt-2 font-medium">{winnerRulePreview}</p>
          )}
          {winnerSelectionError && (
            <p className="text-xs text-red-500 mt-1">{winnerSelectionError}</p>
          )}
          {winnerSel.mode !== 'single' && (
            <p className="text-xs text-gray-400 mt-1">
              If options tie at a seat boundary, your organization&apos;s
              tie-resolution method picks among them (the &quot;expand
              winners&quot; method may seat all tied options, exceeding the cap).
            </p>
          )}
        </div>
      )}

      {/* num_winners input (ranked-choice only) */}
      {votingMethod === 'ranked_choice' && (
        <div>
          <label htmlFor="proposal-number-of-winners" className="block text-xs text-gray-500 mb-1">Number of Winners</label>
          <input
            id="proposal-number-of-winners"
            type="number"
            min={1}
            max={options.length || 1}
            value={numWinners}
            onChange={e => {
              const v = parseInt(e.target.value, 10);
              if (Number.isNaN(v)) return;
              setNumWinners(Math.max(1, Math.min(options.length || 1, v)));
            }}
            className="w-32 px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[var(--brand-accent)]"
          />
          <p className="text-xs text-gray-500 mt-1">
            1 winner = ranked-choice voting (IRV). More than 1 winner = single transferable vote (STV).
          </p>
          {!numWinnersValid && (
            <p className="text-xs text-red-500 mt-1">
              Number of winners must be between 1 and the number of options ({options.length}).
            </p>
          )}
        </div>
      )}

      {/* Phase 52 Stage 1 — per-proposal verification floor. Empty value
          means no extra verification required (today's behavior). Picking
          a non-empty floor gates the vote at cast-time; delegated weight
          from voters who don't meet the floor is also dropped unless the
          org's "delegation carries unverified weight" setting is on. */}
      <div className="border border-gray-200 rounded-lg p-4 bg-gray-50/50 space-y-3">
        <div>
          <label htmlFor="proposal-verification-floor" className="block text-xs font-medium text-gray-700 mb-1">
            Identity verification required to vote
          </label>
          <select
            id="proposal-verification-floor"
            value={verificationFloor}
            onChange={e => setVerificationFloor(e.target.value)}
            className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm bg-white focus:outline-none focus:ring-2 focus:ring-[var(--brand-accent)]"
          >
            {VERIFICATION_STATE_OPTIONS.map(opt => (
              <option key={opt.value || 'none'} value={opt.value}>{opt.label}</option>
            ))}
          </select>
          <p className="text-xs text-gray-500 mt-1">
            Leave default to keep this proposal open to all members. A
            higher floor restricts who can cast a vote (or delegate
            weight that counts) on this proposal.
          </p>
        </div>
        {(verificationFloor === 'address_on_id' || verificationFloor === 'residency_verified') && (
          <div>
            <label htmlFor="proposal-verification-jurisdiction" className="block text-xs text-gray-500 mb-1">
              Jurisdiction (optional)
            </label>
            <input
              id="proposal-verification-jurisdiction"
              type="text"
              value={verificationJurisdiction}
              onChange={e => setVerificationJurisdiction(e.target.value)}
              placeholder="e.g. US-CA, GB-LND"
              maxLength={16}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[var(--brand-accent)]"
            />
            <p className="text-xs text-gray-500 mt-1">
              Restrict to voters whose verified address matches this
              jurisdiction. Leave blank to accept any verified address.
            </p>
          </div>
        )}
      </div>

      {inScopeTopics.length > 0 && (
        <fieldset>
          <legend className="block text-xs text-gray-500 mb-2">
            Topics ({inScopeTopics.length} in scope)
          </legend>
          {/* Phase 56 F3 — org-level topic guidance hint. Collapsed by
              default to keep the form lean; expandable when present. */}
          <TopicGuidanceHint guidance={orgSettings?.topic_guidance} />
          {/* Phase 56 F4 — group by category when the org has the
              toggle on; otherwise render the flat list as before. */}
          <TopicPickerList
            topics={inScopeTopics}
            categoriesEnabled={!!orgSettings?.topic_categories_enabled}
            selectedTopics={selectedTopics}
            onToggle={toggleTopic}
            onRelevance={setRelevance}
          />
        </fieldset>
      )}

      {/* Phase 12.5 F3 — threshold sliders are gated on `proposal.set_thresholds`.
          Members granted `proposal.create` but not this key see the explanatory
          notice in lieu of the inputs; backend uses the org defaults. */}
      {canSetThresholds ? (
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label htmlFor="proposal-pass-threshold" className="block text-xs text-gray-500 mb-1">
              Pass Threshold: {Math.round(passThreshold * 100)}%
            </label>
            <input
              id="proposal-pass-threshold"
              type="range"
              min={0}
              max={100}
              value={Math.round(passThreshold * 100)}
              onChange={e => setPassThreshold(parseInt(e.target.value) / 100)}
              className="w-full accent-[var(--brand-accent)]"
            />
          </div>
          <div>
            <label htmlFor="proposal-quorum-threshold" className="block text-xs text-gray-500 mb-1">
              Quorum Threshold: {Math.round(quorumThreshold * 100)}%
            </label>
            <input
              id="proposal-quorum-threshold"
              type="range"
              min={0}
              max={100}
              value={Math.round(quorumThreshold * 100)}
              onChange={e => setQuorumThreshold(parseInt(e.target.value) / 100)}
              className="w-full accent-[var(--brand-accent)]"
            />
          </div>
        </div>
      ) : (
        // Phase 12.6 C1 — show actual default percentages read-only instead
        // of the prior "ask an Admin" copy. Numbers from the orgSettings
        // prop (= currentOrg.settings, 12.5 B2) with fallback to 0.50/0.40.
        <div className="rounded-lg border border-gray-200 bg-gray-50 px-4 py-3">
          <p className="text-sm font-medium text-[var(--brand-primary)] mb-1">Approval thresholds</p>
          <p className="text-sm text-[#2C3E50]">
            This proposal will use the organization's defaults:{' '}
            <strong>{Math.round((orgSettings?.default_pass_threshold ?? 0.50) * 100)}% pass</strong>
            {' / '}
            <strong>{Math.round((orgSettings?.default_quorum_threshold ?? 0.40) * 100)}% quorum</strong>.
          </p>
        </div>
      )}

      {/* Phase 16 F1 — duration inputs gated on `proposal.set_durations`.
          Same shape as the Phase 12.5 thresholds gate above. Authors with
          the permission can override per-proposal (Q2: 0.05-day voting
          floor enables sub-day live polls; 0-day deliberation valid for
          time-pressure decisions). Authors without it see the org defaults
          read-only — same UX as the Phase 12.6 threshold-form-copy fix:
          actual numbers, NOT "ask an admin" copy. */}
      {canSetDurations ? (
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label htmlFor="proposal-deliberation-days" className="block text-xs text-gray-500 mb-1">
              Deliberation duration (days)
            </label>
            <input
              id="proposal-deliberation-days"
              type="number"
              min={0}
              step={1}
              value={deliberationDays}
              onChange={e => {
                const v = parseFloat(e.target.value);
                if (Number.isNaN(v)) return;
                setDeliberationDays(Math.max(0, v));
              }}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[var(--brand-accent)]"
            />
            <p className="text-xs text-gray-400 mt-1">
              0 days skips deliberation (straight to voting).
            </p>
          </div>
          <div>
            <label htmlFor="proposal-voting-days" className="block text-xs text-gray-500 mb-1">
              Voting duration (days)
            </label>
            <input
              id="proposal-voting-days"
              type="number"
              min={0.05}
              step={0.05}
              value={votingDays}
              onChange={e => {
                const v = parseFloat(e.target.value);
                if (Number.isNaN(v)) return;
                setVotingDays(Math.max(0.05, v));
              }}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[var(--brand-accent)]"
            />
            <p className="text-xs text-gray-400 mt-1">
              Minimum 0.05 days (72 minutes) for live polls.
            </p>
          </div>
        </div>
      ) : (
        <div className="rounded-lg border border-gray-200 bg-gray-50 px-4 py-3">
          <p className="text-sm font-medium text-[var(--brand-primary)] mb-1">Durations</p>
          <p className="text-sm text-[#2C3E50]">
            This proposal will use the organization's defaults:{' '}
            <strong>
              Deliberation: {formatDays(orgSettings?.default_deliberation_days ?? 7)}{' '}
              {pluralizeDays(orgSettings?.default_deliberation_days ?? 7)}
            </strong>
            {' / '}
            <strong>
              Voting: {formatDays(orgSettings?.default_voting_days ?? 3)}{' '}
              {pluralizeDays(orgSettings?.default_voting_days ?? 3)}
            </strong>.
          </p>
        </div>
      )}

      {/* Phase 75a — optional absolute voting deadline. Useful when an item
          has a known meeting/decision date. Wins over the voting duration. */}
      <div>
        <label htmlFor="proposal-voting-deadline" className="block text-xs text-gray-500 mb-1">
          Absolute voting deadline (optional)
        </label>
        <input
          id="proposal-voting-deadline"
          type="datetime-local"
          value={votingEndDate}
          onChange={e => setVotingEndDate(e.target.value)}
          className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[var(--brand-accent)]"
        />
        <p className="text-xs text-gray-400 mt-1">
          When set, voting closes at this date (overrides the voting duration).
          Leave blank to use the duration above. Checked at advance time.
        </p>
      </div>

      {/* Phase 9 — Linked Deliberations picker. Backend currently rejects
          linked_polis_ids on parent-org-wide proposals (only org-scoped
          proposals can carry structural links — see routes/proposals.py),
          so the picker only renders when a sub-org scope is selected. */}
      {/* Phase 62 A1 — linked Polises are a structural link captured at
          creation; not editable in draft-edit for now (no PATCH endpoint
          difference, but exposing the picker invites unexpected diffs). */}
      {!isEditMode && scope && (
        <LinkedPolisesPicker
          parentSlug={slug}
          scopeSubOrgId={scope}
          value={linkedPolisIds}
          onChange={setLinkedPolisIds}
          required={requirePolis}
        />
      )}

      {/* Phase 32.2 F1 — Deliberation-engagement override sections,
          mode-aware. Toggles render only when the org mode is
          `default_*` (overridable). When the org mode is `always_*`,
          we render a small "locked by org settings" note instead of
          the toggle. */}
      <div className="bg-[#F4F6F9] border border-gray-200 rounded-lg p-4 space-y-3">
        <p className="text-sm font-semibold text-gray-700">Deliberation Engagement</p>
        {/* Write-ins — hidden for binary voting */}
        {isMultiOption && (
          <div className="space-y-2 pl-2 border-l-2 border-gray-200">
            {writeInsOverridable ? (
              <label className="flex items-start gap-3 cursor-pointer">
                <input
                  type="checkbox"
                  checked={allowWriteIns}
                  onChange={e => setAllowWriteIns(e.target.checked)}
                  className="mt-0.5 accent-[var(--brand-accent)]"
                />
                <div>
                  <p className="text-sm text-gray-700 font-medium">Allow members to add options</p>
                  <p className="text-xs text-gray-500">
                    Members can propose write-in options during deliberation
                    (and optionally voting). Useful for open-ended polls.
                  </p>
                </div>
              </label>
            ) : (
              <p className="text-xs text-gray-500 italic">
                Write-in options: {orgWriteInsAllowed ? 'always on' : 'always off'} (locked by organization settings).
              </p>
            )}
            {writeInsOverridable && allowWriteIns && (
              <div className="pl-6 space-y-2">
                {writeInsDuringVotingOverridable ? (
                  <label className="flex items-start gap-3 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={allowWriteInsDuringVoting}
                      onChange={e => setAllowWriteInsDuringVoting(e.target.checked)}
                      className="mt-0.5 accent-[var(--brand-accent)]"
                    />
                    <span className="text-sm text-gray-700">
                      Allow during voting period too
                      <span className="block text-xs text-gray-500">
                        Members can keep adding options even after voting opens.
                        Voters with cast ballots are notified.
                      </span>
                    </span>
                  </label>
                ) : (
                  <p className="text-xs text-gray-500 italic">
                    Write-ins during voting: {orgWriteInsDuringVoting ? 'always on' : 'always off'} (locked by organization settings).
                  </p>
                )}
                <label className="flex items-center gap-3">
                  <span className="text-sm text-gray-700 min-w-[140px]">
                    Maximum write-ins
                  </span>
                  <input
                    type="number"
                    min={1}
                    max={50}
                    value={maxWriteIns}
                    onChange={e => setMaxWriteIns(e.target.value)}
                    className="w-20 px-2 py-1 border border-gray-300 rounded text-sm"
                  />
                </label>
              </div>
            )}
          </div>
        )}
        {/* Pre-voting */}
        <div className="space-y-2 pl-2 border-l-2 border-gray-200">
          {preVotingOverridable ? (
            <label className="flex items-start gap-3 cursor-pointer">
              <input
                type="checkbox"
                checked={allowPreVoting}
                onChange={e => setAllowPreVoting(e.target.checked)}
                className="mt-0.5 accent-[var(--brand-accent)]"
              />
              <div>
                <p className="text-sm text-gray-700 font-medium">Allow voting during deliberation</p>
                <p className="text-xs text-gray-500">
                  Members can cast and change their votes before voting officially
                  opens. Pre-votes are changeable until voting closes.
                </p>
              </div>
            </label>
          ) : (
            <p className="text-xs text-gray-500 italic">
              Voting during deliberation: {orgPreVotingAllowed ? 'always on' : 'always off'} (locked by organization settings).
            </p>
          )}
          {preVotingOverridable && allowPreVoting && (
            <div className="pl-6">
              {visibilityOverridable ? (
                <label className="flex items-start gap-3 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={showVotesDuringDelib}
                    onChange={e => setShowVotesDuringDelib(e.target.checked)}
                    className="mt-0.5 accent-[var(--brand-accent)]"
                  />
                  <span className="text-sm text-gray-700">
                    Show vote totals during deliberation
                    <span className="block text-xs text-gray-500">
                      Off by default to avoid anchoring. When on, the trajectory
                      chart extends back to deliberation start.
                    </span>
                  </span>
                </label>
              ) : (
                <p className="text-xs text-gray-500 italic">
                  Vote totals during deliberation: {orgShowVotesDuringDelib ? 'always visible' : 'always hidden'} (locked by organization settings).
                </p>
              )}
            </div>
          )}
        </div>
        {/* Editing lockout */}
        <div className="space-y-2 pl-2 border-l-2 border-gray-200">
          <label className="flex items-center gap-3">
            <span className="text-sm text-gray-700 min-w-[200px]">
              Lock editing in final % of deliberation
            </span>
            <input
              type="number"
              min={0}
              max={100}
              step={5}
              value={Math.round(Number(editLockoutFrac) * 100)}
              onChange={e => setEditLockoutFrac(Number(e.target.value) / 100)}
              className="w-20 px-2 py-1 border border-gray-300 rounded text-sm"
            />
            <span className="text-xs text-gray-500">%</span>
          </label>
          <p className="text-xs text-gray-500 pl-2">
            Authors can't edit the proposal once this fraction of deliberation has elapsed.
            Default {Math.round(orgEditLockoutFrac * 100)}%.
          </p>
        </div>
      </div>

      {/* Phase 20 — Stable Result Required toggle (only when org allows override). */}
      {smOverrideAllowed && (
        <div className="bg-[#F4F6F9] border border-gray-200 rounded-lg p-4 space-y-2">
          <label className="flex items-start gap-3 cursor-pointer">
            <input
              type="checkbox"
              checked={smEnabled}
              onChange={e => setSmEnabled(e.target.checked)}
              className="mt-0.5 accent-[var(--brand-accent)]"
            />
            <div>
              <p className="text-sm text-gray-700 font-medium">Stable Result Required</p>
              <p className="text-xs text-gray-500">
                The result must be stable across the closing portion of the voting
                window. Destabilization triggers an extension. Useful for high-stakes
                decisions; overkill for routine matters.{' '}
                <Link to="/help/stable-result" className="text-[var(--brand-accent)] hover:underline">
                  Learn more →
                </Link>
              </p>
              {smEnabled !== orgSmDefault && (
                <p className="text-xs text-amber-600 mt-1">
                  Overriding org default ({orgSmDefault ? 'on' : 'off'}).
                </p>
              )}
            </div>
          </label>
        </div>
      )}

      {error && <p role="alert" className="text-sm text-red-600">{error}</p>}

      <div className="flex gap-2 items-center">
        <button
          type="submit"
          disabled={saving || !title.trim() || !optionsValid || !numWinnersValid || !winnerSelectionValid || !budgetValid || !projectBudgetValid}
          className="text-sm px-4 py-2 bg-[var(--brand-primary)] text-white rounded-lg hover:bg-[var(--brand-accent)] transition-colors disabled:opacity-50"
        >
          {saving
            ? (isEditMode ? 'Saving...' : 'Creating...')
            : (isEditMode ? 'Save Changes' : 'Create Proposal')}
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="text-sm px-4 py-2 border border-gray-300 text-gray-600 rounded-lg hover:bg-gray-50"
        >
          Cancel
        </button>
        {/* Save & advance button (edit mode only, when the caller supplies
            an onAdvance handler — gated upstream on can_advance). Lets an
            author move a draft into deliberation from the editor. We pass
            saveChanges so the handler confirms, persists the open form
            edits, THEN advances — the author never loses in-progress edits.
            The parent owns the confirm dialog + advance API call. */}
        {isEditMode && onAdvance && (
          <button
            type="button"
            onClick={() => onAdvance(saveChanges)}
            disabled={advancing || saving || !title.trim() || !optionsValid || !numWinnersValid || !winnerSelectionValid || !budgetValid || !projectBudgetValid}
            className="text-sm px-4 py-2 bg-[var(--brand-primary)] text-white rounded-lg hover:bg-[var(--brand-accent)] transition-colors disabled:opacity-50"
          >
            {advancing ? 'Advancing…' : (advanceLabel || 'Advance')}
          </button>
        )}
        {/* Phase 62 A3 — Delete-draft button (edit mode only, when caller
            supplies an onDelete handler). Destructive styling; the
            handler is responsible for confirm dialog + navigation. */}
        {isEditMode && onDelete && (
          <button
            type="button"
            onClick={onDelete}
            className="ml-auto text-sm px-4 py-2 border border-red-300 text-red-600 rounded-lg hover:bg-red-50"
          >
            Delete draft
          </button>
        )}
      </div>
    </form>
  );
}

// Phase 62 A3 — re-export under the friendlier name for downstream
// consumers (ProposalDetail wires the edit-mode form). The functional
// alias keeps the existing import paths working without renaming.
export { CreateProposalForm as ProposalForm };


// Phase 72 — review list for a multi-proposal import. Each row is one
// per-item preview result from import-preview ({index, proposal, warnings,
// resolved_topics, errors}). Valid rows are selectable; "Create selected"
// creates them sequentially through the EXISTING single-create endpoint
// (Option A — no batch endpoint). Each created proposal is an independent
// draft, so a mid-batch failure is resume-able: already-created drafts stay,
// remaining rows stay actionable for retry.
function MultiImportReview({ items, slug, onDone, onCancel }) {
  const toast = useToast();
  const canHighVolumeCreate = useHasPermission('proposal.high_volume_create');
  const [rows, setRows] = useState(() => items.map((it, i) => ({
    id: it.index ?? i,
    valid: !!it.proposal && (!it.errors || Object.keys(it.errors).length === 0),
    title: it.proposal?.title ?? `(untitled #${(it.index ?? i) + 1})`,
    payload: it.proposal || null,
    warnings: it.warnings || [],
    errors: it.errors || {},
    // Phase 75b — the AI's topic-assignment reasoning (smart import only).
    aiReasoning: it.ai_reasoning || '',
    selected: !!it.proposal && (!it.errors || Object.keys(it.errors).length === 0),
    created: false,
    failed: null,
  })));
  const [expanded, setExpanded] = useState(null);
  const [creating, setCreating] = useState(false);
  const [progress, setProgress] = useState(null);

  const validCount = rows.filter(r => r.valid).length;
  const selectedRemaining = rows.filter(r => r.selected && r.valid && !r.created);
  const createdCount = rows.filter(r => r.created).length;
  const selectionState = proposalImportSelectionState(
    selectedRemaining.length, canHighVolumeCreate,
  );

  function patchRow(id, patch) {
    setRows(prev => prev.map(r => (r.id === id ? { ...r, ...patch } : r)));
  }

  async function createSelected() {
    if (selectionState.blocked) return;
    setCreating(true);
    const toCreate = rows.filter(r => r.selected && r.valid && !r.created);
    const result = await createProposalRowsSequentially(
      toCreate,
      row => api.post(
        `/api/orgs/${slug}/proposals`,
        { ...row.payload, title: row.title },
      ),
      {
        highVolumeEnabled: canHighVolumeCreate,
        onProgress: (current, total) => setProgress({ current, total }),
        onCreated: row => {
          patchRow(row.id, { created: true, selected: false, failed: null });
        },
        onFailed: (row, error) => {
          patchRow(row.id, { failed: error?.message || 'Create failed' });
        },
      },
    );
    setCreating(false);
    setProgress(null);

    if (result.error) {
      if (result.error?.status === 429) {
        const message = proposalImportRateLimitMessage(
          canHighVolumeCreate, result.created, result.remaining,
        );
        patchRow(result.failedRow.id, { failed: message });
        toast.error(message);
      } else {
        toast.error(
          `${result.created} created, ${result.remaining} remaining — retry the rest.`,
        );
      }
      return;
    }
    toast.success(
      `Created ${result.created} proposal${result.created === 1 ? '' : 's'}.`,
    );
    if (result.remaining === 0) {
      onDone(createdCount + result.created);
    }
  }

  return (
    <div className="bg-white border border-gray-200 rounded-xl p-5 space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-semibold text-[var(--brand-primary)]">
          Review imported proposals
        </h3>
        <button
          type="button"
          onClick={onCancel}
          className="text-sm text-gray-500 hover:text-gray-800"
        >
          Cancel
        </button>
      </div>
      <p className="text-sm text-gray-500">
        {items.length} proposals in this file · {validCount} ready ·{' '}
        {items.length - validCount} with errors. Selected proposals are created
        as drafts; you can review each before they go to deliberation.
      </p>

      {/* Phase 72c — all-invalid is a rendered state, not a blank screen or a
          false success. Every row is still shown below with its errors. */}
      {validCount === 0 && (
        <div className="bg-amber-50 border border-amber-200 rounded-lg p-3 text-sm text-amber-900">
          No proposals are ready to create yet — fix the flagged items below
          (or cancel).
        </div>
      )}

      {(selectionState.note || selectionState.guidance) && (
        <div
          id="proposal-import-create-guidance"
          role={selectionState.blocked ? 'alert' : 'status'}
          aria-live="polite"
          className={`rounded-lg border p-3 text-sm ${
            selectionState.blocked
              ? 'bg-amber-50 border-amber-200 text-amber-900'
              : 'bg-blue-50 border-blue-200 text-blue-900'
          }`}
        >
          {selectionState.guidance || selectionState.note}
        </div>
      )}

      <div className="border border-gray-200 rounded-lg divide-y divide-gray-100">
        {rows.map((row) => (
          <div key={row.id} className="p-3">
            <div className="flex items-center gap-3">
              <input
                type="checkbox"
                disabled={!row.valid || row.created || creating}
                checked={row.selected && !row.created}
                onChange={e => patchRow(row.id, { selected: e.target.checked })}
                className="h-4 w-4"
              />
              {row.valid ? (
                <input
                  type="text"
                  value={row.title}
                  disabled={row.created || creating}
                  onChange={e => patchRow(row.id, { title: e.target.value })}
                  className="flex-1 px-2 py-1 text-sm border border-gray-200 rounded focus:outline-none focus:ring-1 focus:ring-[var(--brand-accent)] disabled:bg-gray-50 disabled:text-gray-500"
                />
              ) : (
                <span className="flex-1 text-sm text-gray-700">{row.title}</span>
              )}
              {row.created ? (
                <span className="text-xs px-2 py-0.5 rounded-full bg-green-100 text-green-700 font-medium">Created ✓</span>
              ) : row.failed ? (
                <span className="text-xs px-2 py-0.5 rounded-full bg-red-100 text-red-700 font-medium">Failed</span>
              ) : row.valid ? (
                <span className="text-xs px-2 py-0.5 rounded-full bg-blue-100 text-blue-700 font-medium">Ready</span>
              ) : (
                <span className="text-xs px-2 py-0.5 rounded-full bg-amber-100 text-amber-800 font-medium">Has errors</span>
              )}
              {row.payload && (
                <button
                  type="button"
                  onClick={() => setExpanded(expanded === row.id ? null : row.id)}
                  className="text-xs text-gray-500 hover:text-[var(--brand-accent)]"
                >
                  {expanded === row.id ? 'Hide' : 'View'}
                </button>
              )}
            </div>

            {row.failed && (
              <p className="mt-2 ml-7 text-xs text-red-600">{row.failed}</p>
            )}

            {Object.keys(row.errors).length > 0 && (
              <div className="mt-2 ml-7 text-xs text-red-700 space-y-0.5">
                {Object.entries(row.errors).map(([field, msgs]) => (
                  (Array.isArray(msgs) ? msgs : [msgs]).map((m, i) => (
                    <div key={`${field}-${i}`}>
                      {field !== '_item' && field !== '_file' && (
                        <span className="font-medium">{field}: </span>
                      )}{m}
                    </div>
                  ))
                ))}
              </div>
            )}

            {row.warnings.length > 0 && (
              <ul className="mt-2 ml-7 text-xs text-blue-800 list-disc list-inside space-y-0.5">
                {row.warnings.map((w, i) => <li key={i}>{w}</li>)}
              </ul>
            )}

            {/* Phase 75b — the AI's reasoning for this draft (smart import). */}
            {row.aiReasoning && (
              <p className="mt-1 ml-7 text-xs text-purple-700 italic">
                <span className="font-medium not-italic">AI:</span> {row.aiReasoning}
              </p>
            )}

            {expanded === row.id && row.payload && (
              <div className="mt-2 ml-7 text-xs text-gray-600 bg-gray-50 border border-gray-100 rounded p-2 space-y-1">
                <div><span className="font-medium">Method:</span> {row.payload.voting_method}</div>
                {row.payload.body && (
                  <div><span className="font-medium">Body:</span> {String(row.payload.body).slice(0, 200)}{String(row.payload.body).length > 200 ? '…' : ''}</div>
                )}
                {Array.isArray(row.payload.options) && row.payload.options.length > 0 && (
                  <div><span className="font-medium">Options:</span> {row.payload.options.map(o => o.label).join(', ')}</div>
                )}
                {Array.isArray(row.payload.topics) && row.payload.topics.length > 0 && (
                  <div><span className="font-medium">Topics:</span> {row.payload.topics.length}</div>
                )}
                {row.payload.pass_threshold != null && (
                  <div><span className="font-medium">Pass threshold:</span> {row.payload.pass_threshold}</div>
                )}
                {row.payload.voting_days != null && (
                  <div><span className="font-medium">Voting days:</span> {row.payload.voting_days}</div>
                )}
              </div>
            )}
          </div>
        ))}
      </div>

      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={createSelected}
          disabled={
            creating || selectedRemaining.length === 0 || selectionState.blocked
          }
          aria-describedby={
            selectionState.note || selectionState.guidance
              ? 'proposal-import-create-guidance'
              : undefined
          }
          className="text-sm px-4 py-2 bg-[var(--brand-primary)] text-white rounded-lg hover:bg-[var(--brand-accent)] transition-colors disabled:opacity-50"
        >
          {creating
            ? `Creating ${progress?.current ?? 0} of ${progress?.total ?? 0}…`
            : `Create selected (${selectedRemaining.length})`}
        </button>
        {createdCount > 0 && (
          <span className="text-xs text-gray-500">{createdCount} created so far</span>
        )}
        <button
          type="button"
          onClick={() => onDone(createdCount)}
          disabled={creating}
          className="text-sm px-3 py-2 border border-gray-300 text-gray-600 rounded-lg hover:bg-gray-50"
        >
          Done
        </button>
      </div>
    </div>
  );
}


export default function ProposalManagement() {
  const { currentOrg, fetchSubOrgsFor } = useOrg();
  const toast = useToast();
  const confirm = useConfirm();
  // Phase 12.5 F2 — per-control permission gating.
  const canCreateProposal = useHasPermission('proposal.create');
  const canAdvancePhase = useHasPermission('proposal.advance_phase');
  const [proposals, setProposals] = useState([]);
  const [topics, setTopics] = useState([]);
  const [subOrgs, setSubOrgs] = useState([]);
  const [loading, setLoading] = useState(true);
  // Phase 25 F1 — open directly on the create form when the inbound
  // link was /admin/proposals?create=1 (e.g. clicking "Create proposal"
  // on the public Proposals page). Otherwise default to the list view.
  const [searchParams, setSearchParams] = useSearchParams();
  const [showCreate, setShowCreate] = useState(searchParams.get('create') === '1');
  const [expandedId, setExpandedId] = useState(null);
  const [proposalSelection, setProposalSelection] = useState(
    () => ({ slug: null, ids: new Set() }),
  );
  const [bulkAdvanceWorking, setBulkAdvanceWorking] = useState(false);
  const selectAllDraftsRef = useRef(null);
  // Phase 72 — when an import file carries 2+ proposals, the create form
  // hands the per-item preview results here and we render the review list.
  const [multiImportItems, setMultiImportItems] = useState(null);

  const slug = currentOrg?.slug;
  const selectedProposalIds = proposalSelection.slug === slug
    ? proposalSelection.ids
    : new Set();
  const updateSelectedProposalIds = useCallback((updater) => {
    setProposalSelection(previous => {
      const current = previous.slug === slug ? previous.ids : new Set();
      const next = typeof updater === 'function' ? updater(current) : updater;
      return { slug, ids: next };
    });
  }, [slug]);
  const visibleDraftIds = useMemo(
    () => visibleDraftProposalIds(proposals),
    [proposals],
  );
  const selectedCount = selectedProposalIds.size;
  const allVisibleDraftsSelected = visibleDraftIds.length > 0
    && visibleDraftIds.every(id => selectedProposalIds.has(id));

  useEffect(() => {
    if (selectAllDraftsRef.current) {
      selectAllDraftsRef.current.indeterminate = selectedCount > 0
        && !allVisibleDraftsSelected;
    }
  }, [selectedCount, allVisibleDraftsSelected]);

  const load = useCallback(async () => {
    if (!slug) return;
    try {
      const [props, tops] = await Promise.all([
        api.get(`/api/orgs/${slug}/proposals`),
        api.get(`/api/orgs/${slug}/topics`),
      ]);
      setProposals(props);
      const eligibleDrafts = new Set(visibleDraftProposalIds(props));
      setProposalSelection(previous => {
        if (previous.slug !== slug || !canAdvancePhase) {
          return { slug, ids: new Set() };
        }
        return {
          slug,
          ids: new Set([...previous.ids].filter(id => eligibleDrafts.has(id))),
        };
      });
      setTopics(tops);
    } catch { /* ignore */ } finally {
      setLoading(false);
    }
    // Phase 8.5 — fetch sub-orgs only when at parent-org scope.
    if (currentOrg && !currentOrg.parent_org_id) {
      try {
        const subs = await fetchSubOrgsFor(slug);
        setSubOrgs(subs || []);
      } catch { setSubOrgs([]); }
    }
  }, [slug, currentOrg, fetchSubOrgsFor, canAdvancePhase]);

  useEffect(() => {
    // Existing page-load synchronization: load owns the loading-state update.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    load();
  }, [load]);

  if (!currentOrg) return <div className="text-center py-16 text-gray-400">No organization selected</div>;
  if (loading) return (
    <div className="flex justify-center items-center py-20">
      <div className="animate-spin w-8 h-8 border-4 border-[var(--brand-accent)] border-t-transparent rounded-full"></div>
    </div>
  );

  async function handleAdvance(proposalId) {
    try {
      // Phase 25 B1.2 — backend now derives voting_end from the proposal's
      // voting_days (or the org default) at the deliberation → voting
      // transition. Sending an explicit voting_end here was a legacy
      // hardcoded 7-day literal that ignored Phase 16 per-proposal overrides.
      await api.post(`/api/orgs/${slug}/proposals/${proposalId}/advance`, {});
      toast.success('Proposal advanced');
      load();
    } catch (e) {
      toast.error(e.message);
    }
  }

  async function handleWithdraw(proposalId) {
    const ok = await confirm({
      title: 'Withdraw Proposal',
      message: 'Withdraw this proposal? It will be marked as failed.',
      destructive: true,
    });
    if (!ok) return;
    try {
      await api.post(`/api/orgs/${slug}/proposals/${proposalId}/advance`, {});
      toast.success('Proposal withdrawn');
      load();
    } catch (e) {
      toast.error(e.message);
    }
  }

  function toggleProposalSelection(proposalId) {
    updateSelectedProposalIds(previous => {
      const next = new Set(previous);
      if (next.has(proposalId)) next.delete(proposalId);
      else next.add(proposalId);
      return next;
    });
  }

  function toggleAllVisibleDrafts() {
    updateSelectedProposalIds(previous => {
      const next = new Set(previous);
      if (allVisibleDraftsSelected) {
        visibleDraftIds.forEach(id => next.delete(id));
      } else {
        visibleDraftIds.forEach(id => next.add(id));
      }
      return next;
    });
  }

  async function handleBulkAdvanceToDeliberation() {
    if (!canAdvancePhase || bulkAdvanceWorking || selectedCount === 0) return;
    const snapshot = [...selectedProposalIds];
    const selectedRows = snapshot
      .map(id => proposals.find(proposal => proposal.id === id))
      .filter(Boolean);
    const shownTitles = selectedRows.slice(0, 5).map(proposal => `“${proposal.title}”`);
    const remainingCount = Math.max(0, selectedRows.length - shownTitles.length);
    const titleList = [
      shownTitles.join(', '),
      remainingCount ? `and ${remainingCount} more` : '',
    ].filter(Boolean).join(' ');
    const ok = await confirm({
      title: 'Advance selected drafts?',
      message: [
        `${currentOrg.name}: move ${snapshot.length} selected ${snapshot.length === 1 ? 'draft' : 'drafts'} to deliberation?`,
        'Only proposals that are still drafts will move, and their deliberation timing starts immediately.',
        titleList,
      ].filter(Boolean).join(' '),
    });
    if (!ok) return;

    const responses = [];
    const completedIds = new Set();
    setBulkAdvanceWorking(true);
    try {
      for (const proposalIds of chunkProposalIds(snapshot)) {
        const response = await api.post(
          `/api/orgs/${slug}/proposals/bulk-advance-to-deliberation`,
          { proposal_ids: proposalIds },
        );
        responses.push(response);
        (response.results || []).forEach(result => completedIds.add(result.proposal_id));
      }
      const summary = aggregateBulkAdvanceResponses(responses);
      updateSelectedProposalIds(previous => new Set(
        [...previous].filter(id => !completedIds.has(id)),
      ));
      const message = bulkAdvanceSummaryMessage(summary);
      if (summary.couldNotAdvance > 0) toast.error(message);
      else toast.success(message);
    } catch (error) {
      const summary = aggregateBulkAdvanceResponses(responses);
      updateSelectedProposalIds(previous => new Set(
        [...previous].filter(id => !completedIds.has(id)),
      ));
      const completedMessage = responses.length
        ? `${bulkAdvanceSummaryMessage(summary)} `
        : '';
      toast.error(
        `${completedMessage}The remaining selected drafts were not submitted. ${error.message || 'Try again.'}`,
      );
    } finally {
      await load();
      setBulkAdvanceWorking(false);
    }
  }

  // Phase 8 — resolve a legacy sustained-majority escalation. Phase 20
  // removed the escalate mechanism going forward; this handler is kept
  // for the rare case that historic proposals still carry status=unresolved.
  async function handleResolveEscalation(proposalId, action, reason = '') {
    try {
      const payload = { action };
      if (reason) payload.reason = reason;
      await api.post(
        `/api/orgs/${slug}/proposals/${proposalId}/resolve_escalation`,
        payload,
      );
      toast.success(`Escalation resolved: ${action}`);
      load();
    } catch (e) {
      toast.error(e.message || 'Failed to resolve');
    }
  }

  return (
    <div className="max-w-4xl mx-auto px-4 py-8 space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold text-[var(--brand-primary)]">Proposal Management</h1>
        {/* Phase 12.5 F2 — Create button gated on `proposal.create`. */}
        {!showCreate && canCreateProposal && (
          <button
            onClick={() => setShowCreate(true)}
            className="text-sm px-4 py-2 bg-[var(--brand-primary)] text-white rounded-lg hover:bg-[var(--brand-accent)] transition-colors"
          >
            Create Proposal
          </button>
        )}
      </div>

      {/* Phase 72 — multi-proposal review list takes over when an import
          file carried 2+ proposals. */}
      {multiImportItems && (
        <MultiImportReview
          items={multiImportItems}
          slug={slug}
          onDone={() => {
            setMultiImportItems(null);
            setShowCreate(false);
            if (searchParams.has('create')) {
              searchParams.delete('create');
              setSearchParams(searchParams, { replace: true });
            }
            load();
          }}
          onCancel={() => setMultiImportItems(null)}
        />
      )}

      {showCreate && !multiImportItems && (
        <CreateProposalForm
          slug={slug}
          orgSettings={currentOrg.settings}
          topics={topics}
          subOrgs={subOrgs}
          onMultiImport={setMultiImportItems}
          onCreated={() => {
            setShowCreate(false);
            // Phase 25 F1 — strip ?create=1 so back/refresh doesn't
            // re-open the form unexpectedly.
            if (searchParams.has('create')) {
              searchParams.delete('create');
              setSearchParams(searchParams, { replace: true });
            }
            load();
          }}
          onCancel={() => {
            setShowCreate(false);
            if (searchParams.has('create')) {
              searchParams.delete('create');
              setSearchParams(searchParams, { replace: true });
            }
          }}
        />
      )}

      {canAdvancePhase && selectedCount > 0 && (
        <div className="sticky top-2 z-10 flex flex-wrap items-center gap-3 rounded-xl border border-blue-200 bg-blue-50 px-4 py-3 shadow-sm">
          <span className="mr-auto text-sm font-medium text-blue-900">
            {selectedCount} {selectedCount === 1 ? 'draft selected' : 'drafts selected'}
          </span>
          <button
            type="button"
            disabled={bulkAdvanceWorking}
            onClick={() => updateSelectedProposalIds(new Set())}
            className="min-h-11 rounded-lg border border-blue-300 px-3 py-2 text-sm text-blue-800 hover:bg-blue-100 disabled:opacity-50"
          >
            Clear selection
          </button>
          <button
            type="button"
            disabled={bulkAdvanceWorking}
            onClick={handleBulkAdvanceToDeliberation}
            className="min-h-11 rounded-lg bg-[var(--brand-primary)] px-4 py-2 text-sm font-medium text-white hover:bg-[var(--brand-accent)] disabled:opacity-50"
          >
            {bulkAdvanceWorking ? 'Advancing selected drafts…' : 'Advance selected to deliberation'}
          </button>
        </div>
      )}

      {/* Proposals Table */}
      <div className="bg-white border border-gray-200 rounded-xl overflow-hidden">
        <div className="flex items-center gap-4 px-4 py-2 bg-gray-50 text-xs font-medium text-gray-500 uppercase">
          {canAdvancePhase && (
            <span className="flex w-11 shrink-0 items-center justify-center">
              <input
                ref={selectAllDraftsRef}
                type="checkbox"
                checked={allVisibleDraftsSelected}
                disabled={bulkAdvanceWorking || visibleDraftIds.length === 0}
                onChange={toggleAllVisibleDrafts}
                aria-label="Select all visible draft proposals"
                className="h-6 w-6 rounded border-gray-300 accent-[var(--brand-primary)] disabled:opacity-50"
              />
            </span>
          )}
          <span className="flex-1">Title</span>
          <span className="w-24">Status</span>
          <span className="hidden w-28 sm:block">Created</span>
          <span className="w-4" />
        </div>
        {proposals.length === 0 ? (
          <div className="px-4 py-8 text-center text-gray-400 text-sm">No proposals yet</div>
        ) : (
          proposals.map(p => (
            <div key={p.id} className="border-t border-gray-100">
              <div
                onClick={() => setExpandedId(expandedId === p.id ? null : p.id)}
                className="flex items-center gap-4 px-4 py-3 text-sm cursor-pointer hover:bg-gray-50 transition-colors"
              >
                {canAdvancePhase && (
                  <span className="flex w-11 shrink-0 items-center justify-center">
                    {p.status === 'draft' && (
                      <input
                        type="checkbox"
                        checked={selectedProposalIds.has(p.id)}
                        disabled={bulkAdvanceWorking}
                        onClick={event => event.stopPropagation()}
                        onChange={() => toggleProposalSelection(p.id)}
                        aria-label={`Select draft: ${p.title}`}
                        className="h-6 w-6 rounded border-gray-300 accent-[var(--brand-primary)] disabled:opacity-50"
                      />
                    )}
                  </span>
                )}
                <span className="flex-1 font-medium text-gray-800">
                  {p.title}
                  {p.voting_method === 'approval' && (
                    <span className="ml-2 text-xs bg-purple-100 text-purple-700 px-1.5 py-0.5 rounded">Approval</span>
                  )}
                  {p.voting_method === 'ranked_choice' && (
                    <span className="ml-2 text-xs bg-indigo-100 text-indigo-700 px-1.5 py-0.5 rounded">
                      {(p.num_winners ?? 1) > 1 ? `STV (${p.num_winners})` : 'IRV'}
                    </span>
                  )}
                </span>
                <span className="w-24"><StatusBadge status={p.status} /></span>
                <span className="hidden w-28 text-xs text-gray-400 sm:block">{new Date(p.created_at).toLocaleDateString()}</span>
                <svg className={`w-4 h-4 text-gray-400 transition-transform ${expandedId === p.id ? 'rotate-180' : ''}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                </svg>
              </div>
              {expandedId === p.id && (
                <div className="px-4 py-3 bg-gray-50 flex items-center flex-wrap gap-3">
                  {/* Phase 70 — "View proposal page" navigates to the
                      member-facing proposal detail (the same route a member
                      reaches it by) so an admin can see it as members do.
                      Pure navigation; present for every status. */}
                  <Link
                    to={`/${slug}/proposals/${p.id}`}
                    className="text-xs px-3 py-1.5 border border-gray-300 text-gray-600 rounded-lg hover:bg-gray-100"
                  >
                    View proposal page →
                  </Link>
                  {/* Phase 12.5 F2 — phase-advance buttons gated on
                      `proposal.advance_phase`. Withdraw also routes through
                      the same advance endpoint, so we gate it identically. */}
                  {p.status === 'draft' && (
                    <>
                      {canAdvancePhase && (
                        <button
                          onClick={() => handleAdvance(p.id)}
                          className="text-xs px-3 py-1.5 bg-[var(--brand-accent)] text-white rounded-lg hover:bg-[var(--brand-primary)]"
                        >
                          Advance to Deliberation
                        </button>
                      )}
                      {/* Phase 59 A1 — was `<a href="/proposals/{id}">`,
                          a flat non-org-scoped URL that fell through to
                          App.jsx's catch-all and redirected to `/`. Now
                          a react-router <Link> to the org-scoped
                          proposal detail route, which renders
                          ProposalDetail (the voter-facing page) where
                          the Phase 32.2 author-edit affordance lives
                          (extended in A2/A3 to cover draft status). */}
                      <Link
                        to={`/${slug}/proposals/${p.id}`}
                        className="text-xs px-3 py-1.5 border border-gray-300 text-gray-600 rounded-lg hover:bg-gray-100"
                      >
                        Edit Draft
                      </Link>
                    </>
                  )}
                  {p.status === 'deliberation' && canAdvancePhase && (
                    <button
                      onClick={() => handleAdvance(p.id)}
                      className="text-xs px-3 py-1.5 bg-[var(--brand-accent)] text-white rounded-lg hover:bg-[var(--brand-primary)]"
                    >
                      Advance to Voting
                    </button>
                  )}
                  {p.status === 'voting' && canAdvancePhase && (
                    <button
                      onClick={() => handleAdvance(p.id)}
                      className="text-xs px-3 py-1.5 bg-[var(--brand-accent)] text-white rounded-lg hover:bg-[var(--brand-primary)]"
                    >
                      Close Voting
                    </button>
                  )}
                  {(p.status === 'draft' || p.status === 'deliberation' || p.status === 'voting') && canAdvancePhase && (
                    <button
                      onClick={() => handleWithdraw(p.id)}
                      className="text-xs px-3 py-1.5 border border-red-300 text-red-600 rounded-lg hover:bg-red-50"
                    >
                      Withdraw
                    </button>
                  )}
                  {(p.status === 'passed' || p.status === 'failed') && (
                    <span className="text-xs text-gray-400">This proposal is closed.</span>
                  )}
                  {p.status === 'unresolved' && (
                    <EscalationResolutionPanel
                      proposalId={p.id}
                      onResolve={handleResolveEscalation}
                    />
                  )}
                </div>
              )}
            </div>
          ))
        )}
      </div>
    </div>
  );
}


// Phase 8 — escalation resolution UI for `unresolved` proposals.
function EscalationResolutionPanel({ proposalId, onResolve }) {
  const [action, setAction] = useState(null);
  const [reason, setReason] = useState('');

  const requiresReason = action === 'pass';

  if (!action) {
    return (
      <div className="flex flex-col gap-2 w-full">
        <div className="bg-amber-50 border border-amber-200 rounded-lg px-3 py-2 text-xs text-amber-800">
          <strong>Awaiting admin review.</strong> Escalated by the legacy
          sustained-majority feature (now Stable Result Required). Phase 20
          removed the escalate mechanism going forward, but legacy
          escalations remain resolvable here.
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            onClick={() => setAction('extend')}
            className="text-xs px-3 py-1.5 border border-[var(--brand-accent)] text-[var(--brand-accent)] rounded-lg hover:bg-blue-50"
          >
            Extend Window
          </button>
          <button
            onClick={() => setAction('fail')}
            className="text-xs px-3 py-1.5 border border-gray-300 text-gray-700 rounded-lg hover:bg-gray-100"
          >
            Mark Failed
          </button>
          <button
            onClick={() => setAction('pass')}
            className="text-xs px-3 py-1.5 border border-amber-400 text-amber-700 rounded-lg hover:bg-amber-50"
          >
            Mark Passed (override)
          </button>
          <button
            onClick={() => setAction('back_to_deliberation')}
            className="text-xs px-3 py-1.5 border border-gray-300 text-gray-700 rounded-lg hover:bg-gray-100"
          >
            Back to Deliberation
          </button>
          <a
            href={`/admin/audit?target_id=${proposalId}`}
            className="text-xs px-3 py-1.5 text-[var(--brand-accent)] hover:underline"
          >
            View breach history →
          </a>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2 w-full">
      <p className="text-xs text-gray-700">
        Confirm: <strong className="text-[var(--brand-primary)]">{action.replace(/_/g, ' ')}</strong>
        {requiresReason && <span className="text-red-600"> — reason required for override</span>}
      </p>
      {(requiresReason || action === 'extend') && (
        <textarea
          value={reason}
          onChange={e => setReason(e.target.value)}
          placeholder={requiresReason ? 'Why are you overriding the failure?' : 'Reason (optional)'}
          rows={2}
          className="w-full px-2 py-1.5 border border-gray-300 rounded text-xs focus:outline-none focus:ring-2 focus:ring-[var(--brand-accent)] resize-none"
        />
      )}
      <div className="flex gap-2">
        <button
          onClick={() => onResolve(proposalId, action, reason.trim())}
          disabled={requiresReason && !reason.trim()}
          className="text-xs px-3 py-1.5 bg-[var(--brand-primary)] text-white rounded-lg hover:bg-[var(--brand-accent)] disabled:opacity-50"
        >
          Confirm
        </button>
        <button
          onClick={() => { setAction(null); setReason(''); }}
          className="text-xs px-3 py-1.5 border border-gray-300 text-gray-600 rounded-lg hover:bg-gray-50"
        >
          Cancel
        </button>
      </div>
    </div>
  );
}

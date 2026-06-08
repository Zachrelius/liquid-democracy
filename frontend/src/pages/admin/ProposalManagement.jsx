import { useState, useEffect, useCallback, useMemo } from 'react';
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
// Phase 12.5 F2 — per-control permission gating.
import { useHasPermission } from '../../hooks/useHasPermission';
// Phase 52 Stage 1 — shared verification state label tables.
import { VERIFICATION_STATE_OPTIONS } from '../../verificationLabels';

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

function OptionsEditor({ options, onChange }) {
  function updateOption(idx, field, value) {
    const updated = options.map((o, i) => i === idx ? { ...o, [field]: value } : o);
    onChange(updated);
  }

  function addOption() {
    if (options.length >= 20) return;
    onChange([...options, { label: '', description: '' }]);
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
          Options ({options.length}/20)
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
          <div key={idx} className="bg-gray-50 border border-gray-200 rounded-lg p-3 space-y-2">
            <div className="flex items-center gap-2">
              <span className="text-xs text-gray-400 w-6">{idx + 1}.</span>
              <input
                type="text"
                value={opt.label}
                onChange={e => updateOption(idx, 'label', e.target.value)}
                placeholder="Option label (required)"
                maxLength={200}
                className={`flex-1 px-2 py-1.5 border rounded text-sm focus:outline-none focus:ring-2 focus:ring-[var(--brand-accent)] ${isDuplicate ? 'border-red-400' : 'border-gray-300'}`}
              />
              <div className="flex gap-1">
                <button type="button" onClick={() => moveOption(idx, -1)} disabled={idx === 0}
                  className="text-gray-400 hover:text-gray-600 disabled:opacity-30 text-xs px-1">
                  &#x25b2;
                </button>
                <button type="button" onClick={() => moveOption(idx, 1)} disabled={idx === options.length - 1}
                  className="text-gray-400 hover:text-gray-600 disabled:opacity-30 text-xs px-1">
                  &#x25bc;
                </button>
              </div>
              <button type="button" onClick={() => removeOption(idx)}
                className="text-red-400 hover:text-red-600 text-sm px-1">
                &#x2715;
              </button>
            </div>
            {isDuplicate && <p className="text-xs text-red-500 ml-8">Duplicate label</p>}
            <textarea
              value={opt.description}
              onChange={e => updateOption(idx, 'description', e.target.value)}
              placeholder="Description (optional)"
              maxLength={2000}
              rows={2}
              className="w-full ml-8 px-2 py-1.5 border border-gray-300 rounded text-xs focus:outline-none focus:ring-2 focus:ring-[var(--brand-accent)] resize-none"
              style={{ width: 'calc(100% - 2rem)' }}
            />
          </div>
        );
      })}
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
  const [options, setOptions] = useState(() => {
    if (isEditMode && Array.isArray(editingProposal.options) && editingProposal.options.length > 0) {
      return editingProposal.options.map(o => ({
        label: o.label ?? '',
        description: o.description ?? '',
      }));
    }
    return [{ label: '', description: '' }, { label: '', description: '' }];
  });
  const [numWinners, setNumWinners] = useState(() => (
    isEditMode ? (editingProposal.num_winners ?? 1) : 1
  ));
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
  const isMultiOption = votingMethod === 'approval' || votingMethod === 'ranked_choice';

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

  async function handleSubmit(e) {
    e.preventDefault();
    // Phase 9 — block submission when require_polis_for_new_proposals is
    // true and the picker is empty. Server enforces this too; we surface
    // it inline so the operator doesn't round-trip a 400.
    if (!isEditMode && requirePolis && (linkedPolisIds || []).length === 0 && scope) {
      setError('At least one linked Polis is required for proposals in this scope.');
      return;
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
      if (!ok) return;
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
      // Phase 62 A1 — sub_org_id is set only on create. Edit mode keeps
      // the proposal's existing scope; the PATCH endpoint does not accept
      // a scope change.
      if (!isEditMode && scope) payload.sub_org_id = scope;
      if (isMultiOption) {
        payload.options = options.map(o => ({
          label: o.label.trim(),
          description: o.description.trim(),
        }));
      }
      if (votingMethod === 'ranked_choice') {
        payload.num_winners = numWinners;
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
      onCreated();
    } catch (err) {
      setError(err.message || (isEditMode ? 'Failed to save changes' : 'Failed to create proposal'));
    } finally {
      setSaving(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="bg-white border border-gray-200 rounded-xl p-5 space-y-4">
      <h3 className="text-lg font-semibold text-[var(--brand-primary)]">
        {isEditMode ? 'Edit Draft Proposal' : 'Create Proposal'}
      </h3>

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
        </div>
      </div>

      <div>
        <label className="block text-xs text-gray-500 mb-1">Title</label>
        <input
          type="text"
          value={title}
          onChange={e => setTitle(e.target.value)}
          required
          className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[var(--brand-accent)]"
        />
      </div>

      <div>
        <label className="block text-xs text-gray-500 mb-1">Body (markdown supported)</label>
        <textarea
          value={body}
          onChange={e => setBody(e.target.value)}
          rows={6}
          className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[var(--brand-accent)] resize-none font-mono"
        />
      </div>

      {/* Options Editor (approval and ranked-choice) */}
      {isMultiOption && (
        <OptionsEditor options={options} onChange={setOptions} />
      )}

      {/* num_winners input (ranked-choice only) */}
      {votingMethod === 'ranked_choice' && (
        <div>
          <label className="block text-xs text-gray-500 mb-1">Number of Winners</label>
          <input
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
          <label className="block text-xs font-medium text-gray-700 mb-1">
            Identity verification required to vote
          </label>
          <select
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
            <label className="block text-xs text-gray-500 mb-1">
              Jurisdiction (optional)
            </label>
            <input
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
        <div>
          <label className="block text-xs text-gray-500 mb-2">
            Topics ({inScopeTopics.length} in scope)
          </label>
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
        </div>
      )}

      {/* Phase 12.5 F3 — threshold sliders are gated on `proposal.set_thresholds`.
          Members granted `proposal.create` but not this key see the explanatory
          notice in lieu of the inputs; backend uses the org defaults. */}
      {canSetThresholds ? (
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-xs text-gray-500 mb-1">
              Pass Threshold: {Math.round(passThreshold * 100)}%
            </label>
            <input
              type="range"
              min={0}
              max={100}
              value={Math.round(passThreshold * 100)}
              onChange={e => setPassThreshold(parseInt(e.target.value) / 100)}
              className="w-full accent-[var(--brand-accent)]"
            />
          </div>
          <div>
            <label className="block text-xs text-gray-500 mb-1">
              Quorum Threshold: {Math.round(quorumThreshold * 100)}%
            </label>
            <input
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
            <label className="block text-xs text-gray-500 mb-1">
              Deliberation duration (days)
            </label>
            <input
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
            <label className="block text-xs text-gray-500 mb-1">
              Voting duration (days)
            </label>
            <input
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

      {error && <p className="text-sm text-red-600">{error}</p>}

      <div className="flex gap-2 items-center">
        <button
          type="submit"
          disabled={saving || !title.trim() || !optionsValid || !numWinnersValid}
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

  const slug = currentOrg?.slug;

  const load = useCallback(async () => {
    if (!slug) return;
    try {
      const [props, tops] = await Promise.all([
        api.get(`/api/orgs/${slug}/proposals`),
        api.get(`/api/orgs/${slug}/topics`),
      ]);
      setProposals(props);
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
  }, [slug, currentOrg, fetchSubOrgsFor]);

  useEffect(() => { load(); }, [load]);

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

      {showCreate && (
        <CreateProposalForm
          slug={slug}
          orgSettings={currentOrg.settings}
          topics={topics}
          subOrgs={subOrgs}
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

      {/* Proposals Table */}
      <div className="bg-white border border-gray-200 rounded-xl overflow-hidden">
        <div className="flex items-center gap-4 px-4 py-2 bg-gray-50 text-xs font-medium text-gray-500 uppercase">
          <span className="flex-1">Title</span>
          <span className="w-24">Status</span>
          <span className="w-28">Created</span>
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
                <span className="w-28 text-xs text-gray-400">{new Date(p.created_at).toLocaleDateString()}</span>
                <svg className={`w-4 h-4 text-gray-400 transition-transform ${expandedId === p.id ? 'rotate-180' : ''}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                </svg>
              </div>
              {expandedId === p.id && (
                <div className="px-4 py-3 bg-gray-50 flex items-center gap-3">
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

import { useEffect, useState, useCallback, useMemo } from 'react';
import { Link } from 'react-router-dom';
import api from '../../api';
import useSubOrg from '../../useSubOrg';
import { urlFor } from '../../utils/urls';
import { useToast } from '../../components/Toast';
import StatusBadge from '../../components/StatusBadge';
import SubOrgErrorState from '../../components/SubOrgErrorState';
import LinkedPolisesPicker from '../../components/LinkedPolisesPicker';
// Phase 12.5 F2/F3 — per-control + threshold gating.
import { useHasPermission } from '../../hooks/useHasPermission';
// Phase 56 F3 — markdown renderer reused for the topic-guidance hint in
// the sub-org proposal-creation topic picker.
import renderMarkdown from '../../utils/renderMarkdown';

/**
 * Phase 8.5 — Sub-Org Proposals admin page.
 *
 * Lists proposals scoped to this sub-org plus a Create form pre-locked to the
 * sub-org. Topic dropdown shows parent-org-wide topics + this sub-org's topics
 * (Decision 3: sub-org proposals can use either of those, not other sub-orgs').
 *
 * Voting-method gating goes through `get_org_config` server-side, but for the
 * client we read the sub-org's own settings or fall back to the parent.
 */
export default function SubOrgProposals() {
  const { parentSlug, subSlug, subOrg, loading: subLoading, error } = useSubOrg();
  // Phase 12.5 F2 — Create button gated on `proposal.create`. The hook
  // resolves against the parent-org's user_permissions because sub-org
  // proposals are routed through the parent org's permission set
  // (sub-org-level permissions are out of scope for 12.5).
  const canCreateProposal = useHasPermission('proposal.create');

  const [proposals, setProposals] = useState([]);
  const [topics, setTopics] = useState([]);
  const [parentSettings, setParentSettings] = useState({});
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);

  const load = useCallback(async () => {
    if (!parentSlug || !subOrg) return;
    setLoading(true);
    try {
      const [allProps, allTopics, parentOrg] = await Promise.all([
        api.get(`/api/orgs/${parentSlug}/proposals`),
        api.get(`/api/orgs/${parentSlug}/topics`),
        api.get(`/api/orgs/${parentSlug}`).catch(() => null),
      ]);
      setProposals((allProps || []).filter(p => p.sub_org_id === subOrg.id));
      // Topics in scope for sub-org proposals: parent-org-wide (sub_org_id null)
      // OR this sub-org's topics. Decision 3 forbids other sub-orgs' topics.
      setTopics((allTopics || []).filter(t => t.sub_org_id === null || t.sub_org_id === subOrg.id));
      setParentSettings(parentOrg?.settings || {});
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

  // Resolve effective settings via the sub-org → parent walk (mirroring
  // backend `get_org_config`).
  const effectiveSettings = { ...parentSettings, ...(subOrg.settings || {}) };
  // For null overrides we want the parent value back; remove keys explicitly
  // set to null so the parent fallback wins.
  Object.keys(subOrg.settings || {}).forEach(k => {
    if ((subOrg.settings || {})[k] === null) {
      effectiveSettings[k] = parentSettings[k];
    }
  });

  return (
    <div className="max-w-4xl mx-auto px-4 py-8 space-y-6">
      <div>
        <p className="text-xs text-gray-400 mb-1">
          <Link to={urlFor(parentSlug, 'admin-sub-orgs')} className="hover:underline">Sub-organizations</Link>
          {' / '}
          <Link to={urlFor(parentSlug, 'admin-sub-org-settings', subSlug)} className="hover:underline">{subOrg.name}</Link>
        </p>
        <div className="flex items-center justify-between">
          <h1 className="text-2xl font-semibold text-[var(--brand-primary)]">{subOrg.name} — Proposals</h1>
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
        <p className="text-xs text-gray-500 mt-1">
          Proposals scoped to this sub-org. Only sub-org members can vote.
        </p>
      </div>

      {showCreate && (
        <CreateProposalForm
          parentSlug={parentSlug}
          subOrg={subOrg}
          orgSettings={effectiveSettings}
          topics={topics}
          onCreated={() => { setShowCreate(false); load(); }}
          onCancel={() => setShowCreate(false)}
        />
      )}

      <div className="bg-white border border-gray-200 rounded-xl overflow-hidden">
        <div className="flex items-center gap-4 px-4 py-2 bg-gray-50 text-xs font-medium text-gray-500 uppercase">
          <span className="flex-1">Title</span>
          <span className="w-24">Status</span>
          <span className="w-28">Created</span>
        </div>
        {loading ? (
          <div className="px-4 py-8 text-center text-gray-400 text-sm">Loading…</div>
        ) : proposals.length === 0 ? (
          <div className="px-4 py-8 text-center text-gray-400 text-sm">No proposals yet</div>
        ) : (
          proposals.map(p => (
            <div key={p.id} className="border-t border-gray-100">
              <div className="flex items-center gap-4 px-4 py-3 text-sm">
                <span className="flex-1 font-medium text-gray-800">
                  <Link to={urlFor(parentSlug, 'proposal-detail', p.id)} className="hover:underline">{p.title}</Link>
                </span>
                <span className="w-24"><StatusBadge status={p.status} /></span>
                <span className="w-28 text-xs text-gray-400">{new Date(p.created_at).toLocaleDateString()}</span>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}

// Phase 16 F1 — same formatting helpers as ProposalManagement.jsx (kept
// inline here to avoid plumbing a new util file just for two functions).
function formatDays(value) {
  if (value === null || value === undefined || Number.isNaN(value)) return '?';
  const n = Number(value);
  if (Number.isInteger(n)) return String(n);
  return n.toFixed(2).replace(/\.?0+$/, '');
}

function pluralizeDays(value) {
  return Number(value) === 1 ? 'day' : 'days';
}

// Phase 56 F3 — collapsible org-guidance hint shown above the sub-org
// topic picker. Hidden entirely when no guidance is set so untouched
// orgs see no change.
function SubOrgTopicGuidanceHint({ guidance }) {
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

// Phase 56 F4 — sub-org variant of the proposal-creation topic picker
// (no relevance slider; sub-org pickers use the implicit 1.0 weight).
// Groups by category when the org enables the categories toggle.
function SubOrgTopicPickerList({
  topics,
  subOrgName,
  categoriesEnabled,
  selectedTopics,
  onToggle,
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

  function renderRow(t) {
    const sel = selectedTopics.find(s => s.topic_id === t.id);
    return (
      <label key={t.id} className="flex items-center gap-2 cursor-pointer">
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
          <span className="text-[10px] uppercase text-blue-600">{subOrgName}</span>
        )}
        {t.purpose && (
          <span className="text-xs text-gray-400">— {t.purpose}</span>
        )}
      </label>
    );
  }

  if (categoriesEnabled && grouped) {
    return (
      <div className="space-y-3 max-h-48 overflow-y-auto">
        {grouped.map(group => (
          <div key={group.label} className="space-y-1">
            <p
              className={`text-[11px] font-semibold uppercase tracking-wide ${
                group.isUncategorized ? 'text-gray-400' : 'text-gray-500'
              }`}
            >
              {group.label}
            </p>
            <div className="space-y-1.5 pl-1">
              {group.items.map(renderRow)}
            </div>
          </div>
        ))}
      </div>
    );
  }
  return (
    <div className="space-y-1.5 max-h-48 overflow-y-auto">
      {topics.map(renderRow)}
    </div>
  );
}

function CreateProposalForm({ parentSlug, subOrg, orgSettings, topics, onCreated, onCancel }) {
  const toast = useToast();
  // Phase 12.5 F3 — threshold inputs gated on `proposal.set_thresholds`.
  const canSetThresholds = useHasPermission('proposal.set_thresholds');
  // Phase 16 F1 — duration inputs gated on `proposal.set_durations`.
  const canSetDurations = useHasPermission('proposal.set_durations');
  const [title, setTitle] = useState('');
  const [body, setBody] = useState('');
  const [votingMethod, setVotingMethod] = useState('binary');
  const [options, setOptions] = useState([{ label: '', description: '' }, { label: '', description: '' }]);
  const [numWinners, setNumWinners] = useState(1);
  const [selectedTopics, setSelectedTopics] = useState([]);
  const [passThreshold, setPassThreshold] = useState(orgSettings?.default_pass_threshold ?? 0.5);
  const [quorumThreshold, setQuorumThreshold] = useState(orgSettings?.default_quorum_threshold ?? 0.4);
  const [deliberationDays, setDeliberationDays] = useState(
    orgSettings?.default_deliberation_days ?? 7,
  );
  const [votingDays, setVotingDays] = useState(
    orgSettings?.default_voting_days ?? 3,
  );
  const [linkedPolisIds, setLinkedPolisIds] = useState([]);
  const requirePolis = orgSettings?.require_polis_for_new_proposals === true;
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  const allowedMethods = orgSettings?.allowed_voting_methods || ['binary'];
  const approvalAllowed = allowedMethods.includes('approval');
  const rcAllowed = allowedMethods.includes('ranked_choice');
  const isMultiOption = votingMethod === 'approval' || votingMethod === 'ranked_choice';

  function toggleTopic(id) {
    setSelectedTopics(prev => {
      const e = prev.find(t => t.topic_id === id);
      if (e) return prev.filter(t => t.topic_id !== id);
      return [...prev, { topic_id: id, relevance: 1.0 }];
    });
  }

  async function handleSubmit(e) {
    e.preventDefault();
    if (requirePolis && (linkedPolisIds || []).length === 0) {
      setError('At least one linked Polis is required for proposals in this sub-org.');
      return;
    }
    setSaving(true);
    setError('');
    try {
      const payload = {
        title,
        body,
        topics: selectedTopics,
        voting_method: votingMethod,
        sub_org_id: subOrg.id,
      };
      // Phase 12.5 F3 — only include thresholds when permitted.
      if (canSetThresholds) {
        payload.pass_threshold = passThreshold;
        payload.quorum_threshold = quorumThreshold;
      }
      // Phase 16 F1/B3 — only include durations when permitted.
      if (canSetDurations) {
        payload.deliberation_days = deliberationDays;
        payload.voting_days = votingDays;
      }
      if (isMultiOption) {
        payload.options = options.map(o => ({ label: o.label.trim(), description: o.description.trim() }));
      }
      if (votingMethod === 'ranked_choice') {
        payload.num_winners = numWinners;
      }
      if ((linkedPolisIds || []).length > 0) {
        payload.linked_polis_ids = linkedPolisIds;
      }
      await api.post(`/api/orgs/${parentSlug}/proposals`, payload);
      toast.success('Proposal created');
      onCreated();
    } catch (err) {
      setError(err.message || 'Failed to create proposal');
    } finally {
      setSaving(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="bg-white border border-gray-200 rounded-xl p-5 space-y-4">
      <div className="bg-blue-50 border border-blue-200 rounded-lg px-3 py-2 text-xs text-blue-900">
        <strong>Scope locked:</strong> {subOrg.name}. Only {subOrg.name} members will be able to vote on this proposal.
      </div>

      <div>
        <label className="block text-xs text-gray-500 mb-2">Voting Method</label>
        <div className="flex gap-3 flex-wrap">
          <label className="flex items-center gap-2 cursor-pointer">
            <input type="radio" name="vm" value="binary" checked={votingMethod === 'binary'} onChange={() => setVotingMethod('binary')} className="accent-[var(--brand-accent)]" />
            <span className="text-sm text-gray-700">Binary (Yes/No)</span>
          </label>
          <label className={`flex items-center gap-2 ${approvalAllowed ? 'cursor-pointer' : 'opacity-50'}`}>
            <input type="radio" name="vm" value="approval" checked={votingMethod === 'approval'} disabled={!approvalAllowed} onChange={() => approvalAllowed && setVotingMethod('approval')} className="accent-[var(--brand-accent)]" />
            <span className="text-sm text-gray-700">Approval</span>
            {!approvalAllowed && <span className="text-xs text-amber-600">(not enabled)</span>}
          </label>
          <label className={`flex items-center gap-2 ${rcAllowed ? 'cursor-pointer' : 'opacity-50'}`}>
            <input type="radio" name="vm" value="ranked_choice" checked={votingMethod === 'ranked_choice'} disabled={!rcAllowed} onChange={() => rcAllowed && setVotingMethod('ranked_choice')} className="accent-[var(--brand-accent)]" />
            <span className="text-sm text-gray-700">Ranked Choice</span>
            {!rcAllowed && <span className="text-xs text-amber-600">(not enabled)</span>}
          </label>
        </div>
      </div>

      <div>
        <label className="block text-xs text-gray-500 mb-1">Title</label>
        <input type="text" value={title} onChange={e => setTitle(e.target.value)} required className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[var(--brand-accent)]" />
      </div>

      <div>
        <label className="block text-xs text-gray-500 mb-1">Body (markdown supported)</label>
        <textarea value={body} onChange={e => setBody(e.target.value)} rows={6} className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[var(--brand-accent)] resize-none font-mono" />
      </div>

      {isMultiOption && (
        <div>
          <p className="text-xs text-gray-500 mb-1">Options ({options.length})</p>
          {options.map((o, i) => (
            <div key={i} className="flex items-center gap-2 mb-2">
              <input
                type="text"
                value={o.label}
                onChange={e => setOptions(prev => prev.map((p, j) => j === i ? { ...p, label: e.target.value } : p))}
                placeholder={`Option ${i + 1}`}
                className="flex-1 px-2 py-1.5 border border-gray-300 rounded text-sm focus:outline-none focus:ring-2 focus:ring-[var(--brand-accent)]"
              />
              {options.length > 2 && (
                <button type="button" onClick={() => setOptions(prev => prev.filter((_, j) => j !== i))} className="text-red-500 text-xs">remove</button>
              )}
            </div>
          ))}
          <button type="button" onClick={() => setOptions(prev => [...prev, { label: '', description: '' }])} className="text-xs text-[var(--brand-accent)] hover:underline">
            + Add option
          </button>
          {votingMethod === 'ranked_choice' && (
            <div className="mt-3">
              <label className="block text-xs text-gray-500 mb-1">Number of winners</label>
              <input
                type="number"
                min={1}
                max={options.length}
                value={numWinners}
                onChange={e => setNumWinners(Math.max(1, Math.min(options.length, parseInt(e.target.value, 10) || 1)))}
                className="w-32 px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[var(--brand-accent)]"
              />
            </div>
          )}
        </div>
      )}

      {topics.length > 0 && (
        <div>
          <label className="block text-xs text-gray-500 mb-2">
            Topics ({topics.length} in scope — parent-org-wide + {subOrg.name})
          </label>
          {/* Phase 56 F3 — org-level topic guidance hint. */}
          <SubOrgTopicGuidanceHint guidance={orgSettings?.topic_guidance} />
          {/* Phase 56 F4 — group by category when the org has the
              toggle on; otherwise the original flat list. */}
          <SubOrgTopicPickerList
            topics={topics}
            subOrgName={subOrg.name}
            categoriesEnabled={!!orgSettings?.topic_categories_enabled}
            selectedTopics={selectedTopics}
            onToggle={toggleTopic}
          />
        </div>
      )}

      {/* Phase 12.5 F3 — threshold sliders gated on `proposal.set_thresholds`. */}
      {canSetThresholds ? (
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-xs text-gray-500 mb-1">Pass Threshold: {Math.round(passThreshold * 100)}%</label>
            <input type="range" min={0} max={100} value={Math.round(passThreshold * 100)} onChange={e => setPassThreshold(parseInt(e.target.value, 10) / 100)} className="w-full accent-[var(--brand-accent)]" />
          </div>
          <div>
            <label className="block text-xs text-gray-500 mb-1">Quorum Threshold: {Math.round(quorumThreshold * 100)}%</label>
            <input type="range" min={0} max={100} value={Math.round(quorumThreshold * 100)} onChange={e => setQuorumThreshold(parseInt(e.target.value, 10) / 100)} className="w-full accent-[var(--brand-accent)]" />
          </div>
        </div>
      ) : (
        // Phase 12.6 C1 — show actual default percentages read-only.
        // For sub-orgs the orgSettings prop is `effectiveSettings`, which
        // walks the parent chain (per get_org_config), so the displayed
        // numbers are whatever applies to this sub-org's proposals.
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

      {/* Phase 16 F1 — duration inputs gated on `proposal.set_durations`. */}
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

      {/* Phase 9 — Linked Deliberations picker. Sub-org proposals always
          carry sub_org_id, so the picker always renders here (no scope
          guard needed — we always have a scope). */}
      <LinkedPolisesPicker
        parentSlug={parentSlug}
        scopeSubOrgId={subOrg.id}
        value={linkedPolisIds}
        onChange={setLinkedPolisIds}
        required={requirePolis}
      />

      {error && <p className="text-sm text-red-600">{error}</p>}

      <div className="flex gap-2">
        <button type="submit" disabled={saving || !title.trim()} className="text-sm px-4 py-2 bg-[var(--brand-primary)] text-white rounded-lg hover:bg-[var(--brand-accent)] disabled:opacity-50">
          {saving ? 'Creating...' : 'Create Proposal'}
        </button>
        <button type="button" onClick={onCancel} className="text-sm px-4 py-2 border border-gray-300 text-gray-600 rounded-lg hover:bg-gray-50">
          Cancel
        </button>
      </div>
    </form>
  );
}

import { useState, useEffect, useCallback } from 'react';
import { Link } from 'react-router-dom';
import { useOrg } from '../../OrgContext';
import api from '../../api';
import StatusBadge from '../../components/StatusBadge';
import { useToast } from '../../components/Toast';
import { useConfirm } from '../../components/ConfirmDialog';
import LinkedPolisesPicker from '../../components/LinkedPolisesPicker';

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
          className="text-xs px-3 py-1 bg-[#2E75B6] text-white rounded-lg hover:bg-[#1B3A5C] transition-colors disabled:opacity-50"
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
                className={`flex-1 px-2 py-1.5 border rounded text-sm focus:outline-none focus:ring-2 focus:ring-[#2E75B6] ${isDuplicate ? 'border-red-400' : 'border-gray-300'}`}
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
              className="w-full ml-8 px-2 py-1.5 border border-gray-300 rounded text-xs focus:outline-none focus:ring-2 focus:ring-[#2E75B6] resize-none"
              style={{ width: 'calc(100% - 2rem)' }}
            />
          </div>
        );
      })}
    </div>
  );
}

function CreateProposalForm({ slug, orgSettings, topics, subOrgs, onCreated, onCancel }) {
  const toast = useToast();
  const [title, setTitle] = useState('');
  const [body, setBody] = useState('');
  const [votingMethod, setVotingMethod] = useState('binary');
  const [options, setOptions] = useState([{ label: '', description: '' }, { label: '', description: '' }]);
  const [numWinners, setNumWinners] = useState(1);
  const [selectedTopics, setSelectedTopics] = useState([]);
  // Phase 8.5 — scope selector. '' == parent-org-wide.
  const [scope, setScope] = useState('');
  const [passThreshold, setPassThreshold] = useState(orgSettings?.default_pass_threshold ?? 0.5);
  const [quorumThreshold, setQuorumThreshold] = useState(orgSettings?.default_quorum_threshold ?? 0.4);

  // Decision 3: sub-org proposals can use parent-org-wide topics + that sub-
  // org's own topics. Parent-org-wide proposals can use ONLY parent-org-wide
  // topics (sub_org_id null).
  const inScopeTopics = scope
    ? topics.filter(t => t.sub_org_id == null || t.sub_org_id === scope)
    : topics.filter(t => t.sub_org_id == null);
  // Phase 8 — per-proposal sustained-majority override.
  // null = inherit org default; only writable when org allows the override.
  const smOverrideAllowed = orgSettings?.sustained_majority_per_proposal_override !== false;
  const orgSmDefault = orgSettings?.sustained_majority_enabled_default === true;
  const [smEnabled, setSmEnabled] = useState(orgSmDefault);
  // Phase 9 — Linked Polises (Decision 2 + 7). When org config has
  // `require_polis_for_new_proposals` true, at least one link is required;
  // form blocks submission otherwise. The org config walks parent chain
  // server-side via `get_org_config`; for parent-org-wide proposals the
  // value lives on `currentOrg.settings`.
  const requirePolis = orgSettings?.require_polis_for_new_proposals === true;
  const [linkedPolisIds, setLinkedPolisIds] = useState([]);
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
    if (requirePolis && (linkedPolisIds || []).length === 0 && scope) {
      setError('At least one linked Polis is required for proposals in this scope.');
      return;
    }
    setSaving(true);
    setError('');
    try {
      const payload = {
        title,
        body,
        topics: selectedTopics,
        pass_threshold: passThreshold,
        quorum_threshold: quorumThreshold,
        voting_method: votingMethod,
      };
      if (scope) payload.sub_org_id = scope;
      if (isMultiOption) {
        payload.options = options.map(o => ({
          label: o.label.trim(),
          description: o.description.trim(),
        }));
      }
      if (votingMethod === 'ranked_choice') {
        payload.num_winners = numWinners;
      }
      // Phase 8 — only send the override when org allows it AND the choice
      // diverges from the org default; otherwise let null inherit.
      if (smOverrideAllowed && smEnabled !== orgSmDefault) {
        payload.sustained_majority_enabled = smEnabled;
      }
      // Phase 9 — structurally-recorded Polis links (Decision 2). Server
      // rejects this on parent-org-wide proposals (linked_polis_ids only
      // supported on org-scoped proposals); only include when scoped.
      if (scope && (linkedPolisIds || []).length > 0) {
        payload.linked_polis_ids = linkedPolisIds;
      }
      await api.post(`/api/orgs/${slug}/proposals`, payload);
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
      <h3 className="text-lg font-semibold text-[#1B3A5C]">Create Proposal</h3>

      {/* Phase 8.5 — Scope Selector */}
      {subOrgs && subOrgs.length > 0 && (
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
            className="w-full max-w-md px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[#2E75B6]"
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
          <Link to="/help/voting-methods" className="ml-2 text-[#2E75B6] hover:underline">Which should I pick?</Link>
        </label>
        <div className="flex gap-3">
          <label className="flex items-center gap-2 cursor-pointer">
            <input type="radio" name="votingMethod" value="binary" checked={votingMethod === 'binary'}
              onChange={() => setVotingMethod('binary')} className="accent-[#2E75B6]" />
            <span className="text-sm text-gray-700">Binary (Yes/No)</span>
          </label>
          <label className={`flex items-center gap-2 ${approvalAllowed ? 'cursor-pointer' : 'opacity-50 cursor-not-allowed'}`}>
            <input type="radio" name="votingMethod" value="approval" checked={votingMethod === 'approval'}
              onChange={() => approvalAllowed && setVotingMethod('approval')}
              disabled={!approvalAllowed} className="accent-[#2E75B6]" />
            <span className="text-sm text-gray-700">Approval</span>
            {!approvalAllowed && <span className="text-xs text-amber-600">(Not enabled for this org)</span>}
          </label>
          <label className={`flex items-center gap-2 ${rankedChoiceAllowed ? 'cursor-pointer' : 'opacity-50 cursor-not-allowed'}`}>
            <input type="radio" name="votingMethod" value="ranked_choice" checked={votingMethod === 'ranked_choice'}
              onChange={() => rankedChoiceAllowed && setVotingMethod('ranked_choice')}
              disabled={!rankedChoiceAllowed} className="accent-[#2E75B6]" />
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
          className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[#2E75B6]"
        />
      </div>

      <div>
        <label className="block text-xs text-gray-500 mb-1">Body (markdown supported)</label>
        <textarea
          value={body}
          onChange={e => setBody(e.target.value)}
          rows={6}
          className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[#2E75B6] resize-none font-mono"
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
            className="w-32 px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[#2E75B6]"
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

      {inScopeTopics.length > 0 && (
        <div>
          <label className="block text-xs text-gray-500 mb-2">
            Topics ({inScopeTopics.length} in scope)
          </label>
          <div className="space-y-2">
            {inScopeTopics.map(t => {
              const sel = selectedTopics.find(s => s.topic_id === t.id);
              return (
                <div key={t.id} className="flex items-center gap-3">
                  <label className="flex items-center gap-2 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={!!sel}
                      onChange={() => toggleTopic(t.id)}
                      className="accent-[#2E75B6]"
                    />
                    <span
                      className="inline-block w-3 h-3 rounded-full"
                      style={{ backgroundColor: t.color }}
                    />
                    <span className="text-sm text-gray-700">{t.name}</span>
                    {t.sub_org_id && (
                      <span className="text-[10px] uppercase text-blue-600">scoped</span>
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
                        onChange={e => setRelevance(t.id, parseInt(e.target.value) / 100)}
                        className="w-24 accent-[#2E75B6]"
                      />
                      <span className="text-xs text-gray-500 w-8">{Math.round(sel.relevance * 100)}%</span>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}

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
            className="w-full accent-[#2E75B6]"
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
            className="w-full accent-[#2E75B6]"
          />
        </div>
      </div>

      {/* Phase 9 — Linked Deliberations picker. Backend currently rejects
          linked_polis_ids on parent-org-wide proposals (only org-scoped
          proposals can carry structural links — see routes/proposals.py),
          so the picker only renders when a sub-org scope is selected. */}
      {scope && (
        <LinkedPolisesPicker
          parentSlug={slug}
          scopeSubOrgId={scope}
          value={linkedPolisIds}
          onChange={setLinkedPolisIds}
          required={requirePolis}
        />
      )}

      {/* Phase 8 — Sustained-Majority toggle (only when org allows override) */}
      {smOverrideAllowed && (
        <div className="bg-[#F4F6F9] border border-gray-200 rounded-lg p-4 space-y-2">
          <label className="flex items-start gap-3 cursor-pointer">
            <input
              type="checkbox"
              checked={smEnabled}
              onChange={e => setSmEnabled(e.target.checked)}
              className="mt-0.5 accent-[#2E75B6]"
            />
            <div>
              <p className="text-sm text-gray-700 font-medium">Sustained-majority voting</p>
              <p className="text-xs text-gray-500">
                Requires the proposal to maintain support throughout the voting window.
                Useful for binding decisions; overkill for routine matters.{' '}
                <Link to="/help/sustained-majority" className="text-[#2E75B6] hover:underline">
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

      <div className="flex gap-2">
        <button
          type="submit"
          disabled={saving || !title.trim() || !optionsValid || !numWinnersValid}
          className="text-sm px-4 py-2 bg-[#1B3A5C] text-white rounded-lg hover:bg-[#2E75B6] transition-colors disabled:opacity-50"
        >
          {saving ? 'Creating...' : 'Create Proposal'}
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="text-sm px-4 py-2 border border-gray-300 text-gray-600 rounded-lg hover:bg-gray-50"
        >
          Cancel
        </button>
      </div>
    </form>
  );
}

export default function ProposalManagement() {
  const { currentOrg, fetchSubOrgsFor } = useOrg();
  const toast = useToast();
  const confirm = useConfirm();
  const [proposals, setProposals] = useState([]);
  const [topics, setTopics] = useState([]);
  const [subOrgs, setSubOrgs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
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
      <div className="animate-spin w-8 h-8 border-4 border-[#2E75B6] border-t-transparent rounded-full"></div>
    </div>
  );

  async function handleAdvance(proposalId) {
    try {
      const votingEnd = new Date(Date.now() + 7 * 86400000).toISOString();
      await api.post(`/api/orgs/${slug}/proposals/${proposalId}/advance`, { voting_end: votingEnd });
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

  // Phase 8 — resolve a sustained-majority escalation.
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
        <h1 className="text-2xl font-semibold text-[#1B3A5C]">Proposal Management</h1>
        {!showCreate && (
          <button
            onClick={() => setShowCreate(true)}
            className="text-sm px-4 py-2 bg-[#1B3A5C] text-white rounded-lg hover:bg-[#2E75B6] transition-colors"
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
          onCreated={() => { setShowCreate(false); load(); }}
          onCancel={() => setShowCreate(false)}
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
                  {p.status === 'draft' && (
                    <>
                      <button
                        onClick={() => handleAdvance(p.id)}
                        className="text-xs px-3 py-1.5 bg-[#2E75B6] text-white rounded-lg hover:bg-[#1B3A5C]"
                      >
                        Advance to Deliberation
                      </button>
                      <a
                        href={`/proposals/${p.id}`}
                        className="text-xs px-3 py-1.5 border border-gray-300 text-gray-600 rounded-lg hover:bg-gray-100"
                      >
                        Edit Draft
                      </a>
                    </>
                  )}
                  {p.status === 'deliberation' && (
                    <button
                      onClick={() => handleAdvance(p.id)}
                      className="text-xs px-3 py-1.5 bg-[#2E75B6] text-white rounded-lg hover:bg-[#1B3A5C]"
                    >
                      Advance to Voting
                    </button>
                  )}
                  {p.status === 'voting' && (
                    <button
                      onClick={() => handleAdvance(p.id)}
                      className="text-xs px-3 py-1.5 bg-[#2E75B6] text-white rounded-lg hover:bg-[#1B3A5C]"
                    >
                      Close Voting
                    </button>
                  )}
                  {(p.status === 'draft' || p.status === 'deliberation' || p.status === 'voting') && (
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
          <strong>Awaiting admin review.</strong> Sustained-majority floor was breached during voting.
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            onClick={() => setAction('extend')}
            className="text-xs px-3 py-1.5 border border-[#2E75B6] text-[#2E75B6] rounded-lg hover:bg-blue-50"
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
            className="text-xs px-3 py-1.5 text-[#2E75B6] hover:underline"
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
        Confirm: <strong className="text-[#1B3A5C]">{action.replace(/_/g, ' ')}</strong>
        {requiresReason && <span className="text-red-600"> — reason required for override</span>}
      </p>
      {(requiresReason || action === 'extend') && (
        <textarea
          value={reason}
          onChange={e => setReason(e.target.value)}
          placeholder={requiresReason ? 'Why are you overriding the failure?' : 'Reason (optional)'}
          rows={2}
          className="w-full px-2 py-1.5 border border-gray-300 rounded text-xs focus:outline-none focus:ring-2 focus:ring-[#2E75B6] resize-none"
        />
      )}
      <div className="flex gap-2">
        <button
          onClick={() => onResolve(proposalId, action, reason.trim())}
          disabled={requiresReason && !reason.trim()}
          className="text-xs px-3 py-1.5 bg-[#1B3A5C] text-white rounded-lg hover:bg-[#2E75B6] disabled:opacity-50"
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

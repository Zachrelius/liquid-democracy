import { useState, useEffect, useCallback } from 'react';
import { Link } from 'react-router-dom';
import { useOrg } from '../../OrgContext';
import api from '../../api';
import StatusBadge from '../../components/StatusBadge';
import { useToast } from '../../components/Toast';
import { useConfirm } from '../../components/ConfirmDialog';

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

function CreateProposalForm({ slug, orgSettings, topics, onCreated, onCancel }) {
  const toast = useToast();
  const [title, setTitle] = useState('');
  const [body, setBody] = useState('');
  const [votingMethod, setVotingMethod] = useState('binary');
  const [options, setOptions] = useState([{ label: '', description: '' }, { label: '', description: '' }]);
  const [selectedTopics, setSelectedTopics] = useState([]);
  const [passThreshold, setPassThreshold] = useState(orgSettings?.default_pass_threshold ?? 0.5);
  const [quorumThreshold, setQuorumThreshold] = useState(orgSettings?.default_quorum_threshold ?? 0.4);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  const allowedMethods = orgSettings?.allowed_voting_methods || ['binary'];
  const approvalAllowed = allowedMethods.includes('approval');

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

  // Validation for approval options
  const hasDuplicateLabels = (() => {
    if (votingMethod !== 'approval') return false;
    const labels = options.map(o => o.label.trim().toLowerCase()).filter(Boolean);
    return new Set(labels).size !== labels.length;
  })();

  const optionsValid = votingMethod !== 'approval' || (
    options.length >= 2 &&
    options.every(o => o.label.trim()) &&
    !hasDuplicateLabels
  );

  async function handleSubmit(e) {
    e.preventDefault();
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
      if (votingMethod === 'approval') {
        payload.options = options.map(o => ({
          label: o.label.trim(),
          description: o.description.trim(),
        }));
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
          <label className="flex items-center gap-2 opacity-50 cursor-not-allowed" title="Coming soon">
            <input type="radio" disabled className="accent-[#2E75B6]" />
            <span className="text-sm text-gray-400">Ranked Choice</span>
            <span className="text-xs text-gray-400">(Coming soon)</span>
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

      {/* Options Editor (approval only) */}
      {votingMethod === 'approval' && (
        <OptionsEditor options={options} onChange={setOptions} />
      )}

      {topics.length > 0 && (
        <div>
          <label className="block text-xs text-gray-500 mb-2">Topics</label>
          <div className="space-y-2">
            {topics.map(t => {
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

      {error && <p className="text-sm text-red-600">{error}</p>}

      <div className="flex gap-2">
        <button
          type="submit"
          disabled={saving || !title.trim() || !optionsValid}
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
  const { currentOrg } = useOrg();
  const toast = useToast();
  const confirm = useConfirm();
  const [proposals, setProposals] = useState([]);
  const [topics, setTopics] = useState([]);
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
  }, [slug]);

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
                </div>
              )}
            </div>
          ))
        )}
      </div>
    </div>
  );
}

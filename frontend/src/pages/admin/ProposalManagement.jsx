import { useState, useEffect, useCallback } from 'react';
import { useOrg } from '../../OrgContext';
import api from '../../api';
import StatusBadge from '../../components/StatusBadge';

function CreateProposalForm({ slug, orgSettings, topics, onCreated, onCancel }) {
  const [title, setTitle] = useState('');
  const [body, setBody] = useState('');
  const [selectedTopics, setSelectedTopics] = useState([]);
  const [passThreshold, setPassThreshold] = useState(orgSettings?.default_pass_threshold ?? 0.5);
  const [quorumThreshold, setQuorumThreshold] = useState(orgSettings?.default_quorum_threshold ?? 0.4);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

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

  async function handleSubmit(e) {
    e.preventDefault();
    setSaving(true);
    setError('');
    try {
      await api.post(`/api/orgs/${slug}/proposals`, {
        title,
        body,
        topics: selectedTopics,
        pass_threshold: passThreshold,
        quorum_threshold: quorumThreshold,
      });
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
          disabled={saving || !title.trim()}
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
      // Calculate a voting_end 7 days from now if advancing to voting
      const votingEnd = new Date(Date.now() + 7 * 86400000).toISOString();
      await api.post(`/api/admin/proposals/${proposalId}/advance`, { voting_end: votingEnd });
      load();
    } catch (e) {
      alert(e.message);
    }
  }

  async function handleWithdraw(proposalId) {
    if (!window.confirm('Withdraw this proposal? It will be marked as failed.')) return;
    try {
      await api.post(`/api/admin/proposals/${proposalId}/advance`, {});
      load();
    } catch (e) {
      alert(e.message);
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
                <span className="flex-1 font-medium text-gray-800">{p.title}</span>
                <span className="w-24"><StatusBadge status={p.status} /></span>
                <span className="w-28 text-xs text-gray-400">{new Date(p.created_at).toLocaleDateString()}</span>
                <svg className={`w-4 h-4 text-gray-400 transition-transform ${expandedId === p.id ? 'rotate-180' : ''}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                </svg>
              </div>
              {expandedId === p.id && (
                <div className="px-4 py-3 bg-gray-50 flex items-center gap-3">
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
                  {(p.status === 'deliberation' || p.status === 'voting') && (
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

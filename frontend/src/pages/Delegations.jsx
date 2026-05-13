import { useState, useEffect, useCallback, useMemo } from 'react';
import { Navigate, useNavigate } from 'react-router-dom';
import { DragDropContext, Droppable, Draggable } from '@hello-pangea/dnd';
import api from '../api';
import { useAuth } from '../AuthContext';
import { useOrg } from '../OrgContext';
import { urlFor } from '../utils/urls';
import TopicBadge from '../components/TopicBadge';
import DelegateModal from '../components/DelegateModal';
import FollowRequests from '../components/FollowRequests';
import DelegationNetworkGraph from '../components/DelegationNetworkGraph';
import UserLink from '../components/UserLink';
import Spinner from '../components/Spinner';
import ErrorMessage from '../components/ErrorMessage';
import VerifyEmailInlineNote from '../components/VerifyEmailInlineNote';
import { useToast } from '../components/Toast';
import { useConfirm } from '../components/ConfirmDialog';

const CHAIN_OPTIONS = [
  { value: 'accept_sub', label: 'Accept sub-delegation' },
  { value: 'revert_direct', label: 'Revert to direct' },
  { value: 'abstain', label: 'Abstain' },
];


// ── Delegation Row ─────────────────────────────────────────────────────────
function DelegationRow({ delegation, topic, onChainChange, onChangeDelegate, onRemove, unverified, parentSlug }) {
  const [saving, setSaving] = useState(false);

  async function handleChainChange(e) {
    setSaving(true);
    try {
      await api.put(`/api/orgs/${parentSlug}/delegations`, {
        delegate_id: delegation.delegate_id,
        topic_id: delegation.topic_id ?? null,
        chain_behavior: e.target.value,
      });
      onChainChange();
    } catch {/* ignore — will reload */} finally {
      setSaving(false);
    }
  }

  return (
    <tr className="border-b border-gray-100 last:border-0">
      <td className="py-3 px-4">
        {topic ? <TopicBadge topic={topic} /> : <span className="text-xs italic text-gray-500">Global default</span>}
      </td>
      <td className="py-3 px-4">
        <UserLink user={delegation.delegate} className="text-sm" />
        <span className="ml-1.5 text-xs text-gray-400">@{delegation.delegate.username}</span>
      </td>
      <td className="py-3 px-4">
        <select
          value={delegation.chain_behavior}
          onChange={handleChainChange}
          disabled={saving}
          className="text-xs border border-gray-200 rounded-lg px-2 py-1 text-gray-600 focus:outline-none focus:ring-1 focus:ring-[var(--brand-accent)] disabled:opacity-50"
        >
          {CHAIN_OPTIONS.map(o => (
            <option key={o.value} value={o.value}>{o.label}</option>
          ))}
        </select>
      </td>
      <td className="py-3 px-4 text-right">
        <div className="flex gap-2 justify-end">
          <button onClick={() => onChangeDelegate(delegation)} disabled={unverified} className="text-xs text-[var(--brand-accent)] hover:underline disabled:opacity-50 disabled:no-underline">Change</button>
          <button onClick={() => onRemove(delegation)} disabled={unverified} className="text-xs text-red-500 hover:underline disabled:opacity-50 disabled:no-underline">Remove</button>
        </div>
      </td>
    </tr>
  );
}

// ── Mobile Delegation Card ─────────────────────────────────────────────────
function DelegationCard({ delegation, topic, onChainChange, onChangeDelegate, onRemove, unverified, parentSlug }) {
  const [saving, setSaving] = useState(false);

  async function handleChainChange(e) {
    setSaving(true);
    try {
      await api.put(`/api/orgs/${parentSlug}/delegations`, {
        delegate_id: delegation.delegate_id,
        topic_id: delegation.topic_id ?? null,
        chain_behavior: e.target.value,
      });
      onChainChange();
    } catch {/* ignore */} finally {
      setSaving(false);
    }
  }

  return (
    <div className="bg-white border border-gray-200 rounded-xl p-4 space-y-3">
      <div className="flex items-center justify-between">
        {topic ? <TopicBadge topic={topic} /> : <span className="text-xs italic text-gray-500">Global default</span>}
        <div className="flex gap-3">
          <button onClick={() => onChangeDelegate(delegation)} disabled={unverified} className="text-xs text-[var(--brand-accent)] hover:underline disabled:opacity-50 disabled:no-underline">Change</button>
          <button onClick={() => onRemove(delegation)} disabled={unverified} className="text-xs text-red-500 hover:underline disabled:opacity-50 disabled:no-underline">Remove</button>
        </div>
      </div>
      <div>
        <UserLink user={delegation.delegate} className="text-sm" />
        <span className="ml-1.5 text-xs text-gray-400">@{delegation.delegate.username}</span>
      </div>
      <select
        value={delegation.chain_behavior}
        onChange={handleChainChange}
        disabled={saving}
        className="text-xs border border-gray-200 rounded-lg px-2 py-1.5 text-gray-600 w-full focus:outline-none focus:ring-1 focus:ring-[var(--brand-accent)]"
      >
        {CHAIN_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
    </div>
  );
}

// ── Main Page ──────────────────────────────────────────────────────────────
export default function Delegations() {
  const { user } = useAuth();
  // Phase 18 F1 — page is now per-org. currentOrg is URL-derived
  // (OrgScopedLayout wraps this route, so loading/accessDenied is handled
  // upstream). The parent slug drives the org-scoped API URL.
  const { currentOrg, userOrgs } = useOrg();
  const navigate = useNavigate();
  const toast = useToast();
  const confirm = useConfirm();
  const unverified = !user?.email_verified;

  // Resolve the parent-org slug. Delegations are per-parent-org (sub-org
  // delegations are still rows on the parent org with sub_org_id set).
  // If currentOrg is itself a sub-org, walk up to the parent for routing.
  const parentOrg = useMemo(() => {
    if (!currentOrg) return null;
    if (currentOrg.parent_org_id) {
      return userOrgs.find(o => o.id === currentOrg.parent_org_id) || null;
    }
    return currentOrg;
  }, [currentOrg, userOrgs]);
  const parentSlug = parentOrg?.slug || null;

  // Filter the org switcher to parent-org members the user belongs to.
  // The Nav.jsx OrgSwitcher pattern lives in the global header; this
  // header-local switcher is a small dropdown that just navigates to
  // /{slug}/delegations on selection.
  const switchableOrgs = useMemo(
    () => userOrgs.filter(o => !o.parent_org_id),
    [userOrgs]
  );

  const [delegations, setDelegations] = useState([]);
  const [precedences, setPrecedences] = useState([]);
  const [topics, setTopics] = useState([]);
  const [network, setNetwork] = useState(null);
  const [networkOpen, setNetworkOpen] = useState(window.innerWidth >= 768);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [modal, setModal] = useState(null); // { topicId, topicName, existingDelegation }
  const [savingPrec, setSavingPrec] = useState(false);

  const load = useCallback(async () => {
    if (!parentSlug) {
      setLoading(false);
      return;
    }
    // Phase 25 F3 — clear any stale error state from a prior load before
    // re-fetching. Without this, a successful Retry click leaves the
    // page stuck on the previous error UI because the error state was
    // never reset; same shape for the in-page org switcher whose
    // parentSlug change re-invokes `load` without unmounting the page.
    setError('');
    try {
      const [dels, precs, tops] = await Promise.all([
        api.get(`/api/orgs/${parentSlug}/delegations`),
        api.get(`/api/orgs/${parentSlug}/delegations/precedence`),
        api.get(`/api/orgs/${parentSlug}/topics`),
      ]);
      setDelegations(dels);
      setPrecedences(precs);
      setTopics(tops);
      // Fetch network graph (non-blocking) — org-scoped post-Phase-18.
      try {
        const net = await api.get(`/api/orgs/${parentSlug}/delegations/network`);
        setNetwork(net);
      } catch {/* ignore */}
    } catch (e) {
      setError(e.message || 'Failed to load delegations');
    } finally {
      setLoading(false);
    }
  }, [parentSlug]);

  useEffect(() => { load(); }, [load]);

  // Phase 18 F1 — defensive redirect: if the wrapper somehow renders us
  // without a current org (multi-org user without selection), bounce to
  // /orgs. In normal routing OrgScopedLayout already handles loading +
  // accessDenied, so this is a belt-and-suspenders guard.
  if (!currentOrg) {
    return <Navigate to="/orgs" replace />;
  }

  const topicMap = Object.fromEntries(topics.map(t => [t.id, t]));

  // Separate global vs topic-specific delegations
  const globalDel = delegations.find(d => d.topic_id == null);
  const topicDels = delegations.filter(d => d.topic_id != null);

  // Topics that don't have a delegation yet
  const undelegatedTopics = topics.filter(t =>
    !delegations.some(d => d.topic_id === t.id)
  );

  async function handleRemove(delegation) {
    const topicId = delegation.topic_id ?? 'global';
    const ok = await confirm({
      title: 'Remove Delegation',
      message: 'Remove this delegation?',
      destructive: true,
    });
    if (!ok) return;
    try {
      await api.delete(`/api/orgs/${parentSlug}/delegations/${topicId}`);
      toast.success('Delegation removed');
      load();
    } catch (e) {
      toast.error(e.message);
    }
  }

  function handleModalDone() {
    setModal(null);
    load();
  }

  async function handleDragEnd(result) {
    if (!result.destination) return;
    const items = Array.from(precedences);
    const [moved] = items.splice(result.source.index, 1);
    items.splice(result.destination.index, 0, moved);
    setPrecedences(items);
    setSavingPrec(true);
    try {
      await api.put(`/api/orgs/${parentSlug}/delegations/precedence`, {
        ordered_topic_ids: items.map(p => p.topic_id),
      });
    } catch (e) {
      toast.error(e.message);
      load(); // revert
    } finally {
      setSavingPrec(false);
    }
  }

  if (loading) return <Spinner />;
  if (error) return (
    <div className="max-w-4xl mx-auto px-4 py-8">
      <ErrorMessage error={error} onRetry={load} />
    </div>
  );

  return (
    <div className="max-w-4xl mx-auto px-4 py-8 space-y-8">
      {/* Phase 18 F1 — header reflects per-org scoping. The org-name
          subhead reminds the viewer that delegations on this page apply
          only within {currentOrg.name}; multi-org users get a small
          dropdown to switch between their orgs without leaving. */}
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-[var(--brand-primary)]">My Delegations</h1>
          <p className="text-sm text-gray-500 mt-1">
            Your delegation network in <span className="font-medium text-gray-700">{parentOrg?.name || currentOrg.name}</span>
          </p>
        </div>
        {switchableOrgs.length > 1 && (
          <label className="text-xs text-gray-500 flex items-center gap-2">
            <span>Org:</span>
            <select
              value={parentSlug || ''}
              onChange={(e) => {
                const next = switchableOrgs.find(o => o.slug === e.target.value);
                if (next) navigate(urlFor(next, 'delegations'));
              }}
              className="text-xs border border-gray-200 rounded-lg px-2 py-1 text-gray-700 focus:outline-none focus:ring-1 focus:ring-[var(--brand-accent)]"
            >
              {switchableOrgs.map(o => (
                <option key={o.id} value={o.slug}>{o.name}</option>
              ))}
            </select>
          </label>
        )}
      </div>

      {unverified && (
        <div className="bg-amber-50 border border-amber-200 rounded-lg px-3 py-2">
          <VerifyEmailInlineNote action="delegate" />
        </div>
      )}

      {/* ── Section 1: Global default ── */}
      <section>
        <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide mb-3">
          Global Default
        </h2>
        <div className="bg-white border border-gray-200 rounded-xl p-5">
          {globalDel ? (
            <div className="flex flex-wrap items-center justify-between gap-4">
              <div>
                <p className="text-sm text-gray-500 mb-1">Default delegate</p>
                <p className="font-semibold"><UserLink user={globalDel.delegate} /></p>
                <p className="text-xs text-gray-400">
                  {CHAIN_OPTIONS.find(o => o.value === globalDel.chain_behavior)?.label}
                </p>
              </div>
              <div className="flex gap-2">
                <button
                  onClick={() => setModal({ topicId: undefined, topicName: null, existingDelegation: globalDel })}
                  disabled={unverified}
                  className="text-sm px-3 py-1.5 border border-[var(--brand-accent)] text-[var(--brand-accent)] rounded-lg hover:bg-[var(--brand-accent)] hover:text-white transition-colors disabled:opacity-50"
                >
                  Change
                </button>
                <button
                  onClick={() => handleRemove(globalDel)}
                  disabled={unverified}
                  className="text-sm px-3 py-1.5 border border-red-300 text-red-500 rounded-lg hover:bg-red-50 transition-colors disabled:opacity-50"
                >
                  Remove
                </button>
              </div>
            </div>
          ) : (
            <div className="flex flex-wrap items-center justify-between gap-4">
              <p className="text-sm text-gray-400 italic">
                No default delegate set. Your vote won't be cast on topics without a specific delegation.
              </p>
              <button
                onClick={() => setModal({ topicId: undefined, topicName: null, existingDelegation: null })}
                disabled={unverified}
                className="text-sm px-3 py-1.5 bg-[var(--brand-primary)] text-white rounded-lg hover:bg-[var(--brand-accent)] transition-colors disabled:opacity-50"
              >
                Set Default Delegate
              </button>
            </div>
          )}
        </div>
      </section>

      {/* ── Section 2: Topic delegations — desktop table ── */}
      <section>
        <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide mb-3">
          Topic Delegations
        </h2>

        {/* Desktop table */}
        <div className="hidden md:block bg-white border border-gray-200 rounded-xl overflow-hidden">
          <table className="w-full">
            <thead>
              <tr className="border-b border-gray-100 bg-gray-50">
                <th className="text-left text-xs font-medium text-gray-500 uppercase px-4 py-3">Topic</th>
                <th className="text-left text-xs font-medium text-gray-500 uppercase px-4 py-3">Delegate</th>
                <th className="text-left text-xs font-medium text-gray-500 uppercase px-4 py-3">Chain Behavior</th>
                <th className="text-right text-xs font-medium text-gray-500 uppercase px-4 py-3">Actions</th>
              </tr>
            </thead>
            <tbody className="px-4">
              {topicDels.map(d => (
                <DelegationRow
                  key={d.id}
                  delegation={d}
                  topic={topicMap[d.topic_id]}
                  onChainChange={load}
                  onChangeDelegate={del => setModal({ topicId: del.topic_id, topicName: topicMap[del.topic_id]?.name, existingDelegation: del })}
                  onRemove={handleRemove}
                  unverified={unverified}
                  parentSlug={parentSlug}
                />
              ))}
              {undelegatedTopics.map(t => (
                <tr key={t.id} className="border-b border-gray-100 last:border-0">
                  <td className="py-3 px-4"><TopicBadge topic={t} /></td>
                  <td className="py-3 px-4 text-sm text-gray-400 italic">Not delegated</td>
                  <td className="py-3 px-4">—</td>
                  <td className="py-3 px-4 text-right">
                    <button
                      onClick={() => setModal({ topicId: t.id, topicName: t.name, existingDelegation: null })}
                      disabled={unverified}
                      className="text-xs text-[var(--brand-accent)] hover:underline disabled:opacity-50 disabled:no-underline"
                    >
                      Set Delegate
                    </button>
                  </td>
                </tr>
              ))}
              {topicDels.length === 0 && undelegatedTopics.length === 0 && (
                <tr><td colSpan={4} className="py-6 text-center text-gray-400 text-sm">No topics configured. Create topics from the admin panel.</td></tr>
              )}
            </tbody>
          </table>
        </div>

        {/* Mobile cards */}
        <div className="md:hidden space-y-3">
          {topicDels.map(d => (
            <DelegationCard
              key={d.id}
              delegation={d}
              topic={topicMap[d.topic_id]}
              onChainChange={load}
              onChangeDelegate={del => setModal({ topicId: del.topic_id, topicName: topicMap[del.topic_id]?.name, existingDelegation: del })}
              onRemove={handleRemove}
              unverified={unverified}
              parentSlug={parentSlug}
            />
          ))}
          {undelegatedTopics.map(t => (
            <div key={t.id} className="bg-white border border-gray-200 rounded-xl p-4 flex items-center justify-between">
              <TopicBadge topic={t} />
              <button
                onClick={() => setModal({ topicId: t.id, topicName: t.name, existingDelegation: null })}
                disabled={unverified}
                className="text-xs text-[var(--brand-accent)] hover:underline disabled:opacity-50 disabled:no-underline"
              >
                Set Delegate
              </button>
            </div>
          ))}
        </div>
      </section>

      {/* ── Section 3: Topic Precedence ── */}
      {precedences.length > 0 && (
        <section>
          <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide mb-1">
            Topic Priority {savingPrec && <span className="text-xs text-gray-400 font-normal ml-2">Saving…</span>}
          </h2>
          <p className="text-xs text-gray-400 mb-3">
            When a proposal covers multiple topics, your highest-priority topic's delegate determines your vote. Drag to reorder.
          </p>

          <DragDropContext onDragEnd={handleDragEnd}>
            <Droppable droppableId="precedence-list">
              {(provided) => (
                <ul
                  {...provided.droppableProps}
                  ref={provided.innerRef}
                  className="space-y-2"
                >
                  {precedences.map((p, index) => {
                    const topic = topicMap[p.topic_id];
                    return (
                      <Draggable key={p.topic_id} draggableId={p.topic_id} index={index}>
                        {(provided, snapshot) => (
                          <li
                            ref={provided.innerRef}
                            {...provided.draggableProps}
                            {...provided.dragHandleProps}
                            className={`flex items-center gap-3 bg-white border rounded-xl px-4 py-3 cursor-grab transition-shadow ${
                              snapshot.isDragging
                                ? 'shadow-lg border-[var(--brand-accent)]'
                                : 'border-gray-200'
                            }`}
                          >
                            <span className="text-gray-300 text-sm select-none">⠿</span>
                            <span className="text-sm text-gray-400 w-5 text-right">{index + 1}.</span>
                            {topic ? <TopicBadge topic={topic} /> : <span className="text-xs text-gray-400">{p.topic_id}</span>}
                          </li>
                        )}
                      </Draggable>
                    );
                  })}
                  {provided.placeholder}
                </ul>
              )}
            </Droppable>
          </DragDropContext>
        </section>
      )}

      {/* Delegation Network Graph */}
      {network && network.nodes.length > 0 && (
        <section className="bg-white border border-gray-200 rounded-xl overflow-hidden">
          <button
            onClick={() => setNetworkOpen(v => !v)}
            className="w-full flex items-center justify-between px-5 py-3 text-sm font-semibold text-gray-500 uppercase tracking-wide hover:bg-gray-50 transition-colors"
          >
            <span>Your Delegation Network in {parentOrg?.name || currentOrg.name}</span>
            <span className="text-gray-400 text-xs font-normal normal-case">
              {networkOpen ? 'Hide' : 'Show'}
            </span>
          </button>
          {networkOpen && (
            <div className="px-4 pb-4 space-y-2">
              <div className="flex flex-wrap gap-x-4 gap-y-1 text-[10px] text-gray-500">
                <span>→ You delegate to</span>
                <span>← Delegates to you</span>
                <span className="text-gray-400">Edge colors match topic badges</span>
              </div>
              <DelegationNetworkGraph
                data={network}
                onChangeDelegate={(node) => {
                  // Find a topic this user delegates on to open the modal
                  const topics = [...new Set(node.topics)];
                  const topic = topics.length > 0 ? topics.find(t => t !== 'Global') : null;
                  const topicObj = topic ? Object.values(topicMap).find(t => t.name === topic) : null;
                  setModal({
                    topicId: topicObj?.id ?? undefined,
                    topicName: topicObj?.name ?? null,
                    existingDelegation: delegations.find(d => d.delegate_id === node.id),
                  });
                }}
                onRemoveDelegate={(node) => {
                  const del = delegations.find(d => d.delegate_id === node.id);
                  if (del) handleRemove(del);
                }}
              />
            </div>
          )}
        </section>
      )}

      {/* Follow requests section */}
      <FollowRequests />

      {/* Delegate selection modal */}
      {modal && (
        <DelegateModal
          topicId={modal.topicId}
          topicName={modal.topicName}
          onClose={() => setModal(null)}
          onDone={handleModalDone}
        />
      )}
    </div>
  );
}

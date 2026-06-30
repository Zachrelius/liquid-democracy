import { useEffect, useState, useCallback } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { useOrg } from '../../OrgContext';
import { urlFor } from '../../utils/urls';
import api from '../../api';
import { useToast } from '../../components/Toast';
import { polisTopicLabel } from '../../utils/polis';
import PolisSeedGenerator from '../../components/PolisSeedGenerator';
import useSubOrg from '../../useSubOrg';
import SubOrgErrorState from '../../components/SubOrgErrorState';

/**
 * Phase 81 — link-an-existing-pol.is-conversation flow.
 *
 * The operator creates + configures the conversation on pol.is themselves
 * (sign in at pol.is/signin, create it, add statements there), then pastes
 * its conversation_id here to link it to the org. This page contributes the
 * value our platform adds over a bare body link: scoped embed, the
 * per-(user,org) pseudonymous xid identity bridge, proposal linking, the
 * disclosure modal, and export.
 *
 * Discussion topic + Description are optional UI-layer relabels of the DB
 * `title`/`prompt` columns; an empty topic falls back to a
 * "Linked pol.is conversation <id>" label (see utils/polis.polisTopicLabel).
 *
 * The backend create route still has a programmatic path + token branches +
 * the retained intended_seed_statements column (untouched — Phase 69's home);
 * this frontend only drives the link-existing path.
 */
export default function CreatePolis() {
  const navigate = useNavigate();
  const params = useParams();
  const isSubOrgRoute = !!params.sub_slug;
  const subOrgCtx = useSubOrg();
  const { currentOrg, isModeratorOrAdmin, fetchSubOrgsFor, userOrgs } = useOrg();
  const toast = useToast();

  // Resolve parent slug.
  let parentSlug = null;
  if (isSubOrgRoute) {
    parentSlug = subOrgCtx.parentSlug;
  } else if (currentOrg) {
    parentSlug = currentOrg.parent_org_id
      ? userOrgs.find(o => o.id === currentOrg.parent_org_id)?.slug
      : currentOrg.slug;
  }

  // Form state
  const [title, setTitle] = useState('');
  const [prompt, setPrompt] = useState('');
  const [scopeSubOrgId, setScopeSubOrgId] = useState(
    isSubOrgRoute ? null : '', // '' = parent-org-wide; null filled in when sub-orgs load
  );
  const [pastedConversationId, setPastedConversationId] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [subOrgs, setSubOrgs] = useState([]);

  // Dispatch result (set on POST success).
  const [result, setResult] = useState(null); // PolisCreateResponse shape

  // Lock scope when on sub-org route.
  useEffect(() => {
    if (isSubOrgRoute && subOrgCtx.subOrg) {
      setScopeSubOrgId(subOrgCtx.subOrg.id);
    }
  }, [isSubOrgRoute, subOrgCtx.subOrg]);

  // Load sub-org list at parent scope (so the dropdown shows scopes the
  // operator can administer).
  const loadSubs = useCallback(async () => {
    if (!parentSlug || isSubOrgRoute) return;
    try {
      const subs = await fetchSubOrgsFor(parentSlug);
      setSubOrgs(subs || []);
    } catch { setSubOrgs([]); }
  }, [parentSlug, fetchSubOrgsFor, isSubOrgRoute]);

  useEffect(() => { loadSubs(); }, [loadSubs]);

  if (isSubOrgRoute && subOrgCtx.loading) {
    return (
      <div className="flex justify-center items-center py-20">
        <div className="animate-spin w-8 h-8 border-4 border-[var(--brand-accent)] border-t-transparent rounded-full"></div>
      </div>
    );
  }
  if (isSubOrgRoute && (subOrgCtx.error || !subOrgCtx.subOrg)) {
    return <SubOrgErrorState error={subOrgCtx.error} />;
  }
  if (!isSubOrgRoute && !currentOrg) {
    return <div className="text-center py-16 text-gray-400">No organization selected</div>;
  }

  // For parent-org route, gate on isModeratorOrAdmin (matches the topic-create
  // pattern; backend is source of truth so this is just UI hygiene).
  if (!isSubOrgRoute && !isModeratorOrAdmin) {
    return (
      <div className="max-w-2xl mx-auto px-4 py-16 text-center">
        <h1 className="text-xl font-semibold text-[var(--brand-primary)] mb-3">Permission required</h1>
        <p className="text-sm text-gray-600 mb-4">
          You need to be a moderator or admin of this org to create a Polis.
        </p>
        <Link to={parentSlug ? urlFor(parentSlug, 'admin-polises') : '/orgs'} className="text-sm text-[var(--brand-accent)] hover:underline">Back to Polises</Link>
      </div>
    );
  }

  // ----- Render success state if we have a result -----
  if (result) {
    return (
      <SuccessPanel
        result={result}
        onGoToDetail={() => {
          const id = result.polis.id;
          if (isSubOrgRoute) {
            navigate(urlFor(parentSlug, 'admin-sub-org-polis-detail', params.sub_slug, id));
          } else {
            navigate(urlFor(parentSlug, 'admin-polis-detail', id));
          }
        }}
      />
    );
  }

  // ----- Form -----
  async function handleSubmit(e) {
    e.preventDefault();
    const cid = pastedConversationId.trim();
    if (!cid) {
      toast.error('A pol.is conversation_id is required.');
      return;
    }
    setSubmitting(true);
    try {
      const payload = {
        polis_conversation_id: cid,
        title: title.trim(),
        prompt: prompt.trim(),
      };
      if (scopeSubOrgId) payload.sub_org_id = scopeSubOrgId;
      const res = await api.post(`/api/orgs/${parentSlug}/polises`, payload);
      setResult(res);
    } catch (e) {
      toast.error(e.message || 'Failed to link Polis');
    } finally {
      setSubmitting(false);
    }
  }

  const scopeName = isSubOrgRoute ? subOrgCtx.subOrg?.name : currentOrg?.name;

  return (
    <div className="max-w-3xl mx-auto px-4 py-8 space-y-6">
      <div>
        <p className="text-xs text-gray-400 mb-1">
          {isSubOrgRoute ? (
            <>
              <Link to={urlFor(parentSlug, 'admin-sub-orgs')} className="hover:underline">Sub-organizations</Link>
              {' / '}
              <Link to={urlFor(parentSlug, 'admin-sub-org-settings', params.sub_slug)} className="hover:underline">{subOrgCtx.subOrg?.name}</Link>
              {' / '}
              <Link to={urlFor(parentSlug, 'admin-sub-org-polises', params.sub_slug)} className="hover:underline">Polises</Link>
            </>
          ) : (
            <Link to={urlFor(parentSlug, 'admin-polises')} className="hover:underline">Polises</Link>
          )}
          {' / '}<span>Link</span>
        </p>
        <h1 className="text-2xl font-semibold text-[var(--brand-primary)]">Link a Polis</h1>
        <p className="text-xs text-gray-500 mt-1">
          Link an existing pol.is conversation to <strong>{scopeName}</strong>.
        </p>
      </div>

      <form onSubmit={handleSubmit} className="bg-white border border-gray-200 rounded-xl p-6 space-y-5">
        <div>
          <label className="block text-xs text-gray-500 mb-1">conversation_id (from pol.is)</label>
          <p className="text-xs text-gray-400 mb-1">
            Required. Create the conversation on{' '}
            <a href="https://pol.is/signin" target="_blank" rel="noreferrer" className="underline">pol.is</a>,
            then paste its conversation_id here (looks like <code>3jrhnuhnjs</code> or similar).
          </p>
          <input
            type="text"
            value={pastedConversationId}
            onChange={e => setPastedConversationId(e.target.value)}
            maxLength={300}
            placeholder="e.g. 3jrhnuhnjs"
            className="w-full max-w-xs px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[var(--brand-accent)]"
          />
        </div>

        <div>
          <label className="block text-xs text-gray-500 mb-1">Discussion topic</label>
          <p className="text-xs text-gray-400 mb-1">
            Optional. A one-line headline for this conversation (matches the &ldquo;Topic&rdquo; field on pol.is).
          </p>
          <input
            type="text"
            value={title}
            onChange={e => setTitle(e.target.value)}
            maxLength={500}
            className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[var(--brand-accent)]"
          />
        </div>
        <div>
          <label className="block text-xs text-gray-500 mb-1">Description</label>
          <p className="text-xs text-gray-400 mb-1">
            Optional. A short description of what this conversation is exploring (matches the &ldquo;Description&rdquo; field on pol.is).
          </p>
          <textarea
            value={prompt}
            onChange={e => setPrompt(e.target.value)}
            rows={4}
            maxLength={10000}
            className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[var(--brand-accent)] resize-none"
          />
        </div>

        {!isSubOrgRoute && subOrgs.length > 0 && (
          <div>
            <label className="block text-xs text-gray-500 mb-1">Scope</label>
            <select
              value={scopeSubOrgId || ''}
              onChange={e => setScopeSubOrgId(e.target.value || '')}
              className="w-full max-w-xs px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[var(--brand-accent)]"
            >
              <option value="">Parent-org-wide (default)</option>
              {subOrgs.map(s => (
                <option key={s.id} value={s.id}>{s.name} only</option>
              ))}
            </select>
            <p className="text-xs text-gray-400 mt-1">
              Sub-org Polises follow Decision 7 (default visible, private flag respected).
            </p>
          </div>
        )}

        {isSubOrgRoute && (
          <div className="bg-blue-50 border border-blue-200 rounded-lg px-3 py-2 text-xs text-blue-900">
            <strong>Scope locked:</strong> {subOrgCtx.subOrg?.name}.
          </div>
        )}

        <div className="flex gap-2">
          <button
            type="submit"
            disabled={submitting || !pastedConversationId.trim()}
            className="text-sm px-4 py-2 bg-[var(--brand-primary)] text-white rounded-lg hover:bg-[var(--brand-accent)] disabled:opacity-50"
          >
            {submitting ? 'Linking…' : 'Link Polis'}
          </button>
          <Link
            to={isSubOrgRoute
              ? urlFor(parentSlug, 'admin-sub-org-polises', params.sub_slug)
              : urlFor(parentSlug, 'admin-polises')}
            className="text-sm px-4 py-2 border border-gray-300 text-gray-600 rounded-lg hover:bg-gray-50"
          >
            Cancel
          </Link>
        </div>
      </form>

      {/* Phase 82 C1 — seed-statement generator. Reads topic/description from
          live form state; produces a CSV the admin uploads on pol.is. */}
      <PolisSeedGenerator topic={title} description={prompt} slug={parentSlug} />
    </div>
  );
}

/**
 * Phase 81 — success state for the link-existing flow. The conversation_id is
 * always supplied at create time, so there's no post-create paste step and no
 * seed-statement handoff — the conversation already exists on pol.is.
 */
function SuccessPanel({ result, onGoToDetail }) {
  const polis = result.polis;
  const label = polisTopicLabel(polis);

  return (
    <div className="max-w-2xl mx-auto px-4 py-12 space-y-6">
      <div className="bg-green-50 border border-green-200 rounded-xl p-6 space-y-3">
        <h1 className="text-xl font-semibold text-green-900">Linked</h1>
        <p className="text-sm text-green-800">
          <strong>{label}</strong> is now linked to your org. Members can
          participate in the embedded conversation.
        </p>
        {polis.polis_conversation_id && (
          <p className="text-xs text-green-700">
            conversation_id: <code>{polis.polis_conversation_id}</code>
          </p>
        )}
      </div>

      <button
        onClick={onGoToDetail}
        className="text-sm px-4 py-2 bg-[var(--brand-primary)] text-white rounded-lg hover:bg-[var(--brand-accent)]"
      >
        Go to Polis →
      </button>
    </div>
  );
}

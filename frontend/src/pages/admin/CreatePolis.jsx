import { useEffect, useState, useCallback } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { useOrg } from '../../OrgContext';
import { usePublicConfig } from '../../PublicConfigContext';
import { urlFor } from '../../utils/urls';
import api from '../../api';
import { useToast } from '../../components/Toast';
import useSubOrg from '../../useSubOrg';
import SubOrgErrorState from '../../components/SubOrgErrorState';

/**
 * Phase 9 Session 3 — Polis creation flow with dual-path UX.
 *
 * One form, two success states:
 *
 *   - Programmatic path (`programmatic_path: true`): server called pol.is
 *     for us. Brief success + "Go to Polis →"; render any `partial_seed_failures`
 *     so the operator can re-add the missing seeds on pol.is by hand.
 *
 *   - Manual-fallback path (`programmatic_path: false`): server has no
 *     POLIS_AUTH_TOKEN, so the operator must (a) create the conversation
 *     on pol.is themselves and (b) paste seed statements into the pol.is
 *     admin UI. The verbatim copy is in `phase9_spec.md` Session 3 brief
 *     and is load-bearing — preserved exactly below.
 *
 * The "Save conversation_id" handler in the manual-fallback success state
 * is a TODO until the API gap is closed (Session 2 PATCH only accepts
 * `title?` and `status?` — see Session 3 closeout report).
 */
export default function CreatePolis() {
  const navigate = useNavigate();
  const params = useParams();
  const isSubOrgRoute = !!params.sub_slug;
  const subOrgCtx = useSubOrg();
  const { currentOrg, isModeratorOrAdmin, fetchSubOrgsFor, userOrgs } = useOrg();
  const toast = useToast();
  const publicConfig = usePublicConfig();

  // Resolve parent slug.
  let parentSlug = null;
  if (isSubOrgRoute) {
    parentSlug = subOrgCtx.parentSlug;
  } else if (currentOrg) {
    parentSlug = currentOrg.parent_org_id
      ? userOrgs.find(o => o.id === currentOrg.parent_org_id)?.slug
      : currentOrg.slug;
  }

  const tokenConfigured = !!publicConfig.polis_token_configured;

  // Form state
  const [title, setTitle] = useState('');
  const [prompt, setPrompt] = useState('');
  const [scopeSubOrgId, setScopeSubOrgId] = useState(
    isSubOrgRoute ? null : '', // '' = parent-org-wide; null filled in when sub-orgs load
  );
  const [seedStatements, setSeedStatements] = useState(['', '', '', '', '']);
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
      // Filter to sub-orgs the user admins (parent-org admins always pass via
      // Decision 6 implicit power, which the server enforces).
      setSubOrgs(subs || []);
    } catch { setSubOrgs([]); }
  }, [parentSlug, fetchSubOrgsFor, isSubOrgRoute]);

  useEffect(() => { loadSubs(); }, [loadSubs]);

  if (isSubOrgRoute && subOrgCtx.loading) {
    return (
      <div className="flex justify-center items-center py-20">
        <div className="animate-spin w-8 h-8 border-4 border-[#2E75B6] border-t-transparent rounded-full"></div>
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
        <h1 className="text-xl font-semibold text-[#1B3A5C] mb-3">Permission required</h1>
        <p className="text-sm text-gray-600 mb-4">
          You need to be a moderator or admin of this org to create a Polis.
        </p>
        <Link to={parentSlug ? urlFor(parentSlug, 'admin-polises') : '/orgs'} className="text-sm text-[#2E75B6] hover:underline">Back to Polises</Link>
      </div>
    );
  }

  // ----- Render success state if we have a result -----
  if (result) {
    return (
      <SuccessPanel
        result={result}
        parentSlug={parentSlug}
        pastedConversationId={pastedConversationId}
        setPastedConversationId={setPastedConversationId}
        onConnected={(updatedPolis) => {
          setResult(prev => prev ? { ...prev, polis: updatedPolis } : prev);
        }}
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
  function updateSeed(i, v) {
    setSeedStatements(prev => prev.map((s, j) => j === i ? v : s));
  }
  function addSeed() { setSeedStatements(prev => [...prev, '']); }
  function removeSeed(i) {
    setSeedStatements(prev => prev.length > 1 ? prev.filter((_, j) => j !== i) : prev);
  }

  const trimmedSeeds = seedStatements.map(s => s.trim()).filter(s => s.length > 0);
  const seedWarning = trimmedSeeds.length < 5
    ? `Only ${trimmedSeeds.length} seed statement${trimmedSeeds.length === 1 ? '' : 's'}. 10–15 is recommended; below 5 makes pol.is's clustering visualizations less useful.`
    : null;

  async function handleSubmit(e) {
    e.preventDefault();
    if (!title.trim() || !prompt.trim()) {
      toast.error('Title and prompt are required.');
      return;
    }
    setSubmitting(true);
    try {
      const payload = {
        title: title.trim(),
        prompt: prompt.trim(),
        seed_statements: trimmedSeeds,
      };
      if (scopeSubOrgId) payload.sub_org_id = scopeSubOrgId;
      // Manual-fallback path: server requires polis_conversation_id when
      // POLIS_AUTH_TOKEN is unset. We don't ask the operator for it on the
      // create form (they paste it post-create on the success panel) — but
      // the server short-circuits with a 400 in that case. To keep the form
      // useful in manual-fallback mode, we pre-emit a placeholder and let
      // the success panel guide the operator through pasting the real ID.
      //
      // The cleanest fix is for Session 4 to extend PATCH with
      // polis_conversation_id (or add a dedicated endpoint). Until then, we
      // require the operator to paste the conversation_id BEFORE submitting
      // when the token isn't configured.
      if (!tokenConfigured) {
        if (!pastedConversationId.trim()) {
          toast.error(
            'Token not configured (manual-fallback): create the conversation ' +
            'on pol.is first, then paste its conversation_id below before submitting.',
          );
          setSubmitting(false);
          return;
        }
        payload.polis_conversation_id = pastedConversationId.trim();
      }
      const res = await api.post(`/api/orgs/${parentSlug}/polises`, payload);
      setResult(res);
    } catch (e) {
      toast.error(e.message || 'Failed to create Polis');
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
          {' / '}<span>Create</span>
        </p>
        <h1 className="text-2xl font-semibold text-[#1B3A5C]">Create a Polis</h1>
        <p className="text-xs text-gray-500 mt-1">
          A pol.is conversation linked to <strong>{scopeName}</strong>.
        </p>
      </div>

      {!tokenConfigured && (
        <div className="bg-amber-50 border border-amber-200 rounded-lg px-4 py-3 text-sm text-amber-900">
          <p className="font-semibold mb-1">Manual-fallback mode</p>
          <p className="text-xs">
            No pol.is API token is configured on the platform. Create your
            conversation on <a href="https://pol.is/admin" target="_blank" rel="noreferrer" className="underline">pol.is/admin</a>{' '}
            first, paste its conversation_id below, then submit. Seed statements
            you enter here will be displayed on the success page so you can
            paste them into pol.is yourself.
          </p>
        </div>
      )}

      <form onSubmit={handleSubmit} className="bg-white border border-gray-200 rounded-xl p-6 space-y-5">
        <div>
          <label className="block text-xs text-gray-500 mb-1">Title</label>
          <input
            type="text"
            value={title}
            onChange={e => setTitle(e.target.value)}
            required
            maxLength={500}
            className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[#2E75B6]"
          />
        </div>
        <div>
          <label className="block text-xs text-gray-500 mb-1">Prompt</label>
          <p className="text-xs text-gray-400 mb-1">
            The central question or topic this Polis is exploring.
          </p>
          <textarea
            value={prompt}
            onChange={e => setPrompt(e.target.value)}
            required
            rows={4}
            maxLength={10000}
            className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[#2E75B6] resize-none"
          />
        </div>

        {!isSubOrgRoute && subOrgs.length > 0 && (
          <div>
            <label className="block text-xs text-gray-500 mb-1">Scope</label>
            <select
              value={scopeSubOrgId || ''}
              onChange={e => setScopeSubOrgId(e.target.value || '')}
              className="w-full max-w-xs px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[#2E75B6]"
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

        <div>
          <label className="block text-xs text-gray-500 mb-1">Seed statements</label>
          <p className="text-xs text-gray-400 mb-2">
            {tokenConfigured
              ? 'These will be inserted into pol.is on creation. 10–15 seeds is the sweet spot for clustering.'
              : "These will be stored on the platform; if your pol.is workspace doesn't yet have programmatic access, you'll be prompted to paste them into pol.is admin manually after creation."}
          </p>
          <div className="space-y-2">
            {seedStatements.map((s, i) => (
              <div key={i} className="flex items-start gap-2">
                <span className="text-xs text-gray-400 mt-2 w-6 text-right">{i + 1}.</span>
                <input
                  type="text"
                  value={s}
                  onChange={e => updateSeed(i, e.target.value)}
                  placeholder={`Statement ${i + 1}`}
                  maxLength={997}
                  className="flex-1 px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[#2E75B6]"
                />
                {seedStatements.length > 1 && (
                  <button
                    type="button"
                    onClick={() => removeSeed(i)}
                    className="text-xs text-red-500 hover:underline mt-2"
                    title="Remove this statement"
                  >remove</button>
                )}
              </div>
            ))}
          </div>
          <button
            type="button"
            onClick={addSeed}
            className="mt-2 text-xs text-[#2E75B6] hover:underline"
          >+ Add statement</button>
          {seedWarning && (
            <p className="text-xs text-amber-600 mt-2">{seedWarning}</p>
          )}
        </div>

        {!tokenConfigured && (
          <div>
            <label className="block text-xs text-gray-500 mb-1">conversation_id (from pol.is)</label>
            <p className="text-xs text-gray-400 mb-1">
              Required in manual-fallback mode. Paste the conversation_id you
              created on pol.is/admin (looks like <code>3jrhnuhnjs</code> or similar).
            </p>
            <input
              type="text"
              value={pastedConversationId}
              onChange={e => setPastedConversationId(e.target.value)}
              maxLength={300}
              className="w-full max-w-xs px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[#2E75B6]"
            />
          </div>
        )}

        <div className="flex gap-2">
          <button
            type="submit"
            disabled={submitting || !title.trim() || !prompt.trim() || (!tokenConfigured && !pastedConversationId.trim())}
            className="text-sm px-4 py-2 bg-[#1B3A5C] text-white rounded-lg hover:bg-[#2E75B6] disabled:opacity-50"
          >
            {submitting ? 'Creating…' : 'Create Polis'}
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
    </div>
  );
}

/**
 * Success state — branches on `programmatic_path` from the response.
 */
function SuccessPanel({
  result,
  parentSlug,
  pastedConversationId, setPastedConversationId, onGoToDetail, onConnected,
}) {
  const toast = useToast();
  const polis = result.polis;
  const programmatic = !!result.programmatic_path;
  const partialFailures = result.partial_seed_failures || [];
  const seeds = polis.intended_seed_statements || [];
  const [savingConn, setSavingConn] = useState(false);

  function copyOne(text) {
    if (!text) return;
    navigator.clipboard?.writeText(text).then(
      () => toast.success('Copied to clipboard'),
      () => toast.error('Copy failed — your browser may not allow it'),
    );
  }
  function copyAll() {
    if (!seeds.length) return;
    const all = seeds.map((s, i) => `${i + 1}. ${s}`).join('\n');
    navigator.clipboard?.writeText(all).then(
      () => toast.success(`Copied all ${seeds.length} statements`),
      () => toast.error('Copy failed'),
    );
  }

  // Phase 9 Session 4 — the API gap is closed (PolisUpdate accepts
  // polis_conversation_id; one-shot connect, audited as polis.connected).
  // Wire the Save button to PATCH and refresh the success panel state on
  // success so the input disappears. 400 = "already set" or empty.
  async function handleSaveConversationId() {
    const cid = pastedConversationId.trim();
    if (!cid) {
      toast.error('Paste a conversation_id first.');
      return;
    }
    if (!parentSlug) {
      toast.error('Cannot resolve org slug — refresh and try again.');
      return;
    }
    setSavingConn(true);
    try {
      const updated = await api.patch(
        `/api/orgs/${parentSlug}/polises/${polis.id}`,
        { polis_conversation_id: cid },
      );
      toast.success('Connected to pol.is — conversation_id saved.');
      if (onConnected) onConnected(updated);
      setPastedConversationId('');
    } catch (e) {
      toast.error(e.message || 'Failed to save conversation_id.');
    } finally {
      setSavingConn(false);
    }
  }

  if (programmatic) {
    return (
      <div className="max-w-2xl mx-auto px-4 py-12 space-y-6">
        <div className="bg-green-50 border border-green-200 rounded-xl p-6 space-y-3">
          <h1 className="text-xl font-semibold text-green-900">Created — view conversation</h1>
          <p className="text-sm text-green-800">
            <strong>{polis.title}</strong> was created on pol.is and seed
            statements inserted server-side.
          </p>
          {polis.polis_conversation_id && (
            <p className="text-xs text-green-700">
              conversation_id: <code>{polis.polis_conversation_id}</code>
            </p>
          )}
        </div>

        {partialFailures.length > 0 && (
          <div className="bg-amber-50 border border-amber-200 rounded-xl p-5 space-y-2">
            <p className="text-sm font-semibold text-amber-900">
              {seeds.length - partialFailures.length}/{seeds.length} seed statements inserted —
              retry the rest on pol.is
            </p>
            <p className="text-xs text-amber-800">
              The pol.is API rejected these statements; add them manually via
              the pol.is admin UI:
            </p>
            <ul className="list-disc pl-5 space-y-1 text-xs text-amber-900">
              {partialFailures.map((f, i) => (
                <li key={i}>{f.statement || f.text || JSON.stringify(f)}</li>
              ))}
            </ul>
          </div>
        )}

        <button
          onClick={onGoToDetail}
          className="text-sm px-4 py-2 bg-[#1B3A5C] text-white rounded-lg hover:bg-[#2E75B6]"
        >
          Go to Polis →
        </button>
      </div>
    );
  }

  // Manual-fallback success state — verbatim copy from spec/brief.
  return (
    <div className="max-w-2xl mx-auto px-4 py-10 space-y-6">
      <div className="bg-amber-50 border border-amber-200 rounded-xl p-6 space-y-4">
        <h1 className="text-xl font-semibold text-amber-900">Almost done — finish on pol.is</h1>
        <p className="text-sm text-amber-900">
          The Polis is created on the platform side. To open it for participation,
          complete two steps on pol.is:
        </p>

        <div className="space-y-3 text-sm text-amber-900">
          <div>
            <p className="font-semibold">
              1. Create the conversation at{' '}
              <a href="https://pol.is/admin" target="_blank" rel="noreferrer" className="underline">
                pol.is/admin
              </a>{' '}
              (or paste an existing conversation_id below)
            </p>
            {polis.polis_conversation_id && (
              <p className="text-xs text-amber-700 mt-1">
                Captured at create-time: <code>{polis.polis_conversation_id}</code>
              </p>
            )}
          </div>

          <div>
            <p className="font-semibold mb-2">
              2. Add these seed statements to your conversation:
            </p>
            {seeds.length === 0 ? (
              <p className="text-xs text-amber-700">No seed statements were entered.</p>
            ) : (
              <div className="bg-white border border-amber-200 rounded-lg p-3 space-y-1.5">
                {seeds.map((s, i) => (
                  <div key={i} className="flex items-start gap-2 text-sm text-gray-800">
                    <span className="text-xs text-gray-400 mt-1 w-6 text-right shrink-0">{i + 1}.</span>
                    <span className="flex-1">{s}</span>
                    <button
                      onClick={() => copyOne(s)}
                      className="text-xs text-[#2E75B6] hover:underline shrink-0"
                    >copy</button>
                  </div>
                ))}
                <div className="pt-2 border-t border-amber-100">
                  <button
                    onClick={copyAll}
                    className="text-xs text-[#2E75B6] hover:underline"
                  >Copy all</button>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Conversation_id input (post-create) — Phase 9 Session 4: wired to
          PATCH polis_conversation_id (one-shot connect). Once saved, the
          panel re-renders with the captured-at-create-time line above and
          this input disappears. */}
      {!polis.polis_conversation_id && (
        <div className="bg-white border border-gray-200 rounded-xl p-5 space-y-3">
          <p className="text-sm font-semibold text-gray-700">Paste conversation_id</p>
          <div className="flex items-center gap-2">
            <input
              type="text"
              value={pastedConversationId}
              onChange={e => setPastedConversationId(e.target.value)}
              placeholder="e.g. 3jrhnuhnjs"
              disabled={savingConn}
              className="flex-1 max-w-xs px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[#2E75B6] disabled:opacity-50"
            />
            <button
              onClick={handleSaveConversationId}
              disabled={savingConn || !pastedConversationId.trim()}
              className="text-sm px-3 py-1.5 bg-[#1B3A5C] text-white rounded-lg hover:bg-[#2E75B6] disabled:opacity-50"
            >{savingConn ? 'Saving…' : 'Save'}</button>
          </div>
          <p className="text-xs text-gray-500">
            Once saved, the conversation_id is locked (one-shot connect — admin tooling required to change it).
          </p>
        </div>
      )}

      <p className="text-sm text-gray-700">
        Once both steps are done, the Polis becomes accessible to your members.
      </p>

      <button
        onClick={onGoToDetail}
        className="text-sm px-4 py-2 bg-[#1B3A5C] text-white rounded-lg hover:bg-[#2E75B6]"
      >
        Go to Polis →
      </button>
    </div>
  );
}

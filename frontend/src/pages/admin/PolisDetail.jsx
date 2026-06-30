import { useEffect, useState, useCallback, useRef } from 'react';
import { Link, useParams, useNavigate } from 'react-router-dom';
import { useOrg } from '../../OrgContext';
import { useAuth } from '../../AuthContext';
import { urlFor } from '../../utils/urls';
import api from '../../api';
import { useToast } from '../../components/Toast';
import { useConfirm } from '../../components/ConfirmDialog';
import { polisTopicLabel } from '../../utils/polis';
import PolisSeedGenerator from '../../components/PolisSeedGenerator';
import useSubOrg from '../../useSubOrg';
// Phase 12.5 F2 — per-control permission gating.
import { useHasPermission } from '../../hooks/useHasPermission';
import SubOrgErrorState from '../../components/SubOrgErrorState';
import PolisEmbed from '../../components/PolisEmbed';

/**
 * Phase 9 Session 3 — Polis detail page (admin scope).
 *
 * Single component, dispatches by URL: when `:sub_slug` is present we
 * resolve via `useSubOrg` (and gate via `SubOrgErrorState`); otherwise
 * we read the parent-org from `OrgContext`. Either way the API endpoint
 * is `/api/orgs/{parentSlug}/polises/{polis_id}` — Polis routes are
 * always parent-org-rooted; sub-org scope is just a UI breadcrumb.
 *
 * Sections:
 *   - Header (title + prompt + status + scope + creator)
 *   - Live participation stats (graceful for live_stats_unavailable)
 *   - Embedded iframe placeholder + xid plumbing for Session 4
 *   - Admin controls (visible iff is_polis_admin proxy is true; the
 *     server is the source of truth and 403s otherwise)
 *   - Linked-from indicator (proposals referencing this Polis)
 */
export default function PolisDetail() {
  const params = useParams();
  const navigate = useNavigate();
  const { user } = useAuth();
  const { currentOrg, userOrgs } = useOrg();
  const toast = useToast();
  const confirm = useConfirm();
  // Phase 12.5 F2 — Admin controls (Edit title, Archive, Export) gated on
  // `polis.manage`. Hook called here at the top so it runs every render
  // (rules-of-hooks); the resolved value flows into showAdminControls below.
  const canManagePolis = useHasPermission('polis.manage');

  // Sub-org dispatch — only present when path contains :sub_slug.
  const subOrgCtx = useSubOrg();
  const isSubOrgRoute = !!params.sub_slug;

  // Resolve parent slug for API calls.
  let parentSlug = null;
  if (isSubOrgRoute) {
    parentSlug = subOrgCtx.parentSlug;
  } else if (currentOrg) {
    parentSlug = currentOrg.parent_org_id
      ? userOrgs.find(o => o.id === currentOrg.parent_org_id)?.slug
      : currentOrg.slug;
  }

  const polisId = params.polis_id;

  const [polis, setPolis] = useState(null);
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [creator, setCreator] = useState(null);
  const [linkedProposals, setLinkedProposals] = useState([]);
  const [editingTitle, setEditingTitle] = useState(false);
  const [titleDraft, setTitleDraft] = useState('');
  const [deanonymize, setDeanonymize] = useState(false);
  const [archiving, setArchiving] = useState(false);

  // Phase 9 Session 4: stash the xid so PolisEmbed can pass it as
  // `data-xid` on the embed. Idempotent on the server — repeat calls
  // return the same xid for (user, org).
  const [polisXid, setPolisXid] = useState(null);
  const xidRequested = useRef(false);

  const load = useCallback(async () => {
    if (!parentSlug || !polisId) return;
    setLoading(true);
    try {
      const data = await api.get(`/api/orgs/${parentSlug}/polises/${polisId}`);
      setPolis(data);
      setStats(data?.participation_stats || null);
      setTitleDraft(data?.title || '');
      setError(null);
      // Resolve creator display name from members list.
      try {
        const members = await api.get(`/api/orgs/${parentSlug}/members`);
        const c = (members || []).find(m => m.user_id === data.created_by);
        setCreator(c || null);
      } catch { /* leave null */ }
      // Linked-from indicator: pull all proposals and filter by linked_polis_ids.
      try {
        const props = await api.get(`/api/orgs/${parentSlug}/proposals`);
        const linked = (props || []).filter(p =>
          Array.isArray(p.linked_polis_ids) && p.linked_polis_ids.includes(polisId),
        );
        setLinkedProposals(linked);
      } catch { setLinkedProposals([]); }
    } catch (e) {
      setError(e);
      setPolis(null);
    } finally {
      setLoading(false);
    }
  }, [parentSlug, polisId]);

  useEffect(() => { load(); }, [load]);

  // Lazy xid request — once per mount per (user, polis). Server idempotently
  // returns the existing xid for (user, org); first call is the only one
  // that emits the polis.xid_generated audit event.
  useEffect(() => {
    if (!parentSlug || !polisId || xidRequested.current) return;
    if (!polis || !user) return;
    xidRequested.current = true;
    (async () => {
      try {
        const r = await api.post(`/api/orgs/${parentSlug}/polises/${polisId}/xid`);
        setPolisXid(r?.polis_xid || null);
      } catch {
        // Non-fatal — admin views still render without xid; iframe in
        // Session 4 will degrade gracefully.
      }
    })();
  }, [parentSlug, polisId, polis, user]);

  if (isSubOrgRoute && subOrgCtx.loading) return (
    <div className="flex justify-center items-center py-20">
      <div className="animate-spin w-8 h-8 border-4 border-[var(--brand-accent)] border-t-transparent rounded-full"></div>
    </div>
  );
  if (isSubOrgRoute && (subOrgCtx.error || !subOrgCtx.subOrg)) {
    return <SubOrgErrorState error={subOrgCtx.error} />;
  }

  if (loading) return (
    <div className="flex justify-center items-center py-20">
      <div className="animate-spin w-8 h-8 border-4 border-[var(--brand-accent)] border-t-transparent rounded-full"></div>
    </div>
  );

  if (error || !polis) {
    return (
      <div className="max-w-2xl mx-auto px-4 py-16 text-center">
        <h1 className="text-xl font-semibold text-[var(--brand-primary)] mb-3">Polis not found</h1>
        <p className="text-sm text-gray-600 mb-4">
          {error?.message || 'This Polis does not exist or is not visible to you.'}
        </p>
        <Link to={isSubOrgRoute ? `/admin/sub-orgs/${params.sub_slug}/polises` : '/admin/polises'} className="text-sm text-[var(--brand-accent)] hover:underline">
          Back to Polises
        </Link>
      </div>
    );
  }

  // is_polis_admin is computed server-side; backend 403s on PATCH/export
  // when the caller doesn't qualify. Phase 12.5 F2 — gate the client-side
  // proxy on `polis.manage` (resolved at the top of the function above) plus
  // the creator-visibility fallback and the sub-org admin role-tier check
  // (Decision-6 implicit power; sub-org permission system is out of scope
  // for 12.5).
  const viewerCreated = polis.created_by === user?.id;
  const subOrgUserRole = isSubOrgRoute ? subOrgCtx.subOrg?.user_role : null;
  const isSubOrgAdmin = subOrgUserRole === 'admin' || subOrgUserRole === 'steward' || subOrgUserRole === 'owner';
  const showAdminControls = !!(viewerCreated || canManagePolis || isSubOrgAdmin);

  const isArchived = polis.status === 'archived';
  const conversationId = polis.polis_conversation_id;
  const polisManageUrl = conversationId
    ? `https://pol.is/${conversationId}`
    : null;

  async function handleSaveTitle() {
    try {
      await api.patch(`/api/orgs/${parentSlug}/polises/${polisId}`, { title: titleDraft });
      toast.success('Title updated');
      setEditingTitle(false);
      load();
    } catch (e) {
      toast.error(e.message || 'Failed to update title');
    }
  }

  async function handleArchive() {
    const ok = await confirm({
      title: 'Archive this Polis?',
      message:
        'Archiving here marks the platform record archived (v1-only lifecycle '
        + '— no un-archive yet). To stop participation, also close the '
        + 'conversation on pol.is.',
      destructive: true,
    });
    if (!ok) return;
    setArchiving(true);
    try {
      await api.patch(`/api/orgs/${parentSlug}/polises/${polisId}`, { status: 'archived' });
      toast.info('Archived on platform. Don\'t forget to close on pol.is.');
      load();
    } catch (e) {
      toast.error(e.message || 'Failed to archive');
    } finally {
      setArchiving(false);
    }
  }

  async function handleExport() {
    if (deanonymize) {
      const ok = await confirm({
        title: 'Export deanonymized data?',
        message:
          'A deanonymized export joins pol.is participation against platform user identities. ' +
          'Treat the resulting CSV as confidential — it links statements/votes to specific users.',
        destructive: true,
      });
      if (!ok) return;
    }
    try {
      const url = `/api/orgs/${parentSlug}/polises/${polisId}/export${deanonymize ? '?deanonymize=true' : ''}`;
      const token = sessionStorage.getItem('token');
      const res = await fetch(url, {
        headers: { Authorization: token ? `Bearer ${token}` : '' },
      });
      if (!res.ok) {
        const text = await res.text();
        toast.error(`Export failed: ${res.status} ${text.slice(0, 200)}`);
        return;
      }
      const blob = await res.blob();
      const dl = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = dl;
      a.download = deanonymize ? `polis_${polisId}_deanon.csv` : `polis_${polisId}.csv`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(dl);
      toast.success('Export downloaded');
    } catch (e) {
      toast.error(e.message || 'Export failed');
    }
  }

  function statusBadge(status) {
    const cls = status === 'active'
      ? 'bg-green-100 text-green-700'
      : 'bg-gray-200 text-gray-600';
    return (
      <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${cls}`}>
        {status}
      </span>
    );
  }

  const liveStatsUnavailable = !!stats?.live_stats_unavailable;

  function statValue(n) {
    if (liveStatsUnavailable || n === null || n === undefined) return '—';
    return Number(n).toLocaleString();
  }

  return (
    <div className="max-w-4xl mx-auto px-4 py-8 space-y-8">
      {/* Breadcrumb */}
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
          {' / '}<span>{polisTopicLabel(polis)}</span>
        </p>
      </div>

      {/* Header */}
      <section className="space-y-2">
        <div className="flex items-start justify-between gap-4">
          <div className="flex-1 min-w-0">
            {editingTitle && showAdminControls ? (
              <div className="flex items-center gap-2">
                <input
                  type="text"
                  value={titleDraft}
                  onChange={e => setTitleDraft(e.target.value)}
                  className="flex-1 max-w-xl px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[var(--brand-accent)]"
                />
                <button
                  onClick={handleSaveTitle}
                  className="text-sm px-3 py-1.5 bg-[var(--brand-primary)] text-white rounded-lg hover:bg-[var(--brand-accent)]"
                >Save</button>
                <button
                  onClick={() => { setEditingTitle(false); setTitleDraft(polis.title); }}
                  className="text-sm px-3 py-1.5 border border-gray-300 text-gray-600 rounded-lg hover:bg-gray-50"
                >Cancel</button>
              </div>
            ) : (
              <div className="flex items-center gap-3 flex-wrap">
                <h1 className="text-2xl font-semibold text-[var(--brand-primary)]">{polisTopicLabel(polis)}</h1>
                {statusBadge(polis.status)}
                {polis.sub_org_id ? (
                  <span className="text-[10px] uppercase px-1.5 py-0.5 rounded bg-blue-50 text-blue-700">
                    {isSubOrgRoute ? subOrgCtx.subOrg?.name : 'Sub-org'}
                  </span>
                ) : (
                  <span className="text-[10px] uppercase px-1.5 py-0.5 rounded bg-gray-100 text-gray-600">
                    Org-wide
                  </span>
                )}
              </div>
            )}
          </div>
        </div>
        {polis.prompt && <p className="text-sm text-gray-700 whitespace-pre-line">{polis.prompt}</p>}
        <p className="text-xs text-gray-400">
          Created {new Date(polis.created_at).toLocaleDateString()}
          {creator ? <> by <span className="text-gray-600">{creator.display_name}</span></> : null}
        </p>
        {!conversationId && (
          <div className="mt-3 px-3 py-2 bg-amber-50 border border-amber-200 rounded text-xs text-amber-800">
            This Polis has no conversation_id yet — the embed and live stats
            light up once it's connected to pol.is.
          </div>
        )}
      </section>

      {/* Participation stats */}
      <section className="space-y-2">
        <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide">Participation</h2>
        <div className="bg-white border border-gray-200 rounded-xl p-5 grid grid-cols-3 gap-6">
          <div>
            <p className="text-xs text-gray-500">Participants</p>
            <p className="text-xl font-semibold text-[var(--brand-primary)]">{statValue(stats?.participant_count)}</p>
          </div>
          <div>
            <p className="text-xs text-gray-500">Statements</p>
            <p className="text-xl font-semibold text-[var(--brand-primary)]">{statValue(stats?.statement_count)}</p>
          </div>
          <div>
            <p className="text-xs text-gray-500">Votes</p>
            <p className="text-xl font-semibold text-[var(--brand-primary)]">{statValue(stats?.vote_count)}</p>
          </div>
        </div>
        {liveStatsUnavailable && (
          <p className="text-xs text-gray-400">
            Live stats unavailable — pol.is API didn't respond. Counts will refresh on next page load.
          </p>
        )}
      </section>

      {/* Embed — Session 4: live pol.is embed via shared PolisEmbed.
          Falls back to a friendly "not yet connected" placeholder when the
          conversation_id is absent. */}
      <section className="space-y-2">
        <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide">Conversation</h2>
        <PolisEmbed
          conversationId={conversationId}
          xid={polisXid}
          height={600}
        />
      </section>

      {/* Admin controls */}
      {showAdminControls && (
        <section className="space-y-3">
          <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide">Admin Controls</h2>
          <div className="bg-white border border-gray-200 rounded-xl p-5 space-y-4">
            {polisManageUrl && (
              <div>
                <a
                  href={polisManageUrl}
                  target="_blank"
                  rel="noreferrer"
                  className="text-sm text-[var(--brand-accent)] hover:underline"
                >
                  Manage on pol.is →
                </a>
                <p className="text-xs text-gray-400 mt-1">
                  Opens the conversation on pol.is. Use this to add statements
                  manually, moderate, or close the conversation.
                </p>
              </div>
            )}

            {!editingTitle && (
              <div>
                <button
                  onClick={() => setEditingTitle(true)}
                  className="text-sm text-[var(--brand-accent)] hover:underline"
                  disabled={isArchived}
                >
                  Edit discussion topic
                </button>
                {isArchived && <span className="text-xs text-gray-400 ml-2">(archived — topic locked)</span>}
              </div>
            )}

            {!isArchived && (
              <div>
                <button
                  onClick={handleArchive}
                  disabled={archiving}
                  className="text-sm px-3 py-1.5 border border-red-300 text-red-600 rounded-lg hover:bg-red-50 disabled:opacity-50"
                >
                  {archiving ? 'Archiving…' : 'Archive Polis'}
                </button>
                <p className="text-xs text-gray-400 mt-1">
                  Archiving here marks the platform record archived. To stop
                  participation, also close the conversation on pol.is.
                </p>
              </div>
            )}

            <div className="border-t border-gray-100 pt-4 space-y-2">
              <p className="text-sm text-gray-700">Download export</p>
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={deanonymize}
                  onChange={e => setDeanonymize(e.target.checked)}
                  className="accent-[var(--brand-accent)]"
                />
                <span className="text-xs text-gray-600">Deanonymized (joins xids back to platform users — handle carefully)</span>
              </label>
              <button
                onClick={handleExport}
                className="text-sm px-3 py-1.5 border border-gray-300 text-gray-700 rounded-lg hover:bg-gray-50"
              >
                Download {deanonymize ? 'deanonymized ' : ''}export
              </button>
              <p className="text-xs text-gray-400">
                Export pulls participation data from pol.is; the conversation
                must be reachable.
              </p>
            </div>
          </div>
        </section>
      )}

      {/* Phase 82 C1 — seed-statement generator (reads the saved topic/
          description). The "I linked it first, now generate seeds" path. */}
      {showAdminControls && (
        <section className="space-y-2">
          <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide">Seed statements</h2>
          <PolisSeedGenerator
            topic={polis.title}
            description={polis.prompt}
            slug={parentSlug}
          />
        </section>
      )}

      {/* Linked-from indicator */}
      {linkedProposals.length > 0 && (
        <section className="space-y-2">
          <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide">
            Linked from {linkedProposals.length} proposal{linkedProposals.length === 1 ? '' : 's'}
          </h2>
          <div className="bg-white border border-gray-200 rounded-xl divide-y divide-gray-100">
            {linkedProposals.map(p => (
              <button
                key={p.id}
                onClick={() => navigate(urlFor(parentSlug, 'proposal-detail', p.id))}
                className="w-full text-left px-4 py-3 hover:bg-gray-50 transition-colors flex items-center justify-between"
              >
                <span className="text-sm font-medium text-gray-800 truncate flex-1">{p.title}</span>
                <span className="text-xs text-gray-400 ml-3">{p.status}</span>
              </button>
            ))}
          </div>
        </section>
      )}

      {/* Phase 81 — the "Intended seed statements" section was removed. New
          polises link an existing pol.is conversation that already has its own
          statements; the intended_seed_statements column is retained for the
          programmatic path / Phase 69 but is no longer surfaced here. */}
    </div>
  );
}

import { useCallback, useEffect, useRef, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { useAuth } from '../AuthContext';
import { useOrg } from '../OrgContext';
import api from '../api';
import PolisEmbed from '../components/PolisEmbed';
import PolisDisclosureModal from '../components/PolisDisclosureModal';
import useShouldShowDisclosure from '../hooks/useShouldShowDisclosure';

/**
 * Phase 9 Session 4 — voter-facing Polis page.
 *
 * Route: /orgs/:slug/polises/:polis_id (parallels the existing /orgs/:slug
 * resource convention used implicitly by topics/proposals — admins use
 * /admin/polises/:polis_id, voters get a public-facing path under /orgs).
 *
 * Sections:
 *   - Header (title, prompt, status, scope, creator, created date) — no
 *     admin controls.
 *   - First-visit privacy disclosure modal (Decision 4).
 *   - PolisEmbed with the user's xid (POST .../xid lazily on mount, same
 *     pattern as admin PolisDetail).
 *   - "Linked from" indicator: read-only list of proposals that link to
 *     this Polis (click-through to proposal detail).
 *
 * Permission gating goes through the server: `eligible_viewers_for_polis`
 * filters returns 404/403 if out-of-scope. We surface 403 + "scoped to a
 * sub-org you're not a member of" as a friendly read-only banner with the
 * title/prompt visible (Decision 7 default visibility) and the iframe
 * suppressed.
 */
export default function Polis() {
  const params = useParams();
  const orgSlug = params.slug;
  const polisId = params.polis_id;

  const { user } = useAuth();
  const { userOrgs } = useOrg();

  const [polis, setPolis] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [creator, setCreator] = useState(null);
  const [linkedProposals, setLinkedProposals] = useState([]);
  const [polisXid, setPolisXid] = useState(null);
  const [readOnlyReason, setReadOnlyReason] = useState(null);
  const xidRequested = useRef(false);

  const [shouldShow, dismiss] = useShouldShowDisclosure(polisId);

  // Resolve parent slug — Polis routes are always parent-org-rooted, so
  // when the URL slug points at a sub-org we walk up via userOrgs.
  const parentSlug = (() => {
    const direct = userOrgs.find(o => o.slug === orgSlug);
    if (!direct) return orgSlug; // fall through; backend will 404 if invalid
    if (direct.parent_org_id) {
      const parent = userOrgs.find(o => o.id === direct.parent_org_id);
      return parent?.slug || orgSlug;
    }
    return direct.slug;
  })();

  const load = useCallback(async () => {
    if (!parentSlug || !polisId) return;
    setLoading(true);
    try {
      const data = await api.get(`/api/orgs/${parentSlug}/polises/${polisId}`);
      setPolis(data);
      setError(null);
      setReadOnlyReason(null);
      // Creator name — best-effort; voters might not have permission to
      // see the full member roster.
      try {
        const members = await api.get(`/api/orgs/${parentSlug}/members`);
        const c = (members || []).find(m => m.user_id === data.created_by);
        setCreator(c || null);
      } catch { /* leave null */ }
      // Linked-from: pull proposals visible to the viewer and filter by
      // linked_polis_ids inclusion.
      try {
        const props = await api.get(`/api/orgs/${parentSlug}/proposals`);
        const linked = (props || []).filter(p =>
          Array.isArray(p.linked_polis_ids) && p.linked_polis_ids.includes(polisId),
        );
        setLinkedProposals(linked);
      } catch { setLinkedProposals([]); }
    } catch (e) {
      // 403 with a sub-org-scoped Polis: try to surface read-only treatment
      // (Decision 7 default visibility for parent-org members of a sub-org
      // they're not in). The backend may still return enough metadata in
      // some flavors of the visibility filter; if the body 403s entirely,
      // fall back to a generic friendly error.
      if (e?.status === 403) {
        setReadOnlyReason(e?.message || 'You do not have access to this Polis.');
      } else {
        setError(e);
      }
      setPolis(null);
    } finally {
      setLoading(false);
    }
  }, [parentSlug, polisId]);

  useEffect(() => { load(); }, [load]);

  // xid request — lazy on mount; backend is idempotent so re-renders don't
  // proliferate xid_generated audit events.
  useEffect(() => {
    if (!parentSlug || !polisId || xidRequested.current) return;
    if (!polis || !user) return;
    xidRequested.current = true;
    (async () => {
      try {
        const r = await api.post(`/api/orgs/${parentSlug}/polises/${polisId}/xid`);
        setPolisXid(r?.polis_xid || null);
      } catch {
        // Non-fatal — embed will treat the user as anonymous.
      }
    })();
  }, [parentSlug, polisId, polis, user]);

  if (loading) {
    return (
      <div className="flex justify-center items-center py-20">
        <div className="animate-spin w-8 h-8 border-4 border-[#2E75B6] border-t-transparent rounded-full"></div>
      </div>
    );
  }

  if (readOnlyReason) {
    // 403 from a sub-org private flag or eligibility filter. Voters get a
    // friendly placeholder so they see they're not in scope.
    return (
      <div className="max-w-2xl mx-auto px-4 py-16 text-center space-y-3">
        <h1 className="text-xl font-semibold text-[#1B3A5C]">Deliberation not available</h1>
        <p className="text-sm text-gray-600">{readOnlyReason}</p>
        <Link to="/proposals" className="text-sm text-[#2E75B6] hover:underline">
          Back to proposals
        </Link>
      </div>
    );
  }

  if (error || !polis) {
    return (
      <div className="max-w-2xl mx-auto px-4 py-16 text-center space-y-3">
        <h1 className="text-xl font-semibold text-[#1B3A5C]">Deliberation not found</h1>
        <p className="text-sm text-gray-600">
          {error?.message || 'This Polis does not exist or is not visible to you.'}
        </p>
        <Link to="/proposals" className="text-sm text-[#2E75B6] hover:underline">
          Back to proposals
        </Link>
      </div>
    );
  }

  const isArchived = polis.status === 'archived';
  const stats = polis.participation_stats || null;
  const liveStatsUnavailable = !!stats?.live_stats_unavailable;

  // Decision 7 read-only treatment: the viewer reaches the page, the
  // backend visibility filter returned the Polis (so they can read), but
  // they're not a sub-org member and so shouldn't participate. We don't
  // currently have a lightweight backend "may_participate" flag; the
  // pragmatic surface is: when `polis.sub_org_id` is set AND `currentOrg`
  // is the parent (NOT the sub-org), and `currentOrg.user_role` doesn't
  // mark sub-org membership, we render the read-only banner and suppress
  // the iframe. This keeps the page useful (title + prompt readable) while
  // not inviting non-member participation.
  let showEmbed = !!polis.polis_conversation_id;
  let readOnlyBanner = null;
  if (polis.sub_org_id) {
    // Resolve the sub-org from userOrgs. If the viewer doesn't have a
    // membership row at the sub-org, treat as non-member.
    const subOrg = userOrgs.find(o => o.id === polis.sub_org_id);
    const isSubOrgMember = !!(subOrg && subOrg.user_role);
    if (!isSubOrgMember) {
      showEmbed = false;
      readOnlyBanner = subOrg?.name
        ? `View only — you're not a member of ${subOrg.name}; you can read but not participate.`
        : "View only — you're not a member of this sub-org; you can read but not participate.";
    }
  }

  function statValue(n) {
    if (liveStatsUnavailable || n === null || n === undefined) return '—';
    return Number(n).toLocaleString();
  }

  return (
    <div className="max-w-4xl mx-auto px-4 py-8 space-y-8">
      {/* Privacy disclosure modal — fires once per Polis on first visit */}
      <PolisDisclosureModal open={shouldShow} onDismiss={dismiss} />

      {/* Header — no admin controls; voter view */}
      <section className="space-y-3">
        <Link to="/proposals" className="text-sm text-[#2E75B6] hover:underline">
          ← Back to proposals
        </Link>
        <div className="flex items-center gap-3 flex-wrap">
          <h1 className="text-2xl font-semibold text-[#1B3A5C]">{polis.title}</h1>
          <span
            className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${
              isArchived ? 'bg-gray-200 text-gray-600' : 'bg-green-100 text-green-700'
            }`}
          >
            {polis.status}
          </span>
          {polis.sub_org_id ? (
            <span className="text-[10px] uppercase px-1.5 py-0.5 rounded bg-blue-50 text-blue-700">
              Sub-org
            </span>
          ) : (
            <span className="text-[10px] uppercase px-1.5 py-0.5 rounded bg-gray-100 text-gray-600">
              Org-wide
            </span>
          )}
        </div>
        <p className="text-sm text-gray-700 whitespace-pre-line">{polis.prompt}</p>
        <p className="text-xs text-gray-400">
          Created {new Date(polis.created_at).toLocaleDateString()}
          {creator ? <> by <span className="text-gray-600">{creator.display_name}</span></> : null}
        </p>
        <p className="text-xs text-gray-400">
          New here? <Link to="/help/polis" className="text-[#2E75B6] hover:underline">Learn how Polis works</Link>.
          Most participants only vote on others&apos; statements — you don&apos;t have to write your own.
        </p>
      </section>

      {readOnlyBanner && (
        <div className="bg-amber-50 border border-amber-200 rounded-xl px-4 py-3 text-sm text-amber-900">
          {readOnlyBanner}
        </div>
      )}

      {/* Participation stats (read-only summary) */}
      <section className="space-y-2">
        <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide">Participation</h2>
        <div className="bg-white border border-gray-200 rounded-xl p-5 grid grid-cols-3 gap-6">
          <div>
            <p className="text-xs text-gray-500">Participants</p>
            <p className="text-xl font-semibold text-[#1B3A5C]">{statValue(stats?.participant_count)}</p>
          </div>
          <div>
            <p className="text-xs text-gray-500">Statements</p>
            <p className="text-xl font-semibold text-[#1B3A5C]">{statValue(stats?.statement_count)}</p>
          </div>
          <div>
            <p className="text-xs text-gray-500">Votes</p>
            <p className="text-xl font-semibold text-[#1B3A5C]">{statValue(stats?.vote_count)}</p>
          </div>
        </div>
        {liveStatsUnavailable && (
          <p className="text-xs text-gray-400">
            Live stats unavailable — pol.is API didn&apos;t respond. Counts will refresh on next page load.
          </p>
        )}
      </section>

      {/* Embed (or read-only placeholder for non-member sub-org viewers) */}
      <section className="space-y-2">
        <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide">Conversation</h2>
        {showEmbed ? (
          <PolisEmbed
            conversationId={polis.polis_conversation_id}
            xid={polisXid}
            height={600}
          />
        ) : readOnlyBanner ? (
          <div
            className="bg-gray-50 border border-dashed border-gray-300 rounded-xl flex items-center justify-center text-center text-sm text-gray-500 px-6"
            style={{ minHeight: 240 }}
          >
            <div>
              <p className="font-medium text-gray-600 mb-1">
                Conversation hidden
              </p>
              <p className="text-xs text-gray-500 max-w-md">
                The deliberation is open to {polis.sub_org_id ? 'sub-org members' : 'eligible members'} only.
                You can see the title and prompt but not the conversation itself.
              </p>
            </div>
          </div>
        ) : (
          <PolisEmbed conversationId={null} xid={null} height={400} />
        )}
      </section>

      {/* Linked-from (read-only list of proposals that reference this Polis) */}
      {linkedProposals.length > 0 && (
        <section className="space-y-2">
          <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide">
            Referenced from {linkedProposals.length} proposal{linkedProposals.length === 1 ? '' : 's'}
          </h2>
          <div className="bg-white border border-gray-200 rounded-xl divide-y divide-gray-100">
            {linkedProposals.map(p => (
              <Link
                key={p.id}
                to={`/proposals/${p.id}`}
                className="flex items-center justify-between px-4 py-3 text-sm hover:bg-gray-50 transition-colors"
              >
                <span className="font-medium text-gray-800 truncate flex-1">{p.title}</span>
                <span className="text-xs text-gray-400 ml-3">{p.status}</span>
              </Link>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}

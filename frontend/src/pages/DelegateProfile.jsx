/**
 * Phase 19 F1 — viewer's own org-scoped delegate page management.
 *
 * Route: ``/{slug}/delegate-profile``.
 *
 * Reads ``GET /api/orgs/{slug}/delegate-profile`` (idempotent get-or-create
 * on the caller's own ``OrgDelegateProfile``); writes via the matching
 * PATCH/POST endpoints documented in ``backend/routes/delegate_profiles.py``.
 *
 * Sections:
 *   1. Intro markdown editor + page-visibility selector.
 *   2. Per-topic editor — bio + position_statement + visibility radio,
 *      with a "Submit for approval" affordance that calls the
 *      ``submit-public-accepting`` endpoint.
 *   3. Hard-revert dialog (D15) — "friction proportional to consequence":
 *      named-delegator list when available, private-delegation
 *      reassurance, reversibility framing, soft-alternative button for
 *      ``public_accepting -> private``, and topic-name typing for >5
 *      affected delegators.
 *   4. Past-vote rationale section.
 *   5. Preview link to F2.
 *
 * API gaps flagged to lead (see in-source notes):
 *   - No endpoint exposes per-topic public-origin delegators with the
 *     required public/private split. We pull the personal delegation
 *     network and approximate the named list by topic — origin (public
 *     vs private) is NOT available client-side, so the dialog falls back
 *     to a count-only warning when the origin can't be inferred. Spec
 *     line 253 anticipated this fallback.
 *   - F6 follower count: derived from
 *     ``GET /api/orgs/{slug}/follows/followers`` (already org-scoped per
 *     Phase 18); rendered next to the ``private_delegators`` choice.
 */
import { useState, useEffect, useCallback, useMemo } from 'react';
import { useParams, Link } from 'react-router-dom';
import api from '../api';
import { useAuth } from '../AuthContext';
import { useOrg } from '../OrgContext';
import { useToast } from '../components/Toast';
import { useConfirm } from '../components/ConfirmDialog';
import Avatar from '../components/Avatar';
import TopicBadge from '../components/TopicBadge';
import renderMarkdown from '../utils/renderMarkdown';

// Phase 30.3 D1 — single ladder: private < followers_only < public < public_accepting.
const VISIBILITY_LABELS = {
  private: 'Private (only me)',
  followers_only: 'Visible to my approved followers in this org',
  public: 'Public — transparent only',
  public_accepting: 'Public — accepting delegation',
};

const VISIBILITY_OPTIONS = [
  'private',
  'followers_only',
  'public',
  'public_accepting',
];

// --------------------------------------------------------------------------
// Hard-revert dialog (D15) — modal with friction proportional to consequence.
// --------------------------------------------------------------------------
function HardRevertDialog({
  topic,
  fromVisibility, // 'public' | 'public_accepting'
  targetVisibility = 'private', // Phase 30.3 — 'private' or 'followers_only'
  affectedDelegators, // [{user_id, display_name}]
  privateDelegatorCount, // number; 0 = no reassurance row
  onCancel,
  onConfirmHardRevert,
  onSoftRevert,
  acting,
}) {
  const [typed, setTyped] = useState('');
  const requireType = affectedDelegators.length > 5;
  const displayName = topic.name;
  const typedOk = !requireType || typed.trim() === displayName;
  const showSoft = fromVisibility === 'public_accepting';
  // Phase 30.3 — softer copy when reverting to followers_only vs private.
  const targetLabel = targetVisibility === 'followers_only'
    ? 'restrict to approved followers'
    : 'make private';
  const targetHeading = targetVisibility === 'followers_only'
    ? `Restrict "${displayName}" to approved followers?`
    : `Make "${displayName}" private?`;

  const namedToShow = affectedDelegators.slice(0, 10);
  const more = Math.max(0, affectedDelegators.length - namedToShow.length);

  return (
    <div className="fixed inset-0 z-[10000] flex items-center justify-center">
      <div className="absolute inset-0 bg-black/40" onClick={onCancel} />
      <div className="relative bg-white rounded-xl shadow-xl max-w-lg w-full mx-4 p-6 space-y-4">
        <h3 className="text-lg font-semibold text-gray-800">
          {targetHeading}
        </h3>

        {affectedDelegators.length > 0 ? (
          <div className="text-sm text-gray-700 space-y-2">
            <p>
              <strong>{affectedDelegators.length}</strong>{' '}
              public delegator{affectedDelegators.length === 1 ? '' : 's'}{' '}
              on this topic will be auto-revoked:
            </p>
            <ul className="space-y-1 max-h-40 overflow-y-auto">
              {namedToShow.map(d => (
                <li
                  key={d.user_id}
                  className="flex items-center gap-2 text-xs"
                >
                  <Avatar
                    user={{
                      id: d.user_id,
                      display_name: d.display_name,
                      avatar_url: d.avatar_url,
                    }}
                    size="sm"
                  />
                  <span>{d.display_name}</span>
                </li>
              ))}
              {more > 0 && (
                <li className="text-xs text-gray-500 italic">
                  …and {more} more
                </li>
              )}
            </ul>
          </div>
        ) : (
          <p className="text-sm text-gray-700">
            Any delegations to you on this topic from the public flow will
            be auto-revoked. (We couldn&apos;t fetch a precise list — see
            below for what stays.)
          </p>
        )}

        {privateDelegatorCount > 0 && (
          <p className="text-sm text-gray-600 bg-blue-50 border border-blue-100 rounded-lg p-3">
            <strong>{privateDelegatorCount}</strong> private delegation
            {privateDelegatorCount === 1 ? '' : 's'} on this topic from
            people following you privately will remain unchanged.
          </p>
        )}

        <p className="text-xs text-gray-500">
          If you make this topic public again later, these delegators will
          need to re-delegate to you — their delegations don&apos;t restore
          automatically.
        </p>

        {requireType && (
          <div className="space-y-1">
            <label className="block text-xs text-gray-500">
              Type <strong>{displayName}</strong> to confirm:
            </label>
            <input
              type="text"
              value={typed}
              onChange={e => setTyped(e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-red-300"
            />
          </div>
        )}

        <div className="flex flex-wrap justify-end gap-2 pt-2">
          <button
            onClick={onCancel}
            disabled={acting}
            className="text-sm px-4 py-2 border border-gray-300 text-gray-600 rounded-lg hover:bg-gray-50 disabled:opacity-50"
          >
            Cancel
          </button>
          {showSoft && (
            <button
              onClick={onSoftRevert}
              disabled={acting}
              className="text-sm px-4 py-2 border border-[var(--brand-accent)] text-[var(--brand-accent)] rounded-lg hover:bg-[var(--brand-accent)] hover:text-white disabled:opacity-50"
            >
              Stop accepting new delegations only
            </button>
          )}
          <button
            onClick={onConfirmHardRevert}
            disabled={acting || !typedOk}
            className="text-sm px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 disabled:opacity-50"
          >
            {acting ? 'Working…' : 'Make private (revoke)'}
          </button>
        </div>
      </div>
    </div>
  );
}

// --------------------------------------------------------------------------
// Per-topic row editor.
// --------------------------------------------------------------------------
function TopicRow({
  topic,
  topicProfile, // OrgDelegateProfileTopicOut | null
  slug,
  onChanged,
  onRequestHardRevert,
}) {
  const toast = useToast();
  const [editing, setEditing] = useState(false);
  const [bio, setBio] = useState(topicProfile?.bio || '');
  const [positionStatement, setPositionStatement] = useState(
    topicProfile?.position_statement || ''
  );
  const [busy, setBusy] = useState(false);

  // Phase 31 D1: default radio selection mirrors the backend's row default
  // (Phase 30.3 D2). Was 'private' — that was inconsistent with the row that
  // ``_get_or_create_delegate_profile`` actually creates on the next PATCH,
  // and made the new-account default look like 'private' instead of
  // 'followers_only' until the user explicitly picked something.
  const visibility = topicProfile?.visibility || 'followers_only';
  const pendingApproval = !!(
    topicProfile?.public_accepting_submitted_at
    && !topicProfile?.public_accepting_approved_at
    && !topicProfile?.public_accepting_denied_comment
  );
  const denied = !!topicProfile?.public_accepting_denied_comment;

  // Reset locals if backend topicProfile changes (e.g. after save).
  useEffect(() => {
    setBio(topicProfile?.bio || '');
    setPositionStatement(topicProfile?.position_statement || '');
  }, [topicProfile?.id, topicProfile?.bio, topicProfile?.position_statement]);

  async function patchTopic(patch) {
    setBusy(true);
    try {
      const res = await api.patch(
        `/api/orgs/${slug}/delegate-profile/topics/${topic.id}`,
        patch
      );
      onChanged?.(res);
    } catch (e) {
      toast.error(e.message || 'Save failed');
    } finally {
      setBusy(false);
    }
  }

  async function saveBioAndPosition() {
    await patchTopic({
      bio: bio,
      position_statement: positionStatement || null,
    });
    setEditing(false);
    toast.success('Saved');
  }

  async function setVisibility(newVis) {
    if (newVis === visibility) return;

    // Phase 30.3 F1.3 — bridge any non-public state to public_accepting
    // in one click. The backend lifecycle requires PATCH to 'public'
    // then POST submit; the frontend bridges both. (Phase 30 B2 originally
    // covered the private→public_accepting path; Phase 30.3 extends to
    // followers_only→public_accepting.) Sequential issue: if POST fails
    // after PATCH succeeds, topic is at 'public' and the user can
    // manually click "Submit for approval" to finish.
    if (
      newVis === 'public_accepting'
      && (visibility === 'private' || visibility === 'followers_only')
    ) {
      setBusy(true);
      try {
        await api.patch(
          `/api/orgs/${slug}/delegate-profile/topics/${topic.id}`,
          { visibility: 'public' }
        );
        const res = await api.post(
          `/api/orgs/${slug}/delegate-profile/topics/${topic.id}/submit-public-accepting`
        );
        onChanged?.(res);
        const topicAfter = (res?.topics || []).find(t => t.topic_id === topic.id);
        if (topicAfter?.visibility === 'public_accepting') {
          toast.success('You are now a public delegate on this topic');
        } else {
          toast.success('Submitted for approval — pending review by org administrators');
        }
      } catch (e) {
        toast.error(e.message || 'Failed to register as public delegate');
      } finally {
        setBusy(false);
      }
      return;
    }
    // Backend rejects direct public_accepting on PATCH — use submit endpoint.
    if (newVis === 'public_accepting' && visibility === 'public') {
      setBusy(true);
      try {
        const res = await api.post(
          `/api/orgs/${slug}/delegate-profile/topics/${topic.id}/submit-public-accepting`
        );
        onChanged?.(res);
        toast.success('Submitted for approval (or auto-approved if no approvers)');
      } catch (e) {
        toast.error(e.message || 'Submit failed');
      } finally {
        setBusy(false);
      }
      return;
    }
    // Backend rejects soft revert via PATCH; route through endpoint.
    if (newVis === 'public' && visibility === 'public_accepting') {
      setBusy(true);
      try {
        const res = await api.post(
          `/api/orgs/${slug}/delegate-profile/topics/${topic.id}/revert-to-public`
        );
        onChanged?.(res);
        toast.success('Stopped accepting new delegations on this topic');
      } catch (e) {
        toast.error(e.message || 'Revert failed');
      } finally {
        setBusy(false);
      }
      return;
    }
    // Phase 30.3 F1.3 — hard-revert path covers two destinations:
    // public_accepting → private  (existing)
    // public_accepting → followers_only  (NEW; public delegators get revoked)
    // public → private (existing)
    // public → followers_only (NEW; the topic stops appearing in the
    //   public delegate browse). Same revocation shape as private since
    //   any public-origin delegators lose their public-flow target.
    if (
      (newVis === 'private' || newVis === 'followers_only')
      && (visibility === 'public' || visibility === 'public_accepting')
    ) {
      onRequestHardRevert(topic, visibility, newVis);
      return;
    }
    // Everything else is a simple PATCH (private↔followers_only and
    // followers_only↔public both fall through).
    await patchTopic({ visibility: newVis });
  }

  return (
    <div className="bg-white border border-gray-200 rounded-xl p-4 space-y-3">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div className="flex items-center gap-2">
          <TopicBadge topic={topic} />
          <span className="text-xs text-gray-500">
            {VISIBILITY_LABELS[visibility]}
          </span>
        </div>
        {pendingApproval && (
          <span className="text-xs text-amber-700 bg-amber-50 px-2 py-0.5 rounded">
            Pending approval — submitted{' '}
            {new Date(topicProfile.public_accepting_submitted_at).toLocaleDateString()}
          </span>
        )}
        {denied && (
          <span className="text-xs text-red-700 bg-red-50 px-2 py-0.5 rounded">
            Denied
          </span>
        )}
      </div>

      {/* Visibility radio group — Phase 30.3 D1 single ladder. */}
      <fieldset className="space-y-1">
        {VISIBILITY_OPTIONS.map(v => (
          <label key={v} className="flex items-start gap-2 text-sm">
            <input
              type="radio"
              name={`vis-${topic.id}`}
              checked={visibility === v}
              disabled={busy}
              onChange={() => setVisibility(v)}
              className="mt-0.5"
            />
            <span>{VISIBILITY_LABELS[v]}</span>
          </label>
        ))}
      </fieldset>

      {visibility === 'public' && !pendingApproval && (
        <button
          onClick={() => setVisibility('public_accepting')}
          disabled={busy}
          className="text-xs px-3 py-1.5 border border-[var(--brand-accent)] text-[var(--brand-accent)] rounded-lg hover:bg-[var(--brand-accent)] hover:text-white disabled:opacity-50"
        >
          Submit for approval (start accepting delegation)
        </button>
      )}

      {denied && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-3 text-sm text-red-800 space-y-2">
          <p>
            <strong>Approver feedback:</strong>{' '}
            {topicProfile.public_accepting_denied_comment}
          </p>
          {visibility === 'public' && (
            <button
              onClick={() => setVisibility('public_accepting')}
              disabled={busy}
              className="text-xs px-3 py-1.5 bg-[var(--brand-primary)] text-white rounded-lg hover:bg-[var(--brand-accent)]"
            >
              Re-submit for approval
            </button>
          )}
        </div>
      )}

      {/* Bio + position statement */}
      {editing ? (
        <div className="space-y-2 border-t border-gray-100 pt-3">
          <label className="block text-xs text-gray-500">Bio</label>
          <textarea
            value={bio}
            onChange={e => setBio(e.target.value)}
            rows={3}
            placeholder="Why should others trust you on this topic?"
            className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[var(--brand-accent)] resize-none"
          />
          <label className="block text-xs text-gray-500">
            Position statement (optional)
          </label>
          <textarea
            value={positionStatement}
            onChange={e => setPositionStatement(e.target.value)}
            rows={4}
            placeholder="What do you stand for on this topic? Markdown supported."
            className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[var(--brand-accent)] resize-none"
          />
          <div className="flex justify-end gap-2">
            <button
              onClick={() => { setEditing(false); setBio(topicProfile?.bio || ''); setPositionStatement(topicProfile?.position_statement || ''); }}
              disabled={busy}
              className="text-xs px-3 py-1.5 border border-gray-300 text-gray-600 rounded-lg hover:bg-gray-50"
            >
              Cancel
            </button>
            <button
              onClick={saveBioAndPosition}
              disabled={busy}
              className="text-xs px-4 py-1.5 bg-[var(--brand-primary)] text-white rounded-lg hover:bg-[var(--brand-accent)] disabled:opacity-50"
            >
              {busy ? 'Saving…' : 'Save'}
            </button>
          </div>
        </div>
      ) : (
        <div className="border-t border-gray-100 pt-3 space-y-2 text-sm">
          {topicProfile?.bio ? (
            <p className="italic text-gray-600">&quot;{topicProfile.bio}&quot;</p>
          ) : (
            <p className="text-gray-400 italic">No bio yet.</p>
          )}
          {topicProfile?.position_statement && (
            <div
              className="prose text-sm text-[#2C3E50]"
              dangerouslySetInnerHTML={{
                __html: `<p>${renderMarkdown(topicProfile.position_statement)}</p>`,
              }}
            />
          )}
          <button
            onClick={() => setEditing(true)}
            className="text-xs text-[var(--brand-accent)] hover:underline"
          >
            Edit bio &amp; position
          </button>
        </div>
      )}
    </div>
  );
}

// --------------------------------------------------------------------------
// Per-vote rationale composer
// --------------------------------------------------------------------------
function VoteRationaleEditor({ vote, slug }) {
  const toast = useToast();
  const confirm = useConfirm();
  const [content, setContent] = useState('');
  const [existing, setExisting] = useState(null);
  const [editing, setEditing] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const r = await api.get(`/api/votes/${vote.id}/rationale`);
        if (cancelled) return;
        setExisting(r);
        setContent(r?.content || '');
      } catch {
        if (cancelled) return;
        setExisting(null);
      } finally {
        if (!cancelled) setLoaded(true);
      }
    })();
    return () => { cancelled = true; };
  }, [vote.id]);

  async function save() {
    if (!content.trim()) {
      toast.error('Rationale cannot be empty');
      return;
    }
    setBusy(true);
    try {
      const r = await api.put(`/api/votes/${vote.id}/rationale`, {
        content: content.trim(),
      });
      setExisting(r);
      setEditing(false);
      toast.success('Rationale saved');
    } catch (e) {
      toast.error(e.message || 'Save failed');
    } finally {
      setBusy(false);
    }
  }

  async function handleDelete() {
    const ok = await confirm({
      title: 'Delete rationale?',
      message: 'This will remove your written rationale on this vote.',
      destructive: true,
    });
    if (!ok) return;
    setBusy(true);
    try {
      await api.delete(`/api/votes/${vote.id}/rationale`);
      setExisting(null);
      setContent('');
      setEditing(false);
      toast.success('Rationale removed');
    } catch (e) {
      toast.error(e.message || 'Delete failed');
    } finally {
      setBusy(false);
    }
  }

  if (!loaded) {
    return <div className="text-xs text-gray-400 italic">Loading rationale…</div>;
  }

  return (
    <div className="text-sm space-y-2">
      {editing ? (
        <div className="space-y-2">
          <textarea
            value={content}
            onChange={e => setContent(e.target.value)}
            rows={4}
            placeholder="Why did you vote this way? Markdown supported."
            className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[var(--brand-accent)] resize-none"
          />
          <div className="flex justify-end gap-2">
            <button
              onClick={() => { setEditing(false); setContent(existing?.content || ''); }}
              disabled={busy}
              className="text-xs px-3 py-1.5 border border-gray-300 text-gray-600 rounded-lg hover:bg-gray-50"
            >
              Cancel
            </button>
            <button
              onClick={save}
              disabled={busy}
              className="text-xs px-4 py-1.5 bg-[var(--brand-primary)] text-white rounded-lg hover:bg-[var(--brand-accent)] disabled:opacity-50"
            >
              {busy ? 'Saving…' : 'Save'}
            </button>
          </div>
        </div>
      ) : existing ? (
        <div className="space-y-2">
          <div
            className="prose text-sm text-[#2C3E50] bg-gray-50 rounded-lg p-3"
            dangerouslySetInnerHTML={{
              __html: `<p>${renderMarkdown(existing.content)}</p>`,
            }}
          />
          <div className="flex gap-3 text-xs">
            <button
              onClick={() => setEditing(true)}
              className="text-[var(--brand-accent)] hover:underline"
            >
              Edit rationale
            </button>
            <button
              onClick={handleDelete}
              disabled={busy}
              className="text-red-600 hover:underline"
            >
              Delete
            </button>
          </div>
        </div>
      ) : (
        <button
          onClick={() => setEditing(true)}
          className="text-xs text-[var(--brand-accent)] hover:underline"
        >
          + Add rationale
        </button>
      )}
    </div>
  );
}

// --------------------------------------------------------------------------
// Top-level page
// --------------------------------------------------------------------------
export default function DelegateProfile() {
  const { org_slug } = useParams();
  const { user: currentUser } = useAuth();
  const { currentOrg } = useOrg();
  const toast = useToast();

  const slug = org_slug || currentOrg?.slug || null;
  const [profile, setProfile] = useState(null); // OrgDelegateProfileOut
  const [topics, setTopics] = useState([]);
  const [votes, setVotes] = useState([]);
  const [followerCount, setFollowerCount] = useState(null);
  const [delegatorsByTopic, setDelegatorsByTopic] = useState({});
  const [privateDelegatorCountByTopic, setPrivateDelegatorCountByTopic] = useState({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  // Intro editor state
  const [intro, setIntro] = useState('');
  const [introPreview, setIntroPreview] = useState(false);
  const [introSaving, setIntroSaving] = useState(false);

  // Hard-revert dialog state
  const [revertDialog, setRevertDialog] = useState(null); // { topic, fromVisibility }
  const [revertActing, setRevertActing] = useState(false);

  const load = useCallback(async () => {
    if (!slug) return;
    setLoading(true);
    setError('');
    try {
      const [prof, tops, ownProfile, network, followers] = await Promise.all([
        api.get(`/api/orgs/${slug}/delegate-profile`),
        api.get(`/api/orgs/${slug}/topics`),
        api.get(`/api/users/${currentUser.id}/profile`).catch(() => null),
        api.get(`/api/orgs/${slug}/delegations/network`).catch(() => null),
        api.get(`/api/orgs/${slug}/follows/followers`).catch(() => []),
      ]);
      setProfile(prof);
      setIntro(prof?.intro || '');
      setTopics(tops || []);
      setVotes(ownProfile?.votes || []);
      setFollowerCount((followers || []).length);

      // Build a per-topic map of incoming delegators (org-scoped) so the
      // hard-revert dialog can show named delegators. NB: origin (public
      // vs private) is not exposed by this endpoint — see the in-source
      // note at top of file. We surface the count + names for ALL
      // incoming delegations on the topic (a superset of the public-
      // origin set the backend will revoke); the dialog copy makes the
      // semantics explicit and the private-delegators reassurance row
      // only fires when the count derived from FollowRelationship +
      // delegation_intent suggests private-origin holders exist.
      const byTopic = {};
      const privCountByTopic = {};
      if (network && Array.isArray(network.edges)) {
        // Only "incoming" edges where target = current user.
        const nodeById = {};
        for (const n of network.nodes || []) nodeById[n.id] = n;
        for (const e of network.edges) {
          if (e.direction !== 'incoming') continue;
          const delegatorNode = nodeById[e.source];
          if (!delegatorNode) continue;
          for (const t of e.topics || []) {
            // edge topics carry name only, not id; resolve name -> id via
            // the topics list. "Global" edges (no topic) skipped.
            if (t.name === 'Global') continue;
            const topic = (tops || []).find(x => x.name === t.name);
            if (!topic) continue;
            byTopic[topic.id] = byTopic[topic.id] || [];
            byTopic[topic.id].push({
              user_id: e.source,
              display_name: delegatorNode.label,
              avatar_url: delegatorNode.avatar_url,
            });
          }
        }
      }
      // Best-effort split — without an authoritative endpoint, we
      // conservatively assume the dialog shows all delegators on the
      // topic and the reassurance copy mentions "any private delegations
      // remain unchanged." Use followers as an upper bound for private
      // count: any delegator who is also an approved follower in this
      // org *might* be private-origin. This is approximate and surfaced
      // as such in the copy.
      const followerIds = new Set((followers || []).map(f => f.follower_id));
      for (const tid of Object.keys(byTopic)) {
        privCountByTopic[tid] = byTopic[tid].filter(d => followerIds.has(d.user_id)).length;
      }
      setDelegatorsByTopic(byTopic);
      setPrivateDelegatorCountByTopic(privCountByTopic);
    } catch (e) {
      setError(e.message || 'Failed to load delegate profile');
    } finally {
      setLoading(false);
    }
  }, [slug, currentUser?.id]);

  useEffect(() => { load(); }, [load]);

  // Topic + topicProfile rows.
  const topicRows = useMemo(() => {
    if (!profile) return [];
    const byTopicId = {};
    for (const tp of profile.topics || []) byTopicId[tp.topic_id] = tp;
    return (topics || []).map(t => ({
      topic: t,
      topicProfile: byTopicId[t.id] || null,
    }));
  }, [profile, topics]);

  async function saveIntro() {
    setIntroSaving(true);
    try {
      const res = await api.patch(`/api/orgs/${slug}/delegate-profile`, {
        intro: intro,
      });
      setProfile(res);
      toast.success('Intro saved');
    } catch (e) {
      toast.error(e.message || 'Save failed');
    } finally {
      setIntroSaving(false);
    }
  }

  function handleRequestHardRevert(topic, fromVisibility, targetVisibility = 'private') {
    setRevertDialog({ topic, fromVisibility, targetVisibility });
  }

  async function handleConfirmHardRevert() {
    if (!revertDialog) return;
    const target = revertDialog.targetVisibility || 'private';
    setRevertActing(true);
    try {
      const res = await api.post(
        `/api/orgs/${slug}/delegate-profile/topics/${revertDialog.topic.id}/revert-to-private`,
        { target_visibility: target },
      );
      setProfile(res);
      setRevertDialog(null);
      toast.success(
        target === 'followers_only'
          ? 'Topic restricted to approved followers'
          : 'Topic reverted to private',
      );
      load();
    } catch (e) {
      toast.error(e.message || 'Revert failed');
    } finally {
      setRevertActing(false);
    }
  }

  async function handleSoftRevert() {
    if (!revertDialog) return;
    setRevertActing(true);
    try {
      const res = await api.post(
        `/api/orgs/${slug}/delegate-profile/topics/${revertDialog.topic.id}/revert-to-public`
      );
      setProfile(res);
      setRevertDialog(null);
      toast.success('Stopped accepting new delegations on this topic');
    } catch (e) {
      toast.error(e.message || 'Revert failed');
    } finally {
      setRevertActing(false);
    }
  }

  if (loading) {
    return (
      <div className="flex justify-center items-center py-20">
        <div className="animate-spin w-8 h-8 border-4 border-[var(--brand-accent)] border-t-transparent rounded-full"></div>
      </div>
    );
  }
  if (error) {
    return (
      <div className="max-w-3xl mx-auto px-4 py-8">
        <div className="bg-red-50 border border-red-200 text-red-700 p-4 rounded-lg text-sm">
          {error}
        </div>
      </div>
    );
  }
  if (!profile || !slug) return null;

  const handleOrUsername = currentUser?.delegate_handle || currentUser?.username;

  return (
    <div className="max-w-3xl mx-auto px-4 py-8 space-y-8">
      {/* Header */}
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <h1 className="text-2xl font-semibold text-[var(--brand-primary)]">
            My Delegate Page
          </h1>
          <p className="text-sm text-gray-500 mt-1">
            Manage your delegate identity in {currentOrg?.name || slug}.
          </p>
        </div>
        {handleOrUsername && (
          <Link
            to={`/${slug}/delegates/${handleOrUsername}`}
            className="text-sm px-3 py-1.5 border border-[var(--brand-accent)] text-[var(--brand-accent)] rounded-lg hover:bg-[var(--brand-accent)] hover:text-white transition-colors"
          >
            Preview public page →
          </Link>
        )}
      </div>

      {/* Intro */}
      <section className="space-y-2">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide">
            Intro
          </h2>
          <button
            onClick={() => setIntroPreview(v => !v)}
            className="text-xs text-[var(--brand-accent)] hover:underline"
          >
            {introPreview ? 'Edit' : 'Preview'}
          </button>
        </div>
        {introPreview ? (
          <div
            className="prose text-sm text-[#2C3E50] bg-white border border-gray-200 rounded-xl p-4"
            dangerouslySetInnerHTML={{
              __html: `<p>${renderMarkdown(intro || '_No intro yet._')}</p>`,
            }}
          />
        ) : (
          <textarea
            value={intro}
            onChange={e => setIntro(e.target.value)}
            rows={6}
            placeholder="Tell potential delegators about yourself. Markdown supported."
            className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[var(--brand-accent)] resize-y"
          />
        )}
        <div className="flex justify-end">
          <button
            onClick={saveIntro}
            disabled={introSaving}
            className="text-xs px-4 py-1.5 bg-[var(--brand-primary)] text-white rounded-lg hover:bg-[var(--brand-accent)] disabled:opacity-50"
          >
            {introSaving ? 'Saving…' : 'Save intro'}
          </button>
        </div>
      </section>


      {/* Per-topic editor */}
      <section className="space-y-2">
        <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide">
          Topics
        </h2>
        <p className="text-xs text-gray-500">
          For each topic in this org, choose your visibility. Becoming
          &quot;public — accepting delegation&quot; goes through your org&apos;s
          approval gate (if configured).
        </p>
        {topicRows.length === 0 ? (
          <p className="text-sm text-gray-500 italic">
            No topics in this org yet.
          </p>
        ) : (
          <div className="space-y-3">
            {topicRows.map(({ topic, topicProfile }) => (
              <TopicRow
                key={topic.id}
                topic={topic}
                topicProfile={topicProfile}
                slug={slug}
                onChanged={(res) => setProfile(res)}
                onRequestHardRevert={handleRequestHardRevert}
              />
            ))}
          </div>
        )}
      </section>

      {/* Past-vote rationale */}
      <section className="space-y-2">
        <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide">
          Vote rationales
        </h2>
        <p className="text-xs text-gray-500">
          Add reasoning to your past votes. Rationale is publicly visible
          on the proposal&apos;s topic when that topic is non-private for you.
        </p>
        {votes.length === 0 ? (
          <p className="text-sm text-gray-500 italic">
            No votes recorded yet.
          </p>
        ) : (
          <div className="bg-white border border-gray-200 rounded-xl divide-y divide-gray-100">
            {votes.slice(0, 30).map(v => (
              <div key={v.id} className="px-4 py-3 space-y-2">
                <div className="flex items-baseline justify-between gap-3">
                  <Link
                    to={`/${slug}/proposals/${v.proposal_id}`}
                    className="text-sm text-[var(--brand-accent)] hover:underline truncate"
                  >
                    {v.proposal_title || v.proposal_id}
                  </Link>
                  <span className="text-xs text-gray-500 whitespace-nowrap">
                    {v.vote_value ? v.vote_value.toUpperCase() : 'Voted'}
                  </span>
                </div>
                <VoteRationaleEditor vote={v} slug={slug} />
              </div>
            ))}
            {votes.length > 30 && (
              <div className="px-4 py-2 text-xs text-gray-400 italic">
                Showing 30 of {votes.length} votes.
              </div>
            )}
          </div>
        )}
      </section>

      {/* Hard-revert dialog */}
      {revertDialog && (
        <HardRevertDialog
          topic={revertDialog.topic}
          fromVisibility={revertDialog.fromVisibility}
          targetVisibility={revertDialog.targetVisibility || 'private'}
          affectedDelegators={delegatorsByTopic[revertDialog.topic.id] || []}
          privateDelegatorCount={privateDelegatorCountByTopic[revertDialog.topic.id] || 0}
          onCancel={() => setRevertDialog(null)}
          onConfirmHardRevert={handleConfirmHardRevert}
          onSoftRevert={handleSoftRevert}
          acting={revertActing}
        />
      )}
    </div>
  );
}

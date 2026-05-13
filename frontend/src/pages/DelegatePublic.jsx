/**
 * Phase 19 F2 — Public delegate page for ``{handle_or_username}`` in org
 * ``{slug}``.
 *
 * Route: ``/{slug}/delegates/{handle_or_username}``.
 *
 * Data sources (current backend surface, see "Open API gap" below):
 *   - ``GET /api/orgs/{slug}/delegates`` (browse list) — for users with at
 *     least one ``public_accepting`` topic. Provides intro + public_topics
 *     (both ``public`` and ``public_accepting`` per the backend response
 *     shape) + delegation_count + recent_rationale_ratio. We resolve
 *     ``handle_or_username`` against the list's ``delegate_handle`` /
 *     ``username`` fields.
 *   - ``GET /api/users/{user_id}/profile`` — for the visibility-aware vote
 *     list. Falls back to no-votes if the call 404s.
 *   - ``GET /api/votes/{vote_id}/rationale`` — for each visible vote we
 *     attempt to fetch any rationale (the endpoint is gated by
 *     ``can_view_vote_rationale`` server-side; we just render whatever
 *     comes back).
 *
 * Open API gap (flagged to lead): no public-read endpoint exists for the
 * org-scoped ``OrgDelegateProfile`` (``GET /api/orgs/{slug}/delegate-
 * profile`` is owner-only). Two consequences:
 *   1. We can't render F2 for users whose page exists ONLY in
 *      ``private_delegators`` state with no ``public_accepting`` topics —
 *      the browse endpoint won't list them. F6 handles the count-message
 *      part of this; the page itself shows a "no public delegate page"
 *      empty state when the resolver returns nothing.
 *   2. Users with ``public``-only (transparent, not accepting) topics are
 *      not listed in the browse endpoint either, even though spec D12
 *      says their page should still render. Same empty-state behavior in
 *      v1; needs a backend follow-up to surface those pages.
 *
 * Visibility gating is enforced by the backend endpoints — when the
 * caller doesn't have access we render a generic "not found" view.
 */
import { useState, useEffect, useCallback } from 'react';
import { useParams, Link } from 'react-router-dom';
import api from '../api';
import { useOrg } from '../OrgContext';
import { useAuth } from '../AuthContext';
import Avatar from '../components/Avatar';
import renderMarkdown from '../utils/renderMarkdown';
import { urlFor } from '../utils/urls';
import DelegateModal from '../components/DelegateModal';

function VoteRow({ vote, slug, rationale }) {
  const [expanded, setExpanded] = useState(false);
  if (!vote.visible) {
    return (
      <li className="text-sm text-gray-400 italic py-1.5">
        Hidden vote
      </li>
    );
  }
  const valueLabel = vote.vote_value
    ? vote.vote_value.toUpperCase()
    : 'Voted';
  const colorClass =
    vote.vote_value === 'yes' ? 'text-[#2D8A56]'
    : vote.vote_value === 'no' ? 'text-[#C0392B]'
    : 'text-gray-500';
  return (
    <li className="border-b border-gray-100 last:border-0 py-2 space-y-1">
      <div className="flex items-baseline justify-between gap-3">
        <Link
          to={`/${slug}/proposals/${vote.proposal_id}`}
          className="text-sm text-[var(--brand-accent)] hover:underline truncate"
        >
          {vote.proposal_title || vote.proposal_id}
        </Link>
        <span className={`text-xs font-semibold ${colorClass} whitespace-nowrap`}>
          {valueLabel}
        </span>
      </div>
      <div className="flex items-center gap-3 text-xs text-gray-400">
        {vote.cast_at && (
          <span>{new Date(vote.cast_at).toLocaleDateString()}</span>
        )}
        {rationale && (
          <button
            type="button"
            onClick={() => setExpanded(v => !v)}
            className="text-[var(--brand-accent)] hover:underline"
          >
            {expanded ? 'Hide rationale' : 'Show rationale'}
          </button>
        )}
      </div>
      {rationale && expanded && (
        <div
          className="prose mt-1 text-sm text-[#2C3E50] bg-gray-50 rounded-lg p-3 leading-relaxed"
          dangerouslySetInnerHTML={{
            __html: `<p>${renderMarkdown(rationale.content)}</p>`,
          }}
        />
      )}
    </li>
  );
}

export default function DelegatePublic() {
  const { org_slug, handle_or_username } = useParams();
  const { currentOrg } = useOrg();
  const { user: currentUser } = useAuth();
  const [delegate, setDelegate] = useState(null);
  const [profile, setProfile] = useState(null); // { user, delegate_profiles, votes }
  const [rationales, setRationales] = useState({}); // { vote_id: rationale }
  const [loading, setLoading] = useState(true);
  const [notFound, setNotFound] = useState(false);
  const [error, setError] = useState('');
  const [delegateModalTopic, setDelegateModalTopic] = useState(null);

  const slug = org_slug || currentOrg?.slug || null;

  const load = useCallback(async () => {
    if (!slug || !handle_or_username) return;
    setLoading(true);
    setNotFound(false);
    setError('');
    try {
      // Step 1: resolve handle/username via the org browse endpoint.
      // The endpoint paginates; we walk pages until we find a match. For
      // an org with hundreds of delegates this is suboptimal — flagged for
      // a backend follow-up to add a direct ``GET /api/orgs/{slug}/
      // delegates/{handle_or_username}`` resolver.
      let found = null;
      let offset = 0;
      const PAGE = 100;
      while (true) {
        const page = await api.get(
          `/api/orgs/${slug}/delegates?limit=${PAGE}&offset=${offset}`
        );
        if (!page || page.length === 0) break;
        found = page.find(
          d => d.delegate_handle === handle_or_username
            || d.username === handle_or_username
        );
        if (found) break;
        if (page.length < PAGE) break;
        offset += PAGE;
      }
      if (!found) {
        setNotFound(true);
        return;
      }
      setDelegate(found);

      // Step 2: pull the user's full profile for vote history. The legacy
      // /api/users/{id}/profile endpoint already does visibility gating;
      // hidden votes come back with visible=false and we render a privacy
      // placeholder for them.
      try {
        const prof = await api.get(`/api/users/${found.user_id}/profile`);
        setProfile(prof);

        // Step 3: best-effort fetch of rationale per visible vote.
        const visibleVotes = (prof?.votes || []).filter(v => v.visible);
        const ratEntries = await Promise.all(
          visibleVotes.map(v =>
            api.get(`/api/votes/${v.id}/rationale`)
              .then(r => [v.id, r])
              .catch(() => [v.id, null])
          )
        );
        const ratMap = {};
        for (const [vid, r] of ratEntries) {
          if (r) ratMap[vid] = r;
        }
        setRationales(ratMap);
      } catch {
        // Profile fetch failed (likely 404) — render delegate header only.
        setProfile(null);
      }
    } catch (e) {
      setError(e.message || 'Failed to load delegate page');
    } finally {
      setLoading(false);
    }
  }, [slug, handle_or_username]);

  useEffect(() => { load(); }, [load]);

  if (loading) {
    return (
      <div className="flex justify-center items-center py-20">
        <div className="animate-spin w-8 h-8 border-4 border-[var(--brand-accent)] border-t-transparent rounded-full"></div>
      </div>
    );
  }

  if (notFound || (!delegate && !error)) {
    return (
      <div className="max-w-3xl mx-auto px-4 py-16 text-center space-y-3">
        <h1 className="text-xl font-semibold text-[var(--brand-primary)]">
          Delegate page not found
        </h1>
        <p className="text-sm text-gray-500">
          No public delegate page for &quot;{handle_or_username}&quot; in this
          organization. The page may be private, not yet set up, or the
          handle may be misspelled.
        </p>
        <Link
          to={`/${slug}/delegates`}
          className="inline-block text-sm px-4 py-1.5 border border-[var(--brand-accent)] text-[var(--brand-accent)] rounded-lg hover:bg-[var(--brand-accent)] hover:text-white transition-colors"
        >
          Browse delegates
        </Link>
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

  // Render
  const userObj = profile?.user || {
    id: delegate.user_id,
    username: delegate.username,
    display_name: delegate.display_name,
    avatar_url: delegate.avatar_url,
  };
  const visibleVotes = (profile?.votes || []).filter(v => v.visible);
  // Group visible votes loosely (no per-topic mapping in legacy profile;
  // we list them in chronological order under each topic for now).
  const isSelf = currentUser?.id === userObj.id;

  return (
    <div className="max-w-3xl mx-auto px-4 py-8 space-y-8">
      {/* Header */}
      <header className="flex items-start justify-between gap-4 flex-wrap">
        <div className="flex items-center gap-4">
          <Avatar user={userObj} size="lg" />
          <div>
            <h1 className="text-2xl font-bold text-[var(--brand-primary)]">
              {userObj.display_name || userObj.username}
            </h1>
            <p className="text-sm text-gray-400">
              @{delegate.delegate_handle || userObj.username}
            </p>
            <p className="text-xs text-gray-400 mt-1">
              Public delegate in {currentOrg?.name || slug}
            </p>
          </div>
        </div>
        <div className="flex flex-col items-end gap-2">
          <Link
            to={`/${slug}/delegates`}
            className="text-sm text-[var(--brand-accent)] hover:underline"
          >
            Browse other delegates →
          </Link>
          {isSelf && (
            <Link
              to={`/${slug}/delegate-profile`}
              className="text-xs px-3 py-1.5 border border-[var(--brand-accent)] text-[var(--brand-accent)] rounded-lg hover:bg-[var(--brand-accent)] hover:text-white transition-colors"
            >
              Edit my page
            </Link>
          )}
        </div>
      </header>

      {/* Intro */}
      {delegate.intro && (
        <section>
          <div
            className="prose text-sm text-[#2C3E50] leading-relaxed"
            dangerouslySetInnerHTML={{
              __html: `<p>${renderMarkdown(delegate.intro)}</p>`,
            }}
          />
        </section>
      )}

      {/* Per-topic sections */}
      {delegate.public_topics && delegate.public_topics.length > 0 ? (
        <section>
          <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide mb-3">
            Topics
          </h2>
          <div className="space-y-4">
            {delegate.public_topics.map(t => {
              // Fetch per-topic bio + position_statement: not in the browse
              // payload (it ships {topic_id, name, visibility} only). Per
              // the API gap noted at the top of this file, we surface the
              // topic name + visibility label only and link to vote history
              // below. A future backend addition could ship the full
              // per-topic profile detail in the browse / public-page
              // payload.
              const labelClasses = t.visibility === 'public_accepting'
                ? 'bg-green-50 text-green-700'
                : 'bg-blue-50 text-blue-700';
              const label = t.visibility === 'public_accepting'
                ? 'Accepting delegation'
                : 'Transparent only';
              // Phase 26 D1 — display-name resolution: description with
              // fallback to name. Demos prefix names for scoping; the
              // description is the user-visible label.
              const topicLabel = t.description?.trim() || t.name;
              return (
                <div
                  key={t.topic_id}
                  className="bg-white border border-gray-200 rounded-xl p-4 space-y-2"
                >
                  <div className="flex items-center justify-between gap-3 flex-wrap">
                    <h3 className="text-base font-semibold text-[var(--brand-primary)]">
                      {topicLabel}
                    </h3>
                    <span
                      className={`text-xs px-2 py-0.5 rounded ${labelClasses}`}
                    >
                      {label}
                    </span>
                  </div>
                  {t.visibility === 'public_accepting' && !isSelf && (
                    <button
                      onClick={() => setDelegateModalTopic({
                        id: t.topic_id, name: topicLabel,
                      })}
                      className="text-xs px-3 py-1.5 bg-[var(--brand-primary)] text-white rounded-lg hover:bg-[var(--brand-accent)] transition-colors"
                    >
                      Delegate to {userObj.display_name || userObj.username} on {topicLabel}
                    </button>
                  )}
                </div>
              );
            })}
          </div>
        </section>
      ) : (
        <section>
          <p className="text-sm text-gray-400 italic">
            No public topics for this delegate yet.
          </p>
        </section>
      )}

      {/* Voting record + rationales */}
      <section>
        <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide mb-3">
          Voting record
        </h2>
        {visibleVotes.length === 0 ? (
          <p className="text-sm text-gray-400 italic">
            No public votes yet.
          </p>
        ) : (
          <ul className="bg-white border border-gray-200 rounded-xl px-4">
            {visibleVotes.map(v => (
              <VoteRow
                key={v.id}
                vote={v}
                slug={slug}
                rationale={rationales[v.id] || null}
              />
            ))}
          </ul>
        )}
      </section>

      {/* Stats footer */}
      <div className="text-xs text-gray-400 flex gap-4">
        <span>
          Active delegations: <strong>{delegate.delegation_count}</strong>
        </span>
        {(delegate.recent_rationale_ratio ?? 0) > 0 && (
          <span>
            Rationale on{' '}
            <strong>
              {Math.round(delegate.recent_rationale_ratio * 100)}%
            </strong>{' '}
            of recent votes
          </span>
        )}
      </div>

      {delegateModalTopic && (
        <DelegateModal
          topicId={delegateModalTopic.id}
          topicName={delegateModalTopic.name}
          // Phase 26 D2 — pre-select this page's delegate. The viewer
          // clicked "Delegate to X on Topic" from X's public page; they
          // shouldn't have to search for X again. The modal still
          // offers "Choose someone else" if they change their mind.
          preselectedUser={{
            user_id: userObj.id,
            display_name: userObj.display_name || userObj.username,
            username: userObj.username,
            avatar_url: userObj.avatar_url,
          }}
          onClose={() => setDelegateModalTopic(null)}
          onDone={() => setDelegateModalTopic(null)}
        />
      )}
    </div>
  );
}

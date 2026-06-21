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
import MessageButton from '../components/MessageButton';
import api from '../api';
import { useOrg } from '../OrgContext';
import { useAuth } from '../AuthContext';
import Avatar from '../components/Avatar';
import renderMarkdown from '../utils/renderMarkdown';
import { urlFor } from '../utils/urls';
import DelegateModal from '../components/DelegateModal';

function VoteRow({ vote, slug, rationale, allRationalesExpanded }) {
  const [individuallyExpanded, setIndividuallyExpanded] = useState(false);
  // Phase 30.3 F3 — global "show all rationales" overrides individual
  // per-row state; switching it off collapses everything regardless of
  // local state (clean reset).
  const expanded = allRationalesExpanded || individuallyExpanded;
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
        {rationale && !allRationalesExpanded && (
          <button
            type="button"
            onClick={() => setIndividuallyExpanded(v => !v)}
            className="text-[var(--brand-accent)] hover:underline"
          >
            {individuallyExpanded ? 'Hide rationale' : 'Show rationale'}
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
  const [allRationalesExpanded, setAllRationalesExpanded] = useState(false);

  const slug = org_slug || currentOrg?.slug || null;

  const load = useCallback(async () => {
    if (!slug || !handle_or_username) return;
    setLoading(true);
    setNotFound(false);
    setError('');
    try {
      // Phase 30.2 B1 — load the public delegate page via the
      // dedicated endpoint (which serves the full per-topic profile
      // shape including bio + position_statement) rather than walking
      // the browse list (which ships only {topic_id, name, visibility}).
      // The browse-walk approach was the original source of the
      // missing bio/position render bug; the dedicated endpoint has
      // existed since Phase 19 — we just weren't using it.
      let page;
      try {
        page = await api.get(
          `/api/orgs/${slug}/delegates/${encodeURIComponent(handle_or_username)}`
        );
      } catch (e) {
        // 404 from the endpoint means no page exists or the viewer
        // can't see it (existence isn't leaked per the endpoint's
        // contract). Surface as not-found.
        if (e.status === 404 || /404|not found/i.test(e.message || '')) {
          setNotFound(true);
          return;
        }
        throw e;
      }
      if (!page) {
        setNotFound(true);
        return;
      }
      // Adapt the response shape to the legacy `delegate` state the
      // rest of this component already reads (display_name / username /
      // avatar_url / intro / public_topics). Map `topics` → `public_topics`.
      setDelegate({
        user_id: page.user_id,
        username: page.username,
        display_name: page.display_name,
        avatar_url: page.avatar_url,
        delegate_handle: page.delegate_handle,
        intro: page.intro,
        public_topics: page.topics || [],
      });

      // Step 2: pull the user's full profile for vote history. The legacy
      // /api/users/{id}/profile endpoint already does visibility gating;
      // hidden votes come back with visible=false and we render a privacy
      // placeholder for them.
      try {
        const prof = await api.get(`/api/users/${page.user_id}/profile`);
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
          {isSelf ? (
            <Link
              to={`/${slug}/delegate-profile`}
              className="text-xs px-3 py-1.5 border border-[var(--brand-accent)] text-[var(--brand-accent)] rounded-lg hover:bg-[var(--brand-accent)] hover:text-white transition-colors"
            >
              Edit my page
            </Link>
          ) : (
            /* Phase 77 — message this delegate. Backend gates on the
               delegate's profile visibility; a 403 surfaces inline. */
            <MessageButton
              orgSlug={slug}
              type="delegate"
              recipientId={userObj.id}
              title={`Message ${userObj.display_name || userObj.username}`}
              className="text-xs px-3 py-1.5 border border-[var(--brand-accent)] text-[var(--brand-accent)] rounded-lg hover:bg-[var(--brand-accent)] hover:text-white transition-colors"
            />
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
              // Phase 30.2 B1 — bio + position_statement now flow through
              // the public-page endpoint and render here. Mirrors the
              // edit-view's TopicRow layout sans edit controls.
              // Phase 30.3 — three badges now (followers_only added).
              let labelClasses;
              let label;
              if (t.visibility === 'public_accepting') {
                labelClasses = 'bg-green-50 text-green-700';
                label = 'Accepting delegation';
              } else if (t.visibility === 'followers_only') {
                labelClasses = 'bg-violet-50 text-violet-700';
                label = 'Followers only';
              } else {
                labelClasses = 'bg-blue-50 text-blue-700';
                label = 'Transparent only';
              }
              // Phase 30.1 B5 — Topic.name is the canonical display label;
              // demos no longer prefix the name.
              const topicLabel = t.topic_name || t.name;
              const bio = (t.bio || '').trim();
              const positionStatement = (t.position_statement || '').trim();
              const hasContent = bio || positionStatement;
              return (
                <div
                  key={t.topic_id}
                  className="bg-white border border-gray-200 rounded-xl p-4 space-y-3"
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
                  {hasContent && (
                    <div className="space-y-2">
                      {bio && (
                        <p className="text-sm text-[#2C3E50] italic">"{bio}"</p>
                      )}
                      {positionStatement && (
                        <div
                          className="text-sm text-[#2C3E50] leading-relaxed whitespace-pre-wrap"
                          dangerouslySetInnerHTML={{
                            __html: renderMarkdown(positionStatement),
                          }}
                        />
                      )}
                    </div>
                  )}
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
        <div className="flex items-center justify-between mb-3 gap-3">
          <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide">
            Voting record
          </h2>
          {visibleVotes.length > 0 && Object.keys(rationales).length > 0 && (
            <button
              type="button"
              onClick={() => setAllRationalesExpanded(v => !v)}
              className="text-xs text-[var(--brand-accent)] hover:underline"
            >
              {allRationalesExpanded ? 'Hide all rationales' : 'Show all rationales'}
            </button>
          )}
        </div>
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
                allRationalesExpanded={allRationalesExpanded}
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

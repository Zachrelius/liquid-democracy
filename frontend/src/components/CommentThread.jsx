import { useState, useCallback, useEffect } from 'react';
import api from '../api';
import { useAuth } from '../AuthContext';
import { useOrg } from '../OrgContext';
import Spinner from './Spinner';
import ErrorMessage from './ErrorMessage';
import Comment from './Comment';
import CommentComposer from './CommentComposer';

/**
 * Phase 10 W3 — collapsible comment thread for a proposal.
 *
 * Pattern follows the OrgSettings sustained-majority demotion (9.6 W4):
 * single header line with a chevron + count, expand-on-click, no shared
 * Collapsible component. Each consumer manages its own expand state.
 *
 * Lifecycle:
 *   - Collapsed by default. Header shows ``▸ Comments (N)`` if known,
 *     else ``▸ Comments``. The first expand triggers GET; subsequent
 *     toggles re-render the cached list. Posting / editing / deleting
 *     re-fetches.
 *
 * Permissions:
 *   - GET is server-gated by ``eligible_viewers_for_proposal``; we
 *     surface the 403 via ErrorMessage if it comes back.
 *   - Posting requires (a) being a member of the proposal's parent org
 *     (here approximated as ``currentOrg.user_role`` set, since the
 *     proposal-detail page already gates this) and (b) email-verified.
 *     The CommentComposer renders the unverified state itself; we just
 *     hide the composer entirely when the viewer has no org role.
 *
 * Props:
 *   proposalId — id of the proposal whose comments we're rendering
 */
export default function CommentThread({ proposalId }) {
  const { user } = useAuth();
  const { currentOrg } = useOrg();
  const [expanded, setExpanded] = useState(false);
  const [comments, setComments] = useState(null); // null = not yet fetched
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const isOrgMember = !!currentOrg?.user_role;
  const canPost = isOrgMember && !!user?.email_verified;
  const showComposer = isOrgMember; // unverified members see the composer's
                                    // own VerifyEmailInlineNote treatment

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.get(`/api/proposals/${proposalId}/comments`);
      setComments(Array.isArray(data) ? data : []);
    } catch (e) {
      setError(e);
    } finally {
      setLoading(false);
    }
  }, [proposalId]);

  // Fetch on first expand. Subsequent expands keep the cached list;
  // post/edit/delete will explicitly call load() to refresh.
  useEffect(() => {
    if (expanded && comments === null && !loading && !error) {
      load();
    }
  }, [expanded, comments, loading, error, load]);

  const count = comments?.length ?? null;
  const headerLabel = count == null || count === 0 ? 'Comments' : `Comments (${count})`;

  // Group comments: top-level items in chronological order, each with its
  // chronological replies immediately below. Backend returns them in a
  // single chronological array; we re-shape client-side so replies follow
  // their parent rather than appearing wherever they fell in the timeline.
  function groupedView(list) {
    if (!list || list.length === 0) return [];
    const topLevel = list.filter((c) => !c.parent_comment_id);
    const repliesByParent = new Map();
    for (const c of list) {
      if (c.parent_comment_id) {
        const arr = repliesByParent.get(c.parent_comment_id) || [];
        arr.push(c);
        repliesByParent.set(c.parent_comment_id, arr);
      }
    }
    const result = [];
    for (const top of topLevel) {
      result.push({ comment: top, isReply: false });
      const replies = repliesByParent.get(top.id) || [];
      for (const r of replies) {
        result.push({ comment: r, isReply: true });
      }
    }
    return result;
  }

  return (
    <section className="bg-white border border-gray-200 rounded-xl overflow-hidden mt-6">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="w-full flex items-center justify-between px-5 py-3 text-sm font-semibold text-gray-700 uppercase tracking-wide hover:bg-gray-50 transition-colors"
        aria-expanded={expanded}
      >
        <span className="flex items-center gap-2">
          <span className="text-gray-400">{expanded ? '▾' : '▸'}</span>
          {headerLabel}
        </span>
      </button>

      {expanded && (
        <div className="px-5 pb-5 space-y-4">
          {loading && <Spinner />}
          {error && <ErrorMessage error={error} onRetry={load} />}
          {!loading && !error && comments && comments.length === 0 && (
            <p className="text-sm text-gray-500 italic">
              No comments yet. Start the discussion below.
            </p>
          )}
          {!loading && !error && comments && comments.length > 0 && (
            <div className="divide-y divide-gray-100">
              {groupedView(comments).map(({ comment, isReply }) => (
                <Comment
                  key={comment.id}
                  comment={comment}
                  currentUser={user}
                  proposalId={proposalId}
                  isReply={isReply}
                  canPost={canPost}
                  onChanged={load}
                />
              ))}
            </div>
          )}

          {showComposer && !loading && !error && (
            <div className="pt-2 border-t border-gray-100">
              <CommentComposer
                proposalId={proposalId}
                onSubmit={load}
              />
            </div>
          )}
        </div>
      )}
    </section>
  );
}

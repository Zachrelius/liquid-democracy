/**
 * Phase 19 F3 — inline "Add / Edit my rationale" affordance for the
 * current user's own vote on a proposal-detail page.
 *
 * Composition site: ProposalDetail.jsx, immediately under the user's
 * vote box (binary VoteStatusBox / ApprovalBallot / RankedBallot).
 *
 * Resolves the user's vote_id by querying ``/api/users/{me}/votes`` and
 * matching ``proposal_id`` (the proposal-scoped ``my-vote`` endpoint
 * doesn't return the underlying ``Vote.id`` — flagged in F3 spec body
 * as a small backend gap; the indirection keeps the existing
 * MyVoteStatus shape unchanged for now).
 *
 * Once vote_id is known the rationale CRUD flows through:
 *   - GET /api/votes/{vote_id}/rationale — fetch (404 = none yet)
 *   - PUT /api/votes/{vote_id}/rationale — body {content}
 *   - DELETE /api/votes/{vote_id}/rationale — 204
 *
 * Visibility: rationale is publicly visible only when the proposal's
 * primary topic is non-private for the user (D5/D11). The component
 * surfaces a small note explaining that, but DOES NOT itself try to
 * resolve the topic-state — the message is informational.
 */
import { useState, useEffect, useCallback } from 'react';
import { Link } from 'react-router-dom';
import api from '../api';
import { useAuth } from '../AuthContext';
import { useToast } from './Toast';
import { useConfirm } from './ConfirmDialog';
import renderMarkdown from '../utils/renderMarkdown';

export default function MyVoteRationaleBox({ proposalId, slug, hasVote }) {
  const { user } = useAuth();
  const toast = useToast();
  const confirm = useConfirm();
  const [voteId, setVoteId] = useState(null);
  const [rationale, setRationale] = useState(null);
  const [loaded, setLoaded] = useState(false);
  const [editing, setEditing] = useState(false);
  const [content, setContent] = useState('');
  const [busy, setBusy] = useState(false);

  // Resolve vote_id for this proposal via the user-scoped votes endpoint.
  useEffect(() => {
    if (!user?.id || !proposalId || !hasVote) {
      setLoaded(true);
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const myVotes = await api.get(`/api/users/${user.id}/votes`);
        if (cancelled) return;
        const v = (myVotes || []).find(x => x.proposal_id === proposalId);
        if (v) {
          setVoteId(v.id);
          // Fetch existing rationale if any.
          try {
            const r = await api.get(`/api/votes/${v.id}/rationale`);
            if (!cancelled) {
              setRationale(r);
              setContent(r?.content || '');
            }
          } catch {
            if (!cancelled) {
              setRationale(null);
              setContent('');
            }
          }
        }
      } catch {
        // No-op — ignore failures, the box just won't render.
      } finally {
        if (!cancelled) setLoaded(true);
      }
    })();
    return () => { cancelled = true; };
  }, [user?.id, proposalId, hasVote]);

  const save = useCallback(async () => {
    if (!voteId || !content.trim()) {
      toast.error('Rationale cannot be empty');
      return;
    }
    setBusy(true);
    try {
      const r = await api.put(`/api/votes/${voteId}/rationale`, {
        content: content.trim(),
      });
      setRationale(r);
      setEditing(false);
      toast.success('Rationale saved');
    } catch (e) {
      toast.error(e.message || 'Save failed');
    } finally {
      setBusy(false);
    }
  }, [voteId, content, toast]);

  const remove = useCallback(async () => {
    if (!voteId) return;
    const ok = await confirm({
      title: 'Remove rationale?',
      message: 'Your written rationale on this vote will be deleted.',
      destructive: true,
    });
    if (!ok) return;
    setBusy(true);
    try {
      await api.delete(`/api/votes/${voteId}/rationale`);
      setRationale(null);
      setContent('');
      setEditing(false);
      toast.success('Rationale removed');
    } catch (e) {
      toast.error(e.message || 'Delete failed');
    } finally {
      setBusy(false);
    }
  }, [voteId, confirm, toast]);

  // Don't render if the user has no vote on this proposal yet, or if we
  // haven't loaded yet. The empty state on first load avoids a flash.
  if (!hasVote || !loaded) return null;
  if (!voteId) return null;

  return (
    <div className="bg-white border border-gray-200 rounded-xl p-4 space-y-2">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-gray-700 uppercase tracking-wide">
          Your rationale
        </h3>
        {slug && (
          <Link
            to={`/${slug}/delegate-profile`}
            className="text-xs text-[var(--brand-accent)] hover:underline"
          >
            Manage delegate page →
          </Link>
        )}
      </div>
      <p className="text-xs text-gray-500">
        Optional. Visible to others on your public delegate page when the
        proposal&apos;s topic is non-private for you.
      </p>
      {editing ? (
        <div className="space-y-2">
          <textarea
            value={content}
            onChange={e => setContent(e.target.value)}
            rows={4}
            placeholder="Why did you vote this way? Markdown supported."
            className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[var(--brand-accent)] resize-y"
          />
          <div className="flex justify-end gap-2">
            <button
              onClick={() => { setEditing(false); setContent(rationale?.content || ''); }}
              disabled={busy}
              className="text-xs px-3 py-1.5 border border-gray-300 text-gray-600 rounded-lg hover:bg-gray-50"
            >
              Cancel
            </button>
            <button
              onClick={save}
              disabled={busy || !content.trim()}
              className="text-xs px-4 py-1.5 bg-[var(--brand-primary)] text-white rounded-lg hover:bg-[var(--brand-accent)] disabled:opacity-50"
            >
              {busy ? 'Saving…' : 'Save'}
            </button>
          </div>
        </div>
      ) : rationale ? (
        <div className="space-y-2">
          <div
            className="prose text-sm text-[#2C3E50] bg-gray-50 rounded-lg p-3 leading-relaxed"
            dangerouslySetInnerHTML={{
              __html: `<p>${renderMarkdown(rationale.content)}</p>`,
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
              onClick={remove}
              disabled={busy}
              className="text-red-600 hover:underline"
            >
              Remove
            </button>
          </div>
        </div>
      ) : (
        <button
          onClick={() => setEditing(true)}
          className="text-sm px-3 py-1.5 border border-[var(--brand-accent)] text-[var(--brand-accent)] rounded-lg hover:bg-[var(--brand-accent)] hover:text-white"
        >
          + Add rationale
        </button>
      )}
    </div>
  );
}

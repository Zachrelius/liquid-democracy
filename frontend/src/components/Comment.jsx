import { useState } from 'react';
import api from '../api';
import { useToast } from './Toast';
import { useConfirm } from './ConfirmDialog';
import Avatar from './Avatar';
import UserLink from './UserLink';
import CommentComposer from './CommentComposer';
import renderMarkdown from '../utils/renderMarkdown';

/**
 * Phase 10 W3 — single-comment renderer.
 *
 * Renders one comment row:
 *   - Avatar (sm) + clickable display name + relative timestamp
 *   - markdown-rendered body via the shared ``renderMarkdown`` utility
 *   - Reply / Edit / Delete affordances, gated by author + edit-window
 *
 * Reply mode and indentation:
 *   ``isReply=true`` indents the row with a left-border (matching the
 *   roadmap's "one level of reply threading" decision). Replies hide
 *   the Reply button — the data layer enforces no nested threads, but
 *   the UI hides the affordance to keep the model obvious.
 *
 * Soft-delete:
 *   When ``deleted_at`` is non-null we render ``[deleted]`` in italic
 *   gray and suppress affordances. The row stays in the DOM so any
 *   replies underneath still render with the conversation context
 *   intact.
 *
 * Props:
 *   comment — CommentOut shape (see backend schema)
 *   currentUser — user object from useAuth(), needed for author-gating
 *   proposalId — for the inline reply composer
 *   isReply — true → indented, no Reply button
 *   onChanged — callback to trigger parent re-fetch after edit/delete/reply
 *   canPost — true if the viewer is allowed to post comments at all
 *     (active org member + email-verified). Controls Reply visibility.
 */

const EDIT_WINDOW_MS = 15 * 60 * 1000;

function timeAgo(dateStr) {
  if (!dateStr) return '';
  const ms = Date.now() - new Date(dateStr).getTime();
  if (ms < 60_000) return 'just now';
  const mins = Math.floor(ms / 60_000);
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days}d ago`;
  // Older than ~a month — show the date instead of "60d ago"
  return new Date(dateStr).toLocaleDateString();
}

export default function Comment({
  comment,
  currentUser,
  proposalId,
  isReply = false,
  onChanged,
  canPost = false,
}) {
  const toast = useToast();
  const confirm = useConfirm();
  const [editing, setEditing] = useState(false);
  const [editBody, setEditBody] = useState(comment.body || '');
  const [saving, setSaving] = useState(false);
  const [showReplyComposer, setShowReplyComposer] = useState(false);
  const [deleting, setDeleting] = useState(false);

  const isDeleted = !!comment.deleted_at;
  const isAuthor = !!currentUser && comment.author_id === currentUser.id;
  const ageMs = Date.now() - new Date(comment.created_at).getTime();
  const withinEditWindow = ageMs < EDIT_WINDOW_MS;
  const wasEdited =
    !isDeleted &&
    comment.updated_at &&
    comment.updated_at !== comment.created_at;

  const showReply = !isDeleted && !isReply && canPost;
  const showEdit = !isDeleted && isAuthor && withinEditWindow;
  const showDelete = !isDeleted && isAuthor;

  // Indent replies with a left-border. Top-level rows have no indent.
  const wrapperClass = isReply
    ? 'border-l-2 border-gray-200 pl-4 py-2'
    : 'py-2';

  async function handleSaveEdit() {
    const trimmed = editBody.trim();
    if (!trimmed) {
      toast.error('Comment cannot be empty');
      return;
    }
    setSaving(true);
    try {
      await api.patch(`/api/comments/${comment.id}`, { body: trimmed });
      setEditing(false);
      toast.success('Comment updated');
      onChanged?.();
    } catch (e) {
      toast.error(e?.message || 'Failed to update comment');
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete() {
    const ok = await confirm({
      title: 'Delete comment?',
      message:
        'This will replace your comment with “[deleted]”. Replies stay visible. You cannot undo this.',
      destructive: true,
    });
    if (!ok) return;
    setDeleting(true);
    try {
      await api.delete(`/api/comments/${comment.id}`);
      toast.success('Comment deleted');
      onChanged?.();
    } catch (e) {
      toast.error(e?.message || 'Failed to delete comment');
    } finally {
      setDeleting(false);
    }
  }

  // ---- Soft-deleted render (no avatar, no affordances) -------------
  if (isDeleted) {
    return (
      <div className={wrapperClass}>
        <div className="flex items-baseline gap-2 text-xs text-gray-400">
          <span>{timeAgo(comment.created_at)}</span>
        </div>
        <div className="mt-1 text-sm">
          <em className="text-gray-400">[deleted]</em>
        </div>
      </div>
    );
  }

  // ---- Normal / edit render ----------------------------------------
  return (
    <div className={wrapperClass}>
      <div className="flex items-start gap-2">
        <Avatar user={comment.author} size="sm" className="mt-0.5 flex-shrink-0" />
        <div className="flex-1 min-w-0">
          <div className="flex items-baseline flex-wrap gap-x-2 text-xs text-gray-500">
            <UserLink user={comment.author} className="text-sm" />
            <span>{timeAgo(comment.created_at)}</span>
            {wasEdited && <span className="italic">(edited)</span>}
          </div>

          {editing ? (
            <div className="mt-2 space-y-2">
              <textarea
                value={editBody}
                onChange={(e) => setEditBody(e.target.value)}
                disabled={saving}
                className="w-full min-h-[80px] rounded-lg border border-gray-300 p-3 text-sm text-[#2C3E50] resize-y focus:outline-none focus:border-[#2E75B6] focus:ring-1 focus:ring-[#2E75B6]/30 disabled:bg-gray-50"
              />
              <div className="flex justify-end gap-2">
                <button
                  type="button"
                  onClick={() => {
                    setEditing(false);
                    setEditBody(comment.body || '');
                  }}
                  disabled={saving}
                  className="text-sm px-3 py-1.5 border border-gray-300 text-gray-600 rounded-lg hover:bg-gray-50 transition-colors disabled:opacity-50"
                >
                  Cancel
                </button>
                <button
                  type="button"
                  onClick={handleSaveEdit}
                  disabled={saving || !editBody.trim()}
                  className="text-sm px-4 py-1.5 rounded-lg bg-[#1B3A5C] text-white hover:bg-[#2E75B6] transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {saving ? 'Saving…' : 'Save'}
                </button>
              </div>
            </div>
          ) : (
            <div
              className="prose mt-1 text-sm text-[#2C3E50] leading-relaxed"
              dangerouslySetInnerHTML={{
                __html: `<p>${renderMarkdown(comment.body)}</p>`,
              }}
            />
          )}

          {!editing && (showReply || showEdit || showDelete) && (
            <div className="flex gap-3 mt-1 text-xs text-gray-500">
              {showReply && (
                <button
                  type="button"
                  onClick={() => setShowReplyComposer((v) => !v)}
                  className="hover:text-[#2E75B6] hover:underline"
                >
                  {showReplyComposer ? 'Cancel reply' : 'Reply'}
                </button>
              )}
              {showEdit && (
                <button
                  type="button"
                  onClick={() => {
                    setEditing(true);
                    setEditBody(comment.body || '');
                  }}
                  className="hover:text-[#2E75B6] hover:underline"
                >
                  Edit
                </button>
              )}
              {showDelete && (
                <button
                  type="button"
                  onClick={handleDelete}
                  disabled={deleting}
                  className="hover:text-red-600 hover:underline disabled:opacity-50"
                >
                  {deleting ? 'Deleting…' : 'Delete'}
                </button>
              )}
            </div>
          )}

          {showReplyComposer && (
            <div className="mt-3">
              <CommentComposer
                proposalId={proposalId}
                parentCommentId={comment.id}
                placeholder="Write a reply…"
                autoFocus
                onSubmit={() => {
                  setShowReplyComposer(false);
                  onChanged?.();
                }}
                onCancel={() => setShowReplyComposer(false)}
              />
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

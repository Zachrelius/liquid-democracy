import { useState, useRef, useEffect } from 'react';
import api from '../api';
import { useAuth } from '../AuthContext';
import { useToast } from './Toast';
import VerifyEmailInlineNote from './VerifyEmailInlineNote';

/**
 * Phase 10 W3 — comment composer.
 *
 * Textarea + char counter + Post button used both for top-level
 * comments and replies.
 *
 * Props:
 *   proposalId — id to POST against
 *   parentCommentId — when set, posts as a reply (and renders Cancel
 *     next to Post)
 *   onSubmit(comment) — callback after successful POST; receives the
 *     CommentOut returned by the server
 *   onCancel — optional; in reply mode the Cancel button calls this
 *   placeholder — textarea placeholder (defaults vary by mode)
 *   autoFocus — focus textarea on mount (used for the inline reply
 *     composer that appears below a comment when Reply is clicked)
 */
const MAX_BODY = 5000;

export default function CommentComposer({
  proposalId,
  parentCommentId = null,
  onSubmit,
  onCancel,
  placeholder,
  autoFocus = false,
}) {
  const { user } = useAuth();
  const toast = useToast();
  const [body, setBody] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const textareaRef = useRef(null);

  const isReply = !!parentCommentId;
  const emailVerified = !!user?.email_verified;
  const trimmed = body.trim();
  const canSubmit = !!trimmed && !submitting && emailVerified && trimmed.length <= MAX_BODY;

  useEffect(() => {
    if (autoFocus && textareaRef.current) {
      textareaRef.current.focus();
    }
  }, [autoFocus]);

  async function handleSubmit() {
    if (!canSubmit) return;
    setSubmitting(true);
    try {
      const created = await api.post(`/api/proposals/${proposalId}/comments`, {
        body: trimmed,
        parent_comment_id: parentCommentId || null,
      });
      setBody('');
      toast.success('Comment posted');
      onSubmit?.(created);
    } catch (e) {
      toast.error(e?.message || 'Failed to post comment');
    } finally {
      setSubmitting(false);
    }
  }

  function handleKeyDown(e) {
    // Cmd+Enter (mac) / Ctrl+Enter — submit.
    if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
      e.preventDefault();
      handleSubmit();
    }
  }

  // Unverified state — disable the textarea + buttons and surface the
  // resend affordance via the shared inline note.
  if (!emailVerified) {
    return (
      <div className="space-y-2">
        <textarea
          disabled
          placeholder={placeholder || (isReply ? 'Write a reply…' : 'Add a comment…')}
          className="w-full min-h-[80px] rounded-lg border border-gray-200 bg-gray-50 p-3 text-sm text-gray-500 placeholder-gray-400 resize-y"
        />
        <div className="flex items-center justify-between gap-3">
          <VerifyEmailInlineNote action="comment" />
          <div className="flex gap-2">
            {isReply && (
              <button
                type="button"
                onClick={onCancel}
                className="text-sm px-3 py-1.5 border border-gray-300 text-gray-600 rounded-lg hover:bg-gray-50 transition-colors"
              >
                Cancel
              </button>
            )}
            <button
              type="button"
              disabled
              className="text-sm px-4 py-1.5 rounded-lg bg-[#1B3A5C] text-white opacity-50 cursor-not-allowed"
            >
              Post
            </button>
          </div>
        </div>
      </div>
    );
  }

  const tooLong = trimmed.length > MAX_BODY;

  return (
    <div className="space-y-2">
      <textarea
        ref={textareaRef}
        value={body}
        onChange={(e) => setBody(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder={placeholder || (isReply ? 'Write a reply…' : 'Add a comment…')}
        disabled={submitting}
        className="w-full min-h-[80px] rounded-lg border border-gray-300 p-3 text-sm text-[#2C3E50] placeholder-gray-400 resize-y focus:outline-none focus:border-[#2E75B6] focus:ring-1 focus:ring-[#2E75B6]/30 disabled:bg-gray-50"
      />
      <div className="flex items-center justify-between gap-3">
        <span className={`text-xs ${tooLong ? 'text-red-600' : 'text-gray-400'}`}>
          {body.length} / {MAX_BODY}
        </span>
        <div className="flex gap-2">
          {isReply && (
            <button
              type="button"
              onClick={onCancel}
              disabled={submitting}
              className="text-sm px-3 py-1.5 border border-gray-300 text-gray-600 rounded-lg hover:bg-gray-50 transition-colors disabled:opacity-50"
            >
              Cancel
            </button>
          )}
          <button
            type="button"
            onClick={handleSubmit}
            disabled={!canSubmit}
            className="text-sm px-4 py-1.5 rounded-lg bg-[#1B3A5C] text-white hover:bg-[#2E75B6] transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {submitting ? 'Posting…' : 'Post'}
          </button>
        </div>
      </div>
    </div>
  );
}

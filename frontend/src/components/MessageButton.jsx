import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import api from '../api';
import { urlFor } from '../utils/urls';
import { useToast } from './Toast';

const MAX_LEN = 5000;

// Maps the backend's generic 403 error codes to user-facing copy. The
// block code is deliberately generic (silent blocks — D7).
const ERR_COPY = {
  unable_to_send: "You can't send a message to this person.",
  dm_policy_disabled: 'Direct messages are turned off in this organization.',
  follow_required: 'You can only message members you follow (or who follow you).',
  recipient_unavailable: "This member isn't accepting direct messages.",
};

/**
 * Phase 77 — reusable "Message" button. Opens a small composer; on send it
 * creates (or reuses, via backend dedup) the conversation and navigates to
 * it. Callers control when to render it (visibility gating per surface).
 *
 * Props:
 *   orgSlug            — parent-org slug for the API + nav URLs.
 *   type               — 'direct' | 'delegate' | 'org_inbox'.
 *   recipientId        — required for direct/delegate; omit for org_inbox.
 *   contextProposalId  — optional proposal to link as context.
 *   label              — button text (default "Message").
 *   title              — optional composer heading (e.g. recipient name).
 *   className          — button classes (caller styles to fit the surface).
 */
export default function MessageButton({
  orgSlug,
  type,
  recipientId = null,
  contextProposalId = null,
  label = 'Message',
  title = null,
  className = '',
}) {
  const navigate = useNavigate();
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const [body, setBody] = useState('');
  const [sending, setSending] = useState(false);
  const [error, setError] = useState('');

  async function send() {
    const trimmed = body.trim();
    if (!trimmed) return;
    setSending(true);
    setError('');
    try {
      const payload = { conversation_type: type, body: trimmed };
      if (recipientId) payload.recipient_id = recipientId;
      if (contextProposalId) payload.context_proposal_id = contextProposalId;
      const conv = await api.post(`/api/orgs/${orgSlug}/conversations`, payload);
      toast.success('Message sent');
      setOpen(false);
      setBody('');
      navigate(urlFor(orgSlug, 'message-detail', conv.id));
    } catch (err) {
      const code = err?.raw?.detail?.error;
      setError(ERR_COPY[code] || err?.message || 'Could not send message.');
    } finally {
      setSending(false);
    }
  }

  return (
    <>
      <button
        type="button"
        onClick={() => { setOpen(true); setError(''); }}
        className={className || 'text-sm px-3 py-1.5 border border-[var(--brand-accent)] text-[var(--brand-accent)] rounded-lg hover:bg-[var(--brand-accent)] hover:text-white transition-colors'}
      >
        {label}
      </button>
      {open && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-black/40" onClick={() => !sending && setOpen(false)} />
          <div className="relative bg-white rounded-xl shadow-xl w-full max-w-md p-5 space-y-3">
            <h3 className="text-sm font-semibold text-[var(--brand-primary)]">
              {title || (type === 'org_inbox' ? 'Message the organization' : 'New message')}
            </h3>
            <textarea
              value={body}
              onChange={(e) => setBody(e.target.value)}
              maxLength={MAX_LEN}
              rows={5}
              autoFocus
              placeholder="Write your message…"
              className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[var(--brand-accent)] resize-y"
            />
            <div className="flex items-center justify-between">
              <span className="text-xs text-gray-400">{body.length} / {MAX_LEN}</span>
              {error && <span className="text-xs text-red-600">{error}</span>}
            </div>
            <div className="flex gap-2 justify-end">
              <button
                type="button"
                onClick={() => setOpen(false)}
                disabled={sending}
                className="text-sm px-3 py-1.5 border border-gray-300 text-gray-600 rounded-lg hover:bg-gray-50 disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={send}
                disabled={sending || !body.trim()}
                className="text-sm px-4 py-1.5 bg-[var(--brand-primary)] text-white rounded-lg hover:bg-[var(--brand-accent)] transition-colors disabled:opacity-50"
              >
                {sending ? 'Sending…' : 'Send'}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

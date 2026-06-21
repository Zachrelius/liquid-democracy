import { useState, useEffect, useCallback, useRef } from 'react';
import { Link, useParams, useNavigate } from 'react-router-dom';
import api from '../api';
import { urlFor } from '../utils/urls';
import { useAuth } from '../AuthContext';
import { useHasPermission } from '../hooks/useHasPermission';
import Spinner from '../components/Spinner';
import ErrorMessage from '../components/ErrorMessage';
import { useToast } from '../components/Toast';
import { useConfirm } from '../components/ConfirmDialog';

const MAX_LEN = 5000;
const TYPE_LABEL = { direct: 'Direct', delegate: 'Delegate', org_inbox: 'Org Inbox' };

const SEND_ERR = {
  unable_to_send: "You can't send messages to this person.",
};

export default function ConversationDetail() {
  const { org_slug: slug, conversation_id: convId } = useParams();
  const { user } = useAuth();
  const navigate = useNavigate();
  const toast = useToast();
  const confirm = useConfirm();
  const canViewInbox = useHasPermission('org_inbox.view');

  const [data, setData] = useState(null);
  const [error, setError] = useState('');
  const [body, setBody] = useState('');
  const [sending, setSending] = useState(false);
  const [sendError, setSendError] = useState('');
  const bottomRef = useRef(null);

  const load = useCallback(async () => {
    try {
      const d = await api.get(`/api/orgs/${slug}/conversations/${convId}`);
      setData(d);
    } catch (err) {
      setError(err?.message || 'Failed to load conversation');
    }
  }, [slug, convId]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    if (data) bottomRef.current?.scrollIntoView({ block: 'end' });
  }, [data]);

  async function send() {
    const trimmed = body.trim();
    if (!trimmed) return;
    setSending(true);
    setSendError('');
    try {
      await api.post(`/api/orgs/${slug}/conversations/${convId}/messages`, { body: trimmed });
      setBody('');
      await load();
    } catch (err) {
      const code = err?.raw?.detail?.error;
      setSendError(SEND_ERR[code] || err?.message || 'Could not send message.');
    } finally {
      setSending(false);
    }
  }

  async function blockUser(otherId) {
    const ok = await confirm({
      title: 'Block this person?',
      message: "They won't be able to message you in this organization, and you won't be able to message them. You can unblock later from the Messages page.",
      destructive: true,
    });
    if (!ok) return;
    try {
      await api.post(`/api/orgs/${slug}/message-blocks`, { blocked_id: otherId });
      toast.success('Blocked');
      navigate(urlFor(slug, 'messages'));
    } catch (err) {
      toast.error(err?.message || 'Could not block');
    }
  }

  async function closeConversation() {
    try {
      await api.post(`/api/orgs/${slug}/conversations/${convId}/close`);
      toast.success('Conversation closed');
      await load();
    } catch (err) {
      toast.error(err?.message || 'Could not close conversation');
    }
  }

  if (error) return <div className="max-w-3xl mx-auto px-4 py-8"><ErrorMessage error={error} /></div>;
  if (!data) return <div className="max-w-3xl mx-auto px-4 py-8"><Spinner /></div>;

  const { conversation: conv, messages, context_proposal: ctxProposal } = data;
  const isInbox = conv.conversation_type === 'org_inbox';
  const canClose = isInbox ? canViewInbox : true;
  const canBlock = !isInbox && conv.other_party_id;

  return (
    <div className="max-w-3xl mx-auto px-4 py-8">
      <Link to={urlFor(slug, 'messages')} className="text-sm text-[var(--brand-accent)] hover:underline inline-block mb-4">
        ← Back to Messages
      </Link>

      {/* Header */}
      <div className="flex items-start justify-between gap-3 mb-4">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-xl font-semibold text-[var(--brand-primary)]">{conv.other_party_display_name}</h1>
            <span className="text-[10px] uppercase tracking-wide text-gray-400 border border-gray-200 rounded px-1.5 py-0.5">
              {TYPE_LABEL[conv.conversation_type] || conv.conversation_type}
            </span>
            {conv.status === 'closed' && <span className="text-[10px] uppercase tracking-wide text-gray-400">closed</span>}
          </div>
          {conv.subject && <p className="text-sm text-gray-500 mt-0.5">{conv.subject}</p>}
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {canBlock && (
            <button type="button" onClick={() => blockUser(conv.other_party_id)} className="text-xs text-gray-400 hover:text-red-600">
              Block
            </button>
          )}
          {canClose && conv.status !== 'closed' && (
            <button type="button" onClick={closeConversation} className="text-xs text-gray-400 hover:text-gray-700">
              Close
            </button>
          )}
        </div>
      </div>

      {/* Linked proposal context */}
      {ctxProposal && (
        <Link
          to={urlFor(slug, 'proposal-detail', ctxProposal.id)}
          className="block bg-white border border-gray-200 rounded-lg px-4 py-2 mb-4 hover:border-[var(--brand-accent)] transition-colors"
        >
          <span className="text-[10px] uppercase tracking-wide text-gray-400">About proposal</span>
          <p className="text-sm font-medium text-[var(--brand-primary)]">{ctxProposal.title}</p>
        </Link>
      )}

      {/* Messages */}
      <div className="space-y-2 mb-4">
        {messages.length === 0 && <p className="text-sm text-gray-400 text-center py-8">No messages yet.</p>}
        {messages.map(m => {
          if (m.is_system) {
            return (
              <div key={m.id} className="text-center">
                <span className="text-[11px] text-gray-400 italic">{m.body}</span>
              </div>
            );
          }
          const mine = m.sender_id === user?.id;
          return (
            <div key={m.id} className={`flex ${mine ? 'justify-end' : 'justify-start'}`}>
              <div className={`max-w-[80%] rounded-2xl px-3 py-2 ${mine ? 'bg-[var(--brand-primary)] text-white' : 'bg-white border border-gray-200 text-gray-800'}`}>
                {!mine && <p className="text-[11px] font-medium text-gray-500 mb-0.5">{m.sender_display_name}</p>}
                <p className="text-sm whitespace-pre-wrap break-words">{m.body}</p>
                <p className={`text-[10px] mt-0.5 ${mine ? 'text-blue-100' : 'text-gray-400'}`}>
                  {new Date(m.created_at).toLocaleString()}
                </p>
              </div>
            </div>
          );
        })}
        <div ref={bottomRef} />
      </div>

      {/* Composer */}
      <div className="bg-white border border-gray-200 rounded-xl p-3 space-y-2">
        {conv.status === 'closed' && (
          <p className="text-xs text-gray-400">Sending a message will reopen this conversation.</p>
        )}
        <textarea
          value={body}
          onChange={(e) => setBody(e.target.value)}
          maxLength={MAX_LEN}
          rows={3}
          placeholder="Write a message…"
          className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[var(--brand-accent)] resize-y"
        />
        <div className="flex items-center justify-between">
          <span className="text-xs text-gray-400">{body.length} / {MAX_LEN}</span>
          <div className="flex items-center gap-3">
            {sendError && <span className="text-xs text-red-600">{sendError}</span>}
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
    </div>
  );
}

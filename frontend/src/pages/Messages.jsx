import { useState, useEffect, useCallback } from 'react';
import { Link, useParams } from 'react-router-dom';
import api from '../api';
import { urlFor } from '../utils/urls';
import { useHasPermission } from '../hooks/useHasPermission';
import Spinner from '../components/Spinner';
import ErrorMessage from '../components/ErrorMessage';
import { useToast } from '../components/Toast';

function relTime(iso) {
  if (!iso) return '';
  const ms = Date.now() - new Date(iso).getTime();
  if (ms < 0) return 'just now';
  const m = Math.floor(ms / 60000);
  if (m < 1) return 'just now';
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.floor(h / 24);
  if (d < 30) return `${d}d ago`;
  return new Date(iso).toLocaleDateString();
}

const TYPE_LABEL = { direct: 'Direct', delegate: 'Delegate', org_inbox: 'Org Inbox' };

function ConversationRow({ slug, conv }) {
  return (
    <Link
      to={urlFor(slug, 'message-detail', conv.id)}
      className="flex items-center gap-3 px-4 py-3 bg-white border border-gray-200 rounded-lg hover:border-[var(--brand-accent)] transition-colors"
    >
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className={`text-sm ${conv.unread_count > 0 ? 'font-semibold text-[var(--brand-primary)]' : 'font-medium text-gray-800'}`}>
            {conv.other_party_display_name}
          </span>
          <span className="text-[10px] uppercase tracking-wide text-gray-400 border border-gray-200 rounded px-1.5 py-0.5">
            {TYPE_LABEL[conv.conversation_type] || conv.conversation_type}
          </span>
          {conv.status === 'closed' && (
            <span className="text-[10px] uppercase tracking-wide text-gray-400">closed</span>
          )}
        </div>
        {conv.last_message_preview && (
          <p className="text-xs text-gray-500 truncate mt-0.5">{conv.last_message_preview}</p>
        )}
      </div>
      <div className="shrink-0 flex flex-col items-end gap-1">
        <span className="text-[11px] text-gray-400">{relTime(conv.last_message_at)}</span>
        {conv.unread_count > 0 && (
          <span className="inline-flex items-center justify-center min-w-[20px] h-5 px-1.5 text-xs font-semibold bg-[var(--brand-accent)] text-white rounded-full">
            {conv.unread_count}
          </span>
        )}
      </div>
    </Link>
  );
}

function BlockedUsers({ slug }) {
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const [blocks, setBlocks] = useState([]);
  const [loaded, setLoaded] = useState(false);

  const load = useCallback(async () => {
    try {
      setBlocks(await api.get(`/api/orgs/${slug}/message-blocks`));
    } catch {
      setBlocks([]);
    } finally {
      setLoaded(true);
    }
  }, [slug]);

  useEffect(() => { if (open && !loaded) load(); }, [open, loaded, load]);

  async function unblock(id) {
    try {
      await api.delete(`/api/orgs/${slug}/message-blocks/${id}`);
      toast.success('Unblocked');
      setBlocks(bs => bs.filter(b => b.blocked_id !== id));
    } catch (err) {
      toast.error(err?.message || 'Could not unblock');
    }
  }

  return (
    <div className="mt-6 border-t border-gray-200 pt-4">
      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        className="text-sm text-gray-500 hover:text-gray-700"
      >
        {open ? '▾' : '▸'} Manage blocked users
      </button>
      {open && (
        <div className="mt-2">
          {!loaded ? (
            <p className="text-xs text-gray-400">Loading…</p>
          ) : blocks.length === 0 ? (
            <p className="text-xs text-gray-400">You haven't blocked anyone in this organization.</p>
          ) : (
            <ul className="space-y-1">
              {blocks.map(b => (
                <li key={b.id} className="flex items-center justify-between gap-3 text-sm bg-white border border-gray-200 rounded px-3 py-1.5">
                  <span className="text-gray-700">{b.blocked_display_name}</span>
                  <button type="button" onClick={() => unblock(b.blocked_id)} className="text-xs text-[var(--brand-accent)] hover:underline">
                    Unblock
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

export default function Messages() {
  const { org_slug: slug } = useParams();
  const canViewInbox = useHasPermission('org_inbox.view');
  const [tab, setTab] = useState('mine');
  const [mine, setMine] = useState(null);
  const [inbox, setInbox] = useState(null);
  const [error, setError] = useState('');

  const loadMine = useCallback(async () => {
    try {
      setMine(await api.get(`/api/orgs/${slug}/conversations`));
    } catch (err) {
      setError(err?.message || 'Failed to load messages');
    }
  }, [slug]);

  const loadInbox = useCallback(async () => {
    try {
      setInbox(await api.get(`/api/orgs/${slug}/org-inbox?status_filter=all`));
    } catch {
      setInbox([]);
    }
  }, [slug]);

  useEffect(() => { loadMine(); }, [loadMine]);
  useEffect(() => { if (tab === 'inbox' && canViewInbox && inbox === null) loadInbox(); }, [tab, canViewInbox, inbox, loadInbox]);

  // "My Messages" = the user's own threads. For org_inbox, the member side
  // has other_party_id === null (their own thread to the org); the admin
  // side (viewing another member's inbox thread) has a non-null other party
  // and belongs only in the Org Inbox tab.
  const myConversations = (mine || []).filter(c => (
    c.conversation_type !== 'org_inbox' || c.other_party_id == null
  ));

  return (
    <div className="max-w-3xl mx-auto px-4 py-8">
      <h1 className="text-2xl font-semibold text-[var(--brand-primary)] mb-6">Messages</h1>

      {canViewInbox && (
        <div className="flex bg-white border border-gray-200 rounded-lg overflow-hidden mb-5 w-fit">
          {[['mine', 'My Messages'], ['inbox', 'Org Inbox']].map(([key, lbl]) => (
            <button
              key={key}
              onClick={() => setTab(key)}
              className={`px-4 py-1.5 text-sm transition-colors ${tab === key ? 'bg-[var(--brand-primary)] text-white' : 'text-gray-600 hover:bg-gray-50'}`}
            >
              {lbl}
            </button>
          ))}
        </div>
      )}

      {error ? (
        <ErrorMessage error={error} />
      ) : tab === 'inbox' && canViewInbox ? (
        inbox === null ? <Spinner /> : inbox.length === 0 ? (
          <p className="text-center py-16 text-gray-400">No messages in the org inbox yet.</p>
        ) : (
          <div className="space-y-2">
            {inbox.map(c => <ConversationRow key={c.id} slug={slug} conv={c} />)}
          </div>
        )
      ) : mine === null ? (
        <Spinner />
      ) : myConversations.length === 0 ? (
        <p className="text-center py-16 text-gray-400">No conversations yet.</p>
      ) : (
        <div className="space-y-2">
          {myConversations.map(c => <ConversationRow key={c.id} slug={slug} conv={c} />)}
        </div>
      )}

      <BlockedUsers slug={slug} />
    </div>
  );
}

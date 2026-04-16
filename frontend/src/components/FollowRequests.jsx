import { useState, useEffect, useCallback } from 'react';
import api from '../api';
import UserLink from './UserLink';

function timeAgo(dateStr) {
  if (!dateStr) return '';
  const ms = Date.now() - new Date(dateStr).getTime();
  const mins = Math.floor(ms / 60000);
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

function IncomingCard({ req, onResponded }) {
  const [acting, setActing] = useState(false);
  const [feedback, setFeedback] = useState('');

  async function respond(status, permissionLevel) {
    setActing(true);
    try {
      await api.put(`/api/follows/requests/${req.id}/respond`, {
        status,
        permission_level: permissionLevel,
      });
      setFeedback(status === 'approved' ? 'Approved' : 'Denied');
      setTimeout(() => onResponded?.(), 600);
    } catch (e) {
      setFeedback(e.message);
    } finally {
      setActing(false);
    }
  }

  return (
    <div className="border border-gray-200 rounded-xl p-4 space-y-2">
      <div>
        <UserLink user={req.requester} className="text-sm" />
        <span className="ml-1.5 text-xs text-gray-400">@{req.requester.username}</span>
        <span className="ml-2 text-xs text-gray-400">{timeAgo(req.requested_at)}</span>
      </div>
      <p className="text-xs text-gray-500">
        Wants to follow you
        <span className="text-gray-400"> — choose "Accept Delegate" if you want them to be able to delegate their vote to you</span>
      </p>
      {req.message && (
        <p className="text-xs text-gray-500 italic">"{req.message}"</p>
      )}
      {feedback ? (
        <p className={`text-xs font-medium ${feedback === 'Denied' ? 'text-red-500' : 'text-green-600'}`}>
          {feedback}
        </p>
      ) : (
        <div className="flex gap-2 flex-wrap">
          <button
            onClick={() => respond('denied', null)}
            disabled={acting}
            className="text-xs px-3 py-1.5 border border-red-200 text-red-500 rounded-lg hover:bg-red-50 transition-colors disabled:opacity-50"
          >
            Deny
          </button>
          <button
            onClick={() => respond('approved', 'view_only')}
            disabled={acting}
            className="text-xs px-3 py-1.5 border border-gray-300 text-gray-600 rounded-lg hover:bg-gray-50 transition-colors disabled:opacity-50"
          >
            Accept (view only)
          </button>
          <button
            onClick={() => respond('approved', 'delegation_allowed')}
            disabled={acting}
            className="text-xs px-3 py-1.5 bg-[#1B3A5C] text-white rounded-lg hover:bg-[#2E75B6] transition-colors disabled:opacity-50"
          >
            Accept Delegate
          </button>
        </div>
      )}
    </div>
  );
}

function OutgoingCard({ req, intent, onCancelled }) {
  const [acting, setActing] = useState(false);

  async function cancel() {
    setActing(true);
    try {
      if (intent) {
        await api.delete(`/api/delegations/intents/${intent.id}`);
      }
      onCancelled?.();
    } catch {
      setActing(false);
    }
  }

  return (
    <div className="border border-gray-200 rounded-xl p-4 space-y-1">
      <div className="flex items-center justify-between">
        <div>
          <UserLink user={req.target} className="text-sm" />
          <span className="ml-1.5 text-xs text-gray-400">@{req.target.username}</span>
        </div>
        <span className={`text-xs px-2 py-0.5 rounded ${
          req.status === 'pending' ? 'bg-amber-100 text-amber-700'
            : req.status === 'approved' ? 'bg-green-100 text-green-700'
            : 'bg-red-100 text-red-700'
        }`}>
          {req.status}
        </span>
      </div>
      <p className="text-xs text-gray-400">
        {intent
          ? <span className="text-[#2E75B6] font-medium">Delegation request</span>
          : <span className="text-gray-500">Follow request</span>
        }
        {' · '}Sent {timeAgo(req.requested_at)}
        {intent && intent.status === 'pending' && intent.topic && (
          <> · Delegation on <span className="font-medium">{intent.topic.name}</span> will auto-activate on approval</>
        )}
      </p>
      {req.status === 'pending' && intent && (
        <button
          onClick={cancel}
          disabled={acting}
          className="text-xs text-red-500 hover:underline disabled:opacity-50"
        >
          Cancel
        </button>
      )}
    </div>
  );
}

export default function FollowRequests() {
  const [incoming, setIncoming] = useState([]);
  const [outgoing, setOutgoing] = useState([]);
  const [intents, setIntents] = useState([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    try {
      const [inc, out, ints] = await Promise.all([
        api.get('/api/follows/requests/incoming'),
        api.get('/api/follows/requests/outgoing'),
        api.get('/api/delegations/intents'),
      ]);
      setIncoming(inc);
      setOutgoing(out);
      setIntents(ints);
    } catch { /* ignore */ } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  // Match intents to outgoing requests
  const intentsByReqId = {};
  for (const i of intents) {
    if (i.status === 'pending') {
      intentsByReqId[i.follow_request_id] = i;
    }
  }

  const pendingIncoming = incoming.filter(r => r.status === 'pending');
  const pendingOutgoing = outgoing.filter(r => r.status === 'pending');

  if (loading) return null;
  if (pendingIncoming.length === 0 && pendingOutgoing.length === 0) return null;

  return (
    <div className="space-y-6">
      {pendingIncoming.length > 0 && (
        <section>
          <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide mb-3">
            Incoming Requests ({pendingIncoming.length})
          </h2>
          <div className="space-y-3">
            {pendingIncoming.map(r => (
              <IncomingCard key={r.id} req={r} onResponded={load} />
            ))}
          </div>
        </section>
      )}

      {pendingOutgoing.length > 0 && (
        <section>
          <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide mb-3">
            Your Pending Requests ({pendingOutgoing.length})
          </h2>
          <div className="space-y-3">
            {pendingOutgoing.map(r => (
              <OutgoingCard
                key={r.id}
                req={r}
                intent={intentsByReqId[r.id]}
                onCancelled={load}
              />
            ))}
          </div>
        </section>
      )}
    </div>
  );
}

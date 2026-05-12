import { useState, useEffect, useCallback, useMemo } from 'react';
import api from '../api';
import { useOrg } from '../OrgContext';
import UserLink from './UserLink';
import Avatar from './Avatar';
import { timeAgo } from '../utils/timeAgo';

function IncomingCard({ req, onResponded, orgSlug }) {
  const [acting, setActing] = useState(false);
  const [feedback, setFeedback] = useState('');

  async function respond(status, permissionLevel) {
    setActing(true);
    try {
      await api.put(`/api/orgs/${orgSlug}/follows/requests/${req.id}/respond`, {
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
      <div className="flex items-center gap-2 flex-wrap">
        <Avatar user={req.requester} size="sm" />
        <UserLink user={req.requester} className="text-sm" />
        <span className="text-xs text-gray-400">@{req.requester.username}</span>
        <span className="text-xs text-gray-400">{timeAgo(req.requested_at)}</span>
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
            className="text-xs px-3 py-1.5 bg-[var(--brand-primary)] text-white rounded-lg hover:bg-[var(--brand-accent)] transition-colors disabled:opacity-50"
          >
            Accept Delegate
          </button>
        </div>
      )}
    </div>
  );
}

function OutgoingCard({ req, intent, onCancelled, orgSlug }) {
  const [acting, setActing] = useState(false);

  async function cancel() {
    setActing(true);
    try {
      if (intent) {
        await api.delete(`/api/orgs/${orgSlug}/delegations/intents/${intent.id}`);
      }
      onCancelled?.();
    } catch {
      setActing(false);
    }
  }

  return (
    <div className="border border-gray-200 rounded-xl p-4 space-y-1">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Avatar user={req.target} size="sm" />
          <UserLink user={req.target} className="text-sm" />
          <span className="text-xs text-gray-400">@{req.target.username}</span>
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
          ? <span className="text-[var(--brand-accent)] font-medium">Delegation request</span>
          : <span className="text-gray-500">Follow request</span>
        }
        {' · '}Sent {timeAgo(req.requested_at)}
        {intent && intent.status === 'pending' && intent.topic && (
          <> · Delegation on <span className="font-medium">{intent.topic.description?.trim() || intent.topic.name}</span> will auto-activate on approval</>
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
  // Phase 18 — follow + delegation surfaces are org-scoped. Resolve the
  // parent-org slug from currentOrg (walk up if currentOrg is a sub-org).
  const { currentOrg, userOrgs } = useOrg();
  const orgSlug = useMemo(() => {
    if (!currentOrg) return null;
    if (currentOrg.parent_org_id) {
      const parent = userOrgs.find(o => o.id === currentOrg.parent_org_id);
      return parent?.slug || null;
    }
    return currentOrg.slug;
  }, [currentOrg, userOrgs]);

  const [incoming, setIncoming] = useState([]);
  const [outgoing, setOutgoing] = useState([]);
  const [intents, setIntents] = useState([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    if (!orgSlug) {
      setLoading(false);
      return;
    }
    try {
      const [inc, out, ints] = await Promise.all([
        api.get(`/api/orgs/${orgSlug}/follows/requests/incoming`),
        api.get(`/api/orgs/${orgSlug}/follows/requests/outgoing`),
        api.get(`/api/orgs/${orgSlug}/delegations/intents`),
      ]);
      setIncoming(inc);
      setOutgoing(out);
      setIntents(ints);
    } catch { /* ignore */ } finally {
      setLoading(false);
    }
  }, [orgSlug]);

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
              <IncomingCard key={r.id} req={r} onResponded={load} orgSlug={orgSlug} />
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
                orgSlug={orgSlug}
              />
            ))}
          </div>
        </section>
      )}
    </div>
  );
}

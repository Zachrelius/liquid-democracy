import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import api from '../api';
import TopicBadge from './TopicBadge';

function timeAgo(dateStr) {
  if (!dateStr) return '';
  const ms = Date.now() - new Date(dateStr).getTime();
  const mins = Math.floor(ms / 60000);
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

function ResultCard({ user, topicId, onDone }) {
  const [acting, setActing] = useState(false);
  const [feedback, setFeedback] = useState('');

  const profiles = user.delegate_profiles || [];
  const isPublicForTopic = topicId && profiles.some(p => p.topic_id === topicId);
  const isPublic = profiles.length > 0;
  const isFollowing = user.follow_status === 'following';
  const isPending = user.follow_status === 'pending';
  const canDelegate = isPublicForTopic || (isFollowing && user.follow_permission === 'delegation_allowed');

  async function doDelegate() {
    setActing(true);
    setFeedback('');
    try {
      await api.post('/api/delegations/request', {
        delegate_id: user.id,
        topic_id: topicId || null,
        chain_behavior: 'accept_sub',
      });
      setFeedback('Delegation created');
      setTimeout(() => onDone?.(), 600);
    } catch (e) {
      setFeedback(e.message);
    } finally {
      setActing(false);
    }
  }

  async function doRequestDelegate() {
    setActing(true);
    setFeedback('');
    try {
      const res = await api.post('/api/delegations/request', {
        delegate_id: user.id,
        topic_id: topicId || null,
        chain_behavior: 'accept_sub',
      });
      setFeedback(res.message || 'Request sent');
    } catch (e) {
      setFeedback(e.message);
    } finally {
      setActing(false);
    }
  }

  async function doRequestFollow() {
    setActing(true);
    setFeedback('');
    try {
      await api.post('/api/follows/request', { target_id: user.id });
      setFeedback('Follow request sent');
    } catch (e) {
      setFeedback(e.message);
    } finally {
      setActing(false);
    }
  }

  return (
    <div className="border border-gray-200 rounded-lg p-3 space-y-2">
      <div className="flex items-start justify-between">
        <div className="flex items-center gap-1.5">
          <span className="font-medium text-sm text-[#1B3A5C]">{user.display_name}</span>
          <span className="text-xs text-gray-400">@{user.username}</span>
          <Link
            to={`/users/${user.id}`}
            target="_blank"
            rel="noopener noreferrer"
            className="text-[#2E75B6] hover:text-[#1B3A5C] ml-0.5"
            title="View Profile"
            onClick={e => e.stopPropagation()}
          >
            <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
          </Link>
        </div>
      </div>

      {/* Status line */}
      <div className="text-xs text-gray-500 space-x-2">
        {isPublicForTopic && (
          <span className="text-green-600 font-medium">Public Delegate</span>
        )}
        {isPublic && !isPublicForTopic && (
          <span className="text-blue-500">Public Delegate (other topics)</span>
        )}
        {isFollowing && (
          <span>Following · {user.follow_permission === 'delegation_allowed' ? 'Delegation allowed' : 'View only'}</span>
        )}
        {isPending && (
          <span className="text-amber-600">Follow request pending</span>
        )}
        {!isFollowing && !isPending && !isPublic && (
          <span className="text-gray-400">Not following</span>
        )}
      </div>

      {/* Bio for public delegates */}
      {isPublicForTopic && profiles.find(p => p.topic_id === topicId)?.bio && (
        <p className="text-xs text-gray-500 italic line-clamp-2">
          "{profiles.find(p => p.topic_id === topicId).bio}"
        </p>
      )}

      {/* Action buttons */}
      <div className="flex gap-2 flex-wrap">
        {canDelegate && (
          <button
            onClick={doDelegate}
            disabled={acting}
            className="text-xs px-3 py-1.5 bg-[#1B3A5C] text-white rounded-lg hover:bg-[#2E75B6] transition-colors disabled:opacity-50"
          >
            Delegate
          </button>
        )}
        {isFollowing && user.follow_permission === 'view_only' && (
          <button
            onClick={doRequestDelegate}
            disabled={acting}
            className="text-xs px-3 py-1.5 border border-[#2E75B6] text-[#2E75B6] rounded-lg hover:bg-[#2E75B6] hover:text-white transition-colors disabled:opacity-50"
          >
            Request Delegate
          </button>
        )}
        {!isFollowing && !isPending && !canDelegate && (
          <>
            <button
              onClick={doRequestFollow}
              disabled={acting}
              className="text-xs px-3 py-1.5 border border-gray-300 text-gray-600 rounded-lg hover:bg-gray-50 transition-colors disabled:opacity-50"
            >
              Request Follow
            </button>
            <button
              onClick={doRequestDelegate}
              disabled={acting}
              className="text-xs px-3 py-1.5 border border-[#2E75B6] text-[#2E75B6] rounded-lg hover:bg-[#2E75B6] hover:text-white transition-colors disabled:opacity-50"
            >
              Request Delegate
            </button>
          </>
        )}
        {isPending && user.has_pending_intent && (
          <span className="text-xs text-amber-600">Pending approval</span>
        )}
      </div>

      {feedback && (
        <p className={`text-xs ${feedback.includes('error') || feedback.includes('Cannot') ? 'text-red-600' : 'text-green-600'}`}>
          {feedback}
        </p>
      )}
    </div>
  );
}

export default function DelegateModal({ topicId, topicName, onClose, onDone }) {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState([]);
  const [searching, setSearching] = useState(false);

  useEffect(() => {
    if (query.length < 2) { setResults([]); return; }
    const timer = setTimeout(async () => {
      setSearching(true);
      try {
        const res = await api.get(`/api/users/search?q=${encodeURIComponent(query)}&limit=10`);
        setResults(res);
      } catch {
        setResults([]);
      } finally {
        setSearching(false);
      }
    }, 300);
    return () => clearTimeout(timer);
  }, [query]);

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-xl shadow-lg w-full max-w-md max-h-[80vh] flex flex-col">
        <div className="p-4 border-b border-gray-100">
          <h2 className="font-semibold text-[#1B3A5C]">
            {topicName ? `Set delegate for ${topicName}` : 'Set global default delegate'}
          </h2>
          <p className="text-xs text-gray-400 mt-0.5">
            Public delegates can be selected directly. Others require a follow request.
          </p>
        </div>
        <div className="p-4 space-y-3 flex-1 overflow-y-auto">
          <input
            autoFocus
            type="text"
            value={query}
            onChange={e => setQuery(e.target.value)}
            placeholder="Search by name or username..."
            className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[#2E75B6]"
          />
          {searching && <p className="text-xs text-gray-400 text-center">Searching...</p>}
          {results.length > 0 && (
            <div className="space-y-2">
              {results.map(u => (
                <ResultCard key={u.id} user={u} topicId={topicId} onDone={onDone || onClose} />
              ))}
            </div>
          )}
          {query.length >= 2 && !searching && results.length === 0 && (
            <p className="text-sm text-gray-400 text-center">No users found</p>
          )}
          {query.length < 2 && (
            <p className="text-xs text-gray-400">Type at least 2 characters to search</p>
          )}
        </div>
        <div className="p-4 border-t border-gray-100">
          <button
            onClick={onClose}
            className="w-full py-2 border border-gray-200 text-gray-500 rounded-lg text-sm hover:bg-gray-50"
          >
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
}

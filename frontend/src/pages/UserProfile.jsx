import { useState, useEffect, useCallback } from 'react';
import { useParams, Link } from 'react-router-dom';
import { useAuth } from '../AuthContext';
import api from '../api';
import TopicBadge from '../components/TopicBadge';

export default function UserProfile() {
  const { id } = useParams();
  const { user: currentUser } = useAuth();
  const [profile, setProfile] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [actionFeedback, setActionFeedback] = useState('');

  const isSelf = currentUser?.id === id;

  const fetchProfile = useCallback(async () => {
    try {
      const data = await api.get(`/api/users/${id}/profile`);
      setProfile(data);
    } catch (e) {
      setError(e.message || 'Failed to load profile');
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => { fetchProfile(); }, [fetchProfile]);

  async function handleFollow() {
    setActionFeedback('');
    try {
      await api.post('/api/follows/request', { target_id: id });
      setActionFeedback('Follow request sent');
      fetchProfile();
    } catch (e) {
      setActionFeedback(e.message);
    }
  }

  async function handleRequestDelegate() {
    setActionFeedback('');
    try {
      const res = await api.post('/api/delegations/request', {
        delegate_id: id,
        topic_id: null,
        chain_behavior: 'accept_sub',
      });
      setActionFeedback(res.message || 'Request sent');
      fetchProfile();
    } catch (e) {
      setActionFeedback(e.message);
    }
  }

  if (loading) return (
    <div className="flex justify-center items-center py-20">
      <div className="animate-spin w-8 h-8 border-4 border-[#2E75B6] border-t-transparent rounded-full"></div>
    </div>
  );
  if (error) return (
    <div className="max-w-3xl mx-auto px-4 py-8">
      <div className="bg-red-50 border border-red-200 text-red-700 p-4 rounded-lg text-sm">{error}</div>
    </div>
  );
  if (!profile) return null;

  const { user, delegate_profiles: profiles, votes } = profile;
  const visibleVotes = votes?.filter(v => v.visible) || [];
  const hiddenCount = (votes?.length || 0) - visibleVotes.length;

  return (
    <div className="max-w-3xl mx-auto px-4 py-8 space-y-8">
      {/* Header */}
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-[#1B3A5C]">{user.display_name}</h1>
          <p className="text-sm text-gray-400">@{user.username}</p>
          {profiles.length > 0 && (
            <div className="flex gap-1.5 mt-2">
              <span className="text-xs text-green-600 font-medium bg-green-50 px-2 py-0.5 rounded">
                Public Delegate
              </span>
            </div>
          )}
        </div>

        {isSelf ? (
          <Link
            to="/settings"
            className="text-sm px-3 py-1.5 border border-[#2E75B6] text-[#2E75B6] rounded-lg hover:bg-[#2E75B6] hover:text-white transition-colors"
          >
            Edit settings
          </Link>
        ) : (
          <div className="flex gap-2">
            <button
              onClick={handleFollow}
              className="text-sm px-3 py-1.5 border border-gray-300 text-gray-600 rounded-lg hover:bg-gray-50 transition-colors"
            >
              Request Follow
            </button>
            <button
              onClick={handleRequestDelegate}
              className="text-sm px-3 py-1.5 border border-[#2E75B6] text-[#2E75B6] rounded-lg hover:bg-[#2E75B6] hover:text-white transition-colors"
            >
              Request Delegate
            </button>
          </div>
        )}
      </div>

      {actionFeedback && (
        <div className={`p-3 rounded-lg text-sm ${
          actionFeedback.includes('Cannot') || actionFeedback.includes('error')
            ? 'bg-red-50 text-red-700 border border-red-200'
            : 'bg-green-50 text-green-700 border border-green-200'
        }`}>
          {actionFeedback}
        </div>
      )}

      {/* Delegate profiles */}
      {profiles.length > 0 && (
        <section>
          <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide mb-3">
            Public Delegate Topics
          </h2>
          <div className="space-y-3">
            {profiles.map(p => (
              <div key={p.id} className="bg-white border border-gray-200 rounded-xl p-4">
                <div className="flex items-center gap-2 mb-2">
                  <TopicBadge topic={p.topic} />
                </div>
                {p.bio && <p className="text-sm text-gray-600 italic">"{p.bio}"</p>}
              </div>
            ))}
          </div>
        </section>
      )}

      {/* Voting record */}
      <section>
        <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide mb-3">
          Voting Record
        </h2>

        {visibleVotes.length > 0 ? (
          <div className="bg-white border border-gray-200 rounded-xl overflow-hidden">
            <table className="w-full">
              <thead>
                <tr className="border-b border-gray-100 bg-gray-50">
                  <th className="text-left text-xs font-medium text-gray-500 uppercase px-4 py-3">Proposal</th>
                  <th className="text-left text-xs font-medium text-gray-500 uppercase px-4 py-3">Vote</th>
                  <th className="text-left text-xs font-medium text-gray-500 uppercase px-4 py-3">Date</th>
                </tr>
              </thead>
              <tbody>
                {visibleVotes.map(v => (
                  <tr key={v.id} className="border-b border-gray-100 last:border-0">
                    <td className="px-4 py-3">
                      <Link
                        to={`/proposals/${v.proposal_id}`}
                        className="text-sm text-[#2E75B6] hover:underline"
                      >
                        {v.proposal_title || v.proposal_id}
                      </Link>
                    </td>
                    <td className="px-4 py-3">
                      {v.vote_value ? (
                        <span className={`text-sm font-medium ${
                          v.vote_value === 'yes' ? 'text-[#2D8A56]'
                            : v.vote_value === 'no' ? 'text-[#C0392B]'
                            : 'text-gray-500'
                        }`}>
                          {v.vote_value.toUpperCase()}
                        </span>
                      ) : v.ballot ? (
                        <span className="text-sm font-medium text-purple-600">
                          {v.ballot.approvals?.length > 0
                            ? `Approved ${v.ballot.approvals.length} option${v.ballot.approvals.length !== 1 ? 's' : ''}`
                            : 'Abstained'}
                        </span>
                      ) : (
                        <span className="text-sm text-gray-400">-</span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-xs text-gray-400">
                      {v.cast_at ? new Date(v.cast_at).toLocaleDateString() : ''}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : hiddenCount > 0 ? (
          <div className="bg-gray-50 border border-gray-200 rounded-xl p-6 text-center">
            <p className="text-gray-500 text-sm mb-2">
              This user's voting record is private.
            </p>
            <p className="text-xs text-gray-400">
              Follow {user.display_name} to see their voting record.
            </p>
            {!isSelf && (
              <button
                onClick={handleFollow}
                className="mt-3 text-sm px-4 py-1.5 border border-[#2E75B6] text-[#2E75B6] rounded-lg hover:bg-[#2E75B6] hover:text-white transition-colors"
              >
                Request Follow
              </button>
            )}
          </div>
        ) : (
          <div className="bg-gray-50 border border-gray-200 rounded-xl p-6 text-center">
            <p className="text-gray-500 text-sm">
              {isSelf ? 'No votes recorded yet.' : `Follow ${user.display_name} to see their voting record.`}
            </p>
            {!isSelf && (
              <button
                onClick={handleFollow}
                className="mt-3 text-sm px-4 py-1.5 border border-[#2E75B6] text-[#2E75B6] rounded-lg hover:bg-[#2E75B6] hover:text-white transition-colors"
              >
                Request Follow
              </button>
            )}
          </div>
        )}

        {hiddenCount > 0 && visibleVotes.length > 0 && (
          <p className="text-xs text-gray-400 mt-2">
            {hiddenCount} additional vote{hiddenCount > 1 ? 's' : ''} hidden (private)
          </p>
        )}
      </section>
    </div>
  );
}

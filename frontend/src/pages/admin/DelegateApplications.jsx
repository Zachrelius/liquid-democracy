import { useState, useEffect, useCallback } from 'react';
import { useOrg } from '../../OrgContext';
import api from '../../api';

export default function DelegateApplications() {
  const { currentOrg } = useOrg();
  const [applications, setApplications] = useState([]);
  const [loading, setLoading] = useState(true);
  const [denyId, setDenyId] = useState(null);
  const [feedback, setFeedback] = useState('');

  const slug = currentOrg?.slug;

  const load = useCallback(async () => {
    if (!slug) return;
    try {
      const data = await api.get(`/api/orgs/${slug}/delegate-applications`);
      setApplications(data);
    } catch { /* ignore */ } finally {
      setLoading(false);
    }
  }, [slug]);

  useEffect(() => { load(); }, [load]);

  if (!currentOrg) return <div className="text-center py-16 text-gray-400">No organization selected</div>;

  const policy = currentOrg.settings?.public_delegate_policy;
  if (policy !== 'admin_approval') {
    return (
      <div className="max-w-3xl mx-auto px-4 py-8">
        <h1 className="text-2xl font-semibold text-[#1B3A5C] mb-4">Delegate Applications</h1>
        <div className="bg-blue-50 border border-blue-200 text-blue-700 p-4 rounded-lg text-sm">
          Public delegate registration is set to "Open" -- no admin approval required.
          Change this in Organization Settings to enable application review.
        </div>
      </div>
    );
  }

  if (loading) return (
    <div className="flex justify-center items-center py-20">
      <div className="animate-spin w-8 h-8 border-4 border-[#2E75B6] border-t-transparent rounded-full"></div>
    </div>
  );

  async function handleApprove(appId) {
    try {
      await api.post(`/api/orgs/${slug}/delegate-applications/${appId}/approve`);
      load();
    } catch (e) {
      alert(e.message);
    }
  }

  async function handleDeny(appId) {
    try {
      await api.post(`/api/orgs/${slug}/delegate-applications/${appId}/deny`, { feedback: feedback || null });
      setDenyId(null);
      setFeedback('');
      load();
    } catch (e) {
      alert(e.message);
    }
  }

  return (
    <div className="max-w-3xl mx-auto px-4 py-8 space-y-6">
      <h1 className="text-2xl font-semibold text-[#1B3A5C]">Delegate Applications</h1>

      {applications.length === 0 ? (
        <div className="text-center py-12 text-gray-400 text-sm">No pending applications</div>
      ) : (
        <div className="space-y-4">
          {applications.map(app => (
            <div key={app.id} className="bg-white border border-gray-200 rounded-xl p-5 space-y-3">
              <div className="flex items-start justify-between">
                <div>
                  <p className="text-sm font-medium text-gray-800">{app.display_name || app.username}</p>
                  <p className="text-xs text-gray-400">@{app.username}</p>
                </div>
                <div className="text-right">
                  <span
                    className="inline-block text-xs px-2 py-0.5 rounded font-medium bg-blue-50 text-blue-700"
                  >
                    {app.topic_name}
                  </span>
                  <p className="text-xs text-gray-400 mt-1">
                    Applied {new Date(app.created_at).toLocaleDateString()}
                  </p>
                </div>
              </div>

              {app.bio && (
                <div className="bg-gray-50 rounded-lg p-3">
                  <p className="text-sm text-gray-600 italic">"{app.bio}"</p>
                </div>
              )}

              {denyId === app.id ? (
                <div className="space-y-2">
                  <label className="block text-xs text-gray-500">Feedback (optional)</label>
                  <textarea
                    value={feedback}
                    onChange={e => setFeedback(e.target.value)}
                    rows={2}
                    placeholder="Reason for denial..."
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[#2E75B6] resize-none"
                  />
                  <div className="flex gap-2">
                    <button
                      onClick={() => handleDeny(app.id)}
                      className="text-xs px-3 py-1.5 bg-red-600 text-white rounded-lg hover:bg-red-700"
                    >
                      Confirm Deny
                    </button>
                    <button
                      onClick={() => { setDenyId(null); setFeedback(''); }}
                      className="text-xs px-3 py-1.5 border border-gray-300 text-gray-600 rounded-lg hover:bg-gray-50"
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              ) : (
                <div className="flex gap-2">
                  <button
                    onClick={() => handleApprove(app.id)}
                    className="text-xs px-3 py-1.5 bg-green-600 text-white rounded-lg hover:bg-green-700"
                  >
                    Approve
                  </button>
                  <button
                    onClick={() => setDenyId(app.id)}
                    className="text-xs px-3 py-1.5 border border-red-300 text-red-600 rounded-lg hover:bg-red-50"
                  >
                    Deny
                  </button>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

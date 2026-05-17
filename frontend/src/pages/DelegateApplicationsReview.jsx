import { useState, useEffect, useCallback } from 'react';
import { Link, useParams } from 'react-router-dom';
import api from '../api';
import { useOrg } from '../OrgContext';
import { useToast } from '../components/Toast';
import { useHasPermission } from '../hooks/useHasPermission';
import Avatar from '../components/Avatar';
import TopicBadge from '../components/TopicBadge';

/**
 * Delegate Applications approver page.
 *
 * Lists pending public_accepting applications in this org with full
 * applicant context (intro / bio / position statement) and one-click
 * Approve / Deny actions per row. Each row links out to the applicant's
 * full delegate page for deeper review before deciding.
 *
 * Permission gate: ``delegate_application.approve``. Non-approvers see
 * an inline 403-style notice.
 */

export default function DelegateApplicationsReview() {
  const { org_slug } = useParams();
  const { currentOrg } = useOrg();
  const toast = useToast();
  const canApprove = useHasPermission('delegate_application.approve');

  const slug = org_slug || currentOrg?.slug || null;

  const [applications, setApplications] = useState([]);
  const [loading, setLoading] = useState(true);
  const [denyOpenFor, setDenyOpenFor] = useState(null);
  const [denyComment, setDenyComment] = useState('');
  const [acting, setActing] = useState(false);

  const load = useCallback(async () => {
    if (!slug || !canApprove) {
      setLoading(false);
      return;
    }
    setLoading(true);
    try {
      const data = await api.get(
        `/api/orgs/${slug}/delegate-applications-pending`
      );
      setApplications(Array.isArray(data) ? data : []);
    } catch (e) {
      toast.error(e.message || 'Failed to load pending applications');
    } finally {
      setLoading(false);
    }
  }, [slug, canApprove, toast]);

  useEffect(() => { load(); }, [load]);

  async function handleApprove(profileId) {
    setActing(true);
    try {
      await api.post(
        `/api/orgs/${slug}/delegate-applications/${profileId}/approve`
      );
      toast.success('Application approved');
      load();
    } catch (e) {
      toast.error(e.message || 'Approve failed');
    } finally {
      setActing(false);
    }
  }

  async function handleDeny(profileId) {
    if (!denyComment.trim()) {
      toast.error('Denial comment is required');
      return;
    }
    setActing(true);
    try {
      await api.post(
        `/api/orgs/${slug}/delegate-applications/${profileId}/deny`,
        { comment: denyComment.trim() }
      );
      toast.success('Application denied');
      setDenyOpenFor(null);
      setDenyComment('');
      load();
    } catch (e) {
      toast.error(e.message || 'Deny failed');
    } finally {
      setActing(false);
    }
  }

  if (!canApprove) {
    return (
      <div className="max-w-3xl mx-auto px-4 py-12">
        <div className="text-center text-sm text-gray-500">
          You do not have permission to review delegate applications in this organization.
        </div>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="flex justify-center items-center py-20">
        <div className="animate-spin w-8 h-8 border-4 border-[var(--brand-accent)] border-t-transparent rounded-full" />
      </div>
    );
  }

  return (
    <div className="max-w-3xl mx-auto px-4 py-8 space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-[var(--brand-primary)]">
          Delegate Applications
        </h1>
        <p className="text-sm text-gray-500 mt-1">
          Review pending applications to become a public delegate in{' '}
          {currentOrg?.name || slug}.
        </p>
      </div>

      {applications.length === 0 ? (
        <div className="text-center py-12 text-gray-400 text-sm">
          No pending applications.
        </div>
      ) : (
        <div className="space-y-4">
          {applications.map(app => (
            <div
              key={app.profile_id}
              className="bg-white border border-gray-200 rounded-xl p-5 space-y-3"
            >
              <div className="flex items-start justify-between gap-3">
                <div className="flex items-start gap-3">
                  <Avatar user={app.applicant} size="md" />
                  <div>
                    <Link
                      to={app.delegate_page_url}
                      className="text-sm font-medium text-[var(--brand-accent)] hover:underline"
                    >
                      {app.applicant.display_name}
                    </Link>
                    <p className="text-xs text-gray-500">
                      @{app.applicant.username}
                    </p>
                    <p className="text-xs text-gray-400 mt-1">
                      Applied {new Date(app.submitted_at).toLocaleDateString()}
                    </p>
                  </div>
                </div>
                <TopicBadge topic={{ name: app.topic_name }} />
              </div>

              {app.intro && (
                <div className="border-t border-gray-100 pt-3">
                  <p className="text-xs uppercase tracking-wide text-gray-500 mb-1">Intro</p>
                  <p className="text-sm text-[#2C3E50] italic">{app.intro}</p>
                </div>
              )}

              {app.bio && (
                <div className="border-t border-gray-100 pt-3">
                  <p className="text-xs uppercase tracking-wide text-gray-500 mb-1">Bio</p>
                  <p className="text-sm text-[#2C3E50] italic">"{app.bio}"</p>
                </div>
              )}

              {app.position_statement && (
                <div className="border-t border-gray-100 pt-3">
                  <p className="text-xs uppercase tracking-wide text-gray-500 mb-1">
                    Position on {app.topic_name}
                  </p>
                  <p className="text-sm text-[#2C3E50] whitespace-pre-wrap">
                    {app.position_statement}
                  </p>
                </div>
              )}

              <div className="border-t border-gray-100 pt-3">
                <Link
                  to={app.delegate_page_url}
                  className="text-xs text-[var(--brand-accent)] hover:underline"
                >
                  View applicant's delegate page →
                </Link>
              </div>

              {denyOpenFor === app.profile_id ? (
                <div className="border-t border-gray-100 pt-3 space-y-2">
                  <label className="block text-xs text-gray-500">
                    Denial comment (required, visible to applicant)
                  </label>
                  <textarea
                    value={denyComment}
                    onChange={e => setDenyComment(e.target.value)}
                    rows={2}
                    placeholder="Why are you denying this application?"
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[var(--brand-accent)] resize-none"
                  />
                  <div className="flex gap-2">
                    <button
                      onClick={() => handleDeny(app.profile_id)}
                      disabled={acting || !denyComment.trim()}
                      className="text-xs px-3 py-1.5 bg-red-600 text-white rounded-lg hover:bg-red-700 disabled:opacity-50"
                    >
                      Confirm deny
                    </button>
                    <button
                      onClick={() => { setDenyOpenFor(null); setDenyComment(''); }}
                      disabled={acting}
                      className="text-xs px-3 py-1.5 border border-gray-300 text-gray-600 rounded-lg hover:bg-gray-50"
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              ) : (
                <div className="border-t border-gray-100 pt-3 flex gap-2">
                  <button
                    onClick={() => handleApprove(app.profile_id)}
                    disabled={acting}
                    className="text-sm px-4 py-1.5 bg-green-600 text-white rounded-lg hover:bg-green-700 disabled:opacity-50"
                  >
                    Approve
                  </button>
                  <button
                    onClick={() => { setDenyOpenFor(app.profile_id); setDenyComment(''); }}
                    disabled={acting}
                    className="text-sm px-4 py-1.5 border border-red-300 text-red-700 rounded-lg hover:bg-red-50 disabled:opacity-50"
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

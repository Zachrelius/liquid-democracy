/**
 * Phase 19 F5 — Approver dashboard for delegate (public_accepting)
 * applications.
 *
 * Route: ``/{slug}/delegate-applications``.
 *
 * Page-level gate: ``delegate_application.approve``. Non-approvers see a
 * 403-style inline notice instead of a hard redirect (matching the
 * RolePermissionsPage pattern).
 *
 * Backend surface (current state, see "API gap" below):
 *   - ``POST /api/orgs/{slug}/delegate-profile/topics/{topic_id}/approve``
 *     — approves the OLDEST pending submission on this topic in this org.
 *     Returns the applicant's serialized ``OrgDelegateProfileOut``.
 *   - ``POST /api/orgs/{slug}/delegate-profile/topics/{topic_id}/deny``
 *     — body ``{comment}`` required (non-empty).
 *
 * API gap (flagged to lead): no list endpoint exists for Phase 19's
 * inline-on-DelegateProfile pending applications. Without one we can't
 * surface a per-applicant pending queue. The Phase 19 approve flow
 * operates per-topic ("oldest pending wins"), so this page is structured
 * around topic selection rather than per-applicant rows. A backend
 * follow-up would add ``GET /api/orgs/{slug}/delegate-applications-
 * pending`` (Phase 19 shape — distinct from the legacy
 * ``/api/orgs/{slug}/delegate-applications`` which uses the
 * pre-Phase-19 ``DelegateApplication`` table).
 *
 * Until the list endpoint lands we expose a topic picker + a "review &
 * decide" panel that calls the per-topic approve / deny endpoints
 * directly. The page also surfaces an explicit note pointing approvers
 * to the legacy admin surface (``/admin/delegates``) for the older
 * application flow which is still wired up.
 */
import { useState, useEffect, useCallback } from 'react';
import { Link, useParams } from 'react-router-dom';
import api from '../api';
import { useOrg } from '../OrgContext';
import { useToast } from '../components/Toast';
import { useHasPermission } from '../hooks/useHasPermission';
import { urlFor } from '../utils/urls';

export default function DelegateApplicationsReview() {
  const { org_slug } = useParams();
  const { currentOrg } = useOrg();
  const toast = useToast();
  const canApprove = useHasPermission('delegate_application.approve');

  const slug = org_slug || currentOrg?.slug || null;

  const [topics, setTopics] = useState([]);
  const [selectedTopic, setSelectedTopic] = useState('');
  const [denyComment, setDenyComment] = useState('');
  const [acting, setActing] = useState(false);
  const [lastResult, setLastResult] = useState(null); // OrgDelegateProfileOut

  useEffect(() => {
    if (!slug) return;
    (async () => {
      try {
        const tops = await api.get(`/api/orgs/${slug}/topics`);
        setTopics(tops || []);
      } catch { /* ignore */ }
    })();
  }, [slug]);

  const handleApprove = useCallback(async () => {
    if (!selectedTopic) return;
    setActing(true);
    try {
      const result = await api.post(
        `/api/orgs/${slug}/delegate-profile/topics/${selectedTopic}/approve`
      );
      setLastResult({ kind: 'approved', data: result });
      toast.success('Application approved');
    } catch (e) {
      toast.error(e.message || 'Approve failed');
    } finally {
      setActing(false);
    }
  }, [slug, selectedTopic, toast]);

  const handleDeny = useCallback(async () => {
    if (!selectedTopic) return;
    if (!denyComment.trim()) {
      toast.error('Denial comment is required');
      return;
    }
    setActing(true);
    try {
      const result = await api.post(
        `/api/orgs/${slug}/delegate-profile/topics/${selectedTopic}/deny`,
        { comment: denyComment.trim() }
      );
      setLastResult({ kind: 'denied', data: result });
      toast.success('Application denied');
      setDenyComment('');
    } catch (e) {
      toast.error(e.message || 'Deny failed');
    } finally {
      setActing(false);
    }
  }, [slug, selectedTopic, denyComment, toast]);

  if (!slug) {
    return (
      <div className="max-w-3xl mx-auto px-4 py-8">
        <p className="text-sm text-gray-500">No organization selected.</p>
      </div>
    );
  }

  if (!canApprove) {
    return (
      <div className="max-w-3xl mx-auto px-4 py-8">
        <h1 className="text-2xl font-semibold text-[var(--brand-primary)] mb-4">
          Delegate Applications
        </h1>
        <div className="bg-yellow-50 border border-yellow-200 text-yellow-800 p-4 rounded-lg text-sm">
          You don&apos;t have the <code>delegate_application.approve</code>{' '}
          permission in this organization. Ask a steward to grant it from{' '}
          <Link
            to={urlFor(slug, 'admin-permissions')}
            className="underline"
          >
            Permissions
          </Link>
          .
        </div>
      </div>
    );
  }

  return (
    <div className="max-w-3xl mx-auto px-4 py-8 space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-[var(--brand-primary)]">
          Delegate Applications (Phase 19)
        </h1>
        <p className="text-sm text-gray-500 mt-1">
          Review pending public-accepting submissions for delegate topics in{' '}
          {currentOrg?.name || slug}.
        </p>
      </div>

      <div className="bg-blue-50 border border-blue-200 text-blue-700 p-4 rounded-lg text-sm space-y-1">
        <p>
          The Phase 19 approval flow operates per-topic: approving or denying
          targets the <strong>oldest pending submission</strong> on the
          selected topic in this org.
        </p>
        <p>
          Looking for the older delegate-application flow (open registration,
          per-application rows)? See{' '}
          <Link
            to={urlFor(slug, 'admin-delegates')}
            className="underline"
          >
            Admin → Delegate Applications
          </Link>
          .
        </p>
      </div>

      {/* Topic picker */}
      <div className="bg-white border border-gray-200 rounded-xl p-4 space-y-4">
        <div>
          <label className="block text-xs text-gray-500 mb-1">
            Select a topic to review the oldest pending submission
          </label>
          <select
            value={selectedTopic}
            onChange={e => {
              setSelectedTopic(e.target.value);
              setLastResult(null);
              setDenyComment('');
            }}
            className="text-sm border border-gray-300 rounded-lg px-2 py-1.5 w-full focus:outline-none focus:ring-2 focus:ring-[var(--brand-accent)]"
          >
            <option value="">— pick a topic —</option>
            {topics.map(t => (
              // Phase 26 D1 — option label reads description || name.
              <option key={t.id} value={t.id}>{t.description?.trim() || t.name}</option>
            ))}
          </select>
        </div>

        {selectedTopic && (
          <div className="space-y-3 border-t border-gray-100 pt-4">
            <p className="text-xs text-gray-500">
              Approving will accept the oldest pending public-accepting
              submission on this topic. Denying requires a comment that
              becomes visible to the applicant.
            </p>
            <div className="flex gap-2 items-start flex-wrap">
              <button
                onClick={handleApprove}
                disabled={acting}
                className="text-sm px-4 py-1.5 bg-green-600 text-white rounded-lg hover:bg-green-700 disabled:opacity-50"
              >
                {acting ? 'Working…' : 'Approve oldest pending'}
              </button>
            </div>
            <div className="space-y-2">
              <label className="block text-xs text-gray-500">
                Denial comment (required)
              </label>
              <textarea
                value={denyComment}
                onChange={e => setDenyComment(e.target.value)}
                rows={3}
                placeholder="Why are you denying this submission? The applicant will see this."
                className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[var(--brand-accent)] resize-none"
              />
              <button
                onClick={handleDeny}
                disabled={acting || !denyComment.trim()}
                className="text-sm px-4 py-1.5 border border-red-300 text-red-700 rounded-lg hover:bg-red-50 disabled:opacity-50"
              >
                {acting ? 'Working…' : 'Deny oldest pending'}
              </button>
            </div>
          </div>
        )}
      </div>

      {lastResult && (
        <div className="bg-white border border-gray-200 rounded-xl p-4 space-y-2">
          <h2 className="text-sm font-semibold text-gray-700">
            Last action: {lastResult.kind === 'approved' ? 'approved' : 'denied'}
          </h2>
          <p className="text-xs text-gray-500">
            Applicant user_id:{' '}
            <code className="text-xs">{lastResult.data?.user_id}</code>
          </p>
          {lastResult.data?.org_slug && lastResult.data?.user_id && (
            <Link
              to={`/${lastResult.data.org_slug}/users/${lastResult.data.user_id}`}
              className="text-xs text-[var(--brand-accent)] hover:underline"
            >
              View applicant profile →
            </Link>
          )}
          <pre className="text-[10px] text-gray-400 bg-gray-50 rounded p-2 overflow-x-auto max-h-40">
{JSON.stringify(lastResult.data, null, 2)}
          </pre>
        </div>
      )}
    </div>
  );
}

import { useState, useEffect, useCallback } from 'react';
import { Link } from 'react-router-dom';
import { useOrg } from '../../OrgContext';
import api from '../../api';
import { useToast } from '../../components/Toast';
import { useConfirm } from '../../components/ConfirmDialog';
import { useHasPermission } from '../../hooks/useHasPermission';

/**
 * Phase 86 (B-4) — moderator content-report queue.
 *
 * Open reports grouped by target. Reports are signal only: this page never
 * changes the target. Moderators act through the real tools (remove comment,
 * archive/delete proposal, remove/ban member) via the inline link, then mark
 * the report Actioned — or Dismiss it. Reporter identity is shown here (and
 * nowhere else).
 */
export default function ReportsQueue() {
  const { currentOrg } = useOrg();
  const toast = useToast();
  const confirm = useConfirm();
  const canModerate = useHasPermission('comment.moderate');
  const [groups, setGroups] = useState([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);

  const slug = currentOrg?.slug;

  const load = useCallback(async () => {
    if (!slug) return;
    setLoading(true);
    try {
      const rows = await api.get(`/api/orgs/${slug}/reports?status=open`);
      setGroups(rows);
    } catch (e) {
      toast.error(e?.message || 'Failed to load reports');
    } finally {
      setLoading(false);
    }
  }, [slug]);

  useEffect(() => { load(); }, [load]);

  async function resolveGroup(group, disposition) {
    const verb = disposition === 'actioned' ? 'mark actioned' : 'dismiss';
    const ok = await confirm({
      title: disposition === 'actioned' ? 'Mark actioned?' : 'Dismiss reports?',
      message:
        disposition === 'actioned'
          ? 'Mark these reports as actioned. This is a record-keeping label; use the moderation tools to actually remove or change the content.'
          : 'Dismiss these reports without acting. The content is unchanged.',
      destructive: false,
    });
    if (!ok) return;
    setBusy(true);
    try {
      for (const r of group.reports) {
        await api.patch(`/api/reports/${r.id}`, { status: disposition });
      }
      toast.success(disposition === 'actioned' ? 'Marked actioned' : 'Dismissed');
      load();
    } catch (e) {
      toast.error(e?.message || `Failed to ${verb}`);
    } finally {
      setBusy(false);
    }
  }

  function targetLink(group) {
    if (!group.proposal_id || !slug) return null;
    return `/${slug}/proposals/${group.proposal_id}`;
  }

  if (!currentOrg) {
    return <div className="text-center py-16 text-gray-400">No organization selected</div>;
  }
  if (!canModerate) {
    return (
      <div className="max-w-3xl mx-auto px-4 py-16 text-center text-gray-500">
        You do not have permission to view reports in this organization.
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
        <h1 className="text-2xl font-bold text-[var(--brand-primary)]">Reports</h1>
        <p className="text-sm text-gray-500 mt-1">
          Member reports of comments and proposals. Reports are a signal only —
          use the moderation tools to act, then mark actioned or dismiss.
        </p>
      </div>

      {groups.length === 0 ? (
        <p className="text-sm text-gray-500 italic">No open reports. Nothing to review.</p>
      ) : (
        <div className="space-y-4">
          {groups.map((g) => {
            const link = targetLink(g);
            return (
              <div key={`${g.target_type}:${g.target_id}`} className="bg-white border border-gray-200 rounded-xl p-4 space-y-3">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="text-xs uppercase tracking-wide text-gray-400">
                      {g.target_type} · {g.open_count} report{g.open_count === 1 ? '' : 's'}
                    </div>
                    <div className="text-sm text-gray-800 mt-0.5 break-words">
                      &ldquo;{g.target_excerpt}&rdquo;
                    </div>
                    {g.target_author_display && (
                      <div className="text-xs text-gray-500 mt-0.5">
                        by {g.target_author_display}
                      </div>
                    )}
                  </div>
                  {link && (
                    <Link
                      to={link}
                      className="text-xs whitespace-nowrap text-[var(--brand-accent)] hover:underline"
                    >
                      View {g.target_type} →
                    </Link>
                  )}
                </div>

                <ul className="border-t border-gray-100 pt-2 space-y-1.5">
                  {g.reports.map((r) => (
                    <li key={r.id} className="text-xs text-gray-600">
                      <span className="font-medium text-gray-700">{r.reason}</span>
                      {' · '}
                      <span>{r.reporter_display_name}</span>
                      {r.created_at && ` · ${new Date(r.created_at).toLocaleDateString()}`}
                      {r.note && <div className="text-gray-500 mt-0.5">&ldquo;{r.note}&rdquo;</div>}
                    </li>
                  ))}
                </ul>

                <div className="flex justify-end gap-2 pt-1">
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => resolveGroup(g, 'dismissed')}
                    className="text-xs px-3 py-1.5 border border-gray-300 text-gray-600 rounded-lg hover:bg-gray-50 disabled:opacity-50"
                  >
                    Dismiss
                  </button>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => resolveGroup(g, 'actioned')}
                    className="text-xs px-3 py-1.5 border border-green-400 text-green-700 rounded-lg hover:bg-green-50 disabled:opacity-50"
                  >
                    Mark actioned
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

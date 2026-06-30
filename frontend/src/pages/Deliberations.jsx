import { useCallback, useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { useOrg } from '../OrgContext';
import { urlFor } from '../utils/urls';
import api from '../api';
import { polisTopicLabel } from '../utils/polis';

/**
 * Phase 82 C2 — member-facing Deliberations (pol.is) list.
 *
 * Lists the org's Polises this member is eligible to see (the
 * `GET /api/orgs/{slug}/polises` endpoint is already eligibility-filtered via
 * eligible_viewers_for_polis). Each row links to the existing voter view
 * (Polis.jsx). Read-only surface — no create/edit/archive controls (those
 * live in the admin Polises pages).
 */
export default function Deliberations() {
  const { org_slug } = useParams();
  const { currentOrg } = useOrg();
  const slug = currentOrg?.slug || org_slug || null;

  const [polises, setPolises] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    if (!slug) return;
    setLoading(true);
    setError('');
    try {
      const data = await api.get(`/api/orgs/${slug}/polises?status=active`);
      setPolises(Array.isArray(data) ? data : []);
    } catch (e) {
      setError(e.message || 'Failed to load deliberations');
    } finally {
      setLoading(false);
    }
  }, [slug]);

  useEffect(() => { load(); }, [load]);

  return (
    <div className="max-w-4xl mx-auto px-4 py-8 space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-[var(--brand-primary)]">Deliberations</h1>
        <p className="text-sm text-gray-500 mt-1">
          Open pol.is conversations in {currentOrg?.name || slug}. Share where you
          agree and disagree to help surface the group&apos;s views.
        </p>
      </div>

      {loading ? (
        <p className="text-sm text-gray-400">Loading…</p>
      ) : error ? (
        <p className="text-sm text-red-600">{error}</p>
      ) : polises.length === 0 ? (
        <div className="text-center py-16 text-gray-400">
          <p className="text-lg mb-2">No deliberations yet</p>
          <p className="text-sm">Check back later — there are no open conversations right now.</p>
        </div>
      ) : (
        <ul className="space-y-2">
          {polises.map(p => (
            <li key={p.id}>
              <Link
                to={urlFor(slug, 'polis-voter', p.id)}
                className="block bg-white border border-gray-200 rounded-xl p-4 hover:border-[var(--brand-accent)] transition-colors"
              >
                <p className="text-sm font-medium text-gray-800">{polisTopicLabel(p)}</p>
                {p.prompt && (
                  <p className="text-xs text-gray-500 mt-1 line-clamp-2">{p.prompt}</p>
                )}
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

import { useState, useEffect, useCallback } from 'react';
import { Navigate } from 'react-router-dom';
import api from '../api';
import { useOrg } from '../OrgContext';
import Spinner from '../components/Spinner';
import ErrorMessage from '../components/ErrorMessage';

/**
 * ShareActivity — Phase 90 member-facing share-event ledger.
 *
 * Visible only in weighted-voting orgs. Renders the org's share-event feed
 * (the backend applies all visibility rules: party names only when the org
 * enables them or the viewer is a party; balances only on the viewer's own
 * events). A "My history" toggle switches to the viewer's own full history.
 */
function eventSummary(ev, unit) {
  const amt = Math.abs(ev.delta);
  const label = amt === 1 ? unit.replace(/s$/, '') : unit;
  if (ev.event_type === 'admin_set') {
    const dir = ev.delta >= 0 ? 'set (+' : 'set (';
    const who = ev.user_display_name ? ev.user_display_name : 'a member';
    const by = ev.actor_display_name ? ` by ${ev.actor_display_name}` : '';
    return `Admin ${dir}${ev.delta} ${label}) for ${who}${by}`;
  }
  if (ev.event_type === 'auto_distribution') {
    const who = ev.user_display_name ? ev.user_display_name : 'a member';
    return `Auto distribution: +${amt} ${label} to ${who}`;
  }
  if (ev.event_type === 'transfer') {
    const from = ev.from_display_name || 'a member';
    const to = ev.to_display_name || 'a member';
    return `Transfer: ${amt} ${label} from ${from} to ${to}`;
  }
  return `${ev.delta >= 0 ? '+' : ''}${ev.delta} ${label}`;
}

export default function ShareActivity() {
  const { currentOrg, isMember } = useOrg();
  const [tab, setTab] = useState('all'); // 'all' | 'mine'
  const [feed, setFeed] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const weighted = currentOrg?.weighted_voting?.enabled === true;
  const unit = currentOrg?.weighted_voting?.unit_label || 'shares';
  const slug = currentOrg?.slug;

  const load = useCallback(async () => {
    if (!slug || !weighted) return;
    setLoading(true);
    setError('');
    try {
      const path = tab === 'mine' ? 'share-events/mine' : 'share-events';
      const data = await api.get(`/api/orgs/${slug}/${path}`);
      setFeed(data);
    } catch (e) {
      setError(e.message || 'Failed to load share activity');
    } finally {
      setLoading(false);
    }
  }, [slug, weighted, tab]);

  useEffect(() => { load(); }, [load]);

  // Weighted-only surface: unweighted orgs (or non-members) never see it.
  if (currentOrg && (!weighted || !isMember)) {
    return <Navigate to={`/${slug}/proposals`} replace />;
  }

  return (
    <div className="max-w-3xl mx-auto px-4 py-6">
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-xl font-semibold text-[var(--brand-primary)]">Share activity</h1>
        <div className="flex gap-1 text-sm">
          <button
            onClick={() => setTab('all')}
            className={`px-3 py-1.5 rounded-lg ${tab === 'all' ? 'bg-[var(--brand-primary)] text-white' : 'text-gray-600 hover:bg-gray-100'}`}
          >
            All activity
          </button>
          <button
            onClick={() => setTab('mine')}
            className={`px-3 py-1.5 rounded-lg ${tab === 'mine' ? 'bg-[var(--brand-primary)] text-white' : 'text-gray-600 hover:bg-gray-100'}`}
          >
            My history
          </button>
        </div>
      </div>

      <p className="text-xs text-gray-500 mb-4">
        Every change to a member's {unit} is recorded here. Amounts and who
        authorized them are always shown.{' '}
        {tab === 'all' && feed && !feed.show_parties
          ? `This organization keeps member names on ${unit} events private, so only your own events show names and balances.`
          : ''}
      </p>

      {error && <ErrorMessage message={error} />}
      {loading ? (
        <Spinner />
      ) : feed && feed.events.length === 0 ? (
        <div className="bg-white border border-gray-200 rounded-xl p-8 text-center text-sm text-gray-400">
          No share activity yet.
        </div>
      ) : feed ? (
        <div className="bg-white border border-gray-200 rounded-xl divide-y divide-gray-100">
          {feed.events.map(ev => (
            <div key={ev.id} className="px-4 py-3 flex items-start justify-between gap-3">
              <div className="text-sm text-gray-800">
                {eventSummary(ev, unit)}
                {ev.resulting_balance != null && (
                  <span className="text-xs text-gray-400"> · your balance: {ev.resulting_balance} {unit}</span>
                )}
              </div>
              <div className="text-xs text-gray-400 whitespace-nowrap">
                {new Date(ev.created_at).toLocaleDateString()}
              </div>
            </div>
          ))}
        </div>
      ) : null}

      {feed?.epoch && (
        <p className="text-xs text-gray-400 mt-4">
          History begins {new Date(feed.epoch).toLocaleDateString()}. Balances
          from before then are not itemized here.
        </p>
      )}
    </div>
  );
}

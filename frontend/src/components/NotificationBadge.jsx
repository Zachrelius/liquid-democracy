import { useState, useEffect, useRef } from 'react';
import { Link } from 'react-router-dom';
import api from '../api';

/**
 * Phase 9 Session 4 — Polis-created notifications.
 *
 * The platform doesn't have a generic notification feed (`/api/notifications`
 * does not exist as of Session 4); the existing badge is composed from
 * listing-endpoint polls — follow-requests + voting-status proposals.
 * Decision 10 calls for a single in-app badge bump when a new Polis
 * appears in the viewer's scope.
 *
 * Client-side approach (matches existing pattern): poll the user's orgs +
 * each org's `/api/orgs/{slug}/polises` list, compare against a localStorage
 * "last seen" timestamp keyed per (user, org). Polises with `created_at`
 * after the last-seen mark are surfaced as notifications. The user "clears"
 * a Polis notification by clicking through (we update the per-org last-seen
 * on dropdown open, mirroring how the existing notifications track click-
 * through implicitly).
 *
 * This is a single-shot notification per Polis — not ongoing updates — per
 * the spec ("Single notification per Polis, not ongoing updates").
 */

const POLIS_LAST_SEEN_PREFIX = 'polis_last_seen_';

function readLastSeen(orgSlug) {
  try {
    const raw = window.localStorage.getItem(POLIS_LAST_SEEN_PREFIX + orgSlug);
    return raw ? Number(raw) : 0;
  } catch { return 0; }
}
function writeLastSeen(orgSlug, ts) {
  try {
    window.localStorage.setItem(POLIS_LAST_SEEN_PREFIX + orgSlug, String(ts));
  } catch { /* best-effort */ }
}

export default function NotificationBadge() {
  const [count, setCount] = useState(0);
  const [items, setItems] = useState([]);
  const [open, setOpen] = useState(false);
  const ref = useRef(null);

  useEffect(() => {
    let mounted = true;
    async function load() {
      try {
        const [incoming, proposals, orgs] = await Promise.all([
          api.get('/api/follows/requests/incoming'),
          api.get('/api/proposals?status=voting'),
          api.get('/api/orgs').catch(() => []),
        ]);

        const notifs = [];
        // Phase 11 — these notifications need an org slug to land on the
        // right page. Pick a default parent-org slug from the user's orgs
        // (first one, or null if zero orgs); for the polis-specific notifs
        // below we use the polis's org slug directly. For the follow/vote
        // notifs we route to the first org's pages — these are coarse
        // notifications and a user with multiple orgs can switch from there.
        const parentOrgs = (orgs || []).filter(o => !o.parent_org_id);
        const defaultOrgSlug = parentOrgs[0]?.slug || null;
        const linkOr = (path) => defaultOrgSlug ? `/${defaultOrgSlug}${path}` : '/orgs';
        if (incoming.length > 0) {
          notifs.push({
            text: `${incoming.length} follow request${incoming.length > 1 ? 's' : ''} pending`,
            link: linkOr('/delegations'),
          });
        }

        // Check for unresolved votes
        const myVotes = await Promise.allSettled(
          proposals.slice(0, 5).map(p => api.get(`/api/proposals/${p.id}/my-vote`))
        );
        const unresolved = myVotes.filter(
          r => r.status === 'fulfilled' && r.value.vote_value == null
        ).length;
        if (unresolved > 0) {
          notifs.push({
            text: `${unresolved} proposal${unresolved > 1 ? 's' : ''} need your vote`,
            link: linkOr('/proposals'),
          });
        }

        // Phase 9 — new-Polis notifications. Poll each parent org the user
        // belongs to and surface Polises created after the per-org
        // "last seen" timestamp. Sub-orgs are reached via their parent's
        // polises endpoint (the backend visibility filter handles which
        // ones the viewer sees). To avoid noise on first sign-in, treat a
        // missing last-seen as "now" (no historical bump).
        const polisCalls = await Promise.allSettled(
          parentOrgs.slice(0, 10).map(o =>
            api.get(`/api/orgs/${o.slug}/polises`).then(list => ({ org: o, list }))
          ),
        );
        for (const r of polisCalls) {
          if (r.status !== 'fulfilled') continue;
          const { org, list } = r.value;
          const lastSeen = readLastSeen(org.slug);
          if (lastSeen === 0) {
            // Initialize without bumping the badge; the next poll will
            // surface anything created after this moment.
            writeLastSeen(org.slug, Date.now());
            continue;
          }
          const fresh = (list || []).filter(p => {
            if (!p?.created_at) return false;
            return new Date(p.created_at).getTime() > lastSeen;
          });
          fresh.forEach(p => {
            notifs.push({
              text: `New deliberation: ${p.title}`,
              // Phase 11 D3 — drop the /orgs/ prefix.
              link: `/${org.slug}/polises/${p.id}`,
              // Used when the dropdown is opened to clear this notif.
              _polisOrgSlug: org.slug,
            });
          });
        }

        if (mounted) {
          setItems(notifs);
          setCount(notifs.reduce((acc, n) => {
            const num = parseInt(n.text);
            return acc + (isNaN(num) ? 1 : num);
          }, 0));
        }
      } catch { /* ignore */ }
    }
    load();
    return () => { mounted = false; };
  }, []);

  // Close dropdown on outside click
  useEffect(() => {
    function handleClick(e) {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false);
    }
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, []);

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen(!open)}
        className="relative text-blue-200 hover:text-white transition-colors p-1"
        aria-label="Notifications"
      >
        <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
            d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9"
          />
        </svg>
        {count > 0 && (
          <span className="absolute -top-1 -right-1 bg-red-500 text-white text-[10px] font-bold w-4 h-4 rounded-full flex items-center justify-center">
            {count > 9 ? '9+' : count}
          </span>
        )}
      </button>

      {open && (
        <div className="absolute right-0 top-full mt-2 w-72 bg-white border border-gray-200 rounded-xl shadow-lg z-50">
          {items.length === 0 ? (
            <div className="p-4 text-sm text-gray-400 text-center">
              All caught up
            </div>
          ) : (
            <ul className="divide-y divide-gray-100">
              {items.map((item, i) => (
                <li key={i}>
                  <Link
                    to={item.link}
                    onClick={() => {
                      setOpen(false);
                      // Phase 9 — clicking a Polis notification updates the
                      // per-org last-seen so the same Polis doesn't keep
                      // bumping the badge after the user has visited it.
                      if (item._polisOrgSlug) {
                        writeLastSeen(item._polisOrgSlug, Date.now());
                      }
                    }}
                    className="block px-4 py-3 text-sm text-gray-700 hover:bg-gray-50 transition-colors"
                  >
                    {item.text}
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

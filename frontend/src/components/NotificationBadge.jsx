import { useState, useEffect, useRef } from 'react';
import { Link } from 'react-router-dom';
import api from '../api';

export default function NotificationBadge() {
  const [count, setCount] = useState(0);
  const [items, setItems] = useState([]);
  const [open, setOpen] = useState(false);
  const ref = useRef(null);

  useEffect(() => {
    let mounted = true;
    async function load() {
      try {
        const [incoming, proposals] = await Promise.all([
          api.get('/api/follows/requests/incoming'),
          api.get('/api/proposals?status=voting'),
        ]);

        const notifs = [];
        if (incoming.length > 0) {
          notifs.push({
            text: `${incoming.length} follow request${incoming.length > 1 ? 's' : ''} pending`,
            link: '/delegations',
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
            link: '/proposals',
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
                    onClick={() => setOpen(false)}
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

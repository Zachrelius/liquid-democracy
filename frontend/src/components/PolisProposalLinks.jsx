import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import api, { isAbortError } from '../api';
import { urlFor } from '../utils/urls';
import {
  createBoundedCursorFeed,
  emptyCursorFeedState,
  polisProposalLinksUrl,
} from '../utils/boundedCursorFeed';

export default function PolisProposalLinks({ slug, polisId }) {
  const [feed, setFeed] = useState(emptyCursorFeedState);
  const loader = useMemo(() => createBoundedCursorFeed({
    get: (url, options) => api.get(url, options),
    buildUrl: polisProposalLinksUrl,
    isAbort: isAbortError,
    onChange: setFeed,
  }), []);
  const query = useMemo(() => ({ slug, polisId, limit: 25 }), [slug, polisId]);

  useEffect(() => {
    if (slug && polisId) loader.reset(query);
    return () => loader.cancel();
  }, [loader, query, slug, polisId]);

  return (
    <section className="space-y-2">
      <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide">
        {feed.loading || feed.error
          ? 'Referenced proposals'
          : `Referenced from ${feed.items.length}${feed.hasMore ? '+' : ''} proposal${feed.items.length === 1 && !feed.hasMore ? '' : 's'}`}
      </h2>
      {feed.loading ? (
        <div className="rounded-xl border border-gray-200 bg-white px-4 py-5 text-sm text-gray-400">
          Loading linked proposals…
        </div>
      ) : feed.error ? (
        <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {feed.error}
          <button type="button" onClick={() => loader.reset(query)} className="ml-2 underline">
            Retry
          </button>
        </div>
      ) : feed.items.length === 0 ? (
        <p className="text-sm text-gray-400">No proposals reference this deliberation.</p>
      ) : (
        <>
          <div className="bg-white border border-gray-200 rounded-xl divide-y divide-gray-100">
            {feed.items.map(proposal => (
              <Link
                key={proposal.id}
                to={urlFor(slug, 'proposal-detail', proposal.id)}
                className="flex items-center justify-between px-4 py-3 text-sm hover:bg-gray-50 transition-colors"
              >
                <span className="font-medium text-gray-800 truncate flex-1">{proposal.title}</span>
                <span className="text-xs text-gray-400 ml-3">{proposal.status}</span>
              </Link>
            ))}
          </div>
          {feed.loadMoreError && <p className="text-sm text-red-600">{feed.loadMoreError}</p>}
          {feed.hasMore && (
            <button
              type="button"
              disabled={feed.loadingMore}
              onClick={() => loader.loadMore(query)}
              className="min-h-11 rounded-lg border border-gray-300 px-4 py-2 text-sm text-gray-700 hover:bg-gray-50 disabled:opacity-50"
            >
              {feed.loadingMore ? 'Loading…' : 'Load more linked proposals'}
            </button>
          )}
        </>
      )}
    </section>
  );
}

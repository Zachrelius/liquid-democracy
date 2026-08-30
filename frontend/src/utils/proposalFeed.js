export const PROPOSAL_FEED_PAGE_SIZE = 25;

/**
 * Coordinates initial and Load-more requests for one mounted feed. Starting
 * any request aborts its predecessor; reset/unmount cancellation also
 * invalidates the generation so a late resolution cannot update state.
 */
export function createProposalFeedRequestCoordinator() {
  let activeController = null;
  let generation = 0;
  return {
    begin({ reset = false } = {}) {
      activeController?.abort();
      if (reset) generation += 1;
      activeController = new AbortController();
      return { controller: activeController, generation };
    },
    cancel() {
      generation += 1;
      activeController?.abort();
      activeController = null;
    },
    isCurrent(candidateGeneration) {
      return candidateGeneration === generation;
    },
  };
}

export function emptyProposalFeedState() {
  return {
    items: [],
    nextCursor: null,
    hasMore: false,
    loading: true,
    loadingMore: false,
    error: '',
    loadMoreError: '',
  };
}

/**
 * Behavior-level feed orchestration kept outside React so request budgets,
 * pagination, and stale cancellation can be exercised with a mocked fetch.
 */
export function createProposalFeedLoader({ get, isAbort, onChange }) {
  const coordinator = createProposalFeedRequestCoordinator();
  let state = emptyProposalFeedState();

  const update = patch => {
    state = { ...state, ...patch };
    onChange({ ...state });
  };

  const load = async (query, append) => {
    if (append && (!state.hasMore || !state.nextCursor || state.loadingMore)) return;
    const { controller, generation } = coordinator.begin({ reset: !append });
    const cursor = append ? state.nextCursor : null;
    if (append) update({ loadingMore: true, loadMoreError: '' });
    else update(emptyProposalFeedState());

    try {
      const data = await get(proposalFeedUrl({ ...query, cursor }), {
        signal: controller.signal,
      });
      if (!coordinator.isCurrent(generation)) return;
      const page = unpackProposalFeed(data);
      update({
        items: append ? [...state.items, ...page.items] : page.items,
        nextCursor: page.nextCursor,
        hasMore: page.hasMore,
      });
    } catch (error) {
      if (!coordinator.isCurrent(generation) || isAbort(error)) return;
      if (append) update({ loadMoreError: error?.message || 'Could not load more proposals.' });
      else update({ error: error?.message || 'Failed to load proposals' });
    } finally {
      if (coordinator.isCurrent(generation)) {
        update(append ? { loadingMore: false } : { loading: false });
      }
    }
  };

  return {
    reset: query => load(query, false),
    loadMore: query => load(query, true),
    getState: () => ({ ...state }),
    cancel() {
      coordinator.cancel();
    },
  };
}

export function proposalFeedUrl({ slug, readOnly, status, topicId, cursor, limit = PROPOSAL_FEED_PAGE_SIZE }) {
  const base = slug
    ? `/api/orgs/${slug}/${readOnly ? 'public/' : ''}proposal-feed`
    : '/api/proposal-feed';
  const params = new URLSearchParams();
  params.set('limit', String(limit));
  if (status && status !== 'all') params.set('status', status);
  if (topicId) params.set('topic_id', topicId);
  if (cursor) params.set('cursor', cursor);
  return `${base}?${params.toString()}`;
}

export function unpackProposalFeed(data) {
  const items = Array.isArray(data?.items) ? data.items : [];
  return {
    items: items.filter(item => item?.proposal?.id),
    nextCursor: typeof data?.next_cursor === 'string' ? data.next_cursor : null,
    hasMore: data?.has_more === true,
  };
}

export async function loadPublicProposalPreview({ get, slug, signal }) {
  const data = await get(proposalFeedUrl({ slug, readOnly: true, limit: 5 }), { signal });
  return unpackProposalFeed(data).items.slice(0, 5).map(item => item.proposal);
}

export function formatViewerVote(proposal, viewerVote) {
  if (!viewerVote?.has_effective_vote) return 'Your vote: Not cast';
  const via = !viewerVote.is_direct && viewerVote.cast_by_display_name
    ? ` via ${viewerVote.cast_by_display_name}`
    : '';
  if (proposal.voting_method === 'binary' && viewerVote.binary_value) {
    return `Your vote: ${viewerVote.binary_value.toUpperCase()}${via}`;
  }
  if (proposal.voting_method === 'approval' && Number.isInteger(viewerVote.selection_count)) {
    const count = viewerVote.selection_count;
    return `Your vote: ${count} option${count === 1 ? '' : 's'} approved${via}`;
  }
  return `Your vote is recorded${via}`;
}

export function votingMethodLabel(method) {
  return {
    binary: 'Yes / No',
    approval: 'Approval',
    ranked_choice: 'Ranked choice',
    budget_allocation: 'Budget allocation',
    budget_project: 'Ranked projects',
  }[method] || method?.replaceAll('_', ' ') || 'Vote';
}

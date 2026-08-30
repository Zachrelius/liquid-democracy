export function emptyCursorFeedState() {
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

export function unpackCursorEnvelope(data) {
  return {
    items: Array.isArray(data?.items) ? data.items : [],
    nextCursor: typeof data?.next_cursor === 'string' ? data.next_cursor : null,
    hasMore: data?.has_more === true,
  };
}

/**
 * One-request-per-page cursor orchestration for compact secondary lists.
 * Reset, filter changes, and unmount invalidate late work as well as aborting
 * the underlying request.
 */
export function createBoundedCursorFeed({ get, buildUrl, isAbort, onChange }) {
  let state = emptyCursorFeedState();
  let controller = null;
  let generation = 0;

  const update = patch => {
    state = { ...state, ...patch };
    onChange({ ...state });
  };

  const request = async (query, append) => {
    if (append && (!state.hasMore || !state.nextCursor || state.loadingMore)) return;
    controller?.abort();
    if (!append) generation += 1;
    const requestGeneration = generation;
    controller = new AbortController();
    const cursor = append ? state.nextCursor : null;

    if (append) update({ loadingMore: true, loadMoreError: '' });
    else update(emptyCursorFeedState());

    try {
      const data = await get(buildUrl({ ...query, cursor }), { signal: controller.signal });
      if (requestGeneration !== generation) return;
      const page = unpackCursorEnvelope(data);
      update({
        items: append ? [...state.items, ...page.items] : page.items,
        nextCursor: page.nextCursor,
        hasMore: page.hasMore,
      });
    } catch (error) {
      if (requestGeneration !== generation || isAbort(error)) return;
      if (append) update({ loadMoreError: error?.message || 'Could not load more.' });
      else update({ error: error?.message || 'Could not load this list.' });
    } finally {
      if (requestGeneration === generation) {
        update(append ? { loadingMore: false } : { loading: false });
      }
    }
  };

  return {
    reset: query => request(query, false),
    loadMore: query => request(query, true),
    getState: () => ({ ...state }),
    cancel() {
      generation += 1;
      controller?.abort();
      controller = null;
    },
  };
}

export function managementProposalFeedUrl({
  slug,
  status = 'all',
  scope = 'all',
  q = '',
  eligibleFor = '',
  cursor,
  limit = 50,
}) {
  const params = new URLSearchParams({ limit: String(limit) });
  if (status !== 'all') params.set('status', status);
  if (scope === 'parent') params.set('parent_only', 'true');
  else if (scope && scope !== 'all') params.set('sub_org_id', scope);
  if (q.trim()) params.set('q', q.trim().slice(0, 100));
  if (eligibleFor) params.set('eligible_for', eligibleFor);
  if (cursor) params.set('cursor', cursor);
  return `/api/orgs/${slug}/proposal-management-feed?${params.toString()}`;
}

export function polisProposalLinksUrl({ slug, polisId, cursor, limit = 25 }) {
  const params = new URLSearchParams({ limit: String(limit) });
  if (cursor) params.set('cursor', cursor);
  return `/api/orgs/${slug}/polises/${polisId}/proposal-links?${params.toString()}`;
}

export function selectionRowsForOrg(selectionByOrg, slug) {
  return selectionByOrg.get(slug) || new Map();
}

export function updateOrgSelection(selectionByOrg, slug, updater) {
  const next = new Map(selectionByOrg);
  const current = selectionRowsForOrg(next, slug);
  next.set(slug, updater(new Map(current)));
  return next;
}

export function selectionAfterFilterDecision(selectionByOrg, slug, accepted) {
  if (!accepted) return selectionByOrg;
  return updateOrgSelection(selectionByOrg, slug, () => new Map());
}

export function selectionAfterCompletedIds(selectionByOrg, slug, completedIds) {
  const completed = completedIds instanceof Set ? completedIds : new Set(completedIds || []);
  return updateOrgSelection(selectionByOrg, slug, rows => {
    completed.forEach(id => rows.delete(id));
    return rows;
  });
}

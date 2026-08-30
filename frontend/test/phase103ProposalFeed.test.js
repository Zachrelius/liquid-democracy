import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

import api, {
  isAbortError,
  refreshAccessToken,
  REQUEST_TIMEOUT_MESSAGE,
  setTokens,
  TEMPORARY_UNAVAILABLE_MESSAGE,
} from '../src/api.js';
import {
  createProposalFeedLoader,
  createProposalFeedRequestCoordinator,
  formatViewerVote,
  loadPublicProposalPreview,
  proposalFeedUrl,
  unpackProposalFeed,
} from '../src/utils/proposalFeed.js';

function source(relativePath) {
  return readFileSync(new URL(`../src/${relativePath}`, import.meta.url), 'utf8');
}

function jsonResponse(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function installBrowserShims() {
  const values = new Map();
  globalThis.sessionStorage = {
    getItem: key => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, String(value)),
    removeItem: key => values.delete(key),
  };
  globalThis.window = { dispatchEvent() {} };
}

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

test.beforeEach(() => {
  installBrowserShims();
  setTokens(null, null);
});

test('feed URLs keep member, public, global, filter, and cursor contracts distinct', () => {
  assert.equal(
    proposalFeedUrl({ slug: 'assembly', readOnly: false, status: 'all' }),
    '/api/orgs/assembly/proposal-feed?limit=25',
  );
  assert.equal(
    proposalFeedUrl({
      slug: 'assembly', readOnly: true, status: 'voting', topicId: 'topic 1', limit: 5,
    }),
    '/api/orgs/assembly/public/proposal-feed?limit=5&status=voting&topic_id=topic+1',
  );
  assert.equal(
    proposalFeedUrl({ status: 'archived', cursor: 'v1.opaque/value' }),
    '/api/proposal-feed?limit=25&status=archived&cursor=v1.opaque%2Fvalue',
  );
});

test('feed envelope and compact viewer summaries drive card state without raw ballots', () => {
  const page = unpackProposalFeed({
    items: [
      { proposal: { id: 'p1' }, viewer_vote: null },
      { proposal: null, viewer_vote: null },
    ],
    next_cursor: 'cursor-2',
    has_more: true,
  });
  assert.deepEqual(page, {
    items: [{ proposal: { id: 'p1' }, viewer_vote: null }],
    nextCursor: 'cursor-2',
    hasMore: true,
  });
  assert.equal(
    formatViewerVote(
      { voting_method: 'binary' },
      {
        has_effective_vote: true,
        is_direct: false,
        binary_value: 'yes',
        cast_by_display_name: 'Example Delegate',
      },
    ),
    'Your vote: YES via Example Delegate',
  );
  assert.equal(
    formatViewerVote(
      { voting_method: 'approval' },
      { has_effective_vote: true, is_direct: true, selection_count: 2 },
    ),
    'Your vote: 2 options approved',
  );
  assert.equal(
    formatViewerVote({ voting_method: 'ranked_choice' }, { has_effective_vote: true }),
    'Your vote is recorded',
  );
  assert.equal(formatViewerVote({ voting_method: 'binary' }, null), 'Your vote: Not cast');
});

test('proposal list has a bounded request budget and no per-card fan-out or tally rendering', () => {
  const proposals = source('pages/Proposals.jsx');
  assert.match(proposals, /createProposalFeedLoader/);
  assert.match(proposals, /Load more proposals/);
  assert.match(proposals, /new AbortController\(\)/);
  assert.match(proposals, /feedLoader\.loadMore/);
  assert.doesNotMatch(proposals, /\/results/);
  assert.doesNotMatch(proposals, /\/my-vote/);
  assert.doesNotMatch(proposals, /Promise\.allSettled/);
  assert.doesNotMatch(proposals, /VoteBar|MultiOptionResultBar|effectiveApprovalWinners/);

  // The component wires one feed loader plus topics and sub-org metadata.
  // Pagination reuses the loader rather than introducing another call site.
  assert.equal((proposals.match(/api\.get\(/g) || []).length, 3);
  assert.match(proposals, /isReadOnly=\{readOnly \|\| \(!!subOrg && !subOrg\.user_role\)\}/);
});

test('request coordinator cancellation aborts the active Load more request and invalidates its generation', () => {
  const coordinator = createProposalFeedRequestCoordinator();
  const initial = coordinator.begin({ reset: true });
  const loadMore = coordinator.begin();
  assert.equal(initial.controller.signal.aborted, true);
  assert.equal(loadMore.controller.signal.aborted, false);
  assert.equal(coordinator.isCurrent(loadMore.generation), true);
  coordinator.cancel();
  assert.equal(loadMore.controller.signal.aborted, true);
  assert.equal(coordinator.isCurrent(loadMore.generation), false);
});

test('initial feed, Load more, and terminal state have an exact one-request budget each', async () => {
  const calls = [];
  const changes = [];
  const loader = createProposalFeedLoader({
    get(url, options) {
      const pending = deferred();
      calls.push({ url, signal: options.signal, pending });
      return pending.promise;
    },
    isAbort: isAbortError,
    onChange: state => changes.push(state),
  });

  const query = { slug: 'assembly', readOnly: false, status: 'all' };
  const initial = loader.reset(query);
  assert.equal(calls.length, 1);
  assert.doesNotMatch(calls[0].url, /\/results|\/my-vote/);
  calls[0].pending.resolve({
    items: [{ proposal: { id: 'p1' }, viewer_vote: null }],
    next_cursor: 'next-page',
    has_more: true,
  });
  await initial;
  assert.equal(loader.getState().loading, false);
  assert.equal(loader.getState().items.length, 1);

  const next = loader.loadMore(query);
  assert.equal(calls.length, 2);
  assert.match(calls[1].url, /cursor=next-page/);
  calls[1].pending.resolve({
    items: [{ proposal: { id: 'p2' }, viewer_vote: null }],
    next_cursor: null,
    has_more: false,
  });
  await next;
  assert.deepEqual(loader.getState().items.map(item => item.proposal.id), ['p1', 'p2']);
  assert.equal(loader.getState().loadingMore, false);
  assert.equal(loader.getState().hasMore, false);

  await loader.loadMore(query);
  assert.equal(calls.length, 2, 'terminal Load more must not issue another request');
  assert.ok(changes.length > 0);
});

test('filter reset aborts stale work and stale failure cannot replace newer items or loading state', async () => {
  const calls = [];
  const loader = createProposalFeedLoader({
    get(url, options) {
      const pending = deferred();
      calls.push({ url, signal: options.signal, pending });
      return pending.promise;
    },
    isAbort: isAbortError,
    onChange() {},
  });
  const stale = loader.reset({ slug: 'assembly', readOnly: false, status: 'all' });
  const fresh = loader.reset({ slug: 'assembly', readOnly: false, status: 'voting' });
  assert.equal(calls.length, 2);
  assert.equal(calls[0].signal.aborted, true);
  assert.match(calls[1].url, /status=voting/);

  calls[0].pending.reject({ message: 'stale failure', status: 503 });
  calls[1].pending.resolve({
    items: [{ proposal: { id: 'fresh' }, viewer_vote: null }],
    next_cursor: null,
    has_more: false,
  });
  await Promise.all([stale, fresh]);
  assert.deepEqual(loader.getState().items.map(item => item.proposal.id), ['fresh']);
  assert.equal(loader.getState().error, '');
  assert.equal(loader.getState().loading, false);
});

test('unmount-style cancellation during Load more aborts that request without emitting an error', async () => {
  const calls = [];
  const changes = [];
  const loader = createProposalFeedLoader({
    get(url, options) {
      const pending = deferred();
      options.signal.addEventListener('abort', () => {
        pending.reject({ name: 'AbortError', code: 'request_aborted', message: '' });
      }, { once: true });
      calls.push({ url, signal: options.signal, pending });
      return pending.promise;
    },
    isAbort: isAbortError,
    onChange: state => changes.push(state),
  });
  const initial = loader.reset({ slug: 'assembly', readOnly: false });
  calls[0].pending.resolve({
    items: [{ proposal: { id: 'p1' }, viewer_vote: null }],
    next_cursor: 'more',
    has_more: true,
  });
  await initial;
  const more = loader.loadMore({ slug: 'assembly', readOnly: false });
  loader.cancel();
  assert.equal(calls[1].signal.aborted, true);
  await more;
  assert.equal(changes.at(-1).loadMoreError, '');
});

test('public landing preview requests and returns no more than five feed items', async () => {
  const calls = [];
  const controller = new AbortController();
  const proposals = await loadPublicProposalPreview({
    slug: 'assembly',
    signal: controller.signal,
    get: async (url, options) => {
      calls.push({ url, signal: options.signal });
      return {
        items: Array.from({ length: 8 }, (_, index) => ({
          proposal: { id: `p${index + 1}` }, viewer_vote: null,
        })),
        next_cursor: 'hidden-remainder',
        has_more: true,
      };
    },
  });
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, '/api/orgs/assembly/public/proposal-feed?limit=5');
  assert.equal(calls[0].signal, controller.signal);
  assert.deepEqual(proposals.map(proposal => proposal.id), ['p1', 'p2', 'p3', 'p4', 'p5']);

  const landing = source('pages/OrgPublicLanding.jsx');
  assert.match(landing, /loadPublicProposalPreview/);
  assert.doesNotMatch(landing, /public\/proposals`/);
});

test('HTML 504 login and empty 503 API errors use calm temporary-unavailability copy', async t => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });

  globalThis.fetch = async () => new Response('<html>gateway timeout</html>', {
    status: 504,
    headers: { 'Content-Type': 'text/html' },
  });
  await assert.rejects(
    api.login('member', 'secret', { timeoutMs: 50 }),
    error => error.status === 504
      && error.message === TEMPORARY_UNAVAILABLE_MESSAGE
      && !error.message.includes('Unexpected token'),
  );

  globalThis.fetch = async () => new Response(null, { status: 503 });
  await assert.rejects(
    api.get('/api/example', { timeoutMs: 50 }),
    error => error.status === 503 && error.message === TEMPORARY_UNAVAILABLE_MESSAGE,
  );
});

test('structured Pydantic detail remains authoritative over status fallback', async t => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = async () => jsonResponse({
    detail: [{ loc: ['query', 'cursor'], msg: 'Malformed cursor' }],
  }, 422);
  await assert.rejects(
    api.get('/api/example'),
    error => error.status === 422 && error.message === 'cursor — Malformed cursor',
  );
});

test('HTML 502 during token refresh is not misreported as session expiry', async t => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  setTokens('expired-access', 'refresh-token');
  let calls = 0;
  globalThis.fetch = async path => {
    calls += 1;
    if (path === '/api/auth/refresh') {
      return new Response('<h1>bad gateway</h1>', {
        status: 502,
        headers: { 'Content-Type': 'text/html' },
      });
    }
    return jsonResponse({ detail: 'expired' }, 401);
  };
  await assert.rejects(
    api.get('/api/protected'),
    error => error.status === 502 && error.message === TEMPORARY_UNAVAILABLE_MESSAGE,
  );
  assert.equal(calls, 2);
});

test('refresh de-duplication does not let a boolean caller swallow a shared 502', async t => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  setTokens('expired-access', 'refresh-token');
  let refreshCalls = 0;
  const release = deferred();
  globalThis.fetch = async path => {
    if (path === '/api/auth/refresh') {
      refreshCalls += 1;
      await release.promise;
      return new Response('<h1>bad gateway</h1>', {
        status: 502,
        headers: { 'Content-Type': 'text/html' },
      });
    }
    return jsonResponse({ detail: 'expired' }, 401);
  };
  const bootProbe = refreshAccessToken();
  const protectedRequest = api.get('/api/protected');
  release.resolve();
  assert.equal(await bootProbe, false);
  await assert.rejects(
    protectedRequest,
    error => error.status === 502 && error.message === TEMPORARY_UNAVAILABLE_MESSAGE,
  );
  assert.equal(refreshCalls, 1);
});

test('network failure during token refresh remains a network error, not session expiry', async t => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  setTokens('expired-access', 'refresh-token');
  globalThis.fetch = async path => {
    if (path === '/api/auth/refresh') throw new TypeError('network unreachable');
    return jsonResponse({ detail: 'expired' }, 401);
  };
  await assert.rejects(
    api.get('/api/protected'),
    error => error.code === 'network_error'
      && error.message === "Couldn't reach the server. Check your connection and try again."
      && !error.message.includes('Session expired'),
  );
});

test('caller abort is distinguishable and silent', async t => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = async (_path, options) => new Promise((_resolve, reject) => {
    options.signal.addEventListener('abort', () => {
      reject(Object.assign(new Error('aborted'), { name: 'AbortError' }));
    }, { once: true });
  });
  const controller = new AbortController();
  const pending = api.get('/api/slow', { signal: controller.signal, timeoutMs: 1000 });
  controller.abort();
  await assert.rejects(
    pending,
    error => isAbortError(error) && error.message === '',
  );
});

test('GET timeout stays active while a response body is stalled after headers', async t => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = async (_path, options) => ({
    status: 200,
    ok: true,
    headers: new Headers({ 'Content-Type': 'application/json' }),
    text: () => new Promise((_resolve, reject) => {
      options.signal.addEventListener('abort', () => {
        reject(Object.assign(new Error('body aborted'), { name: 'AbortError' }));
      }, { once: true });
    }),
  });
  await assert.rejects(
    api.get('/api/stalled-body', { timeoutMs: 5 }),
    error => error.code === 'request_timeout' && error.message === REQUEST_TIMEOUT_MESSAGE,
  );
});

test('concurrent 401 requests still deduplicate refresh and retry with fresh auth', async t => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  setTokens('expired-access', 'refresh-token');
  let refreshCalls = 0;
  globalThis.fetch = async (path, options) => {
    if (path === '/api/auth/refresh') {
      refreshCalls += 1;
      await new Promise(resolve => setTimeout(resolve, 5));
      return jsonResponse({ access_token: 'fresh-access', refresh_token: 'fresh-refresh' });
    }
    if (options.headers.Authorization === 'Bearer expired-access') {
      return jsonResponse({ detail: 'expired' }, 401);
    }
    return jsonResponse({ ok: true });
  };
  const [first, second] = await Promise.all([
    api.get('/api/one'),
    api.get('/api/two'),
  ]);
  assert.deepEqual(first, { ok: true });
  assert.deepEqual(second, { ok: true });
  assert.equal(refreshCalls, 1);
});

test('form-data and download errors use the same safe parser', async t => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = async () => new Response('<html>busy</html>', {
    status: 503,
    headers: { 'Content-Type': 'text/html' },
  });
  await assert.rejects(
    api.postFormData('/api/upload', new FormData()),
    error => error.message === TEMPORARY_UNAVAILABLE_MESSAGE,
  );
  await assert.rejects(
    api.download('/api/export', 'export.csv'),
    error => error.message === TEMPORARY_UNAVAILABLE_MESSAGE,
  );
});

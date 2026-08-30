import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';

import { isAbortError } from '../src/api.js';
import {
  createBoundedCursorFeed,
  managementProposalFeedUrl,
  polisProposalLinksUrl,
  selectionAfterCompletedIds,
  selectionAfterFilterDecision,
  selectionRowsForOrg,
  updateOrgSelection,
} from '../src/utils/boundedCursorFeed.js';
import {
  proposalEligibleForBulkOperation,
  visibleEligibleProposalIds,
} from '../src/utils/bulkDeliberation.js';

function source(relativePath) {
  return readFileSync(new URL(`../src/${relativePath}`, import.meta.url), 'utf8');
}

function productionSourceFiles(directory = new URL('../src/', import.meta.url)) {
  return readdirSync(directory, { withFileTypes: true }).flatMap(entry => {
    const child = new URL(`${entry.name}${entry.isDirectory() ? '/' : ''}`, directory);
    if (entry.isDirectory()) return productionSourceFiles(child);
    return /\.[jt]sx?$/.test(entry.name) ? [child] : [];
  });
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

test('management URL encodes every bounded filter and scoped sub-org mode', () => {
  assert.equal(
    managementProposalFeedUrl({ slug: 'assembly' }),
    '/api/orgs/assembly/proposal-management-feed?limit=50',
  );
  assert.equal(
    managementProposalFeedUrl({
      slug: 'assembly',
      status: 'voting',
      scope: 'parent',
      q: '  literal title  ',
      eligibleFor: 'set_end',
      cursor: 'opaque/next',
    }),
    '/api/orgs/assembly/proposal-management-feed?limit=50&status=voting&parent_only=true&q=literal+title&eligible_for=set_end&cursor=opaque%2Fnext',
  );
  assert.equal(
    managementProposalFeedUrl({ slug: 'assembly', scope: 'sub org', limit: 25 }),
    '/api/orgs/assembly/proposal-management-feed?limit=25&sub_org_id=sub+org',
  );
  assert.equal(
    polisProposalLinksUrl({ slug: 'assembly', polisId: 'polis-1', cursor: 'next' }),
    '/api/orgs/assembly/polises/polis-1/proposal-links?limit=25&cursor=next',
  );
});

test('secondary cursor feeds spend exactly one request per page and stop at terminal state', async () => {
  const calls = [];
  const loader = createBoundedCursorFeed({
    get(url, options) {
      const pending = deferred();
      calls.push({ url, signal: options.signal, pending });
      return pending.promise;
    },
    buildUrl: managementProposalFeedUrl,
    isAbort: isAbortError,
    onChange() {},
  });
  const query = { slug: 'assembly', status: 'all' };
  const first = loader.reset(query);
  assert.equal(calls.length, 1);
  calls[0].pending.resolve({
    items: [{ id: 'p1' }], next_cursor: 'page-2', has_more: true,
  });
  await first;

  const more = loader.loadMore(query);
  assert.equal(calls.length, 2);
  assert.match(calls[1].url, /cursor=page-2/);
  calls[1].pending.resolve({
    items: [{ id: 'p2' }], next_cursor: null, has_more: false,
  });
  await more;
  assert.deepEqual(loader.getState().items.map(item => item.id), ['p1', 'p2']);

  await loader.loadMore(query);
  assert.equal(calls.length, 2);
});

test('filter reset and unmount abort stale secondary list work without surfacing stale failures', async () => {
  const calls = [];
  const loader = createBoundedCursorFeed({
    get(url, options) {
      const pending = deferred();
      calls.push({ url, signal: options.signal, pending });
      return pending.promise;
    },
    buildUrl: managementProposalFeedUrl,
    isAbort: isAbortError,
    onChange() {},
  });
  const stale = loader.reset({ slug: 'assembly', status: 'all' });
  const fresh = loader.reset({ slug: 'assembly', status: 'draft' });
  assert.equal(calls[0].signal.aborted, true);
  calls[0].pending.reject({ status: 503, message: 'stale error' });
  calls[1].pending.resolve({ items: [{ id: 'fresh' }], next_cursor: 'more', has_more: true });
  await Promise.all([stale, fresh]);
  assert.deepEqual(loader.getState().items.map(item => item.id), ['fresh']);
  assert.equal(loader.getState().error, '');

  const more = loader.loadMore({ slug: 'assembly', status: 'draft' });
  loader.cancel();
  assert.equal(calls[2].signal.aborted, true);
  calls[2].pending.reject({ name: 'AbortError', code: 'request_aborted', message: '' });
  await more;
  assert.equal(loader.getState().loadMoreError, '');
});

test('selection map keeps cross-page row metadata org-scoped and filter Cancel is lossless', () => {
  const firstPage = { id: 'p1', title: 'First page', voting_end: '2026-09-10T12:00:00Z' };
  const secondPage = { id: 'p2', title: 'Second page', voting_end: null };
  let selection = new Map();
  selection = updateOrgSelection(selection, 'assembly', rows => rows.set(firstPage.id, firstPage));
  selection = updateOrgSelection(selection, 'assembly', rows => rows.set(secondPage.id, secondPage));
  selection = updateOrgSelection(selection, 'other-org', rows => rows.set('p9', { id: 'p9' }));

  assert.deepEqual([...selectionRowsForOrg(selection, 'assembly').keys()], ['p1', 'p2']);
  assert.equal(selectionRowsForOrg(selection, 'assembly').get('p1').title, 'First page');
  assert.equal(selectionRowsForOrg(selection, 'other-org').size, 1);

  const cancelled = selectionAfterFilterDecision(selection, 'assembly', false);
  assert.equal(cancelled, selection);
  assert.equal(selectionRowsForOrg(cancelled, 'assembly').size, 2);

  const accepted = selectionAfterFilterDecision(selection, 'assembly', true);
  assert.equal(selectionRowsForOrg(accepted, 'assembly').size, 0);
  assert.equal(selectionRowsForOrg(accepted, 'other-org').size, 1);
});

test('partial bulk completion removes terminal rows while outer failure preserves unsubmitted rows', () => {
  const rows = [
    { id: 'p1', title: 'First submitted row' },
    { id: 'p2', title: 'Second submitted row' },
    { id: 'p3', title: 'Never submitted after network failure' },
  ];
  let selection = new Map();
  for (const row of rows) {
    selection = updateOrgSelection(selection, 'assembly', current => current.set(row.id, row));
  }

  // The first chunk returned terminal per-row results, then the next request
  // failed before receiving a response. The handler uses this same helper in
  // both its success and outer-failure paths.
  selection = selectionAfterCompletedIds(selection, 'assembly', new Set(['p1', 'p2']));
  assert.deepEqual([...selectionRowsForOrg(selection, 'assembly').keys()], ['p3']);
  assert.equal(
    selectionRowsForOrg(selection, 'assembly').get('p3').title,
    'Never submitted after network failure',
  );
});

test('server eligibility is authoritative and set_end includes cosign-gated rows', () => {
  const serverRows = [
    { id: 'yes', status: 'failed', eligible_operations: ['set_end'] },
    { id: 'no', status: 'voting', eligible_operations: [] },
  ];
  assert.deepEqual(visibleEligibleProposalIds(serverRows, 'set_end'), ['yes']);
  assert.equal(proposalEligibleForBulkOperation(
    { status: 'deliberation', is_cosign_gated: true },
    'set_end',
  ), true);
});

test('all Phase 104 consumers use compact endpoints with no internal legacy raw proposal reads', () => {
  const management = source('pages/admin/ProposalManagement.jsx');
  const subOrgProposals = source('pages/admin/SubOrgProposals.jsx');
  const subOrgSettings = source('pages/admin/SubOrgSettings.jsx');
  const polis = source('pages/Polis.jsx');
  const polisDetail = source('pages/admin/PolisDetail.jsx');
  const links = source('components/PolisProposalLinks.jsx');
  const consumers = [management, subOrgProposals, subOrgSettings, polis, polisDetail];

  for (const consumer of consumers) {
    assert.doesNotMatch(consumer, /api\.get\(`\/api\/orgs\/\$\{[^}]+\}\/proposals`/);
    assert.doesNotMatch(consumer, /api\.get\('\/api\/proposals'|api\.get\("\/api\/proposals"/);
    assert.doesNotMatch(consumer, /public\/proposals/);
  }
  assert.match(management, /managementProposalFeedUrl/);
  assert.match(management, /Select all loaded eligible proposals/);
  assert.match(management, /aria-expanded=\{expandedId === p\.id\}/);
  assert.match(subOrgProposals, /limit: 25/);
  assert.match(subOrgSettings, /deletion-impact/);
  assert.match(subOrgSettings, /This sub-organization cannot be deleted while scoped topics or proposals remain\./);
  assert.match(polis, /PolisProposalLinks/);
  assert.match(polisDetail, /PolisProposalLinks/);
  assert.match(links, /polisProposalLinksUrl/);
  assert.match(links, /Load more linked proposals/);

  const legacyListPattern = /(?:api\.get|fetch)\(\s*(?:`\/api\/proposals(?:\?[^`]*)?`|`\/api\/orgs\/\$\{[^}]+\}\/(?:public\/)?proposals(?:\?[^`]*)?`|['"]\/api\/proposals(?:\?[^'"]*)?['"]|['"]\/api\/orgs\/[^/'"]+\/(?:public\/)?proposals(?:\?[^'"]*)?['"])/;
  const offenders = productionSourceFiles()
    .filter(file => legacyListPattern.test(readFileSync(file, 'utf8')))
    .map(file => file.pathname);
  assert.deepEqual(offenders, [], `legacy proposal list callers: ${offenders.join(', ')}`);
});

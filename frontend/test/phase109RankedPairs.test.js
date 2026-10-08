import { before, after, test } from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'vite';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { assignmentsFromGroups, hasRankGroupsBallot, rankGroupsPayload } from '../src/utils/rankGroups.js';

test('rank group payload preserves ties, incomplete rankings and skips unused groups', () => {
  assert.deepEqual(rankGroupsPayload({ a: 1, b: 1, c: 3, d: null }, ['a', 'b', 'c', 'd']), { rank_groups: [['a', 'b'], ['c']] });
  assert.deepEqual(assignmentsFromGroups([['b', 'a'], ['c']]), { b: 1, a: 1, c: 2 });
  assert.deepEqual(rankGroupsPayload({}, ['a', 'b']), { rank_groups: [] });
  assert.deepEqual(rankGroupsPayload({ a: 1 }, ['a', 'b'], true), { abstain: true });
  assert.equal(hasRankGroupsBallot({ rank_groups: [] }), true);
  assert.equal(hasRankGroupsBallot({ abstain: true }), true);
  assert.equal(hasRankGroupsBallot({ rank_groups: null }), false);
});
test('rank payload rejects stale options and malformed ranks before submission', () => {
  assert.throws(() => rankGroupsPayload({ removed: 1 }, ['a', 'b']), /removed/);
  for (const rank of [true, '1', 1.5, 0, -1, 3, NaN]) assert.throws(() => rankGroupsPayload({ a: rank }, ['a', 'b']), /valid rank/);
});

let server, Results, Ballot, Controls, ToastProvider, History;
before(async () => {
  server = await createServer({ cacheDir: 'node_modules/.vite-phase109-rp-tests', server: { middlewareMode: true, hmr: false }, appType: 'custom' });
  Results = (await server.ssrLoadModule('/src/components/ExperimentalResultsPanel.jsx')).default;
  const module = await server.ssrLoadModule('/src/components/RankGroupsBallot.jsx');
  Ballot = module.default; Controls = module.RankGroupControls;
  ToastProvider = (await server.ssrLoadModule('/src/components/Toast.jsx')).ToastProvider;
  History = (await server.ssrLoadModule('/src/components/RankedPairsHistory.jsx')).default;
});
after(async () => { await server?.close(); });

const edges = [
  { winner: 'a', loser: 'b', margin: '3', support: '5' },
  { winner: 'b', loser: 'c', margin: '3', support: '5' },
  { winner: 'c', loser: 'a', margin: '1', support: '4' },
];
const result = overrides => ({ pairwise: { a: { a: '0', b: '5', c: '3' }, b: { a: '2', b: '0', c: '5' }, c: { a: '4', b: '2', c: '0' } },
  ordered_victories: edges, locked_edges: edges.slice(0, 2).map(edge => ({ ...edge, reason: 'locked' })),
  skipped_edges: [{ ...edges[2], reason: 'would_create_cycle' }], source_candidates: ['a'], winner: 'a',
  option_labels: { a: 'A', b: 'B', c: 'C' }, quorum_met: true, priority_used: false,
  total_ballots_cast: '7', total_abstain: '0', participating_headcount: '7', eligible_headcount: '7', ...overrides });

test('cycle results explain locked victories and skipped cycle edge without first-choice artifacts', () => {
  const html = renderToStaticMarkup(createElement(Results, { proposal: { voting_method: 'ranked_pairs', status: 'passed' }, tally: { method_result: result() } }));
  assert.match(html, /Winner: A/);
  assert.match(html, /Skipped — would create a directed cycle/);
  assert.match(html, /Options with no incoming locked defeat: A/);
  assert.match(html, /Each cell counts votes preferring the row option/);
  assert.doesNotMatch(html, /runoff|stars|Total points|first.choice/i);
});
test('ranked results retain exact large support and disclose priority dependence', () => {
  const html = renderToStaticMarkup(createElement(Results, { proposal: { voting_method: 'ranked_pairs', status: 'voting' }, tally: { method_result: result({
    ordered_victories: [{ winner: 'a', loser: 'b', margin: '900719925474099312345', support: '900719925474099312346' }],
    priority_used: true, tie_trace: [{ stage: 'edge_priority', margin: '3', support: '5' }],
  }) } }));
  assert.match(html, /900,719,925,474,099,312,346/);
  assert.match(html, /cannot satisfy Stable Result Required/);
  assert.match(html, /Equal-strength victories/);
});
test('rank controls expose named menus and non-submitting movement buttons', () => {
  const html = renderToStaticMarkup(createElement(Controls, { idPrefix: 'r', options: [{ id: 'a', label: 'A' }, { id: 'b', label: 'B' }], assignments: { a: 1, b: 1 }, onChange() {} }));
  assert.match(html, /for="r-a"[^>]*>Rank group for A/);
  assert.match(html, /Unranked — tied last/);
  assert.match(html, /aria-label="Move A up one rank group"/);
  assert.match(html, /type="button"[^>]*aria-label="Move B down one rank group"/);
  assert.equal((html.match(/value="1" selected=""/g) || []).length, 2);
  assert.doesNotMatch(html, /type="submit"/);
});
test('saved tied groups and neutral rank ballot distinguish submission from abstention', () => {
  const render = myVote => renderToStaticMarkup(createElement(ToastProvider, null, createElement(Ballot, {
    proposal: { options: [{ id: 'a', label: 'A' }, { id: 'b', label: 'B' }, { id: 'c', label: 'Late C' }] }, proposalId: 'rp', myVote, emailVerified: true, onVoteChange() {},
  })));
  assert.match(render({ rank_groups: [['a', 'b']], is_direct: true }), /A = B/);
  assert.match(render({ rank_groups: [['a', 'b']], is_direct: true }), /Unranked \(tied last\): Late C/);
  assert.match(render({ rank_groups: [], is_direct: true }), /Your neutral ballot counts as participation/);
  assert.match(render({ abstain: true, is_direct: true }), /You abstained/);
});
test('history preserves the actual winner and explains cycle skips in method units', () => {
  const html = renderToStaticMarkup(createElement(History, { snapshots: [{ captured_at: '2026-10-08T12:00:00Z', method_result: result() }], optionsById: {} }));
  assert.match(html, /Ranked Pairs snapshots/);
  assert.match(html, /Skipped to avoid cycles: C over A/);
  assert.doesNotMatch(html, /runoff|stars|points|approval percentages/);
});

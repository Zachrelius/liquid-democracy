import { before, after, test } from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'vite';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { ratedPayload } from '../src/utils/ratedBallot.js';
let server, Results, Ballot, ToastProvider, Graph;
before(async () => {
  server = await createServer({ cacheDir: 'node_modules/.vite-phase109-score-tests', server: { middlewareMode: true, hmr: false, ws: false }, appType: 'custom' });
  Results = (await server.ssrLoadModule('/src/components/RatedResultsPanel.jsx')).default;
  Ballot = (await server.ssrLoadModule('/src/components/RatedBallot.jsx')).default;
  Graph = (await server.ssrLoadModule('/src/components/VoteFlowGraph.jsx')).default;
  ToastProvider = (await server.ssrLoadModule('/src/components/Toast.jsx')).ToastProvider;
});
after(async () => { await server?.close(); });

const result = overrides => ({ scores: { a: '15', b: '20', c: '10' }, winner: 'b',
  option_labels: { a: 'A', b: 'B', c: 'C' }, quorum_met: true, priority_used: false,
  total_ballots_cast: '5', total_abstain: '0', participating_headcount: '5', eligible_headcount: '5', ...overrides });
const renderResult = overrides => renderToStaticMarkup(createElement(Results, {
  proposal: { voting_method: 'score', status: 'passed' }, tally: { method_result: result(overrides) },
}));

test('Score renders the highest-total winner separately from STAR and without runoff artifacts', () => {
  const html = renderResult();
  assert.match(html, /Winner: B/);
  assert.match(html, /Total points/);
  assert.doesNotMatch(html, /STAR|Finalist|runoff|five.star|Scoring round/);
});
test('Score tied maxima use exact large totals and disclose the final draw', () => {
  const html = renderResult({ scores: { a: '900719925474099312345', b: '900719925474099312345', c: '900719925474099312344' }, priority_used: true });
  assert.match(html, /900,719,925,474,099,312,345/);
  assert.match(html, /Tied highest totals: A, B/);
  assert.match(html, /Equal highest totals were resolved by the committed draw order/);
});
test('Score neutral ballots and abstentions retain distinct submission and omission semantics', () => {
  const render = myVote => renderToStaticMarkup(createElement(ToastProvider, null, createElement(Ballot, {
    proposal: { voting_method: 'score', options: [{ id: 'late', label: 'Late option' }] },
    proposalId: 'score', myVote, emailVerified: true, onVoteChange() {},
  })));
  const html = render({ scores: {}, is_direct: true });
  assert.match(html, /Your Score ballot/);
  assert.match(html, /0 to 5 points/);
  assert.match(html, /highest total points wins/);
  assert.match(html, /Late option: <strong>0\/5/);
  assert.doesNotMatch(html, /STAR|stars|runoff/);
  assert.match(render({ abstain: true, is_direct: true }), /You abstained/);
  assert.deepEqual(ratedPayload({ a: 5 }, ['a', 'late']), { scores: { a: 5 } });
  assert.deepEqual(ratedPayload({}, ['a', 'late']), { scores: {} });
  assert.deepEqual(ratedPayload({}, ['a', 'late'], true), { abstain: true });
});
test('Score no-result and graph summaries remain method appropriate', () => {
  const html = renderResult({ scores: { a: '0', b: '0' }, winner: null, no_result_reason: 'all_bottom_ratings' });
  assert.match(html, /No option received a rating above zero/);
  assert.doesNotMatch(html, /Winner:|Tied highest totals/);
  const graph = renderToStaticMarkup(createElement(Graph, { data: { voting_method: 'score' }, tally: { method_result: result() } }));
  assert.match(graph, /Score.*preferences/);
  assert.doesNotMatch(graph, /runoff|STAR|<table/);
});

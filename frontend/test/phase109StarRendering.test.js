import { before, after, test } from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'vite';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';

let server;
let Results;
let Ballot;
let VoteGraph;
let ToastProvider;
before(async () => {
  server = await createServer({ cacheDir: 'node_modules/.vite-phase109-tests', server: { middlewareMode: true, hmr: false, ws: false }, appType: 'custom' });
  Results = (await server.ssrLoadModule('/src/components/StarResultsPanel.jsx')).default;
  Ballot = (await server.ssrLoadModule('/src/components/RatedBallot.jsx')).default;
  VoteGraph = (await server.ssrLoadModule('/src/components/VoteFlowGraph.jsx')).default;
  ToastProvider = (await server.ssrLoadModule('/src/components/Toast.jsx')).ToastProvider;
});
after(async () => { await server?.close(); });

function result(overrides = {}) {
  return { scores: { a: '15', b: '20', c: '10' }, finalists: ['b', 'a'],
    runoff: { a: '3', b: '2' }, equal_preference: '0', winner: 'a',
    option_labels: { a: 'Original A', b: 'B', c: 'C' }, quorum_met: true,
    total_ballots_cast: '5', total_abstain: '0', participating_headcount: '5',
    eligible_headcount: '5', ...overrides };
}
test('rendered final results use preserved labels and actual runoff winner', () => {
  const html = renderToStaticMarkup(createElement(Results, {
    proposal: { status: 'passed', options: [{ id: 'a', label: 'Later renamed A' }] },
    tally: { method_result: result() },
  }));
  assert.match(html, /Winner: Original A/);
  assert.doesNotMatch(html, /Later renamed A/);
  assert.match(html, /Scoring round/);
  assert.match(html, /Automatic runoff/);
  assert.doesNotMatch(html, /Winner: B/);
});
test('rendered live results disclose priority ties and preserve exact large totals', () => {
  const html = renderToStaticMarkup(createElement(Results, {
    proposal: { status: 'voting' }, tally: { weighted: true, unit_label: 'shares', method_result: result({
      scores: { a: '900719925474099312345' }, priority_used: true,
      tie_trace: [{ stage: 'runoff_priority', pool: ['a', 'b'] }],
    }) },
  }));
  assert.match(html, /900,719,925,474,099,312,345/);
  assert.match(html, /Provisional leader/);
  assert.match(html, /cannot satisfy Stable Result Required/);
  assert.match(html, /Automatic runoff — shares/);
  assert.match(html, /Runoff tie: use the committed draw order/);
});
test('rendered neutral and explicit-abstention ballots remain distinct', () => {
  const render = myVote => renderToStaticMarkup(createElement(ToastProvider, null, createElement(Ballot, {
    proposal: { options: [{ id: 'a', label: 'Late option' }] }, proposalId: 'fixture',
    myVote, emailVerified: true, onVoteChange() {},
  })));
  const neutral = render({ scores: {}, is_direct: true });
  assert.match(neutral, /Your submitted ballot/);
  assert.match(neutral, /Late option: <strong>0\/5/);
  assert.match(neutral, /including any added later/);
  assert.doesNotMatch(neutral, /No ballot cast/);
  const abstain = render({ abstain: true, is_direct: true });
  assert.match(abstain, /You abstained/);
  assert.doesNotMatch(abstain, /Late option: <strong>/);
});
test('no meaningful result renders its reason without a fabricated winner', () => {
  const html = renderToStaticMarkup(createElement(Results, {
    proposal: { status: 'failed' }, tally: { method_result: result({ winner: null, no_result_reason: 'all_bottom_ratings' }) },
  }));
  assert.match(html, /No option received a rating above zero/);
  assert.doesNotMatch(html, /Winner:/);
});

test('STAR network fallback stays compact without duplicating full results', () => {
  const html = renderToStaticMarkup(createElement(VoteGraph, {
    data: { voting_method: 'star' }, tally: { method_result: result() },
  }));
  assert.match(html, /5 ballot units cast/);
  assert.match(html, /See the results panel/);
  assert.doesNotMatch(html, /Scoring round|Automatic runoff|Winner:/);
});
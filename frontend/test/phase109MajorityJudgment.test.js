import { before, after, test } from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'vite';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { gradePayload, hasRatedBallot } from '../src/utils/ratedBallot.js';
import { gradeDistributionWidths, gradeLabel } from '../src/utils/majorityJudgment.js';

test('grade payload preserves explicit Reject, missing late options and distinct neutral/abstain', () => {
  assert.deepEqual(gradePayload({ a: 5, b: 0 }, ['a', 'b', 'late']), { grades: { a: 5, b: 0 } });
  assert.deepEqual(gradePayload({}, ['a']), { grades: {} });
  assert.deepEqual(gradePayload({ a: 5 }, ['a'], true), { abstain: true });
  assert.equal(hasRatedBallot({ grades: {} }), true);
  for (const grade of [true, '5', 1.5, -1, 6]) assert.throws(() => gradePayload({ a: grade }, ['a']), /whole number/);
  assert.throws(() => gradePayload({ deleted: 5 }, ['a']), /removed/);
});
test('verbal grade labels preserve order and histogram widths use exact large integer ratios', () => {
  assert.deepEqual([0, '1', 2, '3', 4, '5'].map(gradeLabel), ['Reject', 'Poor', 'Acceptable', 'Good', 'Very good', 'Excellent']);
  assert.equal(gradeLabel(null), 'Unavailable');
  assert.equal(gradeLabel(2.5), 'Unavailable');
  assert.deepEqual(gradeDistributionWidths(['900719925474099312345', '0', '0', '0', '0', '900719925474099312345']), [50, 0, 0, 0, 0, 50]);
  assert.deepEqual(gradeDistributionWidths(['0', '0', '0', '0', '0', '0']), [0, 0, 0, 0, 0, 0]);
});

let server, Results, Ballot, Choices, ToastProvider, History;
before(async () => {
  server = await createServer({ cacheDir: 'node_modules/.vite-phase109-mj-tests', server: { middlewareMode: true, hmr: false, ws: false }, appType: 'custom' });
  Results = (await server.ssrLoadModule('/src/components/ExperimentalResultsPanel.jsx')).default;
  const module = await server.ssrLoadModule('/src/components/RatedBallot.jsx');
  Ballot = module.default; Choices = module.RatingChoices;
  ToastProvider = (await server.ssrLoadModule('/src/components/Toast.jsx')).ToastProvider;
  History = (await server.ssrLoadModule('/src/components/MajorityJudgmentHistory.jsx')).default;
});
after(async () => { await server?.close(); });

const result = overrides => ({ grade_histograms: { a: ['2', '0', '0', '0', '0', '3'], b: ['0', '0', '0', '0', '5', '0'] },
  majority_grades: { a: 5, b: '4' }, option_labels: { a: 'A', b: 'B' }, winner: 'a',
  quorum_met: true, priority_used: false, total_ballots_cast: '5', total_abstain: '0', participating_headcount: '5', eligible_headcount: '5', ...overrides });
const renderResult = overrides => renderToStaticMarkup(createElement(Results, { proposal: { voting_method: 'majority_judgment', status: 'passed' }, tally: { method_result: result(overrides) } }));

test('majority grade results elect the median winner and render original distributions', () => {
  const html = renderResult();
  assert.match(html, /Winner: A/);
  assert.match(html, /Majority grade: <strong>Excellent/);
  assert.match(html, /Majority grade: <strong>Very good/);
  assert.match(html, /A grade distribution: Reject 2, Poor 0, Acceptable 0, Good 0, Very good 0, Excellent 3/);
  assert.doesNotMatch(html, /Total points|runoff|stars|average|\/5/);
});
test('median comparison trace preserves displayed original grades and exact removal counts', () => {
  const html = renderResult({ majority_grades: { a: 2, b: 2 }, tie_trace: [{ stage: 'median_removal', pool: ['a', 'b'], removed_per_candidate: '900719925474099312345', majority_grades: { a: 2, b: 0 }, remaining_candidates: ['a'] }] });
  assert.match(html, /900,719,925,474,099,312,345/);
  assert.equal((html.match(/Majority grade: <strong>Acceptable/g) || []).length, 2);
  assert.match(html, /B: Reject/);
  assert.match(html, /original distributions and displayed majority grades intact/);
});
test('grade controls have six verbal radio labels and visible selection without points', () => {
  const html = renderToStaticMarkup(createElement(Choices, { option: { id: 'a', label: 'A' }, id: 'grades', selectedValue: 4, isGrade: true, onChange() {} }));
  for (const label of ['Reject', 'Poor', 'Acceptable', 'Good', 'Very good', 'Excellent']) assert.ok(html.includes(`aria-label="A: ${label}"`));
  assert.match(html, /aria-label="A: Very good"[^>]*checked=""/);
  assert.match(html, /grid-cols-2 sm:grid-cols-3/);
  assert.doesNotMatch(html, />[0-5]<|stars|points|type="submit"/);
});
test('saved empty grade ballot shows Reject for late options without becoming abstention', () => {
  const render = myVote => renderToStaticMarkup(createElement(ToastProvider, null, createElement(Ballot, { proposal: { voting_method: 'majority_judgment', options: [{ id: 'late', label: 'Late option' }] }, proposalId: 'mj', myVote, emailVerified: true, onVoteChange() {} })));
  const html = render({ grades: {}, is_direct: true });
  assert.match(html, /Your Majority Judgment ballot/);
  assert.match(html, /Late option: <strong>Reject/);
  assert.match(html, /Ungraded options receive Reject/);
  assert.doesNotMatch(html, /No ballot cast|You abstained|stars|\/5/);
  assert.match(render({ abstain: true, is_direct: true }), /You abstained/);
});
test('all Reject and identical distributions disclose no-result or draw as appropriate', () => {
  assert.match(renderResult({ winner: null, no_result_reason: 'all_bottom_ratings' }), /No option received a grade above Reject/);
  assert.match(renderResult({ priority_used: true, tie_trace: [{ stage: 'identical_distribution_priority', pool: ['a', 'b'] }] }), /Identical grade distributions required the committed draw order/);
});
test('grade history preserves distributions and verbal majority labels', () => {
  const html = renderToStaticMarkup(createElement(History, { snapshots: [{ captured_at: '2026-10-08T12:00:00Z', method_result: result() }], optionsById: {} }));
  assert.match(html, /Majority Judgment result history/);
  assert.match(html, /Majority grade: <strong>Excellent/);
  assert.doesNotMatch(html, /runoff|stars|points|average/);
});

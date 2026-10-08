import { before, after, test } from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'vite';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';

let server, Results;
before(async () => {
  server = await createServer({ cacheDir: 'node_modules/.vite-phase109-final-tests', server: { middlewareMode: true, hmr: false, ws: false }, appType: 'custom' });
  Results = (await server.ssrLoadModule('/src/components/ExperimentalResultsPanel.jsx')).default;
});
after(async () => { await server?.close(); });

const methodFields = {
  star: { scores: { a: '5', b: '1' }, finalists: ['a', 'b'], runoff: { a: '1', b: '0' }, equal_preference: '0' },
  score: { scores: { a: '5', b: '1' } },
  ranked_pairs: { pairwise: { a: { a: '0', b: '1' }, b: { a: '0', b: '0' } }, source_candidates: ['a'], ordered_victories: [], locked_edges: [], skipped_edges: [] },
  majority_judgment: { grade_histograms: { a: ['0', '0', '0', '0', '0', '1'], b: ['0', '1', '0', '0', '0', '0'] }, majority_grades: { a: 5, b: 1 } },
};
for (const [method, aggregates] of Object.entries(methodFields)) {
  test(`${method}: archiving preserves the frozen winner and final draw wording`, () => {
    const html = renderToStaticMarkup(createElement(Results, {
      proposal: { voting_method: method, status: 'withdrawn' },
      tally: { method_result: { ...aggregates, finalized: true, winner: 'a', option_labels: { a: 'Original winner', b: 'B' },
        quorum_met: true, priority_used: true, participating_headcount: '1', eligible_headcount: '1', total_ballots_cast: '1', total_abstain: '0' } },
    }));
    assert.match(html, /Winner: Original winner/);
    assert.match(html, /recorded outcome preserves that draw/);
    assert.doesNotMatch(html, /Provisional leader|cannot satisfy Stable Result Required/);
  });
}

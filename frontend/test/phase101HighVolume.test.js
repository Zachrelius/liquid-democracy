import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

import { normalizeApiError } from '../src/api.js';
import {
  createProposalRowsSequentially,
  proposalImportRateLimitMessage,
  proposalImportSelectionState,
} from '../src/utils/proposalImportBatch.js';


function source(relativePath) {
  return readFileSync(new URL(`../src/${relativePath}`, import.meta.url), 'utf8');
}


test('shared API errors preserve detail precedence and accept SlowAPI strings', () => {
  assert.equal(
    normalizeApiError({
      detail: [{ loc: ['body', 'title'], msg: 'Required' }],
      error: 'lower precedence',
    }, 422),
    'title — Required',
  );
  assert.equal(
    normalizeApiError({ detail: 'Specific detail', error: 'lower' }, 400),
    'Specific detail',
  );
  assert.equal(
    normalizeApiError({ error: 'Rate limit exceeded: 10 per 1 day' }, 429),
    'Rate limit exceeded: 10 per 1 day',
  );
  assert.equal(normalizeApiError({ error: { unsafe: true } }, 429), 'Server error 429');
});


test('11 selected ordinary rows are blocked before any create call', async () => {
  const rows = Array.from({ length: 11 }, (_, id) => ({ id }));
  let calls = 0;
  const result = await createProposalRowsSequentially(
    rows,
    async () => { calls += 1; },
    { highVolumeEnabled: false },
  );
  assert.equal(result.blocked, true);
  assert.equal(calls, 0);
  const state = proposalImportSelectionState(11, false);
  assert.equal(state.blocked, true);
  assert.match(state.guidance, /at most 10 proposals in a 24-hour window/);
  assert.match(state.guidance, /Select no more than ten/);
});


test('10 ordinary rows retain sequential one-at-a-time creation', async () => {
  const rows = Array.from({ length: 10 }, (_, id) => ({ id }));
  const order = [];
  const result = await createProposalRowsSequentially(
    rows,
    async row => { order.push(row.id); },
    { highVolumeEnabled: false },
  );
  assert.deepEqual(order, rows.map(row => row.id));
  assert.deepEqual(
    { blocked: result.blocked, created: result.created, remaining: result.remaining },
    { blocked: false, created: 10, remaining: 0 },
  );
});


test('high-volume permission allows 20 sequential single-create calls', async () => {
  const rows = Array.from({ length: 20 }, (_, id) => ({ id }));
  const order = [];
  const result = await createProposalRowsSequentially(
    rows,
    async row => { order.push(row.id); },
    { highVolumeEnabled: true },
  );
  assert.equal(result.created, 20);
  assert.equal(result.remaining, 0);
  assert.deepEqual(order, rows.map(row => row.id));
  const state = proposalImportSelectionState(20, true);
  assert.equal(state.blocked, false);
  assert.equal(
    state.note,
    'High-volume proposal creation is enabled for your role.',
  );
});


test('429 stops sequential work while preserving successes and retry rows', async () => {
  const rows = Array.from({ length: 6 }, (_, id) => ({ id }));
  const createdRows = [];
  const failedRows = [];
  let calls = 0;
  const result = await createProposalRowsSequentially(
    rows,
    async () => {
      calls += 1;
      if (calls === 4) throw { status: 429, message: 'Rate limit exceeded' };
    },
    {
      highVolumeEnabled: true,
      onCreated: row => createdRows.push(row.id),
      onFailed: row => failedRows.push(row.id),
    },
  );
  assert.equal(calls, 4);
  assert.deepEqual(createdRows, [0, 1, 2]);
  assert.deepEqual(failedRows, [3]);
  assert.equal(result.created, 3);
  assert.equal(result.remaining, 3);
  assert.equal(result.failedRow.id, 3);
  assert.match(proposalImportRateLimitMessage(false, 3, 3), /standard limit is 10/);
  assert.match(
    proposalImportRateLimitMessage(true, 3, 3),
    /high-volume safety limit is 10,000/,
  );
  assert.match(proposalImportRateLimitMessage(true, 3, 3), /drafts are safely created/);
  assert.match(proposalImportRateLimitMessage(true, 3, 3), /retry later/);
});


test('multi-import source keeps existing endpoint and accessible guidance', () => {
  const management = source('pages/admin/ProposalManagement.jsx');
  const apiSource = source('api.js');
  assert.match(management, /useHasPermission\('proposal\.high_volume_create'\)/);
  assert.match(management, /createProposalRowsSequentially/);
  assert.match(management, /`\/api\/orgs\/\$\{slug\}\/proposals`/);
  assert.doesNotMatch(management, /proposals\/batch-create/);
  assert.doesNotMatch(management, /advance-to-deliberation[\s\S]{0,200}createProposalRowsSequentially/);
  assert.match(management, /aria-describedby=/);
  assert.match(management, /proposal-import-create-guidance/);
  assert.match(apiSource, /normalizeApiError\(data, res\.status\)/g);
});

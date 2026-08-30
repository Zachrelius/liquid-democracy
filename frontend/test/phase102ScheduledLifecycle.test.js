import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

import {
  chunkProposalIds,
  proposalEligibleForBulkOperation,
  visibleEligibleProposalIds,
} from '../src/utils/bulkDeliberation.js';

const management = readFileSync(
  new URL('../src/pages/admin/ProposalManagement.jsx', import.meta.url), 'utf8',
);
const detail = readFileSync(
  new URL('../src/pages/ProposalDetail.jsx', import.meta.url), 'utf8',
);

test('operation choice owns proposal checkbox eligibility', () => {
  const rows = [
    { id: 'draft', status: 'draft' },
    { id: 'ordinary', status: 'deliberation', is_cosign_gated: false },
    { id: 'cosign', status: 'deliberation', is_cosign_gated: true },
    { id: 'voting', status: 'voting', is_cosign_gated: false },
  ];
  assert.deepEqual(visibleEligibleProposalIds(rows, 'draft_to_deliberation'), ['draft']);
  assert.deepEqual(visibleEligibleProposalIds(rows, 'deliberation_to_voting'), ['ordinary']);
  assert.deepEqual(visibleEligibleProposalIds(rows, 'schedule_start'), ['ordinary']);
  assert.deepEqual(visibleEligibleProposalIds(rows, 'set_end'), ['ordinary', 'cosign', 'voting']);
  assert.equal(proposalEligibleForBulkOperation(rows[2], 'set_end'), true);
});

test('bounded deterministic chunks remain capped at 500', () => {
  const ids = Array.from({ length: 501 }, (_, index) => String(index).padStart(4, '0'));
  assert.deepEqual(chunkProposalIds(ids).map(chunk => chunk.length), [500, 1]);
});

test('management source wires only the typed Phase 102 endpoints', () => {
  assert.match(management, /bulk-advance-to-voting/);
  assert.match(management, /bulk-schedule/);
  assert.match(management, /voting_starts_at/);
  assert.match(management, /voting_ends_at/);
  assert.match(management, /reason when shortening active voting/i);
  assert.match(management, /Intl\.DateTimeFormat\(\)\.resolvedOptions\(\)\.timeZone/);
  assert.match(management, /Changing the operation clears the current proposal selection/);
});

test('proposal detail uses authoritative schedule and date-time copy', () => {
  assert.match(detail, /proposal\.deliberation_end/);
  assert.match(detail, /Voting is scheduled to begin/);
  assert.match(detail, /Voting is scheduled to begin shortly/);
  assert.match(detail, /automatic transition is delayed/);
  assert.match(detail, /Voting has not been scheduled/);
  assert.match(detail, /toLocaleString\(\)/);
  assert.doesNotMatch(detail, /startMs \+ Number\(proposal\.deliberation_days\)/);
});

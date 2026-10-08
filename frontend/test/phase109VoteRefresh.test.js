import { test } from 'node:test';
import assert from 'node:assert/strict';
import { refreshProposalVote, proposalClosedAt } from '../src/utils/proposalVoteRefresh.js';

test('hidden preliminary results do not discard a successfully saved neutral override', async () => {
  const calls = [];
  const api = { async get(path) {
    calls.push(path);
    if (path.endsWith('/my-vote')) return { scores: {}, abstain: false, is_direct: true };
    throw { status: 404, message: 'Results are not visible yet' };
  } };
  const state = await refreshProposalVote(api, 'early');
  assert.deepEqual(state.myVote, { scores: {}, abstain: false, is_direct: true });
  assert.equal(state.tally, null);
  assert.equal(state.voteGraph, null);
  assert.equal(state.ballotError, null);
  assert.equal(state.resultsError, null);
  assert.equal(calls.length, 3);
});

test('failed refreshes clear stale visibility and surface genuine ballot/results errors', async () => {
  const error = { status: 503, message: 'Unavailable' };
  const state = await refreshProposalVote({ get: async () => { throw error; } }, 'vote');
  assert.equal(state.myVote, null);
  assert.equal(state.tally, null);
  assert.equal(state.voteGraph, null);
  assert.equal(state.ballotError, error);
  assert.equal(state.resultsError, error);
});

test('successful refresh retains independently returned ballot and aggregate data', async () => {
  const state = await refreshProposalVote({ get: async path => ({ path }) }, 'vote');
  assert.equal(state.myVote.path, '/api/proposals/vote/my-vote');
  assert.equal(state.tally.path, '/api/proposals/vote/results');
  assert.equal(state.voteGraph.path, '/api/proposals/vote/vote-graph');
});

test('experimental closing date uses frozen actual closure and preserves legacy display', () => {
  const proposal = { voting_method: 'star', voting_end: '2026-10-15T12:00:00Z' };
  const tally = { method_result: { closed_at: '2026-10-08T12:00:00Z' } };
  assert.equal(proposalClosedAt(proposal, tally), '2026-10-08T12:00:00Z');
  assert.equal(proposalClosedAt(proposal, null), null);
  assert.equal(proposalClosedAt({ ...proposal, voting_method: 'approval' }, tally), proposal.voting_end);
});

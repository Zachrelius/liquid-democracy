import test from 'node:test';
import assert from 'node:assert/strict';
import {
  VOTING_METHODS, FALLBACK_ENABLED_METHODS, MAJORITY_JUDGMENT_GRADES,
  selectableVotingMethods, toggleAllowedVotingMethod, votingMethodLabel,
} from '../src/utils/votingMethods.js';

test('legacy defaults remain binary and method labels remain unchanged', () => {
  assert.deepEqual(FALLBACK_ENABLED_METHODS, ['binary']);
  assert.deepEqual(selectableVotingMethods(undefined), ['binary']);
  assert.deepEqual(['binary', 'approval', 'ranked_choice', 'budget_allocation', 'budget_project']
    .map(votingMethodLabel), ['Yes / No', 'Approval', 'Ranked choice', 'Budget allocation', 'Ranked projects']);
  assert.equal(votingMethodLabel('future_method'), 'future method');
  assert.equal(votingMethodLabel(null), 'Vote');
});

test('explicit legacy organization methods are retained without adding others', () => {
  assert.deepEqual(selectableVotingMethods({ allowed_voting_methods: ['binary', 'ranked_choice'] }),
    ['binary', 'ranked_choice']);
  assert.deepEqual(selectableVotingMethods({ allowed_voting_methods: [] }), []);
});

test('unfinished experimental methods cannot appear even in an opted-in organization', () => {
  const settings = { allowed_voting_methods: Object.keys(VOTING_METHODS) };
  assert.deepEqual(selectableVotingMethods(settings, { hasOrg: true }),
    ['binary', 'approval', 'ranked_choice', 'budget_allocation', 'budget_project', 'star']);
  for (const context of [{ hasOrg: false }, { hasOrg: true, election: true }]) {
    assert.deepEqual(selectableVotingMethods(settings, context),
      ['binary', 'approval', 'ranked_choice', 'budget_allocation', 'budget_project']);
  }
  assert.deepEqual(toggleAllowedVotingMethod(['binary'], 'score', true), ['binary']);
});

test('settings edits preserve unrelated and future method choices', () => {
  const stored = ['binary', 'approval', 'future_method'];
  assert.deepEqual(toggleAllowedVotingMethod(stored, 'approval', false), ['binary', 'future_method']);
  assert.deepEqual(toggleAllowedVotingMethod(stored, 'ranked_choice', true),
    ['binary', 'approval', 'future_method', 'ranked_choice']);
  assert.deepEqual(toggleAllowedVotingMethod(stored, 'binary', false), stored);
  assert.deepEqual(stored, ['binary', 'approval', 'future_method']);
});

test('rated ballot contracts preserve distinct methods and grade ordering', () => {
  assert.equal(VOTING_METHODS.star.ballotField, VOTING_METHODS.score.ballotField);
  assert.notEqual(VOTING_METHODS.star.ruleId, VOTING_METHODS.score.ruleId);
  assert.equal(VOTING_METHODS.ranked_pairs.ballotField, 'rank_groups');
  assert.deepEqual(MAJORITY_JUDGMENT_GRADES, ['Reject', 'Poor', 'Acceptable', 'Good', 'Very good', 'Excellent']);
});

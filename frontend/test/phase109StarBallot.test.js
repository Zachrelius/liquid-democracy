import test from 'node:test';
import assert from 'node:assert/strict';
import { ratedPayload, formatExactCount, hasRatedBallot } from '../src/utils/ratedBallot.js';

test('rated ballot preserves omitted options and distinct explicit zero', () => {
  assert.deepEqual(ratedPayload({ a: 5, b: 0 }, ['a', 'b', 'new-write-in']), { scores: { a: 5, b: 0 } });
  assert.deepEqual(ratedPayload({}, ['a', 'b']), { scores: {} });
});
test('abstaining submits no preference fields and overrides delegation', () => {
  assert.deepEqual(ratedPayload({ a: 5 }, ['a', 'b'], true), { abstain: true });
  assert.equal(hasRatedBallot({ abstain: true }), true);
  assert.equal(hasRatedBallot({ scores: {} }), true);
  assert.equal(hasRatedBallot({ scores: null, abstain: false }), false);
});
test('removed options and invalid scores cannot be silently changed at submission', () => {
  assert.throws(() => ratedPayload({ removed: 5 }, ['a', 'b']), /removed/);
  for (const value of [true, '5', 1.5, -1, 6, NaN]) {
    assert.throws(() => ratedPayload({ a: value }, ['a']), /whole number/);
  }
});
test('large aggregate values render exactly without rounding', () => {
  assert.equal(formatExactCount('900719925474099312345'), '900,719,925,474,099,312,345');
  assert.equal(formatExactCount(123), '123');
  assert.equal(formatExactCount(9007199254740992), 'Unavailable');
  assert.equal(formatExactCount(undefined), 'Unavailable');
});

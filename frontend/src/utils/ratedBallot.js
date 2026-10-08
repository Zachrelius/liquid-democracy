export function ratedPayload(scores, optionIds, abstain = false) {
  if (abstain) return { abstain: true };
  const allowed = new Set(optionIds);
  const result = {};
  for (const [id, value] of Object.entries(scores)) {
    if (!allowed.has(id)) throw new Error('An option was removed. Cancel and reopen your ballot.');
    if (!Number.isInteger(value) || value < 0 || value > 5) throw new Error('Choose a whole number from 0 to 5.');
    result[id] = value;
  }
  return { scores: result };
}

// Aggregate integers may arrive as decimal strings above Number.MAX_SAFE_INTEGER.
export function formatExactCount(value) {
  if (typeof value === 'number' && !Number.isSafeInteger(value)) return 'Unavailable';
  if (!/^-?\d+$/.test(String(value))) return 'Unavailable';
  return BigInt(value).toLocaleString('en-US');
}

export function hasRatedBallot(vote) {
  return vote?.scores != null || vote?.grades != null || vote?.abstain === true;
}

export function gradePayload(grades, optionIds, abstain = false) {
  if (abstain) return { abstain: true };
  return { grades: ratedPayload(grades, optionIds).scores };
}

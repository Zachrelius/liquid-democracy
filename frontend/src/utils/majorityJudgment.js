import { MAJORITY_JUDGMENT_GRADES } from './votingMethods.js';

export function gradeLabel(grade) {
  const value = String(grade);
  return /^[0-5]$/.test(value) ? MAJORITY_JUDGMENT_GRADES[Number(value)] : 'Unavailable';
}

// Convert only the bounded display ratio to Number; never convert share counts.
export function gradeDistributionWidths(histogram) {
  if (!Array.isArray(histogram) || histogram.length !== 6 || histogram.some(value => !/^\d+$/.test(String(value)))) return [];
  const counts = histogram.map(value => BigInt(value));
  const total = counts.reduce((sum, value) => sum + value, 0n);
  return counts.map(value => total === 0n ? 0 : Number(value * 10000n / total) / 100);
}

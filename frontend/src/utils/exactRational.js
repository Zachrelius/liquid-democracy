import { formatExactCount } from './ratedBallot.js';

export function exactRational(value) {
  const n = value?.numerator, d = value?.denominator;
  if (!/^\d+$/.test(n) || !/^\d+$/.test(d) || BigInt(d) <= 0n) return 'Unavailable';
  return d === '1' ? formatExactCount(n) : `${n}/${d}`;
}

// Presentation only: all seat decisions and stored values use exact fractions.
export function displayRational(value) {
  if (exactRational(value) === 'Unavailable') return 'Unavailable';
  if (value.denominator === '1') return formatExactCount(value.numerator);
  const n = BigInt(value.numerator), d = BigInt(value.denominator);
  const hundredths = (n * 100n + d / 2n) / d;
  return `≈ ${(hundredths / 100n).toLocaleString('en-US')}.${String(hundredths % 100n).padStart(2, '0')}`;
}

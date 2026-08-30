export function normalizeHexColor(hex) {
  const value = String(hex || '').trim();
  const short = /^#([0-9a-f]{3})$/i.exec(value);
  if (short) return `#${[...short[1]].map(char => char + char).join('')}`;
  return /^#[0-9a-f]{6}$/i.test(value) ? value : null;
}

function relativeLuminance(hex) {
  const normalized = normalizeHexColor(hex);
  if (!normalized) return null;
  const channels = [1, 3, 5].map(index => Number.parseInt(normalized.slice(index, index + 2), 16) / 255);
  const linear = channels.map(value => (
    value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4
  ));
  return (0.2126 * linear[0]) + (0.7152 * linear[1]) + (0.0722 * linear[2]);
}

export function contrastRatio(first, second) {
  const a = relativeLuminance(first);
  const b = relativeLuminance(second);
  if (a == null || b == null) return null;
  return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
}

function rgbToHex(channels) {
  return `#${channels.map(value => Math.round(value).toString(16).padStart(2, '0')).join('')}`;
}

/** Choose whichever of black or white gives stronger text contrast. */
export function contrastTextColor(background) {
  const luminance = relativeLuminance(background);
  if (luminance == null) return '#ffffff';
  const whiteContrast = 1.05 / (luminance + 0.05);
  const blackContrast = (luminance + 0.05) / 0.05;
  return whiteContrast >= blackContrast ? '#ffffff' : '#000000';
}

/**
 * Preserve an accent's hue while darkening it enough for normal-size text on
 * the platform's lightest tinted surfaces. Background uses blue-50, which is
 * slightly more demanding than plain white for dark foreground colors.
 */
export function accessibleAccentTextColor(accent, minimum = 4.5) {
  const normalized = normalizeHexColor(accent);
  if (!normalized) return '#25639b';
  const background = '#eff6ff';
  if (contrastRatio(normalized, background) >= minimum) return normalized.toLowerCase();

  const channels = [1, 3, 5].map(index => Number.parseInt(normalized.slice(index, index + 2), 16));
  for (let step = 19; step >= 0; step -= 1) {
    const candidate = rgbToHex(channels.map(value => value * (step / 20)));
    if (contrastRatio(candidate, background) >= minimum) return candidate;
  }
  return '#000000';
}

/** Return a validated color as rgba(), or null for malformed input. */
export function hexWithAlpha(hex, alpha) {
  const normalized = normalizeHexColor(hex);
  if (!normalized || !Number.isFinite(alpha)) return null;
  const channels = [1, 3, 5].map(index => (
    Number.parseInt(normalized.slice(index, index + 2), 16)
  ));
  return `rgba(${channels.join(', ')}, ${Math.min(1, Math.max(0, alpha))})`;
}

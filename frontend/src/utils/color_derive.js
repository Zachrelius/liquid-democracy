// Phase 12.7 F3 — color derivation utilities for org branding.
//
// HSL is the right color space for "lighter / darker version of a color"
// because it preserves hue and saturation, only modifying perceived
// brightness. Delta of ~10-15 in lightness is roughly one perceived shade
// step in CSS — large enough to read distinctly, small enough to stay in
// the same brand family.
//
// Used by:
//   - F2 theme application: deriveDarker(primary) -> --brand-primary-dark
//     (mobile menu / hover states), so stewards only configure primary
//     and accent, not the dark shade.
//   - F4 Org Settings branding section: getDerivedAccent(primary) drives
//     the auto-derived accent preview when the "Use auto-derived accent"
//     checkbox is on. The derived value is what the frontend submits to
//     PATCH /api/orgs/{slug}/branding.accent_color, per spec D3 line 46:
//     backend stores whatever the frontend computes; no server-side HSL.

function clamp(n, lo, hi) {
  return Math.max(lo, Math.min(hi, n));
}

// Hex -> [h, s, l] where h is 0-360, s/l are 0-100.
// Accepts #RRGGBB or #RGB. Returns [0, 0, 0] for invalid input rather than
// throwing — color derivation is a UI nicety; a malformed hex shouldn't
// crash the branding section.
function hexToHsl(hex) {
  if (typeof hex !== 'string') return [0, 0, 0];
  let h = hex.trim().replace(/^#/, '');
  if (h.length === 3) {
    h = h.split('').map((c) => c + c).join('');
  }
  if (!/^[0-9a-fA-F]{6}$/.test(h)) return [0, 0, 0];
  const r = parseInt(h.slice(0, 2), 16) / 255;
  const g = parseInt(h.slice(2, 4), 16) / 255;
  const b = parseInt(h.slice(4, 6), 16) / 255;
  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  const l = (max + min) / 2;
  let s = 0;
  let hue = 0;
  if (max !== min) {
    const d = max - min;
    s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
    switch (max) {
      case r:
        hue = (g - b) / d + (g < b ? 6 : 0);
        break;
      case g:
        hue = (b - r) / d + 2;
        break;
      case b:
        hue = (r - g) / d + 4;
        break;
      default:
        hue = 0;
    }
    hue *= 60;
  }
  return [Math.round(hue), Math.round(s * 100), Math.round(l * 100)];
}

// HSL (h: 0-360, s: 0-100, l: 0-100) -> #RRGGBB.
function hslToHex(h, s, l) {
  const sn = clamp(s, 0, 100) / 100;
  const ln = clamp(l, 0, 100) / 100;
  const hn = ((h % 360) + 360) % 360;
  const c = (1 - Math.abs(2 * ln - 1)) * sn;
  const x = c * (1 - Math.abs(((hn / 60) % 2) - 1));
  const m = ln - c / 2;
  let r1 = 0;
  let g1 = 0;
  let b1 = 0;
  if (hn < 60) {
    r1 = c; g1 = x; b1 = 0;
  } else if (hn < 120) {
    r1 = x; g1 = c; b1 = 0;
  } else if (hn < 180) {
    r1 = 0; g1 = c; b1 = x;
  } else if (hn < 240) {
    r1 = 0; g1 = x; b1 = c;
  } else if (hn < 300) {
    r1 = x; g1 = 0; b1 = c;
  } else {
    r1 = c; g1 = 0; b1 = x;
  }
  const r = Math.round((r1 + m) * 255);
  const g = Math.round((g1 + m) * 255);
  const b = Math.round((b1 + m) * 255);
  const toHex = (n) => clamp(n, 0, 255).toString(16).padStart(2, '0');
  return `#${toHex(r)}${toHex(g)}${toHex(b)}`;
}

/**
 * Return a lighter shade of `hex` by `lightenAmount` percentage points in HSL.
 * Capped at L=95 to avoid flat-white results that lose all perceived hue.
 * Defaults to 15 (the value used for getDerivedAccent and most of the F2
 * variant logic).
 */
export function deriveLighter(hex, lightenAmount = 15) {
  const [h, s, l] = hexToHsl(hex);
  return hslToHex(h, s, Math.min(95, l + lightenAmount));
}

/**
 * Return a darker shade of `hex` by `darkenAmount` percentage points in HSL.
 * Floored at L=5 to avoid pure-black results. Default 10 matches the legacy
 * platform palette where #1B3A5C (primary) and #152d4a (mobile menu /
 * hover dark) are about 10 L apart in HSL.
 */
export function deriveDarker(hex, darkenAmount = 10) {
  const [h, s, l] = hexToHsl(hex);
  return hslToHex(h, s, Math.max(5, l - darkenAmount));
}

/**
 * Convenience wrapper used by the Branding settings section: when the
 * "Use auto-derived accent" checkbox is on, the displayed and submitted
 * accent value is deriveLighter(primary, 15).
 */
export function getDerivedAccent(primaryHex) {
  return deriveLighter(primaryHex, 15);
}

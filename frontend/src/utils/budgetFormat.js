// Budget amount formatting with a configurable unit (Phase 76a).
//
// Budget proposals carry a `budget_config.currency` value. Historically this
// was an ISO 4217 currency code (defaulting to "USD") rendered via
// Intl.NumberFormat. We now also let authors set a free-text unit label
// ("pesos", "credits", "thousand", "€", "₱", …) so amounts read in whatever
// terms the group uses. Display is purely cosmetic — it never changes the math.
//
// Rules, in order:
//   1. No unit set → default to "$" prefix (legacy behavior).
//   2. Unit is a valid ISO currency code (USD, MXN, EUR…) → Intl formatting,
//      so existing budget proposals keep "$1,000" / "MX$1,000" exactly.
//   3. Otherwise treat the unit as a literal label and place it smartly:
//      short symbols (≤2 chars) hug the number as a prefix ("$1,000"),
//      longer words trail as a suffix ("1,000 pesos").

export function formatBudget(amount, unit) {
  const n = Number(amount) || 0;
  const u = (unit ?? '').trim();
  if (u) {
    try {
      return new Intl.NumberFormat(undefined, {
        style: 'currency',
        currency: u,
        maximumFractionDigits: 0,
      }).format(n);
    } catch {
      // Not an ISO currency code — render as a literal unit label.
      const num = Math.round(n).toLocaleString();
      return u.length <= 2 ? `${u}${num}` : `${num} ${u}`;
    }
  }
  return `$${Math.round(n).toLocaleString()}`;
}

/**
 * The leading symbol to show inside an amount input, when one fits. Returns a
 * short symbol ("$", "€", "₱") or '' when the unit is a word (in which case the
 * surrounding copy carries the unit instead). Used for input adornments.
 */
export function unitInputSymbol(unit) {
  const u = (unit ?? '').trim();
  if (!u || u.toUpperCase() === 'USD') return '$';
  return u.length <= 2 ? u : '';
}

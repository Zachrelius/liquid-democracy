/**
 * Phase 52 Stage 1 — plain-language labels for verification state
 * codes and structured-403 payloads.
 *
 * Backend state codes never leak into rendered FE copy
 * (the Phase 49a C2 "no internal-name leakage in user-visible
 * strings" rule). Every Phase-52 FE surface that needs to render a
 * verification state or a structured-403 detail funnels through
 * this module — keep the label tables in one place so a future
 * copy change is a one-file edit.
 */
import { countryName } from './utils/countries';

// Long labels intentionally spell out what was verified (a government
// ID was confirmed for the account) so the badge doesn't overclaim —
// we don't currently check that the user's display name matches the
// ID name, only that the ID is valid + linked to this account. A
// future phase may add a display-name-match option (see backlog).
export const VERIFICATION_STATE_LABELS = {
  email_only: 'Email only (no extra verification)',
  identity: 'Identity verified — a government ID was confirmed for this account',
  identity_unique: 'Identity verified — a government ID was confirmed for this account, and this ID has not been used on another account',
  address_on_id: 'Identity verified — a government ID was confirmed for this account, with an address on it',
  residency_verified: 'Identity verified — residency confirmed against a government ID for this account',
};

export const VERIFICATION_STATE_SHORT_LABELS = {
  email_only: 'Email only',
  identity: 'Identity',
  identity_unique: 'Unique person',
  address_on_id: 'Address on ID',
  residency_verified: 'Residency',
};

// Phase 52j J2 — collapsed to the three meaningful tiers (Z-locked
// relabel; backend ladder UNCHANGED so any stored stale value still
// resolves through labelForState). Membership + role floor dropdowns
// and the proposal-floor dropdown all read from this list.
export const VERIFICATION_STATE_OPTIONS = [
  { value: '', label: 'No verification required (default)' },
  { value: 'identity', label: 'Identity verified' },
  { value: 'address_on_id', label: 'Verified resident' },
];

export const VERIFICATION_PROVENANCE_LABELS = {
  none: '',
  persona: 'Verified via our identity provider',
  didit: 'Verified via our identity provider',
  demo_stub: 'Demo stub (not a real verification)',
  backdoor: 'Set by a platform administrator',
};

export function labelForState(state) {
  return VERIFICATION_STATE_LABELS[state] || VERIFICATION_STATE_LABELS.email_only;
}

export function shortLabelForState(state) {
  return VERIFICATION_STATE_SHORT_LABELS[state] || VERIFICATION_STATE_SHORT_LABELS.email_only;
}

/**
 * Render a "verify to {scope}" CTA copy from a structured-403 detail
 * payload (the backend's verification_required_payload shape:
 *   { error: 'verification_required', floor, jurisdiction, scope }
 * ). Returns null if the payload isn't a verification-required one.
 */
export function ctaCopyForVerificationRequired(detail) {
  if (!detail || detail.error !== 'verification_required') return null;
  // Phase 52g — min_age scope returns a different copy shape (no
  // floor / no jurisdiction; just the threshold).
  if (detail.scope === 'min_age') {
    const threshold = detail.min_age;
    if (!threshold) return null;
    return `This organization requires members to be ${threshold}+. Your verified age band doesn't meet that minimum.`;
  }
  // Phase 52i — locality scope (city-level residency gate).
  // ``locality_city`` is the readable admin-configured value; the
  // member's city is hashed, never displayed.
  if (detail.scope === 'locality') {
    const city = detail.locality_city || 'the required city';
    const state = detail.locality_state ? `, ${detail.locality_state}` : '';
    return `This organization requires members to be verified residents of ${city}${state}.`;
  }
  // Phase 52j J1 — residency-scope scope (org-level list of allowed
  // (state, city?) localities, OR-matched). The detail carries the
  // readable scope so the CTA names the places.
  if (detail.scope === 'residency_scope') {
    const scope = Array.isArray(detail.residency_scope) ? detail.residency_scope : [];
    if (!scope.length) {
      return "This organization requires members to be a verified resident of an allowed location.";
    }
    const labels = scope.map(e => {
      if (e && e.city) return `${e.city}, ${e.state}`;
      if (e && e.state) return e.state;
      // Phase 76c — country-level entry (no US state). Name the country.
      if (e && e.country) return countryName(e.country);
      return null;
    }).filter(Boolean);
    if (!labels.length) {
      return "This organization requires members to be a verified resident of an allowed location.";
    }
    const list = labels.length === 1
      ? labels[0]
      : labels.length === 2
        ? `${labels[0]} or ${labels[1]}`
        : `${labels.slice(0, -1).join(', ')}, or ${labels[labels.length - 1]}`;
    return `This organization requires members to be a verified resident of ${list}.`;
  }
  const floorLabel = labelForState(detail.floor);
  const jurisdictionSuffix = detail.jurisdiction ? ` (${detail.jurisdiction})` : '';
  const scopeCopy = {
    membership: 'join this organization',
    role: 'hold this role in this organization',
    vote: 'cast a vote on this proposal',
    delegate: 'become a public delegate in this organization',
  }[detail.scope] || 'continue';
  return `To ${scopeCopy}, your account needs: ${floorLabel}${jurisdictionSuffix}. Open Settings to start verification.`;
}

/**
 * Phase 52f — copy for the ``name_match_required`` 422 when an org's
 * display-name-match setting is on and the candidate name doesn't
 * match the legal name on file. Mode tells the user what part must
 * match.
 */
export function copyForNameMatchRequired(detail) {
  if (!detail || detail.error !== 'name_match_required') return null;
  const part = {
    first: 'first name',
    last: 'last name',
    full: 'full name',
  }[detail.mode] || 'name';
  return `This organization requires your display name to match the ${part} on your ID.`;
}

/**
 * Phase 52h Stage 2 — up-front expectation copy shown before a
 * user leaves for the verification provider. The platform-wide
 * "one account per person" claim shipped in Phase 52e Stage 2 was
 * RETIRED here when the document-number hard block was removed:
 * the platform no longer enforces cross-org uniqueness (the locked
 * principle is confidence-determines-scope + org-scoped harm), so
 * claiming it would be a copy lie. The honest framing is per-org —
 * an org may flag or limit duplicate members within its own
 * approval queue.
 */
export const UP_FRONT_ONE_IDENTITY_COPY =
  "Identity verification confirms who you are. Each organization " +
  "may have its own rules about duplicate members; if your verified " +
  "identity matches another member of the same organization, that " +
  "organization's admin can review and decide.";

/**
 * Best-effort detection of a verification-required error from a
 * fetch-style rejection. The api client wraps responses as objects
 * carrying ``detail`` (parsed JSON) or sometimes ``response.data``;
 * this normalizes both.
 */
export function extractVerificationRequiredDetail(error) {
  if (!error) return null;
  const candidates = [
    error.detail,
    error?.response?.data?.detail,
    error?.body?.detail,
  ];
  for (const c of candidates) {
    if (c && typeof c === 'object' && c.error === 'verification_required') {
      return c;
    }
  }
  return null;
}

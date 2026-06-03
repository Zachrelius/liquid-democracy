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

export const VERIFICATION_STATE_LABELS = {
  email_only: 'Email only (no extra verification)',
  identity: 'Identity verified',
  identity_unique: 'Identity verified — unique person',
  address_on_id: 'Identity verified — address on ID',
  residency_verified: 'Identity verified — residency confirmed',
};

export const VERIFICATION_STATE_SHORT_LABELS = {
  email_only: 'Email only',
  identity: 'Identity',
  identity_unique: 'Unique person',
  address_on_id: 'Address on ID',
  residency_verified: 'Residency',
};

export const VERIFICATION_STATE_OPTIONS = [
  { value: '', label: 'No verification required (default)' },
  { value: 'identity', label: VERIFICATION_STATE_LABELS.identity },
  { value: 'identity_unique', label: VERIFICATION_STATE_LABELS.identity_unique },
  { value: 'address_on_id', label: VERIFICATION_STATE_LABELS.address_on_id },
  { value: 'residency_verified', label: VERIFICATION_STATE_LABELS.residency_verified },
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
  const floorLabel = labelForState(detail.floor);
  const jurisdictionSuffix = detail.jurisdiction ? ` (${detail.jurisdiction})` : '';
  const scopeCopy = {
    membership: 'join this organization',
    role: 'hold this role in this organization',
    vote: 'cast a vote on this proposal',
  }[detail.scope] || 'continue';
  return `To ${scopeCopy}, your account needs: ${floorLabel}${jurisdictionSuffix}. Open Settings to start verification.`;
}

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

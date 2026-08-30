const ADDRESS_FLOORS = new Set(['address_on_id', 'residency_verified']);
const VALID_ALWAYS_FLOORS = new Set([
  'identity', 'address_on_id', 'residency_verified',
]);
const VALID_US_JURISDICTIONS = new Set([
  'AL', 'AK', 'AZ', 'AR', 'CA', 'CO', 'CT', 'DE', 'FL', 'GA',
  'HI', 'ID', 'IL', 'IN', 'IA', 'KS', 'KY', 'LA', 'ME', 'MD',
  'MA', 'MI', 'MN', 'MS', 'MO', 'MT', 'NE', 'NV', 'NH', 'NJ',
  'NM', 'NY', 'NC', 'ND', 'OH', 'OK', 'OR', 'PA', 'RI', 'SC',
  'SD', 'TN', 'TX', 'UT', 'VT', 'VA', 'WA', 'WV', 'WI', 'WY',
  'DC',
]);

export function validateProposalVerificationPolicy(settings = {}) {
  if (settings.verification_proposal_policy !== 'always') return {};
  const floor = settings.verification_proposal_floor;
  if (!VALID_ALWAYS_FLOORS.has(floor)) {
    return {
      verification_proposal_floor:
        'Choose a verification floor above email-only.',
    };
  }
  if (ADDRESS_FLOORS.has(floor)) {
    const jurisdiction = String(
      settings.verification_proposal_jurisdiction || '',
    ).trim().toUpperCase();
    if (!VALID_US_JURISDICTIONS.has(jurisdiction)) {
      return {
        verification_proposal_jurisdiction:
          'Choose a valid U.S. state or District of Columbia code.',
      };
    }
  }
  return {};
}

export function proposalPolicyErrorsFromApi(error) {
  const detail = error?.raw?.detail;
  if (
    detail?.error === 'invalid_proposal_verification_policy'
    && detail.fields
    && typeof detail.fields === 'object'
    && !Array.isArray(detail.fields)
  ) {
    return detail.fields;
  }
  return {};
}

const VALID_US_JURISDICTIONS = new Set([
  'AL', 'AK', 'AZ', 'AR', 'CA', 'CO', 'CT', 'DE', 'FL', 'GA',
  'HI', 'ID', 'IL', 'IN', 'IA', 'KS', 'KY', 'LA', 'ME', 'MD',
  'MA', 'MI', 'MN', 'MS', 'MO', 'MT', 'NE', 'NV', 'NH', 'NJ',
  'NM', 'NY', 'NC', 'ND', 'OH', 'OK', 'OR', 'PA', 'RI', 'SC',
  'SD', 'TN', 'TX', 'UT', 'VT', 'VA', 'WA', 'WV', 'WI', 'WY',
  'DC',
]);

export const VISIBLE_REQUIREMENT_OPTIONS = [
  { value: 'none', label: 'No verification required' },
  { value: 'identity', label: 'Identity verified' },
  { value: 'resident', label: 'Verified resident of the allowed locations' },
];

export function storedRequirementChoice(floor, requireResidency) {
  if (!floor || floor === 'email_only') return requireResidency ? 'legacy' : 'none';
  if (floor === 'identity' && !requireResidency) return 'identity';
  if (floor === 'address_on_id' && requireResidency === true) return 'resident';
  return 'legacy';
}

export function requirementStorage(choice) {
  if (choice === 'none') return { floor: null, requireResidency: false };
  if (choice === 'identity') return { floor: 'identity', requireResidency: false };
  if (choice === 'resident') return { floor: 'address_on_id', requireResidency: true };
  return null;
}

export function proposalPolicyChoice(settings = {}) {
  const policy = settings.verification_proposal_policy;
  if (policy === 'never') return 'never';
  if (!policy || policy === 'author') return 'author';
  if (policy !== 'always') return 'legacy';
  const requirement = storedRequirementChoice(
    settings.verification_proposal_floor,
    settings.verification_proposal_require_residency,
  );
  return requirement === 'identity' ? 'always_identity'
    : requirement === 'resident' ? 'always_resident' : 'legacy';
}

export function proposalPolicyStorage(choice) {
  if (choice === 'never') return {
    verification_proposal_policy: 'never',
    verification_proposal_require_residency: false,
  };
  if (choice === 'author') return {
    verification_proposal_policy: 'author',
    verification_proposal_require_residency: false,
  };
  if (choice === 'always_identity') return {
    verification_proposal_policy: 'always',
    verification_proposal_floor: 'identity',
    verification_proposal_require_residency: false,
    verification_proposal_jurisdiction: null,
  };
  if (choice === 'always_resident') return {
    verification_proposal_policy: 'always',
    verification_proposal_floor: 'address_on_id',
    verification_proposal_require_residency: true,
    verification_proposal_jurisdiction: null,
  };
  return null;
}

function hasValidResidencyScope(scope) {
  return Array.isArray(scope) && scope.some(entry => {
    if (!entry || typeof entry !== 'object') return false;
    const country = String(entry.country || 'US').trim().toUpperCase();
    if (!SUPPORTED_COUNTRIES.has(country)) return false;
    if (country !== 'US') return true;
    const state = String(entry.state || '').trim().toUpperCase();
    if (!state) return !String(entry.city || '').trim();
    if (!VALID_US_JURISDICTIONS.has(state)) return false;
    return true;
  });
}

export function validateProposalVerificationPolicy(settings = {}) {
  if (proposalPolicyChoice(settings) === 'legacy') return {};
  if (settings.verification_proposal_policy !== 'always') return {};
  if (settings.verification_proposal_floor === 'address_on_id'
      && settings.verification_proposal_require_residency === true
      && !hasValidResidencyScope(settings.verification_residency_scope)) {
    return {
      verification_residency_scope: 'Add at least one valid allowed residency location.',
    };
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

export function verificationSettingsErrorFromApi(error) {
  const detail = error?.raw?.detail;
  if (!detail || typeof detail !== 'object' || Array.isArray(detail)) return null;
  if (detail.error === 'invalid_verification_settings') {
    return {
      fields: detail.fields && typeof detail.fields === 'object' ? detail.fields : {},
      conflict: null,
    };
  }
  if (detail.error === 'public_delegate_name_policy_conflict') {
    return {
      fields: {},
      conflict: {
        total: Number(detail.total || detail.total_count || detail.count || 0),
        items: Array.isArray(detail.items) ? detail.items : [],
      },
    };
  }
  return null;
}
import { COUNTRIES } from './countries.js';

const SUPPORTED_COUNTRIES = new Set(COUNTRIES.map(country => country.code));

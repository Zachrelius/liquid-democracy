import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

import {
  proposalPolicyChoice,
  proposalPolicyStorage,
  proposalPolicyErrorsFromApi,
  validateProposalVerificationPolicy,
} from '../src/utils/proposalVerificationPolicy.js';

const settingsSource = readFileSync(
  new URL('../src/pages/admin/OrgSettings.jsx', import.meta.url), 'utf8',
);

test('Phase 105 proposal policy maps coherent choices and validates shared residency', () => {
  assert.deepEqual(proposalPolicyStorage('always_identity'), {
    verification_proposal_policy: 'always',
    verification_proposal_floor: 'identity',
    verification_proposal_require_residency: false,
    verification_proposal_jurisdiction: null,
  });
  const resident = {
    ...proposalPolicyStorage('always_resident'),
    verification_residency_scope: [{ country: 'US', state: 'MA' }],
  };
  assert.equal(proposalPolicyChoice(resident), 'always_resident');
  assert.deepEqual(validateProposalVerificationPolicy(resident), {});
  assert.ok(validateProposalVerificationPolicy({
    ...resident, verification_residency_scope: [{ country: 'ZZ' }],
  }).verification_residency_scope);
  assert.deepEqual(validateProposalVerificationPolicy({
    verification_proposal_policy: 'always',
    verification_proposal_floor: 'identity',
  }), {});
  assert.equal(proposalPolicyChoice({
    verification_proposal_policy: 'always',
    verification_proposal_floor: 'address_on_id',
    verification_proposal_jurisdiction: 'MA',
  }), 'legacy');
});

test('structured backend policy errors are extracted without assuming shape', () => {
  const fields = { verification_proposal_floor: 'Choose a floor.' };
  assert.deepEqual(proposalPolicyErrorsFromApi({
    raw: { detail: { error: 'invalid_proposal_verification_policy', fields } },
  }), fields);
  assert.deepEqual(proposalPolicyErrorsFromApi({ raw: { detail: 'invalid' } }), {});
  assert.deepEqual(proposalPolicyErrorsFromApi(null), {});
});

test('organization settings blocks save, focuses first error, and exposes accessible feedback', () => {
  const proposalPolicySection = settingsSource.slice(
    settingsSource.indexOf('Phase 52j J3 / Phase 95'),
    settingsSource.indexOf('Multi-Admin Approval — Phase 44'),
  );
  assert.match(settingsSource, /validateProposalVerificationPolicy\(settings\)/);
  assert.match(settingsSource, /focusRef\.current\?\.focus\(\)/);
  assert.match(settingsSource, /proposalPolicyErrorsFromApi\(e\)/);
  assert.match(proposalPolicySection, /Who must verify to vote on proposals/);
  assert.match(proposalPolicySection, /Verified resident for every proposal/);
  assert.match(proposalPolicySection, /aria-invalid=/);
  assert.match(proposalPolicySection, /role="alert"/);
  assert.match(proposalPolicySection, /No proposal-level verification/);
  assert.doesNotMatch(proposalPolicySection, /Required jurisdiction/);
});

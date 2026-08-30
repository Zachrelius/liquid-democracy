import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

import {
  proposalPolicyErrorsFromApi,
  validateProposalVerificationPolicy,
} from '../src/utils/proposalVerificationPolicy.js';

const settingsSource = readFileSync(
  new URL('../src/pages/admin/OrgSettings.jsx', import.meta.url), 'utf8',
);

test('always policy requires a real floor and jurisdiction for address gates', () => {
  assert.ok(validateProposalVerificationPolicy({
    verification_proposal_policy: 'always',
  }).verification_proposal_floor);
  assert.ok(validateProposalVerificationPolicy({
    verification_proposal_policy: 'always',
    verification_proposal_floor: 'email_only',
  }).verification_proposal_floor);
  assert.ok(validateProposalVerificationPolicy({
    verification_proposal_policy: 'always',
    verification_proposal_floor: 'address_on_id',
  }).verification_proposal_jurisdiction);
  assert.deepEqual(validateProposalVerificationPolicy({
    verification_proposal_policy: 'always',
    verification_proposal_floor: 'address_on_id',
    verification_proposal_jurisdiction: 'ma',
  }), {});
  assert.deepEqual(validateProposalVerificationPolicy({
    verification_proposal_policy: 'always',
    verification_proposal_floor: 'identity',
  }), {});
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
  assert.match(settingsSource, /firstInvalid\.current\?\.focus\(\)/);
  assert.match(settingsSource, /proposalPolicyErrorsFromApi\(e\)/);
  assert.match(proposalPolicySection, /Required floor for every proposal/);
  assert.match(proposalPolicySection, /Required jurisdiction/);
  assert.match(proposalPolicySection, /aria-invalid=/);
  assert.match(proposalPolicySection, /role="alert"/);
  assert.match(proposalPolicySection, /Select a required floor/);
  assert.doesNotMatch(proposalPolicySection, /No verification required<\/option>/);
});

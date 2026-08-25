import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

import {
  extractVerificationRequiredDetail,
  formatMembershipVerificationRequirements,
} from '../src/verificationLabels.js';

function source(relativePath) {
  return readFileSync(new URL(`../src/${relativePath}`, import.meta.url), 'utf8');
}

test('canonical api raw-detail envelope is extracted safely', () => {
  const detail = { error: 'verification_required', scope: 'membership' };
  assert.equal(extractVerificationRequiredDetail({ status: 403, raw: { detail } }), detail);
  assert.equal(extractVerificationRequiredDetail({ status: 403, raw: { detail: 'denied' } }), null);
  assert.equal(extractVerificationRequiredDetail({ status: 403, raw: { error: 'other' } }), null);
});

test('identity-only membership requirement stays plain language', () => {
  const result = formatMembershipVerificationRequirements({
    error: 'verification_required',
    membership_requirements: {
      floor: 'identity', requires_residency: false, residency_scope: [], min_age: null,
    },
  });
  assert.deepEqual(result.requirements, ['A government-issued ID is required.']);
});

test('state and city residency rules use grammatical readable lists', () => {
  const result = formatMembershipVerificationRequirements({
    error: 'verification_required',
    membership_requirements: {
      floor: 'address_on_id',
      requires_residency: true,
      residency_scope: [
        { city: 'Boston', state: 'ma', country: null },
        { city: 'Somerville', state: 'MA', country: null },
        { country: 'CA', state: null, city: null },
      ],
    },
  });
  assert.equal(
    result.requirements[1],
    'Your verified ID address must be in Boston, Massachusetts, Somerville, Massachusetts, or Canada.',
  );
  assert.ok(result.requirements.every(line => !/address_on_id|residency_scope/.test(line)));
});

test('minimum age, legacy jurisdiction, and malformed fallback remain truthful', () => {
  const legacy = formatMembershipVerificationRequirements({
    error: 'verification_required', floor: 'address_on_id', jurisdiction: 'MA', min_age: 18,
  });
  assert.ok(legacy.requirements.includes('Your verified ID address must be in Massachusetts.'));
  assert.ok(legacy.requirements.includes('You must be at least 18 years old based on your verification.'));
  assert.deepEqual(
    formatMembershipVerificationRequirements(null).requirements,
    ['Identity verification is required.'],
  );
});

test('public landing opens the dialog only for structured verification denials', () => {
  const landing = source('pages/OrgPublicLanding.jsx');
  assert.match(landing, /setVerificationDialogDetail\(vDetail\)/);
  assert.match(landing, /if \(vDetail\)[\s\S]*?else \{[\s\S]*?toast\.error/);
  assert.doesNotMatch(landing, /toast\.error\(cta/);
  assert.match(landing, /navigate\('\/settings#identity-verification'\)/);
});

test('verification join dialog preserves the accessible modal contract', () => {
  const dialog = source('components/VerificationJoinDialog.jsx');
  assert.match(dialog, /useModalDialog\(\{ open, onClose, initialFocusRef: primaryRef \}\)/);
  assert.match(dialog, /role="dialog"/);
  assert.match(dialog, /aria-modal="true"/);
  assert.match(dialog, /aria-labelledby="verification-join-dialog-title"/);
  assert.match(dialog, /aria-describedby="verification-join-dialog-description"/);
  assert.match(dialog, />\s*Go to identity verification\s*</);
  assert.match(dialog, />\s*Not now\s*</);
});

test('Didit privacy link is isolated and primary action stays in-app', () => {
  const dialog = source('components/VerificationJoinDialog.jsx');
  assert.match(dialog, /href="https:\/\/didit\.me\/terms\/privacy-policy\/"/);
  assert.match(dialog, /target="_blank"/);
  assert.match(dialog, /rel="noopener noreferrer"/);
  assert.doesNotMatch(dialog, /didit\.me\/(?:login|signup)/i);
});

test('settings exposes an anchored, confirmed update path while sealing demos', () => {
  const settings = source('pages/Settings.jsx');
  assert.match(settings, /id="identity-verification"/);
  assert.match(settings, /scrollIntoView/);
  assert.match(settings, /sectionRef\.current\?\.focus/);
  assert.match(settings, /isDemoStub = user\?\.verification_provenance === 'demo_stub'/);
  assert.match(settings, /isFullyVerified \? 'Update verification' : 'Start verification'/);
  assert.match(settings, /title: 'Update identity verification\?'/);
  assert.match(settings, /use verification capacity/);
  assert.match(settings, /if \(!ok\) return;[\s\S]*?api\.post\('\/api\/verification\/session'/);
});

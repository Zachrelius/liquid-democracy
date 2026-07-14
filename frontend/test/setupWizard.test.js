import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

import {
  parseInvitationEmails,
  pendingSelectedTopics,
  slugifyOrganizationName,
} from '../src/utils/setupWizard.js';

test('organization slugs are normalized and capped', () => {
  assert.equal(slugifyOrganizationName(' Cedar Hollow HOA! '), 'cedar-hollow-hoa');
  assert.equal(slugifyOrganizationName('A'.repeat(80)).length, 50);
});

test('invitation parsing normalizes, deduplicates, and reports malformed lines', () => {
  const parsed = parseInvitationEmails(
    ' Alice@Example.com\ninvalid\nalice@example.com\n bob@example.org ',
  );
  assert.deepEqual(parsed.valid, ['alice@example.com', 'bob@example.org']);
  assert.deepEqual(parsed.invalid, ['invalid']);
});

test('topic retry excludes server-existing and locally completed topics', () => {
  const topics = [
    { name: 'General', checked: true },
    { name: 'Budget', checked: true },
    { name: 'Policy', checked: true },
    { name: 'Operations', checked: false },
  ];
  assert.deepEqual(
    pendingSelectedTopics(topics, ['general'], ['BUDGET']).map(topic => topic.name),
    ['Policy'],
  );
});

test('organization creation continues into the resumable onboarding route', () => {
  const createOrg = readFileSync(
    new URL('../src/pages/CreateOrg.jsx', import.meta.url),
    'utf8',
  );
  const wizard = readFileSync(
    new URL('../src/pages/SetupWizard.jsx', import.meta.url),
    'utf8',
  );

  assert.match(createOrg, /navigate\(`\/setup\?org=/);
  assert.match(wizard, /searchParams\.get\('org'\)/);
  assert.doesNotMatch(wizard, /onClick=\{\(\) => setStep\(0\)\}/);
  assert.match(wizard, /Create your first proposal/);
});

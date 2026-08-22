import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

function source(relativePath) {
  return readFileSync(new URL(`../src/${relativePath}`, import.meta.url), 'utf8');
}

test('pilot is a fixed public route registered before the org catch-all', () => {
  const app = source('App.jsx');
  const pilotRoute = app.indexOf('path="/pilot"');
  const orgCatchAll = app.indexOf('path="/:org_slug"');

  assert.ok(pilotRoute >= 0, 'the direct /pilot route must exist');
  assert.ok(orgCatchAll > pilotRoute, 'the fixed route must win before the org-slug route');
  assert.match(app, /import Pilot from '\.\/pages\/Pilot';/);
});

test('pilot preview carries the approved offer, actions, and trust boundaries', () => {
  const pilot = source('pages/Pilot.jsx');

  for (const claim of [
    'Supported organizational pilots',
    'Pilot Liquid Democracy with your organization',
    'supported, no-cost pilot',
    'roughly 20–200 members',
    'no preset end date',
    'Not a certified public-election system',
    'Honest boundaries, tested recovery',
    'No pilot organization will be charged later without advance discussion and express agreement',
  ]) {
    assert.match(pilot, new RegExp(claim.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
  }

  assert.match(pilot, /mailto:support@liquiddemocracy\.us\?subject=Pilot%20conversation/);
  assert.match(pilot, /to="\/demo"/);
  assert.doesNotMatch(pilot, /<form\b|<iframe\b|youtube|google\.com/i);
});

test('pilot metadata is noindex and restores pre-existing head state', () => {
  const pilot = source('pages/Pilot.jsx');

  assert.match(pilot, /robots\.setAttribute\('content', 'noindex,nofollow'\)/);
  assert.match(pilot, /document\.title = 'Supported organizational pilots \| Liquid Democracy'/);
  assert.match(pilot, /document\.title = previousTitle/);
  assert.match(pilot, /description\.remove\(\)/);
  assert.match(pilot, /robots\.remove\(\)/);
});

test('preview remains isolated from every public and authenticated navigation surface', () => {
  for (const file of [
    'pages/Landing.jsx',
    'components/PublicLayout.jsx',
    'pages/About.jsx',
    'pages/Security.jsx',
    'components/Nav.jsx',
  ]) {
    assert.doesNotMatch(source(file), /["'`]\/pilot(?:["'`?#]|$)/, `${file} must not promote /pilot`);
  }
});

test('privacy and terms use shared public chrome and approved hosted-service copy', () => {
  const privacy = source('pages/Privacy.jsx');
  const terms = source('pages/Terms.jsx');

  for (const page of [privacy, terms]) {
    assert.match(page, /<PublicLayout>/);
    assert.match(page, /August 22, 2026/);
    assert.match(page, /support@liquiddemocracy\.us/);
    assert.doesNotMatch(page, /template (?:policy |)for self-hosted|infrastructure controlled by your organization/i);
    assert.doesNotMatch(page, /youtube|google\/youtube|google privacy/i);
  }

  assert.match(privacy, /restricted platform-admin API/);
  assert.match(privacy, /does not include a complete self-service account or organization export/);
  assert.match(terms, /not a certified public-election system/);
  assert.match(terms, /no preset end date/);
  assert.match(terms, /without a separate written commitment/);
});

test('about and security no longer claim demo-era adoption or routine ballot access', () => {
  const about = source('pages/About.jsx');
  const security = source('pages/Security.jsx');

  assert.match(about, /ready for its first\s+supported external pilots/);
  assert.doesNotMatch(about, /in pilot use by\s+real organizations/);
  assert.match(about, /platform does not otherwise verify a member&apos;s age/);
  assert.match(about, /daily encrypted offsite backups/);
  assert.doesNotMatch(about, /["'`]\/pilot(?:["'`?#]|$)/);

  assert.match(security, /About this hosted pilot service/);
  assert.match(security, /ordinary platform-admin\s+screen has no ballot viewer/);
  assert.match(security, /specific unredacted audit entry only when supplied with its\s+entry ID and a written reason/);
  assert.match(security, /successful restore rehearsals/);
  assert.doesNotMatch(security, /About this demo specifically/);
  assert.doesNotMatch(security, /["'`]\/pilot(?:["'`?#]|$)/);
});

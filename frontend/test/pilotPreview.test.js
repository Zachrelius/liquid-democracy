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

test('pilot page carries the approved offer, actions, and clarified FAQ answers', () => {
  const pilot = source('pages/Pilot.jsx');
  const adminFaq = pilot.slice(
    pilot.indexOf('<Faq question="Can administrators see how members voted?">'),
    pilot.indexOf('<Faq question="Is this a legally binding election system?">'),
  );

  for (const claim of [
    'Supported organizational pilots',
    'Pilot Liquid Democracy with your organization',
    'supported, no-cost pilot',
    'roughly 20–200 members',
    'no preset end date',
    'Not a certified public-election system',
    'Honest boundaries, tested recovery',
    'No. Liquid Democracy is free to use during and after the pilot.',
    'There is no subscription fee.',
    'No. Organization administrators can see membership and aggregate results, but not individual members&apos; ballots.',
  ]) {
    assert.match(pilot, new RegExp(claim.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
  }

  assert.doesNotMatch(pilot, /No pilot organization will be charged later/);
  assert.doesNotMatch(pilot, /Keep names, logos, quotes, and results private/);
  assert.doesNotMatch(adminFaq, /reason-recorded API|audit entry|GET \/api\/admin\/audit\/ballots/i);
  assert.match(pilot, /mailto:support@liquiddemocracy\.us\?subject=Pilot%20conversation/);
  assert.match(pilot, /to="\/demo"/);
  assert.doesNotMatch(pilot, /<form\b|<iframe\b|youtube|google\.com/i);
});

test('pilot metadata is indexable and restores pre-existing title and description state', () => {
  const pilot = source('pages/Pilot.jsx');

  assert.doesNotMatch(pilot, /noindex,nofollow|meta\[name=["']robots["']\]|existingRobots|previousRobots/);
  assert.match(pilot, /document\.title = 'Supported organizational pilots \| Liquid Democracy'/);
  assert.match(pilot, /document\.title = previousTitle/);
  assert.match(pilot, /description\.remove\(\)/);
});

test('homepage promotes the pilot while shared and authenticated navigation stay bounded', () => {
  const landing = source('pages/Landing.jsx');

  assert.match(landing, /to="\/pilot"[\s\S]*Pilot your organization/);
  assert.match(landing, /to="\/pilot"[\s\S]*Explore the supported pilot/);
  assert.match(landing, /to="\/demo"/);
  assert.match(landing, /to="\/explore"/);
  assert.match(landing, /to=\{startOrgTo\}/);
  assert.match(landing, /to="\/about"/);
  assert.match(landing, /to="\/login"/);
  assert.match(landing, /Member resolutions, policy priorities, committee recommendations, and issue discussions\./);
  assert.doesNotMatch(landing, /mailto:z@liquiddemocracy\.us|2,500\+ unit tests/);
  assert.doesNotMatch(landing, /Contract ratification|officer elections|strike authorization/);

  for (const file of [
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

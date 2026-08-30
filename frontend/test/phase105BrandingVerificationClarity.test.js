import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

import {
  contrastRatio,
  hexWithAlpha,
  normalizeHexColor,
} from '../src/utils/colorContrast.js';
import {
  proposalPolicyChoice,
  proposalPolicyStorage,
  requirementStorage,
  storedRequirementChoice,
  verificationSettingsErrorFromApi,
} from '../src/utils/proposalVerificationPolicy.js';
import {
  createDisplayNameSaveCoordinator,
  displayNameSettingsPath,
  displayNameTargetFromSearch,
} from '../src/utils/displayNameEditor.js';
import {
  copyForNameMatchRequired,
  extractNameMatchRequiredDetail,
} from '../src/verificationLabels.js';

function source(relative) {
  return readFileSync(new URL(`../src/${relative}`, import.meta.url), 'utf8');
}

test('header color utility accepts both contract hex forms and derives contrast hierarchy', () => {
  assert.equal(normalizeHexColor('#abc'), '#aabbcc');
  assert.equal(normalizeHexColor('#A1B2C3'), '#A1B2C3');
  assert.equal(normalizeHexColor('gold'), null);
  assert.equal(hexWithAlpha('#fff', 0.78), 'rgba(255, 255, 255, 0.78)');
  assert.equal(contrastRatio('#000', '#fff'), 21);
  assert.ok(contrastRatio('#fff', '#ffd700') < 4.5);
});

test('three-choice mapper writes atomic floor and residency pairs and preserves legacy reads', () => {
  assert.deepEqual(requirementStorage('none'), { floor: null, requireResidency: false });
  assert.deepEqual(requirementStorage('identity'), { floor: 'identity', requireResidency: false });
  assert.deepEqual(requirementStorage('resident'), { floor: 'address_on_id', requireResidency: true });
  assert.equal(storedRequirementChoice('address_on_id', false), 'legacy');
  assert.equal(storedRequirementChoice('residency_verified', true), 'legacy');
  assert.equal(storedRequirementChoice('address_on_id', true), 'resident');
  const resident = proposalPolicyStorage('always_resident');
  assert.equal(proposalPolicyChoice(resident), 'always_resident');
  assert.equal(resident.verification_proposal_jurisdiction, null);
});

test('display-name selection is sorted by caller and stale save generations are aborted', () => {
  const orgs = [{ slug: 'beta' }, { slug: 'alpha' }];
  assert.equal(displayNameTargetFromSearch('?displayNameOrg=alpha', orgs), 'alpha');
  assert.equal(displayNameTargetFromSearch('?displayNameOrg=missing', orgs), 'default');
  assert.equal(displayNameSettingsPath('hello world'), '/settings?displayNameOrg=hello%20world#display-names');

  const coordinator = createDisplayNameSaveCoordinator();
  const first = coordinator.begin('alpha');
  const second = coordinator.begin('beta');
  assert.equal(first.signal.aborted, true);
  assert.equal(first.isCurrent(), false);
  assert.equal(second.isCurrent(), true);
  coordinator.cancel('default');
  assert.equal(second.signal.aborted, true);
  assert.equal(second.isCurrent(), false);
});

test('privacy-safe name and activation errors expose actionable public fields only', () => {
  const detail = {
    error: 'name_match_required', mode: 'either', org_slug: 'cedar',
    org_name: 'Cedar', settings_path: displayNameSettingsPath('cedar'),
  };
  assert.equal(extractNameMatchRequiredDetail({ raw: { detail } }), detail);
  assert.match(copyForNameMatchRequired(detail), /Cedar.*first or last name/);
  assert.doesNotMatch(JSON.stringify(detail), /legal_name|address|date_of_birth|provider/i);

  const conflict = verificationSettingsErrorFromApi({ raw: { detail: {
    error: 'public_delegate_name_policy_conflict', total: 2,
    items: [{ user_id: 1, display_name: 'Member', reason_code: 'name_mismatch' }],
  } } });
  assert.equal(conflict.conflict.total, 2);
  assert.deepEqual(conflict.fields, {});
  const invalid = verificationSettingsErrorFromApi({ raw: { detail: {
    error: 'invalid_verification_settings',
    fields: { verification_residency_scope: 'Add an allowed location.' },
  } } });
  assert.deepEqual(invalid.fields, {
    verification_residency_scope: 'Add an allowed location.',
  });
});

test('branding and nav source wire nullable header variables without recoloring white panels', () => {
  const theme = source('components/BrandingThemeApplier.jsx');
  const nav = source('components/Nav.jsx');
  const badge = source('components/NotificationBadge.jsx');
  const settings = source('pages/admin/OrgSettings.jsx');
  assert.match(theme, /--brand-header-text-muted/);
  assert.match(theme, /removeProperty\('--brand-header-text'/);
  assert.match(nav, /text-\[var\(--brand-header-text-muted\)\]/);
  assert.match(badge, /brand-header-text-muted/);
  assert.match(nav, /bg-white border border-gray-200/);
  assert.match(settings, /header_text_color: headerTextColor/);
  assert.match(settings, /below WCAG AA for normal text\. You can still save/);
});

test('settings uses the org list once, typed writes, deep link, reset, and selection cancellation', () => {
  const settings = source('pages/Settings.jsx');
  assert.match(settings, /id="display-names"/);
  assert.match(settings, /displayNameOrg/);
  assert.match(settings, /displayNameTargetFromSearch\(window\.location\.search, topLevelOrgs\)/);
  assert.match(settings, /userOrgs[\s\S]*sort\(\(a, b\) => a\.name\.localeCompare/);
  assert.match(settings, /\/me\/display-name`/);
  assert.match(settings, /display_name: bodyName/);
  assert.match(settings, /saveProfile\(\{ reset: true \}\)/);
  assert.match(settings, /nameSaveCoordinator\.cancel\(effectiveNameTarget\)/);
  assert.match(settings, /nameSaveCoordinator\.begin\(target\)/);
  assert.match(settings, /await refreshOrgs\(\);[\s\S]*?if \(!request\.isCurrent\(\)/);
  assert.doesNotMatch(settings, /api\.get\(`\/api\/orgs\/\$\{[^}]+\}`/);
});

test('proposal form supports only three new choices while retaining signed legacy imports', () => {
  const proposal = source('pages/admin/ProposalManagement.jsx');
  assert.match(proposal, /VISIBLE_REQUIREMENT_OPTIONS/);
  assert.match(proposal, /verification_require_residency = verificationStorage\.requireResidency/);
  assert.match(proposal, /verification_jurisdiction = null/);
  assert.match(proposal, /verification_legacy_import_token/);
  assert.match(proposal, /legacyVerification\.jurisdiction/);
  assert.doesNotMatch(proposal, /Jurisdiction \(optional\)/);
});

test('delegate visibility transitions distinguish verification and org-name failures', () => {
  const delegate = source('pages/DelegateProfile.jsx');
  assert.match(delegate, /extractVerificationRequiredDetail\(error\)/);
  assert.match(delegate, /extractNameMatchRequiredDetail\(error\)/);
  assert.match(delegate, /settings\?displayNameOrg=/);
  assert.match(delegate, /settings#identity-verification/);
});

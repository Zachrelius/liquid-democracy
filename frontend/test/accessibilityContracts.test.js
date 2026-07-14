import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { accessibleAccentTextColor, contrastTextColor } from '../src/utils/colorContrast.js';

function source(relativePath) {
  return readFileSync(new URL(`../src/${relativePath}`, import.meta.url), 'utf8');
}

test('pilot-critical forms use programmatic labels and named filter groups', () => {
  const login = source('pages/Login.jsx');
  const createOrg = source('pages/CreateOrg.jsx');
  const setup = source('pages/SetupWizard.jsx');
  const proposals = source('pages/Proposals.jsx');
  const proposalManagement = source('pages/admin/ProposalManagement.jsx');
  const orgSettings = source('pages/admin/OrgSettings.jsx');

  for (const id of ['login-username', 'login-password', 'register-email', 'register-password']) {
    assert.match(login, new RegExp(`htmlFor="${id}"`));
    assert.match(login, new RegExp(`id="${id}"`));
  }
  for (const id of ['create-org-name', 'create-org-slug', 'create-org-description']) {
    assert.match(createOrg, new RegExp(`htmlFor="${id}"`));
    assert.match(createOrg, new RegExp(`id="${id}"`));
  }
  assert.match(createOrg, /<fieldset>[\s\S]*?<legend[^>]*>[\s\S]*?Activity visibility/);
  assert.match(setup, /htmlFor="setup-invitation-emails"/);
  assert.match(setup, /aria-label="Setup progress"/);
  assert.match(proposals, /aria-label="Filter proposals by status"/);
  assert.match(proposals, /aria-pressed=\{statusFilter === s\}/);
  assert.match(proposals, /aria-label="Filter proposals by topic"/);
  assert.match(proposalManagement, /htmlFor="proposal-title"/);
  assert.match(proposalManagement, /htmlFor="proposal-verification-floor"/);
  assert.match(proposalManagement, /<fieldset key=\{idx\}/);
  assert.match(orgSettings, /htmlFor="org-settings-name"/);
  assert.match(orgSettings, /htmlFor="org-settings-tie-ranked"/);
});

test('shared modal behavior traps focus, closes on Escape, and restores focus', () => {
  const hook = source('hooks/useModalDialog.js');
  const confirm = source('components/ConfirmDialog.jsx');
  const report = source('components/ReportModal.jsx');
  const delegate = source('components/DelegateModal.jsx');

  assert.match(hook, /event\.key === 'Escape'/);
  assert.match(hook, /event\.key !== 'Tab'/);
  assert.match(hook, /previousFocusRef\.current = document\.activeElement/);
  assert.match(hook, /previous\.focus\(\)/);
  assert.match(confirm, /role="dialog"/);
  assert.match(confirm, /aria-modal="true"/);
  assert.doesNotMatch(confirm, /e\.key === 'Enter'/);
  assert.match(report, /useModalDialog/);
  assert.match(report, /htmlFor="report-note"/);
  assert.match(delegate, /useModalDialog\(\{ onClose \}\)/);
  assert.doesNotMatch(delegate, /autoFocus/);
});

test('ordered governance interactions have explicit non-drag controls', () => {
  const ranked = source('components/RankedBallot.jsx');
  const budget = source('components/BudgetProjectBallot.jsx');
  const delegations = source('pages/Delegations.jsx');
  const proposalManagement = source('pages/admin/ProposalManagement.jsx');

  assert.match(ranked, /function moveWithinRanking/);
  assert.match(ranked, /Move \$\{optionDisplayLabel\(proposal, opt\)\} up in your ranking/);
  assert.match(ranked, /aria-label=\{`Rank \$\{optionDisplayLabel\(proposal, opt\)\}`\}/);
  assert.match(ranked, /aria-label=\{`Drag to reorder \$\{optionDisplayLabel\(proposal, opt\)\}`\}/);
  assert.match(budget, /Funding tier for/);
  assert.match(budget, /Move \$\{optionDisplayLabel\(proposal, o\)\} down in your ranking/);
  assert.match(delegations, /function moveDelegation/);
  assert.match(delegations, /Use the arrow buttons or drag delegated topics/);
  assert.match(proposalManagement, /aria-label=\{`Move option \$\{idx \+ 1\} up`\}/);
});

test('dynamic feedback and keyboard focus have accessible defaults', () => {
  const css = source('index.css');
  const errors = source('components/ErrorMessage.jsx');
  const toasts = source('components/Toast.jsx');
  const notifications = source('components/NotificationBadge.jsx');
  const avatar = source('components/Avatar.jsx');
  const topicBadge = source('components/TopicBadge.jsx');

  assert.match(css, /:focus-visible/);
  assert.match(css, /outline: 3px solid #0b63ce/);
  assert.match(errors, /role="alert"/);
  assert.match(toasts, /role=\{t\.type === 'error' \? 'alert' : 'status'\}/);
  assert.match(toasts, /aria-atomic="true"/);
  assert.match(notifications, /aria-expanded=\{open\}/);
  assert.match(notifications, /event\.key !== 'Escape'/);
  assert.match(avatar, /alt=""/);
  assert.match(avatar, /aria-hidden="true"/);
  assert.match(topicBadge, /contrastTextColor\(color\)/);
  assert.equal(contrastTextColor('#f59e0b'), '#000000');
  assert.equal(contrastTextColor('#1b3a5c'), '#ffffff');
  assert.equal(accessibleAccentTextColor('#2E75B6'), '#2c6fad');
  assert.equal(accessibleAccentTextColor('#123456'), '#123456');
});

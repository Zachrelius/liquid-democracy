import { useMemo, useState } from 'react';
import { useLocation, useNavigate, useSearchParams } from 'react-router-dom';
import { useOrg } from '../OrgContext';
import { urlFor } from '../utils/urls';
import {
  parseInvitationEmails,
  pendingSelectedTopics,
  slugifyOrganizationName,
} from '../utils/setupWizard';
import api from '../api';

const SUGGESTED_TOPICS = [
  { name: 'General', color: '#6366f1', checked: true },
  { name: 'Budget', color: '#3b82f6', checked: true },
  { name: 'Policy', color: '#10b981', checked: true },
  { name: 'Operations', color: '#f59e0b', checked: true },
];

function StepIndicator({ current, total }) {
  const names = ['Organization', 'Topics', 'Invite members', 'Finish'];
  return (
    <ol aria-label="Setup progress" className="flex items-center gap-2 mb-8">
      {Array.from({ length: total }, (_, i) => (
        <li key={i} className="flex items-center gap-2">
          <span
            aria-current={i === current ? 'step' : undefined}
            className={`w-8 h-8 rounded-full flex items-center justify-center text-sm font-medium transition-colors ${
              i < current
                ? 'bg-[#2D8A56] text-white'
                : i === current
                ? 'bg-[var(--brand-primary)] text-white'
                : 'bg-gray-200 text-gray-500'
            }`}
          >
            <span aria-hidden="true">{i < current ? '\u2713' : i + 1}</span>
            <span className="sr-only">
              Step {i + 1} of {total}: {names[i] || `Step ${i + 1}`}
              {i < current ? ', completed' : i === current ? ', current' : ''}
            </span>
          </span>
          {i < total - 1 && (
            <span aria-hidden="true" className={`w-12 h-0.5 ${i < current ? 'bg-[#2D8A56]' : 'bg-gray-200'}`} />
          )}
        </li>
      ))}
    </ol>
  );
}

export default function SetupWizard() {
  const navigate = useNavigate();
  const location = useLocation();
  const [searchParams] = useSearchParams();
  const { setCurrentOrg, refreshOrgs, userOrgs, loading: orgsLoading } = useOrg();
  const onboardingSlug = searchParams.get('org');
  const initialOrg = location.state?.onboardingOrg || null;
  const [step, setStep] = useState(initialOrg ? 1 : 0);
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);

  // Step 1: Org
  const [orgName, setOrgName] = useState('');
  const [orgSlug, setOrgSlug] = useState('');
  const [slugEdited, setSlugEdited] = useState(false);
  const [orgDescription, setOrgDescription] = useState('');
  // Phase 57 — three-value vocabulary; was 'approval_required'.
  const [joinPolicy, setJoinPolicy] = useState('approval');
  const [createdOrg, setCreatedOrg] = useState(initialOrg);

  // Step 2: Topics
  const [topics, setTopics] = useState(SUGGESTED_TOPICS.map(t => ({ ...t })));
  const [createdTopicNames, setCreatedTopicNames] = useState([]);
  const [customTopic, setCustomTopic] = useState('');
  const [customColor, setCustomColor] = useState('#8b5cf6');

  // Step 3: Invitations
  const [emails, setEmails] = useState('');
  const [inviteMsg, setInviteMsg] = useState('');

  const resumedOrg = useMemo(
    () => (!createdOrg && onboardingSlug
      ? userOrgs.find(org => org.slug === onboardingSlug) || null
      : null),
    [createdOrg, onboardingSlug, userOrgs],
  );
  const activeOrg = createdOrg || resumedOrg;
  const currentStep = activeOrg && onboardingSlug && step === 0 ? 1 : step;

  const completedTopicKeys = useMemo(
    () => new Set(createdTopicNames.map(name => name.trim().toLowerCase())),
    [createdTopicNames],
  );

  function handleOrgNameChange(val) {
    setOrgName(val);
    if (!slugEdited) setOrgSlug(slugifyOrganizationName(val));
  }

  async function handleCreateOrg() {
    setSaving(true);
    setError('');
    try {
      const org = await api.post('/api/orgs', {
        name: orgName,
        slug: orgSlug,
        description: orgDescription,
        join_policy: joinPolicy,
      });
      setCreatedOrg(org);
      await refreshOrgs();
      setCurrentOrg(org);
      setStep(1);
      navigate(`/setup?org=${encodeURIComponent(org.slug)}`, {
        replace: true,
        state: { onboardingOrg: org },
      });
    } catch (err) {
      setError(err.message || 'Failed to create organization');
    } finally {
      setSaving(false);
    }
  }

  function toggleTopic(index) {
    setTopics(prev => prev.map((t, i) => i === index ? { ...t, checked: !t.checked } : t));
  }

  function addCustomTopic() {
    if (!customTopic.trim()) return;
    if (topics.some(topic => topic.name.trim().toLowerCase() === customTopic.trim().toLowerCase())) {
      setError('That topic is already in the list.');
      return;
    }
    setError('');
    setTopics(prev => [...prev, { name: customTopic.trim(), color: customColor, checked: true }]);
    setCustomTopic('');
    setCustomColor('#8b5cf6');
  }

  async function handleCreateTopics() {
    if (!activeOrg) return;
    setSaving(true);
    setError('');
    let readyNames = [...createdTopicNames];
    try {
      // Reconcile with the server before writing so a page refresh or a
      // response lost after commit does not turn Retry into duplicate POSTs.
      const existing = await api.get(`/api/orgs/${activeOrg.slug}/topics`);
      const existingNames = existing.map(topic => topic.name);
      const selectedAlreadyPresent = topics
        .filter(topic => (
          topic.checked
          && existingNames.some(name => name.trim().toLowerCase() === topic.name.trim().toLowerCase())
        ))
        .map(topic => topic.name);
      readyNames = [...new Set([...readyNames, ...selectedAlreadyPresent])];
      setCreatedTopicNames(readyNames);

      const pending = pendingSelectedTopics(topics, existingNames, readyNames);
      for (const t of pending) {
        await api.post(`/api/orgs/${activeOrg.slug}/topics`, {
          name: t.name,
          description: '',
          color: t.color,
        });
        readyNames = [...readyNames, t.name];
        setCreatedTopicNames([...new Set(readyNames)]);
      }
      setStep(2);
    } catch (err) {
      const progress = readyNames.length > 0
        ? ` ${readyNames.length} selected topic${readyNames.length === 1 ? ' is' : 's are'} already ready; retry to create only the remainder.`
        : '';
      const message = (err.message || 'Failed to create topics').replace(/[.!?]+$/, '');
      setError(`${message}.${progress}`);
    } finally {
      setSaving(false);
    }
  }

  async function handleSendInvites() {
    if (!activeOrg) return;
    setSaving(true);
    setError('');
    setInviteMsg('');
    try {
      const { valid: emailList, invalid } = parseInvitationEmails(emails);
      if (invalid.length > 0) {
        setError(`Fix or remove ${invalid.length} invalid email ${invalid.length === 1 ? 'address' : 'addresses'} before continuing.`);
        return;
      }
      if (emailList.length === 0) {
        setStep(3);
        return;
      }
      const createdInvitations = await api.post(`/api/orgs/${activeOrg.slug}/invitations`, {
        emails: emailList,
        role: 'member',
      });
      const count = createdInvitations.length;
      setInviteMsg(`${count} invitation${count === 1 ? '' : 's'} created and queued for email delivery.`);
      setStep(3);
    } catch (err) {
      setError(err.message || 'Failed to send invitations');
    } finally {
      setSaving(false);
    }
  }

  if (onboardingSlug && !activeOrg) {
    return (
      <div className="max-w-2xl mx-auto px-4 py-12">
        <div className="bg-white border border-gray-200 rounded-xl p-6 text-center">
          {orgsLoading ? (
            <p className="text-sm text-gray-500">Loading organization setup…</p>
          ) : (
            <>
              <h1 className="text-lg font-semibold text-[var(--brand-primary)] mb-2">Organization unavailable</h1>
              <p className="text-sm text-gray-500 mb-4">
                This organization is not available to your account.
              </p>
              <button
                type="button"
                onClick={() => navigate('/orgs')}
                className="text-sm px-4 py-2 bg-[var(--brand-primary)] text-white rounded-lg hover:bg-[var(--brand-accent)]"
              >
                Return to your organizations
              </button>
            </>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="max-w-2xl mx-auto px-4 py-12">
      <div className="text-center mb-6">
        <h1 className="text-2xl font-semibold text-[var(--brand-primary)]">
          {currentStep === 3 ? "You're All Set!" : 'Set Up Your Organization'}
        </h1>
        {currentStep < 3 && (
          <p className="text-sm text-gray-500 mt-1">
            A few guided steps will get your first decision ready for members.
          </p>
        )}
      </div>

      <div className="flex justify-center">
        <StepIndicator current={currentStep} total={4} />
      </div>

      {error && (
        <div role="alert" className="mb-4 p-3 bg-red-50 border border-red-200 text-red-700 text-sm rounded-lg">
          {error}
        </div>
      )}

      {/* Step 1: Create Organization */}
      {currentStep === 0 && (
        <div className="bg-white border border-gray-200 rounded-xl p-6 space-y-5">
          <h2 className="text-lg font-semibold text-[var(--brand-primary)]">Create Your Organization</h2>
          <p className="text-sm text-gray-500">
            An organization is the group of people who will vote and delegate together.
          </p>

          <div>
            <label htmlFor="setup-org-name" className="block text-xs text-gray-500 mb-1">Organization Name</label>
            <input
              id="setup-org-name"
              type="text"
              value={orgName}
              onChange={e => handleOrgNameChange(e.target.value)}
              placeholder="My Organization"
              className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[var(--brand-accent)]"
            />
          </div>

          <div>
            <label htmlFor="setup-org-slug" className="block text-xs text-gray-500 mb-1">Slug (URL identifier)</label>
            <div className="flex items-center gap-2">
              <span className="text-sm text-gray-400">/</span>
              <input
                id="setup-org-slug"
                type="text"
                value={orgSlug}
                onChange={e => { setOrgSlug(e.target.value); setSlugEdited(true); }}
                className="flex-1 px-3 py-2 border border-gray-300 rounded-lg text-sm font-mono focus:outline-none focus:ring-2 focus:ring-[var(--brand-accent)]"
              />
            </div>
          </div>

          <div>
            <label htmlFor="setup-org-description" className="block text-xs text-gray-500 mb-1">Description (optional)</label>
            <textarea
              id="setup-org-description"
              value={orgDescription}
              onChange={e => setOrgDescription(e.target.value)}
              rows={2}
              placeholder="What is this organization about?"
              className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[var(--brand-accent)] resize-none"
            />
          </div>

          <fieldset>
            <legend className="block text-xs text-gray-500 mb-2">Join Policy</legend>
            {/* Phase 57 — three-value vocabulary (was open / approval_required
                / invite_only). The CreateOrg page exposes the full
                three-axis model; this Setup Wizard intentionally only
                surfaces the join axis with sensible discoverability +
                activity defaults (listed + members_only — today's
                behavior). Stewards can refine via OrgSettings later. */}
            <div className="space-y-2">
              {[
                { value: 'invite', label: 'Invitation only' },
                { value: 'approval', label: 'Approval required' },
                { value: 'open', label: 'Open' },
              ].map(opt => (
                <label key={opt.value} className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="radio"
                    name="joinPolicy"
                    value={opt.value}
                    checked={joinPolicy === opt.value}
                    onChange={() => setJoinPolicy(opt.value)}
                    className="accent-[var(--brand-accent)]"
                  />
                  <span className="text-sm text-gray-700">{opt.label}</span>
                </label>
              ))}
            </div>
          </fieldset>

          <div className="flex justify-end pt-2">
            <button
              onClick={handleCreateOrg}
              disabled={saving || !orgName.trim() || !orgSlug.trim()}
              className="text-sm px-6 py-2 bg-[var(--brand-primary)] text-white rounded-lg hover:bg-[var(--brand-accent)] transition-colors disabled:opacity-50"
            >
              {saving ? 'Creating...' : 'Next: Topics'}
            </button>
          </div>
        </div>
      )}

      {/* Step 2: Topics */}
      {currentStep === 1 && (
        <div className="bg-white border border-gray-200 rounded-xl p-6 space-y-5">
          <h2 className="text-lg font-semibold text-[var(--brand-primary)]">Create Topics</h2>
          <p className="text-sm text-gray-500">
            Topics help categorize proposals and let members delegate their votes per-topic.
          </p>

          <div className="space-y-2">
            {topics.map((t, i) => {
              const created = completedTopicKeys.has(t.name.trim().toLowerCase());
              return (
              <label key={`${t.name}-${i}`} className={`flex items-center gap-3 p-2 rounded-lg ${created ? 'bg-green-50' : 'cursor-pointer hover:bg-gray-50'}`}>
                <input
                  type="checkbox"
                  checked={t.checked}
                  disabled={created}
                  onChange={() => toggleTopic(i)}
                  className="accent-[var(--brand-accent)]"
                />
                <span
                  className="w-4 h-4 rounded-full flex-shrink-0"
                  style={{ backgroundColor: t.color }}
                />
                <span className="text-sm text-gray-700">{t.name}</span>
                {created && <span className="ml-auto text-xs font-medium text-green-700">Ready</span>}
              </label>
              );
            })}
          </div>

          <div className="flex items-center gap-2 pt-2 border-t border-gray-100">
            <input
              aria-label="Custom topic name"
              type="text"
              value={customTopic}
              onChange={e => setCustomTopic(e.target.value)}
              placeholder="Add custom topic..."
              className="flex-1 px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[var(--brand-accent)]"
              onKeyDown={e => e.key === 'Enter' && (e.preventDefault(), addCustomTopic())}
            />
            <input
              aria-label="Custom topic color"
              type="color"
              value={customColor}
              onChange={e => setCustomColor(e.target.value)}
              className="w-9 h-9 rounded cursor-pointer border border-gray-300"
            />
            <button
              onClick={addCustomTopic}
              disabled={!customTopic.trim()}
              className="text-sm px-3 py-2 border border-[var(--brand-accent)] text-[var(--brand-accent)] rounded-lg hover:bg-[var(--brand-accent)] hover:text-white transition-colors disabled:opacity-50"
            >
              Add
            </button>
          </div>

          <div className="flex justify-between pt-2">
            <button
              onClick={() => navigate(urlFor(activeOrg, 'proposals'))}
              className="text-sm px-4 py-2 border border-gray-300 text-gray-600 rounded-lg hover:bg-gray-50"
            >
              Finish later
            </button>
            <div className="flex gap-2">
              <button
                onClick={() => setStep(2)}
                className="text-sm px-4 py-2 text-gray-500 hover:text-gray-700"
              >
                Skip
              </button>
              <button
                onClick={handleCreateTopics}
                disabled={saving || topics.filter(t => t.checked).length === 0}
                className="text-sm px-6 py-2 bg-[var(--brand-primary)] text-white rounded-lg hover:bg-[var(--brand-accent)] transition-colors disabled:opacity-50"
              >
                {saving ? 'Creating...' : 'Next: Invite Members'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Step 3: Invite Members */}
      {currentStep === 2 && (
        <div className="bg-white border border-gray-200 rounded-xl p-6 space-y-5">
          <h2 className="text-lg font-semibold text-[var(--brand-primary)]">Invite Members</h2>
          <p className="text-sm text-gray-500">
            Enter email addresses to invite people to your organization (one per line).
          </p>

          <label htmlFor="setup-invitation-emails" className="block text-xs font-medium text-gray-600">
            Email addresses, one per line
          </label>
          <textarea
            id="setup-invitation-emails"
            value={emails}
            onChange={e => setEmails(e.target.value)}
            rows={5}
            placeholder={"alice@example.com\nbob@example.com\ncarol@example.com"}
            className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm font-mono focus:outline-none focus:ring-2 focus:ring-[var(--brand-accent)] resize-none"
          />

          {inviteMsg && (
            <div role="status" aria-live="polite" className="p-2 bg-green-50 border border-green-200 text-green-700 text-sm rounded-lg">
              {inviteMsg}
            </div>
          )}

          <div className="flex justify-between pt-2">
            <button
              onClick={() => setStep(1)}
              className="text-sm px-4 py-2 border border-gray-300 text-gray-600 rounded-lg hover:bg-gray-50"
            >
              Back
            </button>
            <div className="flex gap-2">
              <button
                onClick={() => setStep(3)}
                className="text-sm px-4 py-2 text-gray-500 hover:text-gray-700"
              >
                Skip for now
              </button>
              <button
                onClick={handleSendInvites}
                disabled={saving}
                className="text-sm px-6 py-2 bg-[var(--brand-primary)] text-white rounded-lg hover:bg-[var(--brand-accent)] transition-colors disabled:opacity-50"
              >
                {saving ? 'Sending...' : 'Send Invitations'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Step 4: Done */}
      {currentStep === 3 && (
        <div className="bg-white border border-gray-200 rounded-xl p-8 text-center space-y-6">
          <div className="text-5xl">&#127881;</div>
          <h2 className="text-xl font-semibold text-[var(--brand-primary)]">Your platform is ready!</h2>
          <p className="text-sm text-gray-500 max-w-md mx-auto">
            {activeOrg?.name || 'Your organization'} has been created. Here are some next steps:
          </p>
          {inviteMsg && (
            <p role="status" className="text-sm text-green-700 bg-green-50 border border-green-200 rounded-lg px-3 py-2 max-w-md mx-auto">
              {inviteMsg}
            </p>
          )}

          <div className="grid gap-3 max-w-sm mx-auto">
            <button
              onClick={() => navigate(`${urlFor(activeOrg, 'admin-proposals')}?create=1`)}
              className="w-full text-sm px-4 py-3 bg-[var(--brand-primary)] text-white rounded-lg hover:bg-[var(--brand-accent)] transition-colors"
            >
              Create your first proposal
            </button>
            <button
              onClick={() => navigate(urlFor(activeOrg, 'admin-settings'))}
              className="w-full text-sm px-4 py-3 border border-gray-200 rounded-lg hover:border-[var(--brand-accent)] hover:bg-blue-50/30 transition-all text-left"
            >
              <span className="font-medium text-[var(--brand-primary)]">Admin Settings</span>
              <span className="block text-xs text-gray-400 mt-0.5">Configure voting rules, thresholds, and more</span>
            </button>
            <button
              onClick={() => navigate(urlFor(activeOrg, 'proposals'))}
              className="w-full text-sm px-4 py-3 border border-gray-200 rounded-lg hover:border-[var(--brand-accent)] hover:bg-blue-50/30 transition-all"
            >
              View proposals
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

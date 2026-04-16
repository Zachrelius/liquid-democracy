import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useOrg } from '../OrgContext';
import api from '../api';

const SUGGESTED_TOPICS = [
  { name: 'General', color: '#6366f1', checked: true },
  { name: 'Budget', color: '#3b82f6', checked: true },
  { name: 'Policy', color: '#10b981', checked: true },
  { name: 'Operations', color: '#f59e0b', checked: true },
];

function slugify(text) {
  return text
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 50);
}

function StepIndicator({ current, total }) {
  return (
    <div className="flex items-center gap-2 mb-8">
      {Array.from({ length: total }, (_, i) => (
        <div key={i} className="flex items-center gap-2">
          <div
            className={`w-8 h-8 rounded-full flex items-center justify-center text-sm font-medium transition-colors ${
              i < current
                ? 'bg-[#2D8A56] text-white'
                : i === current
                ? 'bg-[#1B3A5C] text-white'
                : 'bg-gray-200 text-gray-500'
            }`}
          >
            {i < current ? '\u2713' : i + 1}
          </div>
          {i < total - 1 && (
            <div className={`w-12 h-0.5 ${i < current ? 'bg-[#2D8A56]' : 'bg-gray-200'}`} />
          )}
        </div>
      ))}
    </div>
  );
}

export default function SetupWizard() {
  const navigate = useNavigate();
  const { setCurrentOrg, refreshOrgs } = useOrg();
  const [step, setStep] = useState(0);
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);

  // Step 1: Org
  const [orgName, setOrgName] = useState('');
  const [orgSlug, setOrgSlug] = useState('');
  const [slugEdited, setSlugEdited] = useState(false);
  const [orgDescription, setOrgDescription] = useState('');
  const [joinPolicy, setJoinPolicy] = useState('approval_required');
  const [createdOrg, setCreatedOrg] = useState(null);

  // Step 2: Topics
  const [topics, setTopics] = useState(SUGGESTED_TOPICS.map(t => ({ ...t })));
  const [customTopic, setCustomTopic] = useState('');
  const [customColor, setCustomColor] = useState('#8b5cf6');

  // Step 3: Invitations
  const [emails, setEmails] = useState('');
  const [inviteMsg, setInviteMsg] = useState('');

  function handleOrgNameChange(val) {
    setOrgName(val);
    if (!slugEdited) setOrgSlug(slugify(val));
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
    setTopics(prev => [...prev, { name: customTopic.trim(), color: customColor, checked: true }]);
    setCustomTopic('');
    setCustomColor('#8b5cf6');
  }

  async function handleCreateTopics() {
    if (!createdOrg) return;
    setSaving(true);
    setError('');
    try {
      const selected = topics.filter(t => t.checked);
      for (const t of selected) {
        await api.post(`/api/orgs/${createdOrg.slug}/topics`, {
          name: t.name,
          description: '',
          color: t.color,
        });
      }
      setStep(2);
    } catch (err) {
      setError(err.message || 'Failed to create topics');
    } finally {
      setSaving(false);
    }
  }

  async function handleSendInvites() {
    if (!createdOrg) return;
    setSaving(true);
    setError('');
    setInviteMsg('');
    try {
      const emailList = emails
        .split('\n')
        .map(e => e.trim())
        .filter(e => e.length > 0 && e.includes('@'));
      if (emailList.length === 0) {
        setStep(3);
        return;
      }
      await api.post(`/api/orgs/${createdOrg.slug}/invitations`, {
        emails: emailList,
        role: 'member',
      });
      setInviteMsg(`${emailList.length} invitation(s) created.`);
      setTimeout(() => setStep(3), 1000);
    } catch (err) {
      setError(err.message || 'Failed to send invitations');
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="max-w-2xl mx-auto px-4 py-12">
      <div className="text-center mb-6">
        <h1 className="text-2xl font-semibold text-[#1B3A5C]">
          {step === 3 ? "You're All Set!" : 'Set Up Your Platform'}
        </h1>
        {step < 3 && (
          <p className="text-sm text-gray-500 mt-1">
            Let's get your liquid democracy instance ready.
          </p>
        )}
      </div>

      <div className="flex justify-center">
        <StepIndicator current={step} total={4} />
      </div>

      {error && (
        <div className="mb-4 p-3 bg-red-50 border border-red-200 text-red-700 text-sm rounded-lg">
          {error}
        </div>
      )}

      {/* Step 1: Create Organization */}
      {step === 0 && (
        <div className="bg-white border border-gray-200 rounded-xl p-6 space-y-5">
          <h2 className="text-lg font-semibold text-[#1B3A5C]">Create Your Organization</h2>
          <p className="text-sm text-gray-500">
            An organization is the group of people who will vote and delegate together.
          </p>

          <div>
            <label className="block text-xs text-gray-500 mb-1">Organization Name</label>
            <input
              type="text"
              value={orgName}
              onChange={e => handleOrgNameChange(e.target.value)}
              placeholder="My Organization"
              className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[#2E75B6]"
            />
          </div>

          <div>
            <label className="block text-xs text-gray-500 mb-1">Slug (URL identifier)</label>
            <div className="flex items-center gap-2">
              <span className="text-sm text-gray-400">/orgs/</span>
              <input
                type="text"
                value={orgSlug}
                onChange={e => { setOrgSlug(e.target.value); setSlugEdited(true); }}
                className="flex-1 px-3 py-2 border border-gray-300 rounded-lg text-sm font-mono focus:outline-none focus:ring-2 focus:ring-[#2E75B6]"
              />
            </div>
          </div>

          <div>
            <label className="block text-xs text-gray-500 mb-1">Description (optional)</label>
            <textarea
              value={orgDescription}
              onChange={e => setOrgDescription(e.target.value)}
              rows={2}
              placeholder="What is this organization about?"
              className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[#2E75B6] resize-none"
            />
          </div>

          <div>
            <label className="block text-xs text-gray-500 mb-2">Join Policy</label>
            <div className="space-y-2">
              {[
                { value: 'invite_only', label: 'Invite Only' },
                { value: 'approval_required', label: 'Approval Required' },
                { value: 'open', label: 'Open' },
              ].map(opt => (
                <label key={opt.value} className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="radio"
                    name="joinPolicy"
                    value={opt.value}
                    checked={joinPolicy === opt.value}
                    onChange={() => setJoinPolicy(opt.value)}
                    className="accent-[#2E75B6]"
                  />
                  <span className="text-sm text-gray-700">{opt.label}</span>
                </label>
              ))}
            </div>
          </div>

          <div className="flex justify-end pt-2">
            <button
              onClick={handleCreateOrg}
              disabled={saving || !orgName.trim() || !orgSlug.trim()}
              className="text-sm px-6 py-2 bg-[#1B3A5C] text-white rounded-lg hover:bg-[#2E75B6] transition-colors disabled:opacity-50"
            >
              {saving ? 'Creating...' : 'Next: Topics'}
            </button>
          </div>
        </div>
      )}

      {/* Step 2: Topics */}
      {step === 1 && (
        <div className="bg-white border border-gray-200 rounded-xl p-6 space-y-5">
          <h2 className="text-lg font-semibold text-[#1B3A5C]">Create Topics</h2>
          <p className="text-sm text-gray-500">
            Topics help categorize proposals and let members delegate their votes per-topic.
          </p>

          <div className="space-y-2">
            {topics.map((t, i) => (
              <label key={i} className="flex items-center gap-3 cursor-pointer p-2 rounded-lg hover:bg-gray-50">
                <input
                  type="checkbox"
                  checked={t.checked}
                  onChange={() => toggleTopic(i)}
                  className="accent-[#2E75B6]"
                />
                <span
                  className="w-4 h-4 rounded-full flex-shrink-0"
                  style={{ backgroundColor: t.color }}
                />
                <span className="text-sm text-gray-700">{t.name}</span>
              </label>
            ))}
          </div>

          <div className="flex items-center gap-2 pt-2 border-t border-gray-100">
            <input
              type="text"
              value={customTopic}
              onChange={e => setCustomTopic(e.target.value)}
              placeholder="Add custom topic..."
              className="flex-1 px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[#2E75B6]"
              onKeyDown={e => e.key === 'Enter' && (e.preventDefault(), addCustomTopic())}
            />
            <input
              type="color"
              value={customColor}
              onChange={e => setCustomColor(e.target.value)}
              className="w-9 h-9 rounded cursor-pointer border border-gray-300"
            />
            <button
              onClick={addCustomTopic}
              disabled={!customTopic.trim()}
              className="text-sm px-3 py-2 border border-[#2E75B6] text-[#2E75B6] rounded-lg hover:bg-[#2E75B6] hover:text-white transition-colors disabled:opacity-50"
            >
              Add
            </button>
          </div>

          <div className="flex justify-between pt-2">
            <button
              onClick={() => setStep(0)}
              className="text-sm px-4 py-2 border border-gray-300 text-gray-600 rounded-lg hover:bg-gray-50"
            >
              Back
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
                className="text-sm px-6 py-2 bg-[#1B3A5C] text-white rounded-lg hover:bg-[#2E75B6] transition-colors disabled:opacity-50"
              >
                {saving ? 'Creating...' : 'Next: Invite Members'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Step 3: Invite Members */}
      {step === 2 && (
        <div className="bg-white border border-gray-200 rounded-xl p-6 space-y-5">
          <h2 className="text-lg font-semibold text-[#1B3A5C]">Invite Members</h2>
          <p className="text-sm text-gray-500">
            Enter email addresses to invite people to your organization (one per line).
          </p>

          <textarea
            value={emails}
            onChange={e => setEmails(e.target.value)}
            rows={5}
            placeholder={"alice@example.com\nbob@example.com\ncarol@example.com"}
            className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm font-mono focus:outline-none focus:ring-2 focus:ring-[#2E75B6] resize-none"
          />

          {inviteMsg && (
            <div className="p-2 bg-green-50 border border-green-200 text-green-700 text-sm rounded-lg">
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
                className="text-sm px-6 py-2 bg-[#1B3A5C] text-white rounded-lg hover:bg-[#2E75B6] transition-colors disabled:opacity-50"
              >
                {saving ? 'Sending...' : 'Send Invitations'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Step 4: Done */}
      {step === 3 && (
        <div className="bg-white border border-gray-200 rounded-xl p-8 text-center space-y-6">
          <div className="text-5xl">&#127881;</div>
          <h2 className="text-xl font-semibold text-[#1B3A5C]">Your platform is ready!</h2>
          <p className="text-sm text-gray-500 max-w-md mx-auto">
            {createdOrg?.name || 'Your organization'} has been created. Here are some next steps:
          </p>

          <div className="grid gap-3 max-w-sm mx-auto">
            <button
              onClick={() => navigate('/admin/topics')}
              className="w-full text-sm px-4 py-3 border border-gray-200 rounded-lg hover:border-[#2E75B6] hover:bg-blue-50/30 transition-all text-left"
            >
              <span className="font-medium text-[#1B3A5C]">Manage Topics</span>
              <span className="block text-xs text-gray-400 mt-0.5">Add or edit topic categories</span>
            </button>
            <button
              onClick={() => navigate('/admin/settings')}
              className="w-full text-sm px-4 py-3 border border-gray-200 rounded-lg hover:border-[#2E75B6] hover:bg-blue-50/30 transition-all text-left"
            >
              <span className="font-medium text-[#1B3A5C]">Admin Settings</span>
              <span className="block text-xs text-gray-400 mt-0.5">Configure voting rules, thresholds, and more</span>
            </button>
            <button
              onClick={() => navigate('/proposals')}
              className="w-full text-sm px-4 py-3 bg-[#1B3A5C] text-white rounded-lg hover:bg-[#2E75B6] transition-colors"
            >
              Go to Proposals
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

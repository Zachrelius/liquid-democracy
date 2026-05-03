import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useOrg } from '../OrgContext';
import { useAuth } from '../AuthContext';
import { urlFor } from '../utils/urls';
import api from '../api';

const SUPPORT_EMAIL = 'support@liquiddemocracy.us';

function slugify(text) {
  return text
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 50);
}

/**
 * Phase 9.5 — classify backend create-org errors into UX kinds.
 * Backend returns these specific detail strings (status, substring match):
 *   - 403 + "temporarily paused"          → platform_paused
 *   - 403 + "verify your email"           → email_not_verified
 *   - 403 + "maximum number of organizations" → cap_reached (parse the (N))
 *   - 429 + "processing many"             → rate_limited
 * Anything else falls back to "generic".
 */
function classifyError(err) {
  if (!err) return { kind: 'generic', message: 'Failed to create organization' };
  const status = err.status;
  const message = err.message || 'Failed to create organization';

  if (status === 429) {
    return { kind: 'rate_limited', message };
  }
  if (status === 403) {
    if (/verify your email/i.test(message)) {
      return { kind: 'email_not_verified', message };
    }
    if (/temporarily paused/i.test(message)) {
      return { kind: 'platform_paused', message };
    }
    if (/maximum number of organizations/i.test(message)) {
      const m = message.match(/\((\d+)\)/);
      const limit = m ? parseInt(m[1], 10) : null;
      return { kind: 'cap_reached', message, limit };
    }
  }
  return { kind: 'generic', message };
}

export default function CreateOrg() {
  const { setCurrentOrg, refreshOrgs } = useOrg();
  const { refreshUser } = useAuth();
  const navigate = useNavigate();
  const [name, setName] = useState('');
  const [slug, setSlug] = useState('');
  const [slugEdited, setSlugEdited] = useState(false);
  const [description, setDescription] = useState('');
  const [joinPolicy, setJoinPolicy] = useState('approval_required');
  const [saving, setSaving] = useState(false);
  // Phase 9.5 — replace plain string error with a classified shape.
  const [errorInfo, setErrorInfo] = useState(null);
  const [resending, setResending] = useState(false);
  const [resent, setResent] = useState(false);
  const [resendError, setResendError] = useState('');

  function handleNameChange(val) {
    setName(val);
    if (!slugEdited) {
      setSlug(slugify(val));
    }
  }

  async function handleResendVerification() {
    setResending(true);
    setResendError('');
    setResent(false);
    try {
      await api.post('/api/auth/resend-verification', {});
      setResent(true);
      // In case the user verified in another tab between attempts.
      await refreshUser();
    } catch (err) {
      setResendError(err.message || 'Failed to send verification email');
    } finally {
      setResending(false);
    }
  }

  async function handleSubmit(e) {
    e.preventDefault();
    setSaving(true);
    setErrorInfo(null);
    setResent(false);
    setResendError('');
    try {
      const org = await api.post('/api/orgs', {
        name,
        slug,
        description,
        join_policy: joinPolicy,
      });
      await refreshOrgs();
      setCurrentOrg(org);
      // Phase 11 — slug-prefixed admin settings path.
      navigate(urlFor(org, 'admin-settings'));
    } catch (err) {
      setErrorInfo(classifyError(err));
    } finally {
      setSaving(false);
    }
  }

  function renderErrorBanner() {
    if (!errorInfo) return null;
    const { kind, message, limit } = errorInfo;

    if (kind === 'email_not_verified') {
      return (
        <div className="bg-amber-50 border border-amber-200 rounded-lg p-4 mb-5">
          <p className="text-sm text-amber-900 font-medium mb-1">
            Verify your email to create an organization
          </p>
          <p className="text-sm text-amber-800 mb-3">{message}</p>
          <div className="flex items-center gap-3 flex-wrap">
            <button
              type="button"
              onClick={handleResendVerification}
              disabled={resending}
              className="text-sm px-3 py-1.5 bg-amber-600 text-white rounded-lg hover:bg-amber-700 transition-colors disabled:opacity-50"
            >
              {resending ? 'Sending...' : 'Resend verification email'}
            </button>
            {resent && (
              <span className="text-xs text-green-700">Verification email sent.</span>
            )}
            {resendError && (
              <span className="text-xs text-red-700">{resendError}</span>
            )}
          </div>
        </div>
      );
    }

    if (kind === 'cap_reached') {
      return (
        <div className="bg-amber-50 border border-amber-200 rounded-lg p-4 mb-5">
          <p className="text-sm text-amber-900 font-medium mb-1">
            Organization limit reached
          </p>
          <p className="text-sm text-amber-800">
            {limit != null
              ? `You've reached the limit of ${limit} organization${limit === 1 ? '' : 's'}.`
              : "You've reached your organization-creation limit."}
            {' '}If you need to create more, contact{' '}
            <span className="font-mono">{SUPPORT_EMAIL}</span>.
          </p>
        </div>
      );
    }

    if (kind === 'platform_paused') {
      return (
        <div className="bg-amber-50 border border-amber-200 rounded-lg p-4 mb-5">
          <p className="text-sm text-amber-900 font-medium mb-1">
            Organization creation is temporarily paused
          </p>
          <p className="text-sm text-amber-800">
            New organization creation is on hold right now. Please contact{' '}
            <span className="font-mono">{SUPPORT_EMAIL}</span> if you need help.
          </p>
        </div>
      );
    }

    if (kind === 'rate_limited') {
      return (
        <div className="bg-amber-50 border border-amber-200 rounded-lg p-4 mb-5">
          <p className="text-sm text-amber-900 font-medium mb-1">
            Too many requests right now
          </p>
          <p className="text-sm text-amber-800">
            {message} If this keeps happening, contact{' '}
            <span className="font-mono">{SUPPORT_EMAIL}</span>.
          </p>
        </div>
      );
    }

    // generic fallback
    return (
      <div className="bg-red-50 border border-red-200 rounded-lg p-3 mb-5">
        <p className="text-sm text-red-700">{message}</p>
      </div>
    );
  }

  return (
    <div className="max-w-xl mx-auto px-4 py-12">
      <h1 className="text-2xl font-semibold text-[#1B3A5C] mb-8">Create Organization</h1>

      {renderErrorBanner()}

      <form onSubmit={handleSubmit} className="bg-white border border-gray-200 rounded-xl p-6 space-y-5">
        <div>
          <label className="block text-xs text-gray-500 mb-1">Organization Name</label>
          <input
            type="text"
            value={name}
            onChange={e => handleNameChange(e.target.value)}
            required
            placeholder="My Organization"
            className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[#2E75B6]"
          />
        </div>

        <div>
          <label className="block text-xs text-gray-500 mb-1">
            Slug (URL-friendly identifier)
          </label>
          <div className="flex items-center gap-2">
            <span className="text-sm text-gray-400">/</span>
            <input
              type="text"
              value={slug}
              onChange={e => { setSlug(e.target.value); setSlugEdited(true); }}
              required
              pattern="[a-z0-9][a-z0-9-]{1,48}[a-z0-9]"
              title="3-50 characters, lowercase letters, numbers, and hyphens"
              className="flex-1 px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[#2E75B6] font-mono"
            />
          </div>
          <p className="text-xs text-gray-400 mt-1">Lowercase letters, numbers, and hyphens only. 3-50 characters.</p>
        </div>

        <div>
          <label className="block text-xs text-gray-500 mb-1">Description</label>
          <textarea
            value={description}
            onChange={e => setDescription(e.target.value)}
            rows={3}
            placeholder="What is this organization about?"
            className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[#2E75B6] resize-none"
          />
        </div>

        <div>
          <label className="block text-xs text-gray-500 mb-2">Join Policy</label>
          <div className="space-y-2">
            {[
              { value: 'invite_only', label: 'Invite Only', desc: 'Only people you invite can join' },
              { value: 'approval_required', label: 'Approval Required', desc: 'Anyone can request, admins approve' },
              { value: 'open', label: 'Open', desc: 'Anyone can join immediately' },
            ].map(opt => (
              <label key={opt.value} className="flex items-start gap-3 cursor-pointer">
                <input
                  type="radio"
                  name="joinPolicy"
                  value={opt.value}
                  checked={joinPolicy === opt.value}
                  onChange={() => setJoinPolicy(opt.value)}
                  className="mt-0.5 accent-[#2E75B6]"
                />
                <div>
                  <p className="text-sm text-gray-700">{opt.label}</p>
                  <p className="text-xs text-gray-400">{opt.desc}</p>
                </div>
              </label>
            ))}
          </div>
        </div>

        <div className="flex gap-3 pt-2">
          <button
            type="submit"
            disabled={saving || !name.trim() || !slug.trim()}
            className="text-sm px-6 py-2 bg-[#1B3A5C] text-white rounded-lg hover:bg-[#2E75B6] transition-colors disabled:opacity-50"
          >
            {saving ? 'Creating...' : 'Create Organization'}
          </button>
          <button
            type="button"
            onClick={() => navigate('/orgs')}
            className="text-sm px-4 py-2 border border-gray-300 text-gray-600 rounded-lg hover:bg-gray-50"
          >
            Cancel
          </button>
        </div>
      </form>
    </div>
  );
}

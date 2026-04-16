import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useOrg } from '../OrgContext';
import api from '../api';

function slugify(text) {
  return text
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 50);
}

export default function CreateOrg() {
  const { setCurrentOrg, refreshOrgs } = useOrg();
  const navigate = useNavigate();
  const [name, setName] = useState('');
  const [slug, setSlug] = useState('');
  const [slugEdited, setSlugEdited] = useState(false);
  const [description, setDescription] = useState('');
  const [joinPolicy, setJoinPolicy] = useState('approval_required');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  function handleNameChange(val) {
    setName(val);
    if (!slugEdited) {
      setSlug(slugify(val));
    }
  }

  async function handleSubmit(e) {
    e.preventDefault();
    setSaving(true);
    setError('');
    try {
      const org = await api.post('/api/orgs', {
        name,
        slug,
        description,
        join_policy: joinPolicy,
      });
      await refreshOrgs();
      setCurrentOrg(org);
      navigate('/admin/settings');
    } catch (err) {
      setError(err.message || 'Failed to create organization');
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="max-w-xl mx-auto px-4 py-12">
      <h1 className="text-2xl font-semibold text-[#1B3A5C] mb-8">Create Organization</h1>

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
            <span className="text-sm text-gray-400">/orgs/</span>
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

        {error && <p className="text-sm text-red-600">{error}</p>}

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

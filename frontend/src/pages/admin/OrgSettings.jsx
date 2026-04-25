import { useState, useEffect } from 'react';
import { useOrg } from '../../OrgContext';
import api from '../../api';
import { useToast } from '../../components/Toast';

export default function OrgSettings() {
  const { currentOrg, refreshOrgs, isOwner } = useOrg();
  const toast = useToast();
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [joinPolicy, setJoinPolicy] = useState('approval_required');
  const [settings, setSettings] = useState({});
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState('');
  const [deleteConfirm, setDeleteConfirm] = useState('');
  const [showDelete, setShowDelete] = useState(false);

  useEffect(() => {
    if (currentOrg) {
      setName(currentOrg.name);
      setDescription(currentOrg.description || '');
      setJoinPolicy(currentOrg.join_policy);
      setSettings(currentOrg.settings || {});
    }
  }, [currentOrg]);

  if (!currentOrg) return <div className="text-center py-16 text-gray-400">No organization selected</div>;

  async function handleSave() {
    setSaving(true);
    setMsg('');
    try {
      await api.patch(`/api/orgs/${currentOrg.slug}`, {
        name,
        description,
        join_policy: joinPolicy,
        settings,
      });
      await refreshOrgs();
      toast.success('Settings saved');
      setMsg('Settings saved');
      setTimeout(() => setMsg(''), 3000);
    } catch (e) {
      setMsg(e.message || 'Failed to save');
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete() {
    if (deleteConfirm !== currentOrg.name) return;
    try {
      await api.delete(`/api/orgs/${currentOrg.slug}`);
      localStorage.removeItem('currentOrgSlug');
      window.location.href = '/orgs';
    } catch (e) {
      toast.error(e.message || 'Failed to delete');
    }
  }

  function updateSetting(key, value) {
    setSettings(prev => ({ ...prev, [key]: value }));
  }

  return (
    <div className="max-w-3xl mx-auto px-4 py-8 space-y-10">
      <h1 className="text-2xl font-semibold text-[#1B3A5C]">Organization Settings</h1>

      {/* General */}
      <section className="space-y-3">
        <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide">General</h2>
        <div className="bg-white border border-gray-200 rounded-xl p-5 space-y-4">
          <div>
            <label className="block text-xs text-gray-500 mb-1">Organization Name</label>
            <input
              type="text"
              value={name}
              onChange={e => setName(e.target.value)}
              className="w-full max-w-md px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[#2E75B6]"
            />
          </div>
          <div>
            <label className="block text-xs text-gray-500 mb-1">Description</label>
            <textarea
              value={description}
              onChange={e => setDescription(e.target.value)}
              rows={3}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[#2E75B6] resize-none"
            />
          </div>
          <div>
            <label className="block text-xs text-gray-500 mb-2">Join Policy</label>
            <div className="space-y-2">
              {[
                { value: 'invite_only', label: 'Invite Only', desc: 'Only people with an invitation can join' },
                { value: 'approval_required', label: 'Approval Required', desc: 'Anyone can request to join, admins approve' },
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
        </div>
      </section>

      {/* Voting Defaults */}
      <section className="space-y-3">
        <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide">Voting Defaults</h2>
        <div className="bg-white border border-gray-200 rounded-xl p-5 space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-xs text-gray-500 mb-1">Default Deliberation Days</label>
              <input
                type="number"
                min={1}
                max={90}
                value={settings.default_deliberation_days ?? 14}
                onChange={e => updateSetting('default_deliberation_days', parseInt(e.target.value) || 14)}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[#2E75B6]"
              />
            </div>
            <div>
              <label className="block text-xs text-gray-500 mb-1">Default Voting Days</label>
              <input
                type="number"
                min={1}
                max={90}
                value={settings.default_voting_days ?? 7}
                onChange={e => updateSetting('default_voting_days', parseInt(e.target.value) || 7)}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[#2E75B6]"
              />
            </div>
            <div>
              <label className="block text-xs text-gray-500 mb-1">
                Pass Threshold: {Math.round((settings.default_pass_threshold ?? 0.5) * 100)}%
              </label>
              <input
                type="range"
                min={0}
                max={100}
                value={Math.round((settings.default_pass_threshold ?? 0.5) * 100)}
                onChange={e => updateSetting('default_pass_threshold', parseInt(e.target.value) / 100)}
                className="w-full accent-[#2E75B6]"
              />
            </div>
            <div>
              <label className="block text-xs text-gray-500 mb-1">
                Quorum Threshold: {Math.round((settings.default_quorum_threshold ?? 0.4) * 100)}%
              </label>
              <input
                type="range"
                min={0}
                max={100}
                value={Math.round((settings.default_quorum_threshold ?? 0.4) * 100)}
                onChange={e => updateSetting('default_quorum_threshold', parseInt(e.target.value) / 100)}
                className="w-full accent-[#2E75B6]"
              />
            </div>
          </div>
        </div>
      </section>

      {/* Voting Methods */}
      <section className="space-y-3">
        <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide">Voting Methods</h2>
        <div className="bg-white border border-gray-200 rounded-xl p-5 space-y-3">
          <label className="flex items-center gap-3">
            <input type="checkbox" checked disabled className="accent-[#2E75B6]" />
            <div>
              <span className="text-sm text-gray-700">Binary (Yes/No/Abstain)</span>
              <p className="text-xs text-gray-400">Always enabled. Standard yes/no voting.</p>
            </div>
          </label>
          <label className="flex items-center gap-3 cursor-pointer">
            <input
              type="checkbox"
              checked={(settings.allowed_voting_methods || ['binary']).includes('approval')}
              onChange={e => {
                const current = settings.allowed_voting_methods || ['binary'];
                const updated = e.target.checked
                  ? [...new Set([...current, 'approval'])]
                  : current.filter(m => m !== 'approval');
                updateSetting('allowed_voting_methods', updated);
              }}
              className="accent-[#2E75B6]"
            />
            <div>
              <span className="text-sm text-gray-700">Approval Voting</span>
              <p className="text-xs text-gray-400">Voters approve any number of options. Best for multi-option decisions.</p>
            </div>
          </label>
          <label className="flex items-center gap-3 cursor-pointer">
            <input
              type="checkbox"
              checked={(settings.allowed_voting_methods || ['binary']).includes('ranked_choice')}
              onChange={e => {
                const current = settings.allowed_voting_methods || ['binary'];
                const updated = e.target.checked
                  ? [...new Set([...current, 'ranked_choice'])]
                  : current.filter(m => m !== 'ranked_choice');
                updateSetting('allowed_voting_methods', updated);
              }}
              className="accent-[#2E75B6]"
            />
            <div>
              <span className="text-sm text-gray-700">Ranked Choice (IRV / STV)</span>
              <p className="text-xs text-gray-400">Voters rank options in preference order. 1 winner = IRV; multiple winners = STV.</p>
            </div>
          </label>
        </div>
      </section>

      {/* Public Delegates */}
      <section className="space-y-3">
        <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide">Public Delegates</h2>
        <div className="bg-white border border-gray-200 rounded-xl p-5 space-y-4">
          <label className="flex items-center gap-3 cursor-pointer">
            <input
              type="checkbox"
              checked={settings.allow_public_delegates ?? true}
              onChange={e => updateSetting('allow_public_delegates', e.target.checked)}
              className="accent-[#2E75B6]"
            />
            <span className="text-sm text-gray-700">Allow public delegates in this organization</span>
          </label>
          {settings.allow_public_delegates !== false && (
            <div className="pl-6 space-y-2">
              <p className="text-xs text-gray-500 mb-1">Public delegate policy:</p>
              {[
                { value: 'admin_approval', label: 'Require admin approval', desc: 'Admins review delegate applications' },
                { value: 'open', label: 'Open registration', desc: 'Anyone can register as a public delegate' },
              ].map(opt => (
                <label key={opt.value} className="flex items-start gap-3 cursor-pointer">
                  <input
                    type="radio"
                    name="delegatePolicy"
                    value={opt.value}
                    checked={(settings.public_delegate_policy ?? 'admin_approval') === opt.value}
                    onChange={() => updateSetting('public_delegate_policy', opt.value)}
                    className="mt-0.5 accent-[#2E75B6]"
                  />
                  <div>
                    <p className="text-sm text-gray-700">{opt.label}</p>
                    <p className="text-xs text-gray-400">{opt.desc}</p>
                  </div>
                </label>
              ))}
            </div>
          )}
        </div>
      </section>

      {/* Save Button */}
      <div className="flex items-center gap-3">
        <button
          onClick={handleSave}
          disabled={saving}
          className="px-6 py-2 bg-[#1B3A5C] text-white text-sm rounded-lg hover:bg-[#2E75B6] transition-colors disabled:opacity-50"
        >
          {saving ? 'Saving...' : 'Save Settings'}
        </button>
        {msg && (
          <span className={`text-sm ${msg === 'Settings saved' ? 'text-green-600' : 'text-red-600'}`}>{msg}</span>
        )}
      </div>

      {/* Danger Zone */}
      {isOwner && (
        <section className="space-y-3">
          <h2 className="text-sm font-semibold text-red-500 uppercase tracking-wide">Danger Zone</h2>
          <div className="bg-white border border-red-200 rounded-xl p-5 space-y-4">
            {!showDelete ? (
              <button
                onClick={() => setShowDelete(true)}
                className="text-sm px-4 py-2 border border-red-300 text-red-600 rounded-lg hover:bg-red-50 transition-colors"
              >
                Delete Organization
              </button>
            ) : (
              <div className="space-y-3">
                <p className="text-sm text-gray-700">
                  This will permanently delete <strong>{currentOrg.name}</strong> and all its data. This action cannot be undone.
                </p>
                <p className="text-xs text-gray-500">Type the organization name to confirm:</p>
                <input
                  type="text"
                  value={deleteConfirm}
                  onChange={e => setDeleteConfirm(e.target.value)}
                  placeholder={currentOrg.name}
                  className="w-full max-w-xs px-3 py-2 border border-red-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-red-400"
                />
                <div className="flex gap-2">
                  <button
                    onClick={handleDelete}
                    disabled={deleteConfirm !== currentOrg.name}
                    className="text-sm px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 transition-colors disabled:opacity-50"
                  >
                    Delete Organization
                  </button>
                  <button
                    onClick={() => { setShowDelete(false); setDeleteConfirm(''); }}
                    className="text-sm px-4 py-2 border border-gray-300 text-gray-600 rounded-lg hover:bg-gray-50"
                  >
                    Cancel
                  </button>
                </div>
              </div>
            )}
          </div>
        </section>
      )}
    </div>
  );
}

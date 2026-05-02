import { useState, useEffect } from 'react';
import { useOrg } from '../../OrgContext';
import api from '../../api';
import { useToast } from '../../components/Toast';

// Phase 9.6 — sustained-majority demotion. Defaults that mirror what the
// backend uses when keys are absent. Used both for the "expand from
// nothing" path and for deciding whether the section is currently
// "customized" (any key present + non-default).
const SM_DEFAULTS = {
  sustained_majority_enabled_default: false,
  sustained_majority_per_proposal_override: true,
  sustained_majority_threshold: 0.5,
  sustained_majority_floor: 0.45,
  sustained_majority_failure_mode: 'fail',
};
const SM_KEYS = Object.keys(SM_DEFAULTS);

// True if any SM key is present in settings AND differs from its default.
// Used to derive the section-expanded state from existing settings —
// avoids needing a new backend schema field.
function smIsCustomized(settings) {
  if (!settings) return false;
  return SM_KEYS.some(k => {
    if (!Object.prototype.hasOwnProperty.call(settings, k)) return false;
    return settings[k] !== SM_DEFAULTS[k];
  });
}

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

  // Phase 9.6 — sustained-majority section is collapsed by default.
  // Local toggle state, derived from loaded settings: expanded if the
  // org has explicitly enabled SM or customized any of the keys.
  const [smExpanded, setSmExpanded] = useState(false);

  useEffect(() => {
    if (currentOrg) {
      setName(currentOrg.name);
      setDescription(currentOrg.description || '');
      setJoinPolicy(currentOrg.join_policy);
      const s = currentOrg.settings || {};
      setSettings(s);
      // Expand the SM section if the org currently has it on, or if any
      // SM key is customized away from the default.
      setSmExpanded(!!s.sustained_majority_enabled_default || smIsCustomized(s));
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

      {/* Sustained-Majority Voting (Phase 8 — demoted to collapsed-by-default in 9.6) */}
      <section className="space-y-3">
        <div className="flex items-baseline justify-between">
          <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide">
            Sustained-majority voting (advanced)
          </h2>
          <a
            href="/help/sustained-majority"
            target="_blank"
            rel="noreferrer"
            className="text-xs text-[#2E75B6] hover:underline"
          >
            Learn more →
          </a>
        </div>
        <div className="bg-white border border-gray-200 rounded-xl p-5 space-y-4">
          <label className="flex items-start gap-3 cursor-pointer">
            <input
              type="checkbox"
              checked={smExpanded}
              onChange={e => {
                const on = e.target.checked;
                setSmExpanded(on);
                if (!on) {
                  // Toggling OFF forces sustained_majority_enabled_default
                  // to false org-wide regardless of any previous value.
                  // Other SM keys are left in the settings object so that
                  // re-enabling restores the previously-saved values.
                  updateSetting('sustained_majority_enabled_default', false);
                } else {
                  // Toggling ON: seed any missing keys with defaults so
                  // the controls render with sane values.
                  setSettings(prev => {
                    const next = { ...prev };
                    SM_KEYS.forEach(k => {
                      if (next[k] === undefined || next[k] === null) {
                        next[k] = SM_DEFAULTS[k];
                      }
                    });
                    return next;
                  });
                }
              }}
              className="mt-0.5 accent-[#2E75B6]"
            />
            <div>
              <p className="text-sm text-gray-700">Enable sustained-majority voting</p>
              <p className="text-xs text-gray-400">
                Off by default. Enable only if your organization makes binding
                decisions that require durable consensus protection. Most groups
                don't need this — the standard pass-threshold check at voting
                close handles routine decisions correctly.
              </p>
            </div>
          </label>

          {smExpanded && (
            <div className="space-y-4 pt-2 border-t border-gray-100">
              <label className="flex items-start gap-3 cursor-pointer">
                <input
                  type="checkbox"
                  checked={settings.sustained_majority_enabled_default ?? false}
                  onChange={e => updateSetting('sustained_majority_enabled_default', e.target.checked)}
                  className="mt-0.5 accent-[#2E75B6]"
                />
                <div>
                  <p className="text-sm text-gray-700">Default on for new proposals</p>
                  <p className="text-xs text-gray-400">
                    When enabled, new proposals use sustained-majority unless the author opts out.
                  </p>
                </div>
              </label>

              <label className="flex items-start gap-3 cursor-pointer">
                <input
                  type="checkbox"
                  checked={settings.sustained_majority_per_proposal_override ?? true}
                  onChange={e => updateSetting('sustained_majority_per_proposal_override', e.target.checked)}
                  className="mt-0.5 accent-[#2E75B6]"
                />
                <div>
                  <p className="text-sm text-gray-700">Allow proposal authors to override per-proposal</p>
                  <p className="text-xs text-gray-400">
                    Authors can opt a single proposal in or out, overriding the org default above.
                  </p>
                </div>
              </label>

              <div>
                <label className="block text-xs text-gray-500 mb-1">
                  Required support level: {Math.round((settings.sustained_majority_threshold ?? 0.5) * 100)}%
                </label>
                <p className="text-xs text-gray-400 mb-1">The headline support level the proposal must reach to pass.</p>
                <input
                  type="range"
                  min={0}
                  max={100}
                  value={Math.round((settings.sustained_majority_threshold ?? 0.5) * 100)}
                  onChange={e => updateSetting('sustained_majority_threshold', parseInt(e.target.value) / 100)}
                  className="w-full accent-[#2E75B6]"
                />
              </div>

              <div>
                <label className="block text-xs text-gray-500 mb-1">
                  Drop-below floor: {Math.round((settings.sustained_majority_floor ?? 0.45) * 100)}%
                </label>
                <p className="text-xs text-gray-400 mb-1">
                  If support drops below this level during voting, the configured failure mode triggers.
                </p>
                <input
                  type="range"
                  min={0}
                  max={100}
                  value={Math.round((settings.sustained_majority_floor ?? 0.45) * 100)}
                  onChange={e => updateSetting('sustained_majority_floor', parseInt(e.target.value) / 100)}
                  className="w-full accent-[#2E75B6]"
                />
              </div>

              <div>
                <p className="text-xs text-gray-500 mb-2">When the floor is breached:</p>
                <div className="space-y-2">
                  {[
                    { value: 'fail', label: 'Fail immediately',
                      desc: 'The proposal moves to "failed" the moment support dips below the floor.' },
                    { value: 'extend', label: 'Extend the voting window once',
                      desc: 'Push voting_end forward to give voters time to recover support. A second breach fails.' },
                    { value: 'escalate', label: 'Escalate to admin review',
                      desc: 'The proposal moves to "unresolved" and an admin chooses how to resolve.' },
                  ].map(opt => (
                    <label key={opt.value} className="flex items-start gap-3 cursor-pointer">
                      <input
                        type="radio"
                        name="sustainedMajorityFailureMode"
                        value={opt.value}
                        checked={(settings.sustained_majority_failure_mode ?? 'fail') === opt.value}
                        onChange={() => updateSetting('sustained_majority_failure_mode', opt.value)}
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
          )}
        </div>
      </section>

      {/* Deliberation (Phase 9) */}
      <section className="space-y-3">
        <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide">Deliberation</h2>
        <div className="bg-white border border-gray-200 rounded-xl p-5 space-y-3">
          <label className="flex items-start gap-3 cursor-pointer">
            <input
              type="checkbox"
              checked={settings.require_polis_for_new_proposals ?? false}
              onChange={e => updateSetting('require_polis_for_new_proposals', e.target.checked)}
              className="mt-0.5 accent-[#2E75B6]"
            />
            <div>
              <p className="text-sm text-gray-700">Require linked Polis for new proposals</p>
              <p className="text-xs text-gray-400">
                Most small orgs leave this off; larger orgs that want structured deliberation as norm turn it on.
              </p>
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

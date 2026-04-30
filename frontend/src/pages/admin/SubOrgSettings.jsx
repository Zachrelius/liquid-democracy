import { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import api from '../../api';
import useSubOrg from '../../useSubOrg';
import { useOrg } from '../../OrgContext';
import { useToast } from '../../components/Toast';
import { useConfirm } from '../../components/ConfirmDialog';
import SubOrgErrorState from '../../components/SubOrgErrorState';

const SM_DEFAULTS = {
  sustained_majority_enabled_default: false,
  sustained_majority_per_proposal_override: true,
  sustained_majority_threshold: 0.5,
  sustained_majority_floor: 0.45,
  sustained_majority_failure_mode: 'fail',
};

const SM_KEYS = Object.keys(SM_DEFAULTS);

const VOTING_METHODS = ['binary', 'approval', 'ranked_choice'];

/**
 * Phase 8.5 — Sub-Org Settings page.
 *
 * Sections:
 *   1. Identity (name, description) — PATCH name/description
 *   2. Visibility — `settings.private` toggle
 *   3. Cross-scope delegations — `settings.reject_non_member_delegations`
 *   4. Voting methods override — `settings.allowed_voting_methods` (with
 *      "inherit" mode = key absent so `get_org_config` walks the parent chain)
 *   5. Sustained-majority override — five keys, each independently
 *      overridable. "Inherit" sends null so parent value applies.
 *   6. Danger zone — delete, blocked when topics/proposals exist.
 */
export default function SubOrgSettings() {
  const { parentSlug, subSlug, subOrg, loading, error, reload } = useSubOrg();
  const { currentOrg, invalidateSubOrgs, refreshOrgs } = useOrg();
  const toast = useToast();
  const confirm = useConfirm();
  const navigate = useNavigate();

  // Identity form
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');

  // Settings form
  const [privateFlag, setPrivateFlag] = useState(false);
  const [rejectNonMember, setRejectNonMember] = useState(false);

  // Voting methods override (null = inherit)
  const [vmOverride, setVmOverride] = useState(false);
  const [vmList, setVmList] = useState(['binary']);

  // Deliberation (Phase 9) — `require_polis_for_new_proposals` follows the
  // same per-key inherit/override pattern as the SM keys.
  const [requirePolisOverride, setRequirePolisOverride] = useState(false);
  const [requirePolisValue, setRequirePolisValue] = useState(false);

  // Sustained-majority overrides — per-key boolean "override"
  const [smOverrides, setSmOverrides] = useState({}); // {key: bool}
  const [smValues, setSmValues] = useState({}); // {key: value}

  // Topic/proposal counts for delete gating
  const [topicCount, setTopicCount] = useState(0);
  const [proposalCount, setProposalCount] = useState(0);
  const [saving, setSaving] = useState(false);

  // Parent settings (for "inherit" placeholder display)
  const [parentSettings, setParentSettings] = useState({});

  useEffect(() => {
    if (!subOrg) return;
    setName(subOrg.name);
    setDescription(subOrg.description || '');
    const s = subOrg.settings || {};
    setPrivateFlag(!!s.private);
    setRejectNonMember(!!s.reject_non_member_delegations);

    // Voting methods override is "on" iff the key exists in sub-org settings.
    if (Array.isArray(s.allowed_voting_methods)) {
      setVmOverride(true);
      setVmList(s.allowed_voting_methods);
    } else {
      setVmOverride(false);
      setVmList(['binary']);
    }

    // Sustained-majority — per-key
    const overs = {}, vals = {};
    SM_KEYS.forEach(k => {
      if (Object.prototype.hasOwnProperty.call(s, k)) {
        overs[k] = true;
        vals[k] = s[k];
      } else {
        overs[k] = false;
        vals[k] = SM_DEFAULTS[k];
      }
    });
    setSmOverrides(overs);
    setSmValues(vals);

    // Deliberation (Phase 9) — sub-org override on require_polis_for_new_proposals.
    if (Object.prototype.hasOwnProperty.call(s, 'require_polis_for_new_proposals')) {
      setRequirePolisOverride(true);
      setRequirePolisValue(!!s.require_polis_for_new_proposals);
    } else {
      setRequirePolisOverride(false);
      setRequirePolisValue(false);
    }
  }, [subOrg]);

  // Fetch topic/proposal counts under this sub-org (for delete gate).
  useEffect(() => {
    if (!parentSlug || !subOrg) return;
    let cancelled = false;
    (async () => {
      try {
        const [topics, props] = await Promise.all([
          api.get(`/api/orgs/${parentSlug}/topics`),
          api.get(`/api/orgs/${parentSlug}/proposals`),
        ]);
        if (cancelled) return;
        setTopicCount((topics || []).filter(t => t.sub_org_id === subOrg.id).length);
        setProposalCount((props || []).filter(p => p.sub_org_id === subOrg.id).length);
      } catch { /* leave as 0 */ }
    })();
    return () => { cancelled = true; };
  }, [parentSlug, subOrg]);

  // Pull parent settings for inherited-value placeholders. Only attempts when
  // the user has at least read access to the parent (which they must, since
  // they're an active parent-org member or admin of *something*).
  useEffect(() => {
    if (!parentSlug) return;
    let cancelled = false;
    (async () => {
      try {
        const data = await api.get(`/api/orgs/${parentSlug}`);
        if (!cancelled) setParentSettings(data?.settings || {});
      } catch { /* ignore — placeholders fall back to defaults */ }
    })();
    return () => { cancelled = true; };
  }, [parentSlug]);

  if (loading) return (
    <div className="flex justify-center items-center py-20">
      <div className="animate-spin w-8 h-8 border-4 border-[#2E75B6] border-t-transparent rounded-full"></div>
    </div>
  );
  if (error || !subOrg) return <SubOrgErrorState error={error} />;

  const inheritedVotingMethods = parentSettings?.allowed_voting_methods || ['binary'];

  function inheritedSmValue(key) {
    if (Object.prototype.hasOwnProperty.call(parentSettings, key)) return parentSettings[key];
    return SM_DEFAULTS[key];
  }

  function toggleVotingMethod(method, on) {
    setVmList(prev => {
      const next = on ? Array.from(new Set([...prev, method])) : prev.filter(m => m !== method);
      // Always keep binary in the list (server allows binary always).
      if (!next.includes('binary')) next.push('binary');
      return next;
    });
  }

  // Build the settings payload. Convention from Session 2: PATCH merges the
  // settings object on the server, so to "remove" a key we set it to null.
  // The backend `get_org_config` walks the parent chain when a key is null
  // OR absent, so null is fine.
  function buildSettingsPayload() {
    const payload = {
      private: privateFlag,
      reject_non_member_delegations: rejectNonMember,
    };
    // Voting methods
    if (vmOverride) {
      payload.allowed_voting_methods = vmList;
    } else {
      payload.allowed_voting_methods = null;
    }
    // Sustained-majority
    SM_KEYS.forEach(k => {
      if (smOverrides[k]) {
        payload[k] = smValues[k];
      } else {
        payload[k] = null;
      }
    });
    // Deliberation (Phase 9) — sub-org override on require_polis_for_new_proposals.
    payload.require_polis_for_new_proposals = requirePolisOverride
      ? !!requirePolisValue
      : null;
    return payload;
  }

  async function handleSave() {
    setSaving(true);
    try {
      await api.patch(`/api/orgs/${parentSlug}/sub-orgs/${subSlug}`, {
        name,
        description,
        settings: buildSettingsPayload(),
      });
      toast.success('Settings saved');
      invalidateSubOrgs(parentSlug);
      reload();
      // If the user renamed the currently active sub-org, refresh org list so
      // the nav reflects it.
      if (currentOrg?.id === subOrg.id) refreshOrgs();
    } catch (e) {
      toast.error(e.message || 'Failed to save');
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete() {
    const ok = await confirm({
      title: `Delete ${subOrg.name}?`,
      message: 'This permanently removes the sub-organization and its memberships. This action cannot be undone.',
      destructive: true,
    });
    if (!ok) return;
    try {
      await api.delete(`/api/orgs/${parentSlug}/sub-orgs/${subSlug}`);
      toast.success('Sub-organization deleted');
      invalidateSubOrgs(parentSlug);
      // If we were scoped here, drop back to parent.
      if (currentOrg?.id === subOrg.id) {
        localStorage.removeItem('currentOrgSlug');
        await refreshOrgs();
      }
      navigate('/admin/sub-orgs');
    } catch (e) {
      // 409 = topic/proposal still exists (race)
      toast.error(e.message || 'Failed to delete');
    }
  }

  const deleteBlocked = topicCount > 0 || proposalCount > 0;

  return (
    <div className="max-w-3xl mx-auto px-4 py-8 space-y-10">
      <div>
        <p className="text-xs text-gray-400 mb-1">
          <Link to="/admin/sub-orgs" className="hover:underline">Sub-organizations</Link>
          {' / '}
          <span>{subOrg.name}</span>
        </p>
        <h1 className="text-2xl font-semibold text-[#1B3A5C]">{subOrg.name} — Settings</h1>
      </div>

      {/* Identity */}
      <section className="space-y-3">
        <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide">Identity</h2>
        <div className="bg-white border border-gray-200 rounded-xl p-5 space-y-4">
          <div>
            <label className="block text-xs text-gray-500 mb-1">Name</label>
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
          <p className="text-xs text-gray-400">Slug <code className="bg-gray-100 px-1.5 py-0.5 rounded">{subOrg.slug}</code> is fixed at creation.</p>
        </div>
      </section>

      {/* Visibility */}
      <section className="space-y-3">
        <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide">Visibility</h2>
        <div className="bg-white border border-gray-200 rounded-xl p-5 space-y-2">
          <label className="flex items-start gap-3 cursor-pointer">
            <input
              type="checkbox"
              checked={privateFlag}
              onChange={e => setPrivateFlag(e.target.checked)}
              className="mt-0.5 accent-[#2E75B6]"
            />
            <div>
              <p className="text-sm text-gray-700">Make sub-org content visible only to members</p>
              <p className="text-xs text-gray-400">
                When off (default), parent-org members see this sub-org's proposals
                and topics in read-only mode. When on, only members and parent-org
                admins can see them.
              </p>
            </div>
          </label>
        </div>
      </section>

      {/* Cross-scope delegations */}
      <section className="space-y-3">
        <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide">Cross-Scope Delegations</h2>
        <div className="bg-white border border-gray-200 rounded-xl p-5 space-y-2">
          <label className="flex items-start gap-3 cursor-pointer">
            <input
              type="checkbox"
              checked={rejectNonMember}
              onChange={e => setRejectNonMember(e.target.checked)}
              className="mt-0.5 accent-[#2E75B6]"
            />
            <div>
              <p className="text-sm text-gray-700">Reject delegations from non-members on this sub-org's topics</p>
              <p className="text-xs text-gray-400">
                By default, a parent-org member who picked a non-member delegate can
                still inherit that delegate's vote on this sub-org's topics. Turning
                this on causes those delegations to fall back to the delegator's
                chain-behavior preference instead.
              </p>
            </div>
          </label>
        </div>
      </section>

      {/* Voting methods override */}
      <section className="space-y-3">
        <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide">Voting Methods Override</h2>
        <div className="bg-white border border-gray-200 rounded-xl p-5 space-y-3">
          <label className="flex items-start gap-3 cursor-pointer">
            <input
              type="checkbox"
              checked={vmOverride}
              onChange={e => setVmOverride(e.target.checked)}
              className="mt-0.5 accent-[#2E75B6]"
            />
            <div>
              <p className="text-sm text-gray-700">Override allowed voting methods for this sub-org</p>
              <p className="text-xs text-gray-400">
                Inherits from parent: <strong>{inheritedVotingMethods.join(', ')}</strong>
              </p>
            </div>
          </label>
          {vmOverride && (
            <div className="pl-7 space-y-2">
              {VOTING_METHODS.map(m => (
                <label key={m} className={`flex items-center gap-2 ${m === 'binary' ? 'opacity-70' : 'cursor-pointer'}`}>
                  <input
                    type="checkbox"
                    checked={vmList.includes(m)}
                    disabled={m === 'binary'}
                    onChange={e => toggleVotingMethod(m, e.target.checked)}
                    className="accent-[#2E75B6]"
                  />
                  <span className="text-sm text-gray-700">
                    {m === 'binary' ? 'Binary (always enabled)' : m === 'approval' ? 'Approval' : 'Ranked Choice'}
                  </span>
                </label>
              ))}
            </div>
          )}
        </div>
      </section>

      {/* Sustained-majority overrides */}
      <section className="space-y-3">
        <div className="flex items-baseline justify-between">
          <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide">Sustained-Majority Override</h2>
          <a href="/help/sustained-majority" target="_blank" rel="noreferrer" className="text-xs text-[#2E75B6] hover:underline">
            Learn more →
          </a>
        </div>
        <div className="bg-white border border-gray-200 rounded-xl p-5 space-y-5">
          <p className="text-xs text-gray-500">
            Each setting can inherit from the parent or be overridden here. Toggle
            "Override" to set a value just for this sub-org.
          </p>

          <SmRow
            label="Default on for new proposals"
            keyName="sustained_majority_enabled_default"
            kind="bool"
            override={smOverrides.sustained_majority_enabled_default}
            value={smValues.sustained_majority_enabled_default}
            inherited={inheritedSmValue('sustained_majority_enabled_default')}
            setOverride={v => setSmOverrides(p => ({ ...p, sustained_majority_enabled_default: v }))}
            setValue={v => setSmValues(p => ({ ...p, sustained_majority_enabled_default: v }))}
          />
          <SmRow
            label="Allow per-proposal override"
            keyName="sustained_majority_per_proposal_override"
            kind="bool"
            override={smOverrides.sustained_majority_per_proposal_override}
            value={smValues.sustained_majority_per_proposal_override}
            inherited={inheritedSmValue('sustained_majority_per_proposal_override')}
            setOverride={v => setSmOverrides(p => ({ ...p, sustained_majority_per_proposal_override: v }))}
            setValue={v => setSmValues(p => ({ ...p, sustained_majority_per_proposal_override: v }))}
          />
          <SmRow
            label="Required support level"
            keyName="sustained_majority_threshold"
            kind="percent"
            override={smOverrides.sustained_majority_threshold}
            value={smValues.sustained_majority_threshold}
            inherited={inheritedSmValue('sustained_majority_threshold')}
            setOverride={v => setSmOverrides(p => ({ ...p, sustained_majority_threshold: v }))}
            setValue={v => setSmValues(p => ({ ...p, sustained_majority_threshold: v }))}
          />
          <SmRow
            label="Drop-below floor"
            keyName="sustained_majority_floor"
            kind="percent"
            override={smOverrides.sustained_majority_floor}
            value={smValues.sustained_majority_floor}
            inherited={inheritedSmValue('sustained_majority_floor')}
            setOverride={v => setSmOverrides(p => ({ ...p, sustained_majority_floor: v }))}
            setValue={v => setSmValues(p => ({ ...p, sustained_majority_floor: v }))}
          />
          <SmRow
            label="Failure mode"
            keyName="sustained_majority_failure_mode"
            kind="failure_mode"
            override={smOverrides.sustained_majority_failure_mode}
            value={smValues.sustained_majority_failure_mode}
            inherited={inheritedSmValue('sustained_majority_failure_mode')}
            setOverride={v => setSmOverrides(p => ({ ...p, sustained_majority_failure_mode: v }))}
            setValue={v => setSmValues(p => ({ ...p, sustained_majority_failure_mode: v }))}
          />
        </div>
      </section>

      {/* Deliberation (Phase 9) */}
      <section className="space-y-3">
        <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide">Deliberation</h2>
        <div className="bg-white border border-gray-200 rounded-xl p-5 space-y-3">
          <p className="text-xs text-gray-500">
            Inherits from parent: <strong>{parentSettings?.require_polis_for_new_proposals ? 'on' : 'off'}</strong>
          </p>
          <label className="flex items-start gap-3 cursor-pointer">
            <input
              type="checkbox"
              checked={!requirePolisOverride}
              onChange={e => setRequirePolisOverride(!e.target.checked)}
              className="mt-0.5 accent-[#2E75B6]"
            />
            <div>
              <p className="text-sm text-gray-700">Use parent default</p>
              <p className="text-xs text-gray-400">
                Walk up to the parent org for this setting. Uncheck to set an explicit value here.
              </p>
            </div>
          </label>
          {requirePolisOverride && (
            <label className="flex items-start gap-3 cursor-pointer pl-6">
              <input
                type="checkbox"
                checked={!!requirePolisValue}
                onChange={e => setRequirePolisValue(e.target.checked)}
                className="mt-0.5 accent-[#2E75B6]"
              />
              <div>
                <p className="text-sm text-gray-700">Require linked Polis for new proposals</p>
                <p className="text-xs text-gray-400">
                  Most small orgs leave this off; larger orgs that want structured deliberation as norm turn it on.
                </p>
              </div>
            </label>
          )}
        </div>
      </section>

      {/* Save */}
      <div className="flex items-center gap-3">
        <button
          onClick={handleSave}
          disabled={saving}
          className="px-6 py-2 bg-[#1B3A5C] text-white text-sm rounded-lg hover:bg-[#2E75B6] transition-colors disabled:opacity-50"
        >
          {saving ? 'Saving...' : 'Save Settings'}
        </button>
      </div>

      {/* Danger zone */}
      <section className="space-y-3">
        <h2 className="text-sm font-semibold text-red-500 uppercase tracking-wide">Danger Zone</h2>
        <div className="bg-white border border-red-200 rounded-xl p-5 space-y-3">
          <div className="text-xs text-gray-500">
            <p>Topics scoped to this sub-org: <strong>{topicCount}</strong></p>
            <p>Proposals scoped to this sub-org: <strong>{proposalCount}</strong></p>
          </div>
          <button
            onClick={handleDelete}
            disabled={deleteBlocked}
            title={deleteBlocked
              ? 'Move or delete all sub-org-scoped topics and proposals first.'
              : 'Permanently delete this sub-organization.'}
            className="text-sm px-4 py-2 border border-red-300 text-red-600 rounded-lg hover:bg-red-50 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            Delete Sub-Organization
          </button>
          {deleteBlocked && (
            <p className="text-xs text-amber-600">
              This sub-org has scoped content. Promote scoped topics to org-wide, or
              archive scoped proposals, before deleting.
            </p>
          )}
        </div>
      </section>
    </div>
  );
}

function SmRow({ label, keyName, kind, override, value, inherited, setOverride, setValue }) {
  return (
    <div className="border-b border-gray-100 last:border-0 pb-4 last:pb-0">
      <div className="flex items-baseline gap-3 mb-1">
        <label className="flex items-center gap-2 cursor-pointer">
          <input
            type="checkbox"
            checked={!!override}
            onChange={e => setOverride(e.target.checked)}
            className="accent-[#2E75B6]"
          />
          <span className="text-sm text-gray-700">Override</span>
        </label>
        <span className="text-sm text-gray-700">— {label}</span>
        <span className="text-xs text-gray-400">
          (inherits: {kind === 'percent' ? `${Math.round((inherited ?? 0) * 100)}%`
            : kind === 'bool' ? (inherited ? 'on' : 'off')
            : String(inherited)})
        </span>
      </div>
      {override && (
        <div className="pl-6">
          {kind === 'bool' && (
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={!!value}
                onChange={e => setValue(e.target.checked)}
                className="accent-[#2E75B6]"
              />
              <span className="text-xs text-gray-600">{value ? 'On' : 'Off'}</span>
            </label>
          )}
          {kind === 'percent' && (
            <div>
              <p className="text-xs text-gray-500 mb-1">{Math.round((value ?? 0) * 100)}%</p>
              <input
                type="range"
                min={0}
                max={100}
                value={Math.round((value ?? 0) * 100)}
                onChange={e => setValue(parseInt(e.target.value, 10) / 100)}
                className="w-full max-w-xs accent-[#2E75B6]"
              />
            </div>
          )}
          {kind === 'failure_mode' && (
            <div className="space-y-1">
              {[
                { value: 'fail', label: 'Fail immediately' },
                { value: 'extend', label: 'Extend window once' },
                { value: 'escalate', label: 'Escalate to admin review' },
              ].map(opt => (
                <label key={opt.value} className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="radio"
                    name={keyName}
                    value={opt.value}
                    checked={value === opt.value}
                    onChange={() => setValue(opt.value)}
                    className="accent-[#2E75B6]"
                  />
                  <span className="text-xs text-gray-700">{opt.label}</span>
                </label>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

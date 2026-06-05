import { useState, useEffect, useRef } from 'react';
import { useOrg } from '../../OrgContext';
import api from '../../api';
import { useToast } from '../../components/Toast';
import { useConfirm } from '../../components/ConfirmDialog';
import NewStewardPointer from '../../components/NewStewardPointer';
import OrgTitlesPanel from '../../components/OrgTitlesPanel';
import PendingActionsBanner from '../../components/PendingActionsBanner';
// Phase 12.5 F4 — Default-thresholds editor gates on `org.edit_settings`.
// Phase 12.7 F4 — Branding section gates on `org.edit_branding`.
import { useHasPermission } from '../../hooks/useHasPermission';
// Phase 12.7 F4 — auto-derived accent + dark variant share the F3 utility.
import { getDerivedAccent } from '../../utils/color_derive';
// Phase 14 F3 — intro_text editor renders a live markdown preview using the
// same renderer as proposal bodies, so what stewards see here matches what
// renders on the public landing page.
import renderMarkdown from '../../utils/renderMarkdown';

// Phase 14 F3 — public landing page intro text length cap. Matches the
// backend B4 cap (5000 chars; a longer payload returns 400). Enforcing it
// client-side keeps the textarea + counter honest without round-tripping
// every keystroke.
const INTRO_TEXT_MAX = 5000;
// Phase 56 F5 — topic guidance is markdown, same max as intro_text.
const TOPIC_GUIDANCE_MAX = 5000;

// Phase 20 — Stable Result Required (renamed from "sustained-majority").
// Defaults mirror the backend's StableResultConfig defaults (see
// backend/sustained_majority.py). The old SM keys (floor / failure_mode /
// threshold) are removed from the schema; orgs that have those keys set
// from earlier phases simply have them silently ignored.
const SR_DEFAULTS = {
  stable_result_enabled_default: false,
  stable_result_per_proposal_override: true,
  stable_window_fraction: 0.25,
  max_extension_fraction: 0.25,
};
const SR_KEYS = Object.keys(SR_DEFAULTS);

// True if any SR key is present in settings AND differs from its default.
// Used to derive the section-expanded state from existing settings.
// Backwards compat: also expand if the legacy
// sustained_majority_enabled_default key was present and on (so an org
// that previously had the feature enabled doesn't see the section
// silently collapse to "off" after the rename).
function srIsCustomized(settings) {
  if (!settings) return false;
  if (settings.sustained_majority_enabled_default === true) return true;
  return SR_KEYS.some(k => {
    if (!Object.prototype.hasOwnProperty.call(settings, k)) return false;
    return settings[k] !== SR_DEFAULTS[k];
  });
}

// Phase 20 helper — humanize a duration (seconds) to a short string for
// the slider helper text. Output samples:
//   86400 -> "1 day"
//   3600  -> "1 hour"
//   1800  -> "30 minutes"
//   151200 -> "1 day 18 hours"
function formatDuration(seconds) {
  const s = Math.max(0, Math.round(seconds));
  if (s < 60) return `${s} second${s === 1 ? '' : 's'}`;
  if (s < 3600) {
    const m = Math.round(s / 60);
    return `${m} minute${m === 1 ? '' : 's'}`;
  }
  if (s < 86400) {
    const h = Math.floor(s / 3600);
    const m = Math.round((s % 3600) / 60);
    if (m === 0) return `${h} hour${h === 1 ? '' : 's'}`;
    return `${h} hour${h === 1 ? '' : 's'} ${m} minute${m === 1 ? '' : 's'}`;
  }
  const d = Math.floor(s / 86400);
  const h = Math.round((s % 86400) / 3600);
  if (h === 0) return `${d} day${d === 1 ? '' : 's'}`;
  return `${d} day${d === 1 ? '' : 's'} ${h} hour${h === 1 ? '' : 's'}`;
}

// Phase 12.7 F4 — platform default colors (used for the picker initial
// value when the org has not yet customized branding). Must match the
// :root defaults in index.css so the picker reflects "what is currently
// rendering" before any explicit pick.
const PLATFORM_PRIMARY_DEFAULT = '#1B3A5C';
const PLATFORM_ACCENT_DEFAULT = '#2E75B6';

// Phase 12.7 F4 — basic hex validator for the synced hex text inputs.
// The native <input type="color"> always emits a valid #RRGGBB so the
// validator only matters on the text-input path. Backend (B2) also
// validates server-side; this is a UX nicety to disable Save on bad input.
function isValidHex(hex) {
  return typeof hex === 'string' && /^#[0-9a-fA-F]{6}$/.test(hex);
}

// Phase 17 F1 — Tie Resolution section.
//
// Eligible methods per voting method, in spec D3 dropdown order. Method
// values match the backend tie_resolution.py constants exactly; the
// labels + descriptions are the user-facing copy from the help page so
// the dropdown microcopy and the help-page details stay in sync.
//
// Platform defaults (D4): approval=broader_approval_base,
// ranked_choice=random_seed. The frontend pre-populates with these when
// settings.tie_resolution[voting_method] is absent so the dropdowns
// always reflect what the backend would actually do.
const TIE_RESOLUTION_DEFAULT_APPROVAL = 'broader_approval_base';
const TIE_RESOLUTION_DEFAULT_RANKED_CHOICE = 'random_seed';

// Phase 32.2 — 4-option mode radio group for the deliberation-
// engagement settings. Surfaces the four enum-mode states with the
// canonical labels per spec D7. Used by the Write-ins + Pre-voting
// subsections under "Proposal Defaults — Deliberation Engagement".
const MODE_OPTIONS = [
  { value: 'always_off', label: 'Always off', help: 'Locked off org-wide. Members cannot enable on individual proposals.' },
  { value: 'default_off', label: 'Default off (members can opt in per proposal)', help: 'Off by default; proposal authors can turn it on at create time.' },
  { value: 'default_on', label: 'Default on (members can opt out per proposal)', help: 'On by default; proposal authors can turn it off at create time.' },
  { value: 'always_on', label: 'Always on', help: 'Locked on org-wide. Members cannot disable on individual proposals.' },
];

function ModeRadioGroup({ label, help, value, onChange }) {
  return (
    <fieldset className="space-y-1">
      <legend className="text-sm text-gray-700 font-medium">{label}</legend>
      {help && <p className="text-xs text-gray-400 mb-1">{help}</p>}
      <div className="space-y-1 pl-1">
        {MODE_OPTIONS.map(opt => (
          <label key={opt.value} className="flex items-start gap-2 cursor-pointer">
            <input
              type="radio"
              name={label}
              value={opt.value}
              checked={value === opt.value}
              onChange={() => onChange(opt.value)}
              className="mt-0.5 accent-[var(--brand-accent)]"
            />
            <span className="text-xs text-gray-700">
              {opt.label}
              <span className="block text-[10px] text-gray-400">{opt.help}</span>
            </span>
          </label>
        ))}
      </div>
    </fieldset>
  );
}

const TIE_METHODS_APPROVAL = [
  {
    value: 'broader_approval_base',
    label: 'Broader approval base',
    desc: 'Tied options are compared by how broadly each is co-approved. The most cross-supported option wins.',
  },
  {
    value: 'expand_winners',
    label: 'Expand winners (seat all tied)',
    desc: 'All tied options become winners (the proposal closes with multiple winners).',
  },
  {
    value: 'earliest_decisive_vote',
    label: 'Earliest decisive vote',
    desc: 'The tied option whose support reached its final count earliest wins.',
  },
  {
    value: 'random_seed',
    label: 'Random with seed',
    desc: "A deterministic random selection using the proposal's ID and end time. Verifiable by anyone.",
  },
];

const TIE_METHODS_RANKED_CHOICE = [
  {
    value: 'expand_winners',
    label: 'Expand winners (seat all tied)',
    desc: 'All tied options become winners (the proposal closes with multiple winners).',
  },
  {
    value: 'earliest_decisive_vote',
    label: 'Earliest decisive vote',
    desc: 'The tied option whose support reached its final count earliest wins.',
  },
  {
    value: 'random_seed',
    label: 'Random with seed',
    desc: "A deterministic random selection using the proposal's ID and end time. Verifiable by anyone.",
  },
];

export default function OrgSettings() {
  const { currentOrg, refreshOrgs } = useOrg();
  const toast = useToast();
  const confirm = useConfirm();
  // Phase 12.5 F4 — Default Approval Thresholds editor visibility.
  const canEditOrgSettings = useHasPermission('org.edit_settings');
  // Phase 12.7 F4 — Branding section visibility. The 'org.edit_branding'
  // permission key has existed in the registry since Stage 1 (defaults to
  // Steward + Admin). This is the UI that finally consumes it.
  const canEditBranding = useHasPermission('org.edit_branding');
  // Phase 12 Stage 2 F7 — D4 hardcoded-gate UI hiding.
  // org.delete is an OWNER_ONLY_KEY: backend grants it iff the caller's
  // role.system_key == 'steward'. Phase 45a F1 switches this gate to the
  // permission-driven check so the UI tracks any future relaxation
  // (recon GAP-5).
  const canDeleteOrg = useHasPermission('org.delete');
  // Phase 45a F2 — voluntary stewardship handoff. Same OWNER_ONLY_KEY
  // pattern: only the Steward currently resolves the permission to True.
  const canTransferStewardship = useHasPermission('org.transfer_stewardship');
  // Phase 45b F1 — Governance mode controls. The mode field surfaces on
  // currentOrg.governance_mode (default 'single_steward'). Mode switch
  // is gated by the actor's role on the backend (steward initiates the
  // switch to council; any admin initiates the revert). FE just gates
  // visibility of the appropriate control.
  const governanceMode = currentOrg?.governance_mode || 'single_steward';
  const userRole = currentOrg?.user_role;
  const canSwitchToCouncil = governanceMode === 'single_steward' && userRole === 'steward';
  const canRevertToSingle = governanceMode === 'admin_council' && userRole === 'admin';
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [joinPolicy, setJoinPolicy] = useState('approval_required');
  const [settings, setSettings] = useState({});
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState('');
  const [deleteConfirm, setDeleteConfirm] = useState('');
  const [showDelete, setShowDelete] = useState(false);

  // Phase 20 — Stable Result Required section is collapsed by default.
  // Local toggle state, derived from loaded settings: expanded if the
  // org has explicitly enabled the feature or customized any of the keys.
  const [srExpanded, setSrExpanded] = useState(false);
  // Phase 20 — local saving state for the per-section save button so the
  // SR section follows the Phase 16 F4 per-section save pattern rather
  // than relying on the General-section "Save Settings" button.
  const [savingSr, setSavingSr] = useState(false);
  // Phase 32.1 F3 — Deliberation Engagement section saving state.
  const [savingDelibEng, setSavingDelibEng] = useState(false);
  // Phase 32.2 F3/P1/P2 — Public Delegates section saving state +
  // disable-confirmation dialog state.
  const [savingPublicDelegates, setSavingPublicDelegates] = useState(false);
  const [pdDisableConfirm, setPdDisableConfirm] = useState(null);  // {count} or null
  // Phase 34 F1 — per-section saving state for Voting Defaults, Default
  // Approval Thresholds, Voting Methods.
  const [savingVotingDefaults, setSavingVotingDefaults] = useState(false);
  const [savingThresholds, setSavingThresholds] = useState(false);
  const [savingVotingMethods, setSavingVotingMethods] = useState(false);
  // Phase 44 F1 — Multi-admin approval section saving state.
  const [savingMultiAdminApproval, setSavingMultiAdminApproval] = useState(false);

  // Phase 12.7 F4 — Branding section local state.
  //
  // Logo lives entirely on the org object (currentOrg.branding.logo_url)
  // because the upload + delete endpoints are immediate-action (each call
  // refreshes the org and mutates the displayed preview). Colors are
  // staged locally so the steward can preview + cancel without
  // accidentally persisting an in-progress pick.
  //
  // autoDeriveAccent gates whether the accent picker is editable. When
  // ON, the displayed accent value follows getDerivedAccent(primary) and
  // submits as accent_color along with accent_auto_derived: true. When
  // OFF, the steward picks the accent freely.
  const [primaryColor, setPrimaryColor] = useState(PLATFORM_PRIMARY_DEFAULT);
  const [accentColor, setAccentColor] = useState(PLATFORM_ACCENT_DEFAULT);
  const [autoDeriveAccent, setAutoDeriveAccent] = useState(true);
  const [savingBranding, setSavingBranding] = useState(false);
  const [uploadingLogo, setUploadingLogo] = useState(false);
  const logoFileInputRef = useRef(null);

  // Phase 14 F3 — public landing page intro text.
  //
  // Persisted at Organization.settings.intro_text (string, capped at
  // INTRO_TEXT_MAX). The B4 PATCH /api/orgs/{slug}/branding endpoint
  // accepts intro_text alongside the existing color/logo fields, so we
  // reuse that endpoint for save (consistent with treating intro_text as
  // org self-presentation alongside branding, per spec).
  //
  // Empty string is treated as "no intro" — the public landing page hides
  // the section entirely when intro_text is empty/absent. We keep the
  // textarea editable regardless of policy so stewards can prepare
  // content before flipping their join_policy to a public variant.
  const [introText, setIntroText] = useState('');
  const [savingIntro, setSavingIntro] = useState(false);

  // Phase 56 F5 — org topic guidance editor state. Persisted at
  // Organization.settings.topic_guidance (markdown, max 5000 chars).
  // The renderer is the same one intro_text uses. Saved via the generic
  // PATCH /api/orgs/{slug} settings-merge so the backend's B4 length
  // validator catches over-cap submits.
  const [topicGuidance, setTopicGuidance] = useState('');
  const [savingTopicGuidance, setSavingTopicGuidance] = useState(false);

  // Phase 56 F4 — categories toggle. Boolean. When ON, topic management
  // + proposal-creation pickers group by category; when OFF, flat list
  // (but category values are retained on the rows so re-enabling
  // restores grouping).
  const [topicCategoriesEnabled, setTopicCategoriesEnabled] = useState(false);
  const [savingTopicCategories, setSavingTopicCategories] = useState(false);

  // Phase 45b F1 — Governance Mode section state. The revert flow needs
  // the active members list to pick a successor; the switch-to-council
  // flow does not (the steward demotes themselves).
  const [savingGovernanceMode, setSavingGovernanceMode] = useState(false);
  const [revertTargetId, setRevertTargetId] = useState('');
  const [revertMembers, setRevertMembers] = useState([]);
  const [loadingRevertMembers, setLoadingRevertMembers] = useState(false);

  // Phase 45a F2 — Transfer Stewardship section state.
  // The form is collapsed by default; expanding reveals a member picker
  // populated from /api/orgs/{slug}/members (active members only,
  // current user excluded — the steward cannot transfer to themselves).
  const [showTransfer, setShowTransfer] = useState(false);
  const [transferTargetId, setTransferTargetId] = useState('');
  const [transferMembers, setTransferMembers] = useState([]);
  const [loadingTransferMembers, setLoadingTransferMembers] = useState(false);
  const [savingTransfer, setSavingTransfer] = useState(false);

  // Phase 50 — Leave organization flow state. Two-step per D2: the
  // first click on Leave shows an informed-confirm dialog naming
  // what's lost; the second click submits. When the backend returns
  // 409 transfer_required (sole-governor case), the confirm dialog
  // is replaced with an inline "transfer first" picker that calls
  // the existing /transfer-stewardship endpoint, then the user
  // re-clicks Leave to complete.
  const [leaveStage, setLeaveStage] = useState('idle'); // 'idle' | 'confirm' | 'transfer_required'
  const [leaveTransferTargetId, setLeaveTransferTargetId] = useState('');
  const [leaveTransferMembers, setLeaveTransferMembers] = useState([]);
  const [leavingNow, setLeavingNow] = useState(false);

  // Phase 17 F1 — Tie Resolution section state.
  //
  // Staged locally so the steward can pick + cancel without persisting.
  // Hydrated in the same effect that sets `settings`, falling back to
  // platform defaults (D4) when the org's settings JSON omits the
  // tie_resolution dict or one of its keys. Save fires a PATCH against
  // /api/orgs/{slug} with `settings.tie_resolution = {approval,
  // ranked_choice}`; the backend B5 validator rejects invalid method
  // values with HTTP 400.
  const [tieApprovalMethod, setTieApprovalMethod] =
    useState(TIE_RESOLUTION_DEFAULT_APPROVAL);
  const [tieRankedChoiceMethod, setTieRankedChoiceMethod] =
    useState(TIE_RESOLUTION_DEFAULT_RANKED_CHOICE);
  const [savingTieResolution, setSavingTieResolution] = useState(false);

  useEffect(() => {
    if (currentOrg) {
      setName(currentOrg.name);
      setDescription(currentOrg.description || '');
      // Phase 14 F3 — the join_policy enum expanded from {invite_only,
      // approval_required, open} to {invite_only_secret, invite_only_public,
      // approval_required, open}. The backend B1 migration renames legacy
      // 'invite_only' rows to 'invite_only_secret', and B5 rejects the old
      // value going forward.
      //
      // Phase 15 G6b (2026-05-06) — the defensive client-side coercion
      // 'invite_only' → 'invite_only_secret' was removed under Z's
      // calendar-gate waiver for this pass. Single-user reality means the
      // cached-bundle population the coercion was protecting is zero, and
      // the migration has long since renamed legacy rows. Phase 14 tech
      // debt #3 closed.
      setJoinPolicy(currentOrg.join_policy);
      const s = currentOrg.settings || {};
      setSettings(s);
      // Expand the SR section if the org currently has it on, or if any
      // SR key is customized away from the default.
      setSrExpanded(!!s.stable_result_enabled_default || srIsCustomized(s));
      // Branding state hydration. Backend B4 returns currentOrg.branding
      // as an object with possibly-null fields; missing object is treated
      // as "all unconfigured" -> use platform defaults in the pickers.
      //
      // accent_auto_derived UX policy: for orgs that have NEVER configured
      // branding (no primary set), default the checkbox to ON regardless
      // of what the backend reports — auto-derive is the recommended path
      // per spec D3. For orgs that HAVE configured a primary, respect the
      // backend's stored flag (true if they accepted the auto-derive when
      // they last saved, false if they explicitly set a custom accent).
      const b = currentOrg.branding || {};
      setPrimaryColor(b.primary_color || PLATFORM_PRIMARY_DEFAULT);
      const autoDer = b.primary_color
        ? b.accent_auto_derived !== false
        : true;
      setAutoDeriveAccent(autoDer);
      if (autoDer && b.primary_color) {
        // Show the derived accent so the disabled picker is truthful
        // about what would be saved.
        setAccentColor(getDerivedAccent(b.primary_color));
      } else {
        setAccentColor(b.accent_color || PLATFORM_ACCENT_DEFAULT);
      }
      // Phase 14 F3 — intro_text lives in settings JSON (B1 doesn't add a
      // schema column, just a documented key). Backend's get_intro_text
      // helper treats empty string as null, so we hydrate empty when the
      // field is missing/null.
      setIntroText(typeof s.intro_text === 'string' ? s.intro_text : '');
      // Phase 56 F4 + F5 — topic guidance + categories toggle. Both live
      // in settings JSON. Empty string for missing guidance; false for
      // missing toggle.
      setTopicGuidance(typeof s.topic_guidance === 'string' ? s.topic_guidance : '');
      setTopicCategoriesEnabled(!!s.topic_categories_enabled);

      // Phase 17 F1 — Tie resolution lives at settings.tie_resolution
      // {approval, ranked_choice}. Hydrate from the org's stored values
      // if present and eligible; otherwise platform defaults (D4). The
      // get_org_tie_resolution_method helper on the backend does the
      // exact same fallback so the dropdowns always reflect what the
      // backend would actually use.
      const tr = (s && typeof s.tie_resolution === 'object' && s.tie_resolution)
        || {};
      const approvalEligible = TIE_METHODS_APPROVAL.map(m => m.value);
      const rcEligible = TIE_METHODS_RANKED_CHOICE.map(m => m.value);
      setTieApprovalMethod(
        approvalEligible.includes(tr.approval)
          ? tr.approval
          : TIE_RESOLUTION_DEFAULT_APPROVAL,
      );
      setTieRankedChoiceMethod(
        rcEligible.includes(tr.ranked_choice)
          ? tr.ranked_choice
          : TIE_RESOLUTION_DEFAULT_RANKED_CHOICE,
      );
    }
  }, [currentOrg]);

  // Phase 12.7 F4 — when auto-derive is on AND primary changes, accent
  // updates in lockstep so the disabled accent picker reflects what would
  // be saved. Decoupled from the hydration effect so user-driven primary
  // edits also recompute accent live.
  useEffect(() => {
    if (autoDeriveAccent) {
      setAccentColor(getDerivedAccent(primaryColor));
    }
  }, [primaryColor, autoDeriveAccent]);

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

  // Phase 45b F1 — switch to council mode. Steward-only; the steward
  // atomically demotes to admin per D2.
  async function handleSwitchToCouncil() {
    const ok = await confirm({
      title: 'Switch to Admin Council mode?',
      message: (
        `You will become an Admin of "${currentOrg.name}" and the org will ` +
        `run on its admin council — no single Steward. Any admin can revert ` +
        `this later. The org's behavior outside this setting is otherwise ` +
        `unchanged.`
      ),
      destructive: true,
    });
    if (!ok) return;
    setSavingGovernanceMode(true);
    try {
      const res = await api.post(
        `/api/orgs/${currentOrg.slug}/governance-mode`,
        { mode: 'admin_council' },
      );
      toast.success('Now running on admin council — you are now an Admin');
      await refreshOrgs();
      return res;
    } catch (e) {
      toast.error(e.message || 'Failed to switch governance mode');
    } finally {
      setSavingGovernanceMode(false);
    }
  }

  async function loadRevertMembers() {
    if (!currentOrg) return;
    setLoadingRevertMembers(true);
    try {
      const all = await api.get(`/api/orgs/${currentOrg.slug}/members`);
      // Council revert needs an existing admin; filter accordingly.
      const eligible = (all || []).filter(
        m => m.status === 'active' && m.role === 'admin',
      );
      setRevertMembers(eligible);
    } catch (e) {
      toast.error(e.message || 'Failed to load admins');
    } finally {
      setLoadingRevertMembers(false);
    }
  }

  async function handleRevertToSingle() {
    const target = revertMembers.find(m => m.user_id === revertTargetId);
    const targetLabel = target ? (target.display_name || target.username) : 'you';
    const ok = await confirm({
      title: 'Revert to Single Steward?',
      message: (
        `${targetLabel === 'you' ? 'You' : targetLabel} will become the new ` +
        `Steward of "${currentOrg.name}" and the org will run on a single ` +
        `top officer again. Any admin can switch back later.`
      ),
      destructive: false,
    });
    if (!ok) return;
    setSavingGovernanceMode(true);
    try {
      const body = { mode: 'single_steward' };
      if (revertTargetId) body.successor_user_id = revertTargetId;
      const res = await api.post(
        `/api/orgs/${currentOrg.slug}/governance-mode`,
        body,
      );
      toast.success('Reverted to single-steward mode');
      await refreshOrgs();
      setRevertTargetId('');
      return res;
    } catch (e) {
      toast.error(e.message || 'Failed to revert governance mode');
    } finally {
      setSavingGovernanceMode(false);
    }
  }

  // Phase 45a F2 — fetch active members for the transfer picker. Triggered
  // when the steward expands the Transfer Stewardship section. We exclude
  // the calling user (cannot transfer to self per B3) and any inactive
  // members the backend may surface.
  async function loadTransferMembers() {
    if (!currentOrg) return;
    setLoadingTransferMembers(true);
    try {
      const all = await api.get(`/api/orgs/${currentOrg.slug}/members`);
      // currentOrg.user_role === 'steward' is the calling user by definition.
      // Filter on status === 'active' to match the backend gate.
      const eligible = (all || []).filter(m => m.status === 'active');
      setTransferMembers(eligible);
    } catch (e) {
      toast.error(e.message || 'Failed to load members');
    } finally {
      setLoadingTransferMembers(false);
    }
  }

  async function handleTransferStewardship() {
    if (!transferTargetId) return;
    const target = transferMembers.find(m => m.user_id === transferTargetId);
    const targetLabel = target ? (target.display_name || target.username) : 'this member';
    const ok = await confirm({
      title: 'Transfer Stewardship?',
      message: (
        `You will become an Admin of "${currentOrg.name}" and ${targetLabel} ` +
        `will become the new Steward. This is an atomic swap and cannot be undone from this side.`
      ),
      destructive: true,
    });
    if (!ok) return;
    setSavingTransfer(true);
    try {
      await api.post(`/api/orgs/${currentOrg.slug}/transfer-stewardship`, {
        target_user_id: transferTargetId,
      });
      toast.success(`Stewardship transferred to ${targetLabel}`);
      // Refresh org list so the user_role + user_permissions flip.
      await refreshOrgs();
      setShowTransfer(false);
      setTransferTargetId('');
    } catch (e) {
      toast.error(e.message || 'Failed to transfer stewardship');
    } finally {
      setSavingTransfer(false);
    }
  }

  // Phase 50 — Leave organization. Reuses the existing
  // /transfer-stewardship endpoint when the backend says
  // transfer_required (sole-governor case).
  async function loadLeaveTransferMembers() {
    try {
      const r = await api.get(`/api/orgs/${currentOrg.slug}/members`);
      const list = Array.isArray(r) ? r : (r?.members || []);
      setLeaveTransferMembers(
        list.filter(m => m.status !== 'pending' && m.user_id !== currentOrg?.user_id),
      );
    } catch (e) {
      toast.error('Failed to load members for handoff');
    }
  }

  async function submitLeave() {
    setLeavingNow(true);
    try {
      await api.post(`/api/orgs/${currentOrg.slug}/leave`, {});
      toast.success(`You've left ${currentOrg.name}.`);
      setLeaveStage('idle');
      await refreshOrgs();
      // The user is no longer a member — redirect to the org list.
      window.location.href = '/orgs';
    } catch (e) {
      // 409 transfer_required — switch to the inline transfer flow.
      const status = e?.status || e?.response?.status;
      const detail = e?.detail || e?.response?.data?.detail || {};
      if (status === 409 && detail?.error === 'transfer_required') {
        setLeaveStage('transfer_required');
        if (leaveTransferMembers.length === 0) {
          await loadLeaveTransferMembers();
        }
        toast.error(detail.detail || 'You need to hand off leadership first.');
      } else {
        toast.error(e.message || 'Failed to leave organization');
      }
    } finally {
      setLeavingNow(false);
    }
  }

  async function handleLeaveTransferThenRetry() {
    if (!leaveTransferTargetId) return;
    const target = leaveTransferMembers.find(
      m => m.user_id === leaveTransferTargetId,
    );
    const targetLabel = target ? (target.display_name || target.username) : 'this member';
    setLeavingNow(true);
    try {
      await api.post(`/api/orgs/${currentOrg.slug}/transfer-stewardship`, {
        target_user_id: leaveTransferTargetId,
      });
      toast.success(
        `Stewardship transferred to ${targetLabel}. Click Leave again to ` +
        'complete your departure.',
      );
      await refreshOrgs();
      // Per D2 — two-step. After the transfer the leave button is
      // unblocked but the user clicks it again deliberately.
      setLeaveStage('confirm');
      setLeaveTransferTargetId('');
    } catch (e) {
      toast.error(e.message || 'Failed to transfer stewardship');
    } finally {
      setLeavingNow(false);
    }
  }

  async function handleDelete() {
    if (deleteConfirm !== currentOrg.name) return;
    try {
      // Phase 44 — when approval is on, send confirmation = org slug
      // (required by the org.delete payload validator). The slug check
      // is incidental to the FE prompt (which uses the name); we just
      // forward the slug as the confirmation token.
      const res = await api.delete(`/api/orgs/${currentOrg.slug}`, {
        body: { confirmation: currentOrg.slug },
      });
      if (res && res.status === 'submitted_for_approval') {
        const need = res.pending_action?.threshold ?? 2;
        toast.success(`Org deletion submitted for approval (${need} approvals needed).`);
        return;
      }
      localStorage.removeItem('currentOrgSlug');
      // Phase 16 F5 — also clear the lastOrgSlug used by Nav.jsx so the
      // user's next visit to /settings doesn't try to resolve nav links
      // for an org that no longer exists.
      localStorage.removeItem('lastOrgSlug');
      window.location.href = '/orgs';
    } catch (e) {
      toast.error(e.message || 'Failed to delete');
    }
  }

  function updateSetting(key, value) {
    setSettings(prev => ({ ...prev, [key]: value }));
  }

  // Phase 12.7 F4 — branding handlers.
  //
  // Logo upload + remove are immediate-action (each call mutates the org
  // and we refresh so the preview reflects what's persisted). Color save
  // is staged: stewards can wiggle the picker without persisting until
  // they click Save branding.

  async function handleLogoFilePicked(e) {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploadingLogo(true);
    try {
      const form = new FormData();
      form.append('file', file);
      await api.postFormData(`/api/orgs/${currentOrg.slug}/logo`, form);
      await refreshOrgs();
      toast.success('Logo uploaded');
    } catch (err) {
      toast.error(err.message || 'Logo upload failed');
    } finally {
      setUploadingLogo(false);
      // Reset the input so re-uploading the same filename re-fires.
      if (logoFileInputRef.current) logoFileInputRef.current.value = '';
    }
  }

  async function handleLogoRemove() {
    const ok = await confirm({
      title: 'Remove logo?',
      message: 'The logo will be removed from the navigation bar and the organization picker. This cannot be undone — you can re-upload at any time.',
      destructive: true,
    });
    if (!ok) return;
    try {
      await api.delete(`/api/orgs/${currentOrg.slug}/logo`);
      await refreshOrgs();
      toast.success('Logo removed');
    } catch (err) {
      toast.error(err.message || 'Failed to remove logo');
    }
  }

  async function handleSaveBranding() {
    if (!isValidHex(primaryColor) || !isValidHex(accentColor)) {
      toast.error('Colors must be a 6-digit hex like #1B3A5C');
      return;
    }
    setSavingBranding(true);
    try {
      // Per spec D3 line 46: when auto-derive is on, frontend submits the
      // computed accent value explicitly so backend stores the snapshot
      // and reads stay simple (no per-load recomputation).
      await api.patch(`/api/orgs/${currentOrg.slug}/branding`, {
        primary_color: primaryColor,
        accent_color: accentColor,
        accent_auto_derived: autoDeriveAccent,
      });
      await refreshOrgs();
      toast.success('Branding saved');
    } catch (err) {
      toast.error(err.message || 'Failed to save branding');
    } finally {
      setSavingBranding(false);
    }
  }

  async function handleSaveIntroText() {
    // Phase 14 F3 — save intro_text via the same B4 branding PATCH endpoint
    // (per spec: bundling with branding since intro_text is conceptually
    // org self-presentation). The backend persists to
    // Organization.settings.intro_text and validates length server-side;
    // we enforce client-side too via the textarea maxLength + a defensive
    // length check here so we don't even send a payload we know will 400.
    if (introText.length > INTRO_TEXT_MAX) {
      toast.error(`Intro text is over the ${INTRO_TEXT_MAX}-character limit.`);
      return;
    }
    setSavingIntro(true);
    try {
      await api.patch(`/api/orgs/${currentOrg.slug}/branding`, {
        intro_text: introText,
      });
      await refreshOrgs();
      toast.success('Intro text saved');
    } catch (err) {
      toast.error(err.message || 'Failed to save intro text');
    } finally {
      setSavingIntro(false);
    }
  }

  async function handleSaveTopicGuidance() {
    // Phase 56 F5 — save topic_guidance via PATCH /api/orgs/{slug}
    // with a single-key settings merge. Backend's B4 validator
    // enforces the 5000-char cap server-side; the defensive check here
    // keeps a known-bad payload from even hitting the wire.
    if (topicGuidance.length > TOPIC_GUIDANCE_MAX) {
      toast.error(`Topic guidance is over the ${TOPIC_GUIDANCE_MAX}-character limit.`);
      return;
    }
    setSavingTopicGuidance(true);
    try {
      await api.patch(`/api/orgs/${currentOrg.slug}`, {
        settings: { topic_guidance: topicGuidance },
      });
      await refreshOrgs();
      toast.success('Topic guidance saved');
    } catch (err) {
      toast.error(err.message || 'Failed to save topic guidance');
    } finally {
      setSavingTopicGuidance(false);
    }
  }

  async function handleSaveTopicCategoriesToggle(nextValue) {
    // Phase 56 F4 — toggle save. Persist the new boolean and refresh.
    // Toggling OFF does NOT clear category values on the existing topics
    // — the backend simply hides grouping when the flag is false. Re-
    // enabling restores grouping with the retained data.
    setSavingTopicCategories(true);
    try {
      await api.patch(`/api/orgs/${currentOrg.slug}`, {
        settings: { topic_categories_enabled: nextValue },
      });
      await refreshOrgs();
      setTopicCategoriesEnabled(nextValue);
      toast.success(
        nextValue ? 'Topic categories enabled' : 'Topic categories disabled',
      );
    } catch (err) {
      toast.error(err.message || 'Failed to update topic categories toggle');
    } finally {
      setSavingTopicCategories(false);
    }
  }

  async function handleSaveStableResult() {
    // Phase 20 F1 — per-section save for the Stable Result Required block.
    // Sends only the four SR keys (plus the off-flip clear of the legacy
    // sustained_majority_enabled_default key when the user collapses the
    // section). Backend silently ignores any leftover sustained_majority_*
    // keys; we don't try to actively unset them here.
    setSavingSr(true);
    try {
      const payload = {
        stable_result_enabled_default: !!settings.stable_result_enabled_default,
        stable_result_per_proposal_override:
          settings.stable_result_per_proposal_override !== false,
        stable_window_fraction: settings.stable_window_fraction
          ?? SR_DEFAULTS.stable_window_fraction,
        max_extension_fraction: settings.max_extension_fraction
          ?? SR_DEFAULTS.max_extension_fraction,
      };
      await api.patch(`/api/orgs/${currentOrg.slug}`, { settings: payload });
      await refreshOrgs();
      toast.success('Stable Result settings saved');
    } catch (err) {
      toast.error(err.message || 'Failed to save Stable Result settings');
    } finally {
      setSavingSr(false);
    }
  }

  async function handleSaveDelibEngagement() {
    // Phase 32.2 F3 — per-section save for the three deliberation-
    // engagement groups (write-ins, pre-voting, proposal-edits). The
    // four migrated bool fields are now enum-typed mode strings;
    // the numeric fields keep their shape.
    setSavingDelibEng(true);
    try {
      const payload = {
        write_ins: {
          allowed_mode: settings.write_ins?.allowed_mode ?? 'default_off',
          during_voting_mode: settings.write_ins?.during_voting_mode ?? 'default_on',
          max_per_proposal: Number(settings.write_ins?.max_per_proposal ?? 10),
        },
        pre_voting: {
          allowed_mode: settings.pre_voting?.allowed_mode ?? 'default_off',
          visibility_mode: settings.pre_voting?.visibility_mode ?? 'default_off',
        },
        proposal_edits: {
          lockout_fraction: Number(settings.proposal_edits?.lockout_fraction ?? 0.75),
        },
      };
      await api.patch(`/api/orgs/${currentOrg.slug}`, { settings: payload });
      await refreshOrgs();
      toast.success('Deliberation engagement settings saved');
    } catch (err) {
      toast.error(err.message || 'Failed to save deliberation engagement settings');
    } finally {
      setSavingDelibEng(false);
    }
  }

  async function handleSaveMultiAdminApproval() {
    // Phase 44 F1 — opt-in N-of-M approval over destructive admin actions.
    setSavingMultiAdminApproval(true);
    try {
      const m = settings.multi_admin_approval || {};
      const payload = {
        multi_admin_approval: {
          enabled: !!m.enabled,
          thresholds: {
            'member.remove': Number(m.thresholds?.['member.remove'] ?? 2),
            'topic.delete': Number(m.thresholds?.['topic.delete'] ?? 2),
            'role_permissions.edit': Number(m.thresholds?.['role_permissions.edit'] ?? 2),
            'org.delete': Number(m.thresholds?.['org.delete'] ?? 2),
          },
          window_hours: Number(m.window_hours ?? 72),
        },
      };
      await api.patch(`/api/orgs/${currentOrg.slug}`, { settings: payload });
      await refreshOrgs();
      toast.success('Multi-admin approval settings saved');
    } catch (err) {
      toast.error(err.message || 'Failed to save multi-admin approval settings');
    } finally {
      setSavingMultiAdminApproval(false);
    }
  }

  async function handleSavePublicDelegates() {
    // Phase 32.2 F3/P1 — per-section save for the Public Delegates
    // block (enabled toggle + approval_required toggle).
    setSavingPublicDelegates(true);
    try {
      const payload = {
        public_delegates: {
          enabled: settings.public_delegates?.enabled !== false,
          approval_required: settings.public_delegates?.approval_required !== false,
        },
      };
      await api.patch(`/api/orgs/${currentOrg.slug}`, { settings: payload });
      await refreshOrgs();
      toast.success('Public delegate settings saved');
    } catch (err) {
      toast.error(err.message || 'Failed to save public delegate settings');
    } finally {
      setSavingPublicDelegates(false);
    }
  }

  // Phase 34 F1 — per-section saves for Voting Defaults, Default Approval
  // Thresholds, Voting Methods. Each sends only that section's keys; PATCH
  // /api/orgs/{slug} merges the settings JSON so untouched fields stay put.
  async function handleSaveVotingDefaults() {
    setSavingVotingDefaults(true);
    try {
      const payload = {
        default_deliberation_days: settings.default_deliberation_days ?? 14,
        default_voting_days: settings.default_voting_days ?? 7,
      };
      await api.patch(`/api/orgs/${currentOrg.slug}`, { settings: payload });
      await refreshOrgs();
      toast.success('Voting defaults saved');
    } catch (err) {
      toast.error(err.message || 'Failed to save voting defaults');
    } finally {
      setSavingVotingDefaults(false);
    }
  }

  async function handleSaveThresholds() {
    setSavingThresholds(true);
    try {
      const payload = {
        default_pass_threshold: settings.default_pass_threshold ?? 0.5,
        default_quorum_threshold: settings.default_quorum_threshold ?? 0.4,
      };
      await api.patch(`/api/orgs/${currentOrg.slug}`, { settings: payload });
      await refreshOrgs();
      toast.success('Default thresholds saved');
    } catch (err) {
      toast.error(err.message || 'Failed to save default thresholds');
    } finally {
      setSavingThresholds(false);
    }
  }

  async function handleSaveVotingMethods() {
    setSavingVotingMethods(true);
    try {
      const payload = {
        allowed_voting_methods: settings.allowed_voting_methods || ['binary'],
      };
      await api.patch(`/api/orgs/${currentOrg.slug}`, { settings: payload });
      await refreshOrgs();
      toast.success('Voting methods saved');
    } catch (err) {
      toast.error(err.message || 'Failed to save voting methods');
    } finally {
      setSavingVotingMethods(false);
    }
  }

  async function handleSaveTieResolution() {
    // Phase 17 F1 — PATCH /api/orgs/{slug} with the per-section
    // settings.tie_resolution payload. The backend B5 validator rejects
    // unknown method values with HTTP 400; defensive surface that to
    // the user even though the dropdown can't produce an invalid value
    // unless the eligibility tuples drift between FE + BE.
    setSavingTieResolution(true);
    try {
      await api.patch(`/api/orgs/${currentOrg.slug}`, {
        settings: {
          tie_resolution: {
            approval: tieApprovalMethod,
            ranked_choice: tieRankedChoiceMethod,
          },
        },
      });
      await refreshOrgs();
      toast.success('Tie resolution saved');
    } catch (err) {
      toast.error(err.message || 'Failed to save tie resolution');
    } finally {
      setSavingTieResolution(false);
    }
  }

  async function handleResetBranding() {
    const ok = await confirm({
      title: 'Reset to platform defaults?',
      message: 'Primary and accent colors will revert to the Liquid Democracy platform defaults. The logo (if any) is unaffected — remove it separately if needed.',
    });
    if (!ok) return;
    setSavingBranding(true);
    try {
      await api.patch(`/api/orgs/${currentOrg.slug}/branding`, {
        primary_color: null,
        accent_color: null,
        accent_auto_derived: true,
      });
      await refreshOrgs();
      toast.success('Branding reset to platform defaults');
    } catch (err) {
      toast.error(err.message || 'Failed to reset branding');
    } finally {
      setSavingBranding(false);
    }
  }

  return (
    <div className="max-w-3xl mx-auto px-4 py-8 space-y-10">
      <h1 className="text-2xl font-semibold text-[var(--brand-primary)]">Organization Settings</h1>

      {/* Phase 43 Cluster C — post-creation orientation pointer (dismissible). */}
      <NewStewardPointer />

      {/* Phase 44 F2b — discovery banner for any pending admin action. */}
      <PendingActionsBanner orgSlug={currentOrg?.slug} />

      {/* General — Phase 16 F4 moves the Save button from the page bottom
          to immediately below this section so per-section save UX is
          consistent across the page (every section now has its Save
          button adjacent rather than the user having to scroll to a
          page-bottom button after editing top-of-page fields). The
          handleSave call still PATCHes the same payload through the
          existing endpoint — only the JSX position of the button
          changed; the lower sections that have no per-section button
          (Voting Defaults / Threshold Defaults / Voting Methods /
          Deliberation / Public Delegates) are still saved through this
          same button, since handleSave sends the whole settings
          object. Phase 20 F1 added a per-section save for the Stable
          Result Required block. */}
      <section className="space-y-3">
        <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide">General</h2>
        <div className="bg-white border border-gray-200 rounded-xl p-5 space-y-4">
          <div>
            <label className="block text-xs text-gray-500 mb-1">Organization Name</label>
            <input
              type="text"
              value={name}
              onChange={e => setName(e.target.value)}
              className="w-full max-w-md px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[var(--brand-accent)]"
            />
          </div>
          <div>
            <label className="block text-xs text-gray-500 mb-1">Description</label>
            <textarea
              value={description}
              onChange={e => setDescription(e.target.value)}
              rows={3}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[var(--brand-accent)] resize-none"
            />
          </div>
          <div>
            <label className="block text-xs text-gray-500 mb-2">Join Policy</label>
            {/* Phase 14 F3 — four-policy selector. The split of the legacy
                "Invite only" into _secret and _public is the visible
                surface of the new public-landing-pages feature: stewards
                choose whether the org has a public splash at all. The
                copy below is verbatim from spec §F3 line 304-307. */}
            <div className="space-y-2">
              {[
                {
                  value: 'invite_only_secret',
                  label: 'Invite only (private)',
                  desc: 'Members must be invited. The organization has no public landing page.',
                },
                {
                  value: 'invite_only_public',
                  label: 'Invite only (public)',
                  desc: 'Members must be invited. The organization has a public landing page that explains who you are; visitors cannot join without an invitation.',
                },
                {
                  value: 'approval_required',
                  label: 'Approval required',
                  desc: 'Anyone can request to join. Your admins approve each request. The organization has a public landing page.',
                },
                {
                  value: 'open',
                  label: 'Open',
                  desc: 'Anyone with the link can join immediately. The organization has a public landing page.',
                },
              ].map(opt => (
                <label key={opt.value} className="flex items-start gap-3 cursor-pointer">
                  <input
                    type="radio"
                    name="joinPolicy"
                    value={opt.value}
                    checked={joinPolicy === opt.value}
                    onChange={() => setJoinPolicy(opt.value)}
                    className="mt-0.5 accent-[var(--brand-accent)]"
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
        {/* Phase 16 F4 — Save button repositioned from page bottom to here
            so the general-settings save action is adjacent to its fields.
            Phase 34 F1 — renamed to "Save All Settings" since per-section
            saves now exist for the other sections; this button still PATCHes
            the entire settings payload (the everything-button). A mirror of
            this button is rendered at the page bottom for users editing
            lower sections. */}
        <div className="flex items-center gap-3">
          <button
            onClick={handleSave}
            disabled={saving}
            className="px-6 py-2 bg-[var(--brand-primary)] text-white text-sm rounded-lg hover:bg-[var(--brand-accent)] transition-colors disabled:opacity-50"
          >
            {saving ? 'Saving...' : 'Save All Settings'}
          </button>
          {msg && (
            <span className={`text-sm ${msg === 'Settings saved' ? 'text-green-600' : 'text-red-600'}`}>{msg}</span>
          )}
        </div>
      </section>

      {/* Phase 12.7 F4 — Organization Branding (logo + primary/accent colors).
          Gated on the `org.edit_branding` permission key (Steward + Admin
          by default per Stage 1). The logo upload + remove call B1
          (POST/DELETE /api/orgs/{slug}/logo); the color save calls B2
          (PATCH /api/orgs/{slug}/branding). The currentOrg.branding object
          (B4 response field) drives the displayed values on hydrate; F2's
          BrandingThemeApplier picks up the changes after refreshOrgs(). */}
      {canEditBranding && (
        <section className="space-y-3">
          <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide">
            Organization Branding
          </h2>
          <div className="bg-white border border-gray-200 rounded-xl p-5 space-y-6">
            {/* Logo */}
            <div className="space-y-2">
              <label className="block text-sm font-medium text-gray-700">Logo</label>
              {currentOrg.branding?.logo_url ? (
                <div className="flex items-center gap-4">
                  <img
                    src={currentOrg.branding.logo_url}
                    alt={`${currentOrg.name} logo`}
                    className="h-16 w-auto max-w-[200px] object-contain border border-gray-200 rounded bg-gray-50 p-2"
                  />
                  <div className="flex flex-col gap-2">
                    <button
                      type="button"
                      onClick={() => logoFileInputRef.current?.click()}
                      disabled={uploadingLogo}
                      className="text-xs px-3 py-1.5 border border-gray-300 text-gray-700 rounded-lg hover:bg-gray-50 disabled:opacity-50"
                    >
                      {uploadingLogo ? 'Uploading…' : 'Replace'}
                    </button>
                    <button
                      type="button"
                      onClick={handleLogoRemove}
                      className="text-xs px-3 py-1.5 border border-red-300 text-red-600 rounded-lg hover:bg-red-50"
                    >
                      Remove
                    </button>
                  </div>
                </div>
              ) : (
                <div className="flex items-center gap-3">
                  <button
                    type="button"
                    onClick={() => logoFileInputRef.current?.click()}
                    disabled={uploadingLogo}
                    className="text-sm px-4 py-2 bg-[var(--brand-primary)] text-white rounded-lg hover:bg-[var(--brand-accent)] transition-colors disabled:opacity-50"
                  >
                    {uploadingLogo ? 'Uploading…' : 'Upload logo'}
                  </button>
                  <span className="text-xs text-gray-400">No logo set</span>
                </div>
              )}
              <input
                ref={logoFileInputRef}
                type="file"
                accept="image/jpeg,image/png,image/webp"
                onChange={handleLogoFilePicked}
                className="hidden"
              />
              <p className="text-xs text-gray-500">
                Logos appear in the navigation bar and the organization picker.
                Recommended dimensions: 400×160 or smaller — square or
                rectangular both work. Maximum 6 MB. Formats: JPEG, PNG, or WEBP.
              </p>
            </div>

            {/* Primary Color */}
            <div className="space-y-2 pt-4 border-t border-gray-100">
              <label className="block text-sm font-medium text-gray-700">
                Primary Color
              </label>
              <div className="flex items-center gap-3">
                <input
                  type="color"
                  value={primaryColor}
                  onChange={(e) => setPrimaryColor(e.target.value)}
                  className="h-10 w-14 border border-gray-300 rounded cursor-pointer p-0"
                  aria-label="Primary color picker"
                />
                <input
                  type="text"
                  value={primaryColor}
                  onChange={(e) => setPrimaryColor(e.target.value)}
                  placeholder="#1B3A5C"
                  className={`px-3 py-2 border rounded-lg text-sm font-mono w-32 focus:outline-none focus:ring-2 focus:ring-[var(--brand-accent)] ${
                    isValidHex(primaryColor) ? 'border-gray-300' : 'border-red-400'
                  }`}
                  aria-label="Primary color hex"
                />
              </div>
              <p className="text-xs text-gray-500">
                Used for the navigation bar, primary buttons, and headings.
              </p>
            </div>

            {/* Accent Color */}
            <div className="space-y-2 pt-4 border-t border-gray-100">
              <label className="block text-sm font-medium text-gray-700">
                Accent Color
              </label>
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={autoDeriveAccent}
                  onChange={(e) => setAutoDeriveAccent(e.target.checked)}
                  className="accent-[var(--brand-accent)]"
                />
                <span className="text-sm text-gray-700">
                  Use auto-derived accent <span className="text-gray-400">(recommended)</span>
                </span>
              </label>
              <div className="flex items-center gap-3 mt-1">
                {/* Phase 26 F1 — Chromium (and some other browsers)
                    paint a disabled <input type="color"> as a generic
                    system-default rectangle, IGNORING the `value`
                    attribute. That's the actual bug Z reported and the
                    reason Phase 25 F2's opacity removal didn't help:
                    the value was correct, the disabled element just
                    won't render it. The fix is to swap to a plain div
                    swatch when the picker is disabled (auto-derive on)
                    — divs paint backgroundColor reliably across
                    browsers — and only use the real <input type="color">
                    when the picker is enabled. The visual on-page is
                    indistinguishable: same size, same border, same
                    cursor behavior. */}
                {autoDeriveAccent ? (
                  <div
                    className="h-10 w-14 border border-gray-300 rounded cursor-not-allowed"
                    style={{ backgroundColor: accentColor }}
                    role="img"
                    aria-label={`Auto-derived accent color ${accentColor}`}
                    title="Auto-derived from primary color. Uncheck the box above to edit."
                  />
                ) : (
                  <input
                    type="color"
                    value={accentColor}
                    onChange={(e) => setAccentColor(e.target.value)}
                    className="h-10 w-14 border border-gray-300 rounded cursor-pointer p-0"
                    aria-label="Accent color picker"
                  />
                )}
                <input
                  type="text"
                  value={accentColor}
                  onChange={(e) => setAccentColor(e.target.value)}
                  disabled={autoDeriveAccent}
                  placeholder="#2E75B6"
                  className={`px-3 py-2 border rounded-lg text-sm font-mono w-32 focus:outline-none focus:ring-2 focus:ring-[var(--brand-accent)] disabled:bg-gray-50 disabled:text-gray-500 ${
                    isValidHex(accentColor) ? 'border-gray-300' : 'border-red-400'
                  }`}
                  aria-label="Accent color hex"
                />
              </div>
              <p className="text-xs text-gray-500">
                Used for links and secondary highlights.
                {autoDeriveAccent && ' Auto-derived as a lighter shade of the primary color.'}
              </p>
            </div>

            {/* Save / Reset */}
            <div className="flex items-center gap-3 pt-4 border-t border-gray-100">
              <button
                type="button"
                onClick={handleSaveBranding}
                disabled={savingBranding}
                className="px-5 py-2 bg-[var(--brand-primary)] text-white text-sm rounded-lg hover:bg-[var(--brand-accent)] transition-colors disabled:opacity-50"
              >
                {savingBranding ? 'Saving…' : 'Save branding'}
              </button>
              <button
                type="button"
                onClick={handleResetBranding}
                disabled={savingBranding}
                className="px-5 py-2 border border-gray-300 text-gray-700 text-sm rounded-lg hover:bg-gray-50 transition-colors disabled:opacity-50"
              >
                Reset to platform defaults
              </button>
            </div>
          </div>
        </section>
      )}

      {/* Phase 14 F3 — Public landing page intro text editor.
          Same permission gate as branding (`org.edit_branding`) since
          intro_text is conceptually org self-presentation. Live markdown
          preview reuses the proposal-body renderer so what stewards see
          here matches what visitors see on /{slug}. The textarea stays
          editable for invite_only_secret orgs (so stewards can stage
          intro content before flipping their policy) but a small
          read-only indicator clarifies that nothing renders publicly
          while the org has no landing page. */}
      {canEditBranding && (
        <section className="space-y-3">
          <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide">
            Public landing page intro
          </h2>
          <div className="bg-white border border-gray-200 rounded-xl p-5 space-y-4">
            {joinPolicy === 'invite_only_secret' && (
              <div className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2">
                Your organization has no public landing page; this intro
                text isn&apos;t shown anywhere. Switch the join policy
                to a public variant (Invite only public, Approval required,
                or Open) to make the intro visible.
              </div>
            )}
            <p className="text-xs text-gray-500">
              A longer introduction shown on your organization&apos;s public
              landing page at <code>/{currentOrg.slug}</code>. Visible only
              when policy is &quot;Invite only (public)&quot;,
              &quot;Approval required&quot;, or &quot;Open&quot;. Markdown
              supported (same syntax as proposal bodies).
            </p>
            <div>
              <label className="block text-xs text-gray-500 mb-1">Intro text</label>
              <textarea
                value={introText}
                onChange={e => setIntroText(e.target.value)}
                maxLength={INTRO_TEXT_MAX}
                rows={8}
                placeholder="# Welcome&#10;&#10;A short paragraph about who you are, why you exist, and what new members can expect."
                className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm font-mono focus:outline-none focus:ring-2 focus:ring-[var(--brand-accent)] resize-y"
              />
              <p className="mt-1 text-xs text-gray-400">
                {introText.length} / {INTRO_TEXT_MAX} characters
              </p>
            </div>
            <div>
              <p className="text-xs text-gray-500 mb-1">Preview</p>
              {introText.trim() ? (
                <div
                  className="prose text-[#2C3E50] text-sm leading-relaxed bg-gray-50 border border-gray-200 rounded-lg p-4"
                  dangerouslySetInnerHTML={{ __html: `<p>${renderMarkdown(introText)}</p>` }}
                />
              ) : (
                <div className="text-xs text-gray-400 italic bg-gray-50 border border-gray-200 rounded-lg p-4">
                  Empty — the intro section is hidden on the public landing page.
                </div>
              )}
            </div>
            <div className="flex items-center gap-3">
              <button
                type="button"
                onClick={handleSaveIntroText}
                disabled={savingIntro}
                className="px-5 py-2 bg-[var(--brand-primary)] text-white text-sm rounded-lg hover:bg-[var(--brand-accent)] transition-colors disabled:opacity-50"
              >
                {savingIntro ? 'Saving…' : 'Save intro text'}
              </button>
            </div>
          </div>
        </section>
      )}

      {/* Phase 56 F5 — Topic guidance editor. Markdown supported (same
          renderer + sanitizer as intro_text). Surfaced at the top of
          the topic-management page and as a hint in proposal-creation
          topic pickers, so members creating new topics or picking
          existing ones see the steward's intent. Page-level admin gate
          already restricts visibility; no additional per-control gate. */}
      <section className="space-y-3">
        <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide">
          Topic guidance
        </h2>
        <div className="bg-white border border-gray-200 rounded-xl p-5 space-y-4">
          <p className="text-xs text-gray-500">
            A short note shown at the top of the Topic Management page and
            in proposal-creation pickers. Use it to explain your org&apos;s
            approach to topics — what they&apos;re for, when to create a new
            one, naming conventions. Markdown supported (same syntax as
            proposal bodies). Hidden when empty.
          </p>
          <div>
            <label className="block text-xs text-gray-500 mb-1">Guidance</label>
            <textarea
              value={topicGuidance}
              onChange={e => setTopicGuidance(e.target.value)}
              maxLength={TOPIC_GUIDANCE_MAX}
              rows={6}
              placeholder="e.g. Topics group proposals by area. Keep them broad — 'Budget', 'Operations' — rather than tied to a single proposal."
              className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm font-mono focus:outline-none focus:ring-2 focus:ring-[var(--brand-accent)] resize-y"
            />
            <p className="mt-1 text-xs text-gray-400">
              {topicGuidance.length} / {TOPIC_GUIDANCE_MAX} characters
            </p>
          </div>
          <div>
            <p className="text-xs text-gray-500 mb-1">Preview</p>
            {topicGuidance.trim() ? (
              <div
                className="prose text-[#2C3E50] text-sm leading-relaxed bg-gray-50 border border-gray-200 rounded-lg p-4"
                dangerouslySetInnerHTML={{ __html: `<p>${renderMarkdown(topicGuidance)}</p>` }}
              />
            ) : (
              <div className="text-xs text-gray-400 italic bg-gray-50 border border-gray-200 rounded-lg p-4">
                Empty — no guidance shown on the topic-management page.
              </div>
            )}
          </div>
          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={handleSaveTopicGuidance}
              disabled={savingTopicGuidance}
              className="px-5 py-2 bg-[var(--brand-primary)] text-white text-sm rounded-lg hover:bg-[var(--brand-accent)] transition-colors disabled:opacity-50"
            >
              {savingTopicGuidance ? 'Saving…' : 'Save topic guidance'}
            </button>
          </div>
        </div>
      </section>

      {/* Phase 56 F4 — Topic categories toggle. When ON, topics are
          grouped by category in topic management + proposal-creation
          pickers. When OFF, flat list (and category values on existing
          rows are retained, so re-enabling restores grouping). */}
      <section className="space-y-3">
        <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide">
          Topic categories
        </h2>
        <div className="bg-white border border-gray-200 rounded-xl p-5 space-y-3">
          <label className="flex items-start gap-3 cursor-pointer">
            <input
              type="checkbox"
              checked={topicCategoriesEnabled}
              disabled={savingTopicCategories}
              onChange={e => handleSaveTopicCategoriesToggle(e.target.checked)}
              className="mt-1 accent-[var(--brand-accent)]"
            />
            <div>
              <p className="text-sm font-medium text-gray-800">
                Group topics by category
              </p>
              <p className="text-xs text-gray-500 mt-1">
                When enabled, topics are grouped and sorted by their
                category label in topic management and in proposal-creation
                pickers. Topics keep their category labels even when this
                is off — re-enabling restores grouping.
              </p>
            </div>
          </label>
        </div>
      </section>

      {/* Voting Defaults — duration */}
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
                className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[var(--brand-accent)]"
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
                className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[var(--brand-accent)]"
              />
            </div>
          </div>
          {/* Phase 34 F1 — per-section save button. */}
          <button
            onClick={handleSaveVotingDefaults}
            disabled={savingVotingDefaults}
            className="px-4 py-1.5 bg-[var(--brand-primary)] text-white text-xs rounded-lg hover:bg-[var(--brand-accent)] transition-colors disabled:opacity-50"
          >
            {savingVotingDefaults ? 'Saving…' : 'Save voting defaults'}
          </button>
        </div>
      </section>

      {/* Default Approval Thresholds — Phase 12.5 F4.
          Gated on `org.edit_settings` (Steward + Admin by default). The
          backend (Cluster B2) reads these from Organization.settings JSON
          via get_default_proposal_thresholds(); new proposals created
          without `proposal.set_thresholds` permission inherit these
          values. The save flow uses the same PATCH /api/orgs/{slug}
          endpoint as the rest of this page (settings JSON merge). */}
      {canEditOrgSettings && (
        <section className="space-y-3">
          <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide">
            Default Approval Thresholds
          </h2>
          <div className="bg-white border border-gray-200 rounded-xl p-5 space-y-4">
            <p className="text-xs text-gray-500">
              These values are used when new proposals are created without
              custom thresholds. Members granted "Set proposal thresholds"
              permission can override these on a per-proposal basis.
            </p>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-xs text-gray-500 mb-1">
                  Default pass threshold: {Math.round((settings.default_pass_threshold ?? 0.5) * 100)}%
                </label>
                <input
                  type="number"
                  min={0}
                  max={1}
                  step={0.01}
                  value={settings.default_pass_threshold ?? 0.5}
                  onChange={e => {
                    const v = parseFloat(e.target.value);
                    if (Number.isNaN(v)) return;
                    // Clamp 0.0–1.0 inclusive per spec validation.
                    updateSetting('default_pass_threshold', Math.max(0, Math.min(1, v)));
                  }}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[var(--brand-accent)]"
                />
                <p className="text-xs text-gray-400 mt-1">0.0 to 1.0 (e.g. 0.5 = 50%)</p>
              </div>
              <div>
                <label className="block text-xs text-gray-500 mb-1">
                  Default quorum threshold: {Math.round((settings.default_quorum_threshold ?? 0.4) * 100)}%
                </label>
                <input
                  type="number"
                  min={0}
                  max={1}
                  step={0.01}
                  value={settings.default_quorum_threshold ?? 0.4}
                  onChange={e => {
                    const v = parseFloat(e.target.value);
                    if (Number.isNaN(v)) return;
                    updateSetting('default_quorum_threshold', Math.max(0, Math.min(1, v)));
                  }}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[var(--brand-accent)]"
                />
                <p className="text-xs text-gray-400 mt-1">0.0 to 1.0 (e.g. 0.4 = 40%)</p>
              </div>
            </div>
            {/* Phase 34 F1 — per-section save button. */}
            <button
              onClick={handleSaveThresholds}
              disabled={savingThresholds}
              className="px-4 py-1.5 bg-[var(--brand-primary)] text-white text-xs rounded-lg hover:bg-[var(--brand-accent)] transition-colors disabled:opacity-50"
            >
              {savingThresholds ? 'Saving…' : 'Save default thresholds'}
            </button>
          </div>
        </section>
      )}

      {/* Voting Methods */}
      <section className="space-y-3">
        <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide">Voting Methods</h2>
        <div className="bg-white border border-gray-200 rounded-xl p-5 space-y-3">
          <label className="flex items-center gap-3">
            <input type="checkbox" checked disabled className="accent-[var(--brand-accent)]" />
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
              className="accent-[var(--brand-accent)]"
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
              className="accent-[var(--brand-accent)]"
            />
            <div>
              <span className="text-sm text-gray-700">Ranked Choice (IRV / STV)</span>
              <p className="text-xs text-gray-400">Voters rank options in preference order. 1 winner = IRV; multiple winners = STV.</p>
            </div>
          </label>
          {/* Phase 34 F1 — per-section save button. */}
          <button
            onClick={handleSaveVotingMethods}
            disabled={savingVotingMethods}
            className="px-4 py-1.5 bg-[var(--brand-primary)] text-white text-xs rounded-lg hover:bg-[var(--brand-accent)] transition-colors disabled:opacity-50"
          >
            {savingVotingMethods ? 'Saving…' : 'Save voting methods'}
          </button>
        </div>
      </section>

      {/* Phase 17 F1 — Tie Resolution.
          Steward configures one method per voting method (approval +
          ranked-choice / STV); when a proposal closes with a tie, the
          configured method runs automatically and the resolution is
          recorded as part of the result. Permission-gated on the
          existing org.edit_settings (Steward + Admin by default).
          Members without that permission see a read-only render of the
          current values so the section is still informative. */}
      <section className="space-y-3">
        <div className="flex items-baseline justify-between">
          <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide">
            Tie Resolution
          </h2>
          <a
            href="/help/voting-methods"
            target="_blank"
            rel="noreferrer"
            className="text-xs text-[var(--brand-accent)] hover:underline"
          >
            Learn more &rarr;
          </a>
        </div>
        <div className="bg-white border border-gray-200 rounded-xl p-5 space-y-4">
          <p className="text-xs text-gray-500">
            What happens when a proposal vote results in a tie. Each
            voting method has its own setting; sub-orgs inherit the
            parent org&apos;s configuration.
          </p>

          {canEditOrgSettings ? (
            <>
              <div className="space-y-2">
                <label className="block text-xs text-gray-500">
                  Approval voting
                </label>
                <select
                  value={tieApprovalMethod}
                  onChange={e => setTieApprovalMethod(e.target.value)}
                  className="w-full max-w-md px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[var(--brand-accent)] bg-white"
                >
                  {TIE_METHODS_APPROVAL.map(m => (
                    <option key={m.value} value={m.value}>{m.label}</option>
                  ))}
                </select>
                <p className="text-xs text-gray-400">
                  {TIE_METHODS_APPROVAL.find(m => m.value === tieApprovalMethod)?.desc}
                </p>
              </div>

              <div className="space-y-2 pt-2 border-t border-gray-100">
                <label className="block text-xs text-gray-500">
                  Ranked choice / STV
                </label>
                <select
                  value={tieRankedChoiceMethod}
                  onChange={e => setTieRankedChoiceMethod(e.target.value)}
                  className="w-full max-w-md px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[var(--brand-accent)] bg-white"
                >
                  {TIE_METHODS_RANKED_CHOICE.map(m => (
                    <option key={m.value} value={m.value}>{m.label}</option>
                  ))}
                </select>
                <p className="text-xs text-gray-400">
                  {TIE_METHODS_RANKED_CHOICE.find(m => m.value === tieRankedChoiceMethod)?.desc}
                </p>
              </div>
            </>
          ) : (
            <div className="space-y-2 text-sm text-gray-700">
              <div>
                <span className="text-xs text-gray-500">Approval voting:</span>{' '}
                <span className="font-medium">
                  {TIE_METHODS_APPROVAL.find(m => m.value === tieApprovalMethod)?.label
                    || tieApprovalMethod}
                </span>
              </div>
              <div>
                <span className="text-xs text-gray-500">Ranked choice / STV:</span>{' '}
                <span className="font-medium">
                  {TIE_METHODS_RANKED_CHOICE.find(m => m.value === tieRankedChoiceMethod)?.label
                    || tieRankedChoiceMethod}
                </span>
              </div>
              <p className="text-xs text-gray-400 italic">
                Read-only &mdash; you don&apos;t have permission to change
                organization settings.
              </p>
            </div>
          )}
        </div>
        {canEditOrgSettings && (
          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={handleSaveTieResolution}
              disabled={savingTieResolution}
              className="px-5 py-2 bg-[var(--brand-primary)] text-white text-sm rounded-lg hover:bg-[var(--brand-accent)] transition-colors disabled:opacity-50"
            >
              {savingTieResolution ? 'Saving…' : 'Save tie resolution'}
            </button>
          </div>
        )}
      </section>

      {/* Phase 20 F1 — Stable Result Required (renamed and simplified from
          the old Phase 8 sustained-majority section). The floor / failure-
          mode / threshold controls are gone; in their place are two
          fraction sliders that drive the unified stable-window mechanic
          on the backend (see backend/sustained_majority.py StableResultConfig).
          Save uses the per-section Phase 16 F4 pattern via
          handleSaveStableResult. */}
      <section className="space-y-3">
        <div className="flex items-baseline justify-between">
          <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide">
            Stable Result Required
          </h2>
          <a
            href="/help/stable-result"
            target="_blank"
            rel="noreferrer"
            className="text-xs text-[var(--brand-accent)] hover:underline"
          >
            Learn more →
          </a>
        </div>
        <div className="bg-white border border-gray-200 rounded-xl p-5 space-y-4">
          <label className="flex items-start gap-3 cursor-pointer">
            <input
              type="checkbox"
              checked={srExpanded}
              onChange={e => {
                const on = e.target.checked;
                setSrExpanded(on);
                if (!on) {
                  // Toggling OFF forces stable_result_enabled_default false
                  // org-wide regardless of any previous value. Other SR keys
                  // are left in settings so re-enabling restores them.
                  updateSetting('stable_result_enabled_default', false);
                } else {
                  // Toggling ON: seed any missing keys with defaults so
                  // the controls render with sane values.
                  setSettings(prev => {
                    const next = { ...prev };
                    SR_KEYS.forEach(k => {
                      if (next[k] === undefined || next[k] === null) {
                        next[k] = SR_DEFAULTS[k];
                      }
                    });
                    return next;
                  });
                }
              }}
              className="mt-0.5 accent-[var(--brand-accent)]"
            />
            <div>
              <p className="text-sm text-gray-700">Enable Stable Result Required</p>
              <p className="text-xs text-gray-400">
                Off by default. Enable when your organization wants extra
                assurance that a result has settled — the proposal must
                show a stable outcome across the closing portion of the
                voting window, with automatic extensions if it doesn&apos;t.
              </p>
            </div>
          </label>

          {srExpanded && (() => {
            const stableFraction = settings.stable_window_fraction
              ?? SR_DEFAULTS.stable_window_fraction;
            const maxExtFraction = settings.max_extension_fraction
              ?? SR_DEFAULTS.max_extension_fraction;
            // Sample voting period for the slider helper text. Uses the
            // org's default voting_days when present, otherwise the
            // platform-wide default of 7 days. Helps stewards visualize
            // what the percentage means in human time.
            const sampleVotingDays = settings.default_voting_days ?? 7;
            const sampleVotingSeconds = sampleVotingDays * 86400;
            const stableWindowSeconds = sampleVotingSeconds * stableFraction;
            const extensionBudgetSeconds = sampleVotingSeconds * maxExtFraction;
            // Number of extensions (mechanically derived per spec D9).
            // floor(max_ext / stable_window). When stableFraction is 0 we
            // can't divide; treat as 0 extensions to avoid Infinity.
            const extensionsPossible = stableFraction > 0
              ? Math.floor(maxExtFraction / stableFraction)
              : 0;
            return (
              <div className="space-y-5 pt-2 border-t border-gray-100">
                <label className="flex items-start gap-3 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={settings.stable_result_enabled_default ?? false}
                    onChange={e => updateSetting('stable_result_enabled_default', e.target.checked)}
                    className="mt-0.5 accent-[var(--brand-accent)]"
                  />
                  <div>
                    <p className="text-sm text-gray-700">Stable Result Required (default for new proposals)</p>
                    <p className="text-xs text-gray-400">
                      When enabled, new proposals require a stable result unless the author opts out.
                    </p>
                  </div>
                </label>

                <label className="flex items-start gap-3 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={settings.stable_result_per_proposal_override ?? true}
                    onChange={e => updateSetting('stable_result_per_proposal_override', e.target.checked)}
                    className="mt-0.5 accent-[var(--brand-accent)]"
                  />
                  <div>
                    <p className="text-sm text-gray-700">Allow per-proposal override</p>
                    <p className="text-xs text-gray-400">
                      Authors can opt a single proposal in or out, overriding the org default above.
                    </p>
                  </div>
                </label>

                <div>
                  <label className="block text-xs text-gray-500 mb-1">
                    Stable window: {Math.round(stableFraction * 100)}% of voting period
                  </label>
                  <p className="text-xs text-gray-400 mb-1">
                    The closing portion of the voting window where the result
                    must remain stable. Destabilization during this window
                    triggers an automatic extension.
                  </p>
                  <input
                    type="range"
                    min={5}
                    max={50}
                    value={Math.round(stableFraction * 100)}
                    onChange={e => updateSetting('stable_window_fraction', parseInt(e.target.value, 10) / 100)}
                    className="w-full accent-[var(--brand-accent)]"
                  />
                  <p className="text-xs text-gray-500 mt-1">
                    Final {Math.round(stableFraction * 100)}% of voting period;
                    a voting period of {sampleVotingDays} day{sampleVotingDays === 1 ? '' : 's'} =
                    {' '}stable window of {formatDuration(stableWindowSeconds)}.
                  </p>
                </div>

                <div>
                  <label
                    className="block text-xs text-gray-500 mb-1"
                    title="Voting can be extended by up to this fraction of the original voting period if the result destabilizes. Extensions happen in stable-window-duration chunks; voting closes when stability is demonstrated or when the extension budget is exhausted."
                  >
                    Maximum total extension: {Math.round(maxExtFraction * 100)}% of voting period
                  </label>
                  <p className="text-xs text-gray-400 mb-1">
                    Cap on the cumulative extension time across all extensions
                    combined. Set to 0% to log destabilization without granting
                    any extension.
                  </p>
                  <input
                    type="range"
                    min={0}
                    max={100}
                    value={Math.round(maxExtFraction * 100)}
                    onChange={e => updateSetting('max_extension_fraction', parseInt(e.target.value, 10) / 100)}
                    className="w-full accent-[var(--brand-accent)]"
                  />
                  <p className="text-xs text-gray-500 mt-1">
                    Extension budget for a {sampleVotingDays}-day vote: up to
                    {' '}{formatDuration(extensionBudgetSeconds)}. With current
                    settings, your proposal can extend up to {extensionsPossible}{' '}
                    time{extensionsPossible === 1 ? '' : 's'} before force-close.
                  </p>
                </div>
              </div>
            );
          })()}
          <div className="flex items-center gap-3 pt-2 border-t border-gray-100">
            <button
              type="button"
              onClick={handleSaveStableResult}
              disabled={savingSr}
              className="px-5 py-2 bg-[var(--brand-primary)] text-white text-sm rounded-lg hover:bg-[var(--brand-accent)] transition-colors disabled:opacity-50"
            >
              {savingSr ? 'Saving…' : 'Save Stable Result settings'}
            </button>
          </div>
        </div>
      </section>

      {/* Phase 32.2 F3 — Deliberation Engagement defaults. The four
          migrated boolean fields are now enum modes (`always_off` /
          `default_off` / `default_on` / `always_on`). Each surfaces
          as a 4-option radio group; numeric settings keep their
          numeric input. */}
      <section className="space-y-3">
        <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide">Proposal Defaults — Deliberation Engagement</h2>
        <div className="bg-white border border-gray-200 rounded-xl p-5 space-y-4">
          {/* Write-ins */}
          <div className="space-y-3 pb-3 border-b border-gray-100">
            <p className="text-sm font-semibold text-gray-700">Write-ins</p>
            <ModeRadioGroup
              label="Allow write-in options"
              help="Members can propose write-in options on multi-option proposals."
              value={settings.write_ins?.allowed_mode ?? 'default_off'}
              onChange={v => updateSetting('write_ins', {
                ...(settings.write_ins || {}),
                allowed_mode: v,
              })}
            />
            <ModeRadioGroup
              label="Allow write-ins during voting"
              help="When write-ins are on, also allow members to add options after voting opens."
              value={settings.write_ins?.during_voting_mode ?? 'default_on'}
              onChange={v => updateSetting('write_ins', {
                ...(settings.write_ins || {}),
                during_voting_mode: v,
              })}
            />
            <label className="flex items-center gap-3">
              <span className="text-sm text-gray-700 min-w-[200px]">Default maximum write-ins</span>
              <input
                type="number"
                min={1}
                max={50}
                value={settings.write_ins?.max_per_proposal ?? 10}
                onChange={e => updateSetting('write_ins', {
                  ...(settings.write_ins || {}),
                  max_per_proposal: parseInt(e.target.value, 10) || 10,
                })}
                className="w-20 px-2 py-1 border border-gray-300 rounded text-sm"
              />
            </label>
          </div>
          {/* Pre-voting */}
          <div className="space-y-3 pb-3 border-b border-gray-100">
            <p className="text-sm font-semibold text-gray-700">Pre-voting</p>
            <ModeRadioGroup
              label="Allow voting during deliberation"
              help="Members can cast and change votes before voting officially opens."
              value={settings.pre_voting?.allowed_mode ?? 'default_off'}
              onChange={v => updateSetting('pre_voting', {
                ...(settings.pre_voting || {}),
                allowed_mode: v,
              })}
            />
            <ModeRadioGroup
              label="Show vote totals during deliberation"
              help="Off avoids anchoring; on enables the trajectory chart to extend back to deliberation start."
              value={settings.pre_voting?.visibility_mode ?? 'default_off'}
              onChange={v => updateSetting('pre_voting', {
                ...(settings.pre_voting || {}),
                visibility_mode: v,
              })}
            />
          </div>
          {/* Editing */}
          <div className="space-y-2">
            <p className="text-sm font-semibold text-gray-700">Editing</p>
            <label className="flex items-center gap-3">
              <span className="text-sm text-gray-700 min-w-[200px]">
                Default editing lockout
              </span>
              <input
                type="number"
                min={0}
                max={100}
                step={5}
                value={Math.round(Number(settings.proposal_edits?.lockout_fraction ?? 0.75) * 100)}
                onChange={e => updateSetting('proposal_edits', {
                  ...(settings.proposal_edits || {}),
                  lockout_fraction: Number(e.target.value) / 100,
                })}
                className="w-20 px-2 py-1 border border-gray-300 rounded text-sm"
              />
              <span className="text-xs text-gray-500">% of deliberation elapsed</span>
            </label>
            <p className="text-xs text-gray-400">
              Authors can't edit a proposal past this fraction of deliberation. Defaults to 75% (edits locked for the final 25%).
            </p>
          </div>
          <div className="flex items-center gap-3 pt-2 border-t border-gray-100">
            <button
              type="button"
              onClick={handleSaveDelibEngagement}
              disabled={savingDelibEng}
              className="px-5 py-2 bg-[var(--brand-primary)] text-white text-sm rounded-lg hover:bg-[var(--brand-accent)] transition-colors disabled:opacity-50"
            >
              {savingDelibEng ? 'Saving…' : 'Save deliberation engagement settings'}
            </button>
          </div>
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
              className="mt-0.5 accent-[var(--brand-accent)]"
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

      {/* Cluster B (49a) — replaced the legacy 3-way creation-mode
          selector with the single "allow cosign petition" toggle. The
          permission matrix decides who creates directly (holders of
          "Create proposals"); the toggle decides whether members
          who lack that permission may instead initiate via cosigned
          petition. */}
      {canEditOrgSettings && (
        <section className="space-y-3">
          <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide">
            Proposal creation
          </h2>
          <div className="bg-white border border-gray-200 rounded-xl p-5 space-y-4">
            <p className="text-sm text-gray-600">
              Who can create a proposal depends on the <em>Create proposals</em> permission in your role matrix. The toggle below opens an alternative path for everyone else: a petition that goes live once enough members co-sign.
            </p>
            <label className="flex items-start gap-3 cursor-pointer">
              <input
                type="checkbox"
                checked={!!currentOrg?.allow_cosign_petition}
                onChange={async (e) => {
                  try {
                    await api.patch(`/api/orgs/${currentOrg.slug}`, {
                      settings: { allow_cosign_petition: e.target.checked },
                    });
                    await refreshOrgs();
                    toast.success(
                      e.target.checked
                        ? 'Members can now initiate proposals by petition.'
                        : 'Members without proposal-creation permission can no longer initiate proposals.',
                    );
                  } catch (err) {
                    toast.error(err.message || 'Failed to update setting');
                  }
                }}
                className="mt-0.5 accent-[var(--brand-accent)]"
              />
              <div>
                <div className="text-sm font-medium text-gray-700">
                  Allow members without proposal-creation permission to start proposals by gathering co-signatures
                </div>
                <div className="text-xs text-gray-500">
                  When on, a member without the <em>Create proposals</em> permission can still file a proposal as a petition. It goes live once the co-signature threshold is met within the gathering window. When off, only members with the <em>Create proposals</em> permission can file.
                </div>
              </div>
            </label>
            {!!currentOrg?.allow_cosign_petition && (
              <div className="border-t border-gray-200 pt-4 space-y-3">
                <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wide">Cosign configuration</h3>
                <div className="flex flex-wrap gap-4">
                  <label className="text-sm space-y-1">
                    <span className="block text-xs text-gray-600">Threshold (signatures including author)</span>
                    <input
                      type="number"
                      min={1}
                      value={settings.cosign?.threshold ?? 3}
                      onChange={e => updateSetting('cosign', {
                        ...(settings.cosign || {}),
                        threshold: Math.max(1, parseInt(e.target.value || '3', 10)),
                      })}
                      className="w-24 px-3 py-1.5 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-400"
                    />
                  </label>
                  <label className="text-sm space-y-1">
                    <span className="block text-xs text-gray-600">
                      Gathering window (hours)
                      {/* Cluster D — secondary-unit hint so admins can
                          glance the equivalent days without doing math. */}
                      {settings.cosign?.expiry_hours > 23 && (
                        <span className="ml-1 text-gray-400">
                          ({(settings.cosign.expiry_hours / 24).toFixed(settings.cosign.expiry_hours % 24 === 0 ? 0 : 1)} days)
                        </span>
                      )}
                    </span>
                    <input
                      type="number"
                      min={1}
                      value={settings.cosign?.expiry_hours ?? 168}
                      onChange={e => updateSetting('cosign', {
                        ...(settings.cosign || {}),
                        expiry_hours: Math.max(1, parseInt(e.target.value || '168', 10)),
                      })}
                      className="w-28 px-3 py-1.5 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-400"
                    />
                  </label>
                </div>
                <p className="text-xs text-gray-500">
                  Save with the main "Save All Settings" button below. Authors count as the first signature, so a threshold of 3 means "author + 2 others."
                </p>
              </div>
            )}
          </div>
        </section>
      )}

      {/* Phase 47 F1 — Org Titles management panel. Renders only when
          the caller holds title.manage. System titles (Steward, Admin)
          are listed but uneditable; custom titles can be created +
          assigned + deleted (when empty). */}
      <OrgTitlesPanel orgSlug={currentOrg?.slug} />

      {/* Phase 48 Stage 1 — Elections opt-in. Off by default per D3;
          appointment (45a/45b) remains the default seat-filling
          mechanism until an admin opts in here. */}
      {canEditOrgSettings && (
        <section className="space-y-3">
          <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide">
            Elections
          </h2>
          <div className="bg-white border border-gray-200 rounded-xl p-5 space-y-3">
            <p className="text-sm text-gray-600">
              When enabled, an electable title can be filled by an election proposal. Members self-nominate during the nomination window; the winner is installed at close. Off by default — appointment remains the default seat-filling mechanism.
            </p>
            <label className="flex items-start gap-3 cursor-pointer">
              <input
                type="checkbox"
                checked={!!settings.elections?.enabled}
                onChange={e => updateSetting('elections', {
                  ...(settings.elections || {}),
                  enabled: e.target.checked,
                })}
                className="mt-0.5 accent-[var(--brand-accent)]"
              />
              <div>
                <div className="text-sm text-gray-700">Enable elections in this organization</div>
                <div className="text-xs text-gray-500">Then set a title's fill method to "elected" or "both" to make it electable, and click "Open election" on that title.</div>
              </div>
            </label>

            {/* Phase 48 Stage 3 — D4 trigger configuration. Default is
                admin_direct (Stage 1+2 behavior); enabling member_cosign
                lets ordinary members open a cosign-gated election petition. */}
            {settings.elections?.enabled && (
              <div className="pl-7 space-y-2 border-l-2 border-gray-100">
                <div className="text-xs font-medium text-gray-500 uppercase tracking-wide">Trigger sources</div>
                {[
                  ['admin_direct', 'Admin/steward direct', 'Admins and stewards can open an election immediately for any electable title.'],
                  ['member_cosign', 'Member cosign petition', 'Any member can open a petition; the election advances to voting when the cosign threshold is met.'],
                  ['scheduled', 'Scheduled / fixed-term', 'Titles with a configured term auto-open an election when the term is due. Set a term on the title to opt that specific seat in.'],
                ].map(([key, label, hint]) => {
                  const sources = settings.elections?.trigger_sources;
                  const list = Array.isArray(sources) ? sources : ['admin_direct'];
                  const checked = list.includes(key);
                  return (
                    <label key={key} className="flex items-start gap-3 cursor-pointer">
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={e => {
                          const next = new Set(list);
                          if (e.target.checked) next.add(key); else next.delete(key);
                          updateSetting('elections', {
                            ...(settings.elections || {}),
                            trigger_sources: Array.from(next),
                          });
                        }}
                        className="mt-0.5 accent-[var(--brand-accent)]"
                      />
                      <div>
                        <div className="text-sm text-gray-700">{label}</div>
                        <div className="text-xs text-gray-500">{hint}</div>
                      </div>
                    </label>
                  );
                })}

                {/* Phase 48 Stage 3 D12 partner — elected revert opt-in.
                    Only meaningful in admin_council mode; surfacing in
                    single_steward mode is harmless (it just doesn't
                    activate). */}
                <label className="flex items-start gap-3 cursor-pointer mt-2">
                  <input
                    type="checkbox"
                    checked={!!settings.elections?.allow_elected_revert}
                    onChange={e => updateSetting('elections', {
                      ...(settings.elections || {}),
                      allow_elected_revert: e.target.checked,
                    })}
                    className="mt-0.5 accent-[var(--brand-accent)]"
                  />
                  <div>
                    <div className="text-sm text-gray-700">Let the admin team elect a single top leader</div>
                    <div className="text-xs text-gray-500">When on, if the admin team holds an election for a Steward seat, the winner becomes the org's single top leader (and the team-of-admins arrangement ends). When off, the admin team has no path to convert back to a single-leader setup through an election.</div>
                  </div>
                </label>
              </div>
            )}
          </div>
        </section>
      )}

      {/* Phase 52 Stage 1 — verification gates. Each of the three
          floors lives in ``settings`` so this is a generic settings
          PATCH (no dedicated endpoint). Defaults are unset → no
          gate → byte-for-byte today's behavior. Backend state codes
          do NOT appear in the dropdown copy (Phase 49a C2 rule). */}
      {canEditOrgSettings && (
        <section className="space-y-3">
          <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide">
            Identity verification gates
          </h2>
          <div className="bg-white border border-gray-200 rounded-xl p-5 space-y-4">
            <p className="text-sm text-gray-600">
              Optionally require members to verify their identity before joining, holding a role, or casting a vote. Leave any setting on "No verification required" to keep the existing behavior. Identity-verification options for members will become available in a future update.
            </p>

            <label className="text-sm space-y-1 block">
              <span className="block text-xs text-gray-600">Required to join this organization</span>
              <select
                value={settings.verification_membership_floor || ''}
                onChange={e => updateSetting('verification_membership_floor', e.target.value || null)}
                className="w-full max-w-md px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-400"
              >
                <option value="">No verification required (default)</option>
                <option value="identity">Identity verified</option>
                <option value="identity_unique">Identity verified — unique person</option>
                <option value="address_on_id">Identity verified — address on ID</option>
                <option value="residency_verified">Identity verified — residency confirmed</option>
              </select>
              {(settings.verification_membership_floor === 'address_on_id'
                  || settings.verification_membership_floor === 'residency_verified') && (
                <input
                  type="text"
                  value={settings.verification_membership_jurisdiction || ''}
                  onChange={e => updateSetting('verification_membership_jurisdiction', e.target.value || null)}
                  placeholder="Jurisdiction (e.g. US state code)"
                  className="mt-2 w-full max-w-md px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-400"
                />
              )}
            </label>

            <div className="space-y-2">
              <p className="text-xs text-gray-600 font-medium">Required to hold a role</p>
              {['admin', 'moderator', 'steward'].map(roleKey => (
                <label key={roleKey} className="text-sm flex items-center gap-3">
                  <span className="capitalize text-xs text-gray-600 w-20">{roleKey}</span>
                  <select
                    value={(settings.verification_role_floors || {})[roleKey] || ''}
                    onChange={e => updateSetting('verification_role_floors', {
                      ...(settings.verification_role_floors || {}),
                      [roleKey]: e.target.value || undefined,
                    })}
                    className="flex-1 max-w-md px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-400"
                  >
                    <option value="">No verification required</option>
                    <option value="identity">Identity verified</option>
                    <option value="identity_unique">Identity verified — unique person</option>
                    <option value="address_on_id">Identity verified — address on ID</option>
                    <option value="residency_verified">Identity verified — residency confirmed</option>
                  </select>
                </label>
              ))}
            </div>

            <label className="flex items-start gap-3 cursor-pointer pt-2 border-t border-gray-200">
              <input
                type="checkbox"
                checked={!!settings.verification_delegation_carries_weight}
                onChange={e => updateSetting('verification_delegation_carries_weight', e.target.checked)}
                className="mt-0.5 accent-[var(--brand-accent)]"
              />
              <div>
                <p className="text-sm text-gray-700">Let unverified members' delegated weight count via verified delegates</p>
                <p className="text-xs text-gray-500">
                  Default (off): on a proposal that requires verification, only verified members count — both their direct votes and the votes their verified delegates would cast on their behalf. When on, a verified delegate can carry an unverified member's delegated weight on a gated proposal (the unverified member still can't cast directly).
                </p>
              </div>
            </label>
          </div>
        </section>
      )}

      {/* Multi-Admin Approval — Phase 44 F1. Opt-in N-of-M ratification
          over four destructive admin actions: remove member, delete topic,
          edit permissions, delete org. Defaults to OFF; every org behaves
          exactly as before until a steward opts in. */}
      <section className="space-y-3">
        <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide">
          Multi-Admin Approval
        </h2>
        <div className="bg-white border border-gray-200 rounded-xl p-5 space-y-4">
          <p className="text-sm text-gray-600">
            When enabled, destructive admin actions (remove member, delete topic, edit permissions, delete this organization) require N-of-M ratification from other eligible approvers before executing. Off by default.
          </p>
          <label className="flex items-start gap-3 cursor-pointer">
            <input
              type="checkbox"
              checked={!!settings.multi_admin_approval?.enabled}
              onChange={e => updateSetting('multi_admin_approval', {
                ...(settings.multi_admin_approval || {}),
                enabled: e.target.checked,
              })}
              className="mt-0.5 accent-[var(--brand-accent)]"
            />
            <div>
              <p className="text-sm text-gray-700">Require multi-admin approval for destructive actions</p>
              <p className="text-xs text-gray-400">
                Approvers receive a notification and a queue entry. One decline vetoes the action. Initiator's submission counts as their own approval.
              </p>
            </div>
          </label>
          {settings.multi_admin_approval?.enabled && (
            <div className="space-y-3 pl-7">
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                {[
                  ['member.remove', 'Remove member'],
                  ['topic.delete', 'Delete topic'],
                  ['role_permissions.edit', 'Edit role permissions'],
                  ['org.delete', 'Delete organization'],
                ].map(([key, label]) => (
                  <label key={key} className="text-sm">
                    <span className="block text-gray-700 mb-1">{label} threshold</span>
                    <input
                      type="number"
                      min={1}
                      max={20}
                      value={settings.multi_admin_approval?.thresholds?.[key] ?? 2}
                      onChange={e => updateSetting('multi_admin_approval', {
                        ...(settings.multi_admin_approval || {}),
                        thresholds: {
                          ...(settings.multi_admin_approval?.thresholds || {}),
                          [key]: Math.max(1, Number(e.target.value) || 1),
                        },
                      })}
                      className="w-24 border border-gray-300 rounded px-2 py-1 text-sm"
                    />
                  </label>
                ))}
              </div>
              <label className="text-sm block">
                <span className="block text-gray-700 mb-1">
                  Expiry window (hours)
                  {/* Cluster D — secondary-unit hint so admins can
                      glance the equivalent days for the common case
                      where the window is set in whole days. */}
                  {(settings.multi_admin_approval?.window_hours ?? 72) > 23 && (
                    <span className="ml-1 text-gray-400">
                      ({((settings.multi_admin_approval?.window_hours ?? 72) / 24).toFixed(
                        ((settings.multi_admin_approval?.window_hours ?? 72) % 24 === 0) ? 0 : 1,
                      )} days)
                    </span>
                  )}
                </span>
                <input
                  type="number"
                  min={1}
                  max={720}
                  value={settings.multi_admin_approval?.window_hours ?? 72}
                  onChange={e => updateSetting('multi_admin_approval', {
                    ...(settings.multi_admin_approval || {}),
                    window_hours: Math.max(1, Number(e.target.value) || 1),
                  })}
                  className="w-28 border border-gray-300 rounded px-2 py-1 text-sm"
                />
                <span className="block text-xs text-gray-400 mt-1">
                  Submitted actions expire if not ratified in this window. Defaults to 72 hours (3 days).
                </span>
              </label>
            </div>
          )}
          <div className="flex items-center gap-3 pt-2 border-t border-gray-100">
            <button
              type="button"
              onClick={handleSaveMultiAdminApproval}
              disabled={savingMultiAdminApproval}
              className="px-5 py-2 bg-[var(--brand-primary)] text-white text-sm rounded-lg hover:bg-[var(--brand-accent)] transition-colors disabled:opacity-50"
            >
              {savingMultiAdminApproval ? 'Saving…' : 'Save multi-admin approval settings'}
            </button>
          </div>
        </div>
      </section>

      {/* Public Delegates — Phase 32.2 P1/P2: enabled toggle with disable
          confirmation dialog + approval_required toggle. */}
      <section className="space-y-3">
        <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide">Public Delegates</h2>
        <div className="bg-white border border-gray-200 rounded-xl p-5 space-y-4">
          <label className="flex items-start gap-3 cursor-pointer">
            <input
              type="checkbox"
              checked={settings.public_delegates?.enabled !== false}
              onChange={async (e) => {
                const turningOff = !e.target.checked
                  && settings.public_delegates?.enabled !== false;
                if (turningOff) {
                  // P2 — count public/public_accepting topics in this org
                  // before showing the confirmation dialog.
                  let count = 0;
                  try {
                    const rows = await api.get(`/api/orgs/${currentOrg.slug}/delegates?limit=100`);
                    count = Array.isArray(rows) ? rows.length : 0;
                  } catch {/* if the count fails, show generic dialog */}
                  setPdDisableConfirm({ count });
                  return;
                }
                updateSetting('public_delegates', {
                  ...(settings.public_delegates || {}),
                  enabled: e.target.checked,
                });
              }}
              className="mt-0.5 accent-[var(--brand-accent)]"
            />
            <div>
              <p className="text-sm text-gray-700">Public delegate pages enabled</p>
              <p className="text-xs text-gray-400">
                When off, public delegate pages return 404 and the delegate browse returns empty. Data is preserved; re-enable to restore.
              </p>
            </div>
          </label>
          {settings.public_delegates?.enabled !== false && (
            <label className="flex items-start gap-3 cursor-pointer">
              <input
                type="checkbox"
                checked={settings.public_delegates?.approval_required !== false}
                onChange={e => updateSetting('public_delegates', {
                  ...(settings.public_delegates || {}),
                  approval_required: e.target.checked,
                })}
                className="mt-0.5 accent-[var(--brand-accent)]"
              />
              <div>
                <p className="text-sm text-gray-700">Require approval for delegates to promote topics to publicly visible</p>
                <p className="text-xs text-gray-400">
                  {settings.public_delegates?.approval_required !== false
                    ? 'Approvers must review and approve before a topic becomes publicly visible.'
                    : 'Members can promote their topics to publicly visible without approval. Approvers do not gate transitions.'}
                </p>
              </div>
            </label>
          )}
          <div className="flex items-center gap-3 pt-2 border-t border-gray-100">
            <button
              type="button"
              onClick={handleSavePublicDelegates}
              disabled={savingPublicDelegates}
              className="px-5 py-2 bg-[var(--brand-primary)] text-white text-sm rounded-lg hover:bg-[var(--brand-accent)] transition-colors disabled:opacity-50"
            >
              {savingPublicDelegates ? 'Saving…' : 'Save public delegate settings'}
            </button>
          </div>
        </div>
      </section>

      {/* P2 disable confirmation dialog. */}
      {pdDisableConfirm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 px-4">
          <div className="bg-white rounded-xl shadow-xl max-w-md w-full p-6 space-y-4">
            <h3 className="text-lg font-semibold text-gray-800">Disable public delegate pages?</h3>
            <p className="text-sm text-gray-700">
              {pdDisableConfirm.count > 0
                ? `${pdDisableConfirm.count} delegate page${pdDisableConfirm.count === 1 ? '' : 's'} ${pdDisableConfirm.count === 1 ? 'has' : 'have'} publicly-visible topics. Disabling will hide them from public view.`
                : 'Public delegate pages will be hidden from public view.'}{' '}
              All data is preserved and pages will return if you re-enable. Continue?
            </p>
            <div className="flex gap-2 justify-end">
              <button
                type="button"
                onClick={() => setPdDisableConfirm(null)}
                className="text-sm px-4 py-2 border border-gray-300 text-gray-700 rounded-lg hover:bg-gray-50 transition-colors"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={() => {
                  updateSetting('public_delegates', {
                    ...(settings.public_delegates || {}),
                    enabled: false,
                  });
                  setPdDisableConfirm(null);
                }}
                className="text-sm px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 transition-colors"
              >
                Disable
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Phase 34 F1 — bottom-of-page "Save All Settings" button so users
          editing the lower sections (Branding / Deliberation Engagement /
          Public Delegates / etc.) don't have to scroll back to the top
          General section. Same handler as the top button; PATCHes the
          entire settings payload. */}
      <section className="space-y-3">
        <div className="flex items-center gap-3">
          <button
            onClick={handleSave}
            disabled={saving}
            className="px-6 py-2 bg-[var(--brand-primary)] text-white text-sm rounded-lg hover:bg-[var(--brand-accent)] transition-colors disabled:opacity-50"
          >
            {saving ? 'Saving...' : 'Save All Settings'}
          </button>
          {msg && (
            <span className={`text-sm ${msg === 'Settings saved' ? 'text-green-600' : 'text-red-600'}`}>{msg}</span>
          )}
        </div>
      </section>

      {/* Phase 45b F1 — Governance Mode. The switch is bidirectional:
          single_steward → admin_council (steward initiates; demotes
          self to admin) and the reverse (any admin picks who claims the
          new steward seat). Hidden in council mode for the transfer
          stewardship section below since there's no steward to transfer
          from. */}
      {(canSwitchToCouncil || canRevertToSingle) && (
        <section className="space-y-3">
          <h2 className="text-sm font-semibold text-gray-700 uppercase tracking-wide">Top leadership</h2>
          <div className="bg-white border border-gray-200 rounded-xl p-5 space-y-3">
            <div>
              <p className="text-sm text-gray-700">
                Currently: <strong>{governanceMode === 'admin_council' ? 'A team of admins, no single top leader' : 'A single top leader (Steward)'}</strong>
              </p>
              <p className="text-xs text-gray-500 mt-1">
                {governanceMode === 'admin_council'
                  ? 'Top authority is shared by every admin. There is no single top officer; any active admin can act with full authority.'
                  : 'The Steward is the single top officer. Every other role is below the Steward. This is the default setup.'}
              </p>
            </div>
            {canSwitchToCouncil && (
              <div className="space-y-2">
                <p className="text-sm text-gray-600">
                  Switch to a team of admins with no single top leader. You become an
                  admin alongside any existing admins; there will no longer be a Steward.
                  Reversible.
                </p>
                <button
                  onClick={handleSwitchToCouncil}
                  disabled={savingGovernanceMode}
                  className="text-sm px-4 py-2 border border-gray-300 text-gray-700 rounded-lg hover:bg-gray-50 transition-colors disabled:opacity-50"
                >
                  {savingGovernanceMode ? 'Switching…' : 'Switch to team of admins'}
                </button>
              </div>
            )}
            {canRevertToSingle && (
              <div className="space-y-2">
                <p className="text-sm text-gray-600">
                  Switch back to a single top leader. Pick an admin (or yourself) to
                  become the new Steward; the remaining admins keep their role.
                </p>
                {revertMembers.length === 0 && !loadingRevertMembers ? (
                  <button
                    onClick={loadRevertMembers}
                    className="text-sm px-4 py-2 border border-gray-300 text-gray-700 rounded-lg hover:bg-gray-50 transition-colors"
                  >
                    Pick new Steward…
                  </button>
                ) : loadingRevertMembers ? (
                  <p className="text-sm text-gray-500">Loading admins…</p>
                ) : (
                  <>
                    <label className="block text-xs text-gray-600">New Steward (leave blank to claim it yourself)</label>
                    <select
                      value={revertTargetId}
                      onChange={e => setRevertTargetId(e.target.value)}
                      className="w-full max-w-md px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-400"
                    >
                      <option value="">(myself)</option>
                      {revertMembers.map(m => (
                        <option key={m.user_id} value={m.user_id}>
                          {m.display_name || m.username}
                        </option>
                      ))}
                    </select>
                    <button
                      onClick={handleRevertToSingle}
                      disabled={savingGovernanceMode}
                      className="text-sm px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors disabled:opacity-50"
                    >
                      {savingGovernanceMode ? 'Switching…' : 'Switch back to a single top leader'}
                    </button>
                  </>
                )}
              </div>
            )}
          </div>
        </section>
      )}

      {/* Phase 45a F2 — voluntary stewardship handoff. Gated on the
          permission key (today Steward-only via OWNER_ONLY_KEYS, but
          using the permission gate keeps the UI honest if the key ever
          relaxes). The action is an atomic role swap (outgoing → admin,
          incoming → steward), implemented as a single backend transaction.
          Phase 45b F2 — also hide when org is in admin_council mode (no
          Steward to transfer from; the analogous control there is the
          Governance Mode revert above). */}
      {canTransferStewardship && governanceMode === 'single_steward' && (
        <section className="space-y-3">
          <h2 className="text-sm font-semibold text-gray-700 uppercase tracking-wide">Stewardship</h2>
          <div className="bg-white border border-gray-200 rounded-xl p-5 space-y-3">
            <p className="text-sm text-gray-700">
              Hand off Steward of <strong>{currentOrg.name}</strong> to another active member.
              You will become an Admin; they will become the new Steward.
            </p>
            {!showTransfer ? (
              <button
                onClick={() => {
                  setShowTransfer(true);
                  if (transferMembers.length === 0) loadTransferMembers();
                }}
                className="text-sm px-4 py-2 border border-gray-300 text-gray-700 rounded-lg hover:bg-gray-50 transition-colors"
              >
                Transfer Stewardship…
              </button>
            ) : (
              <div className="space-y-3">
                {loadingTransferMembers ? (
                  <p className="text-sm text-gray-500">Loading members…</p>
                ) : (
                  <>
                    <label className="block text-xs text-gray-600">
                      New Steward
                    </label>
                    <select
                      value={transferTargetId}
                      onChange={e => setTransferTargetId(e.target.value)}
                      className="w-full max-w-md px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-400"
                    >
                      <option value="">Select a member…</option>
                      {transferMembers
                        .filter(m => m.role !== 'steward')
                        .map(m => (
                          <option key={m.user_id} value={m.user_id}>
                            {m.display_name || m.username} ({m.role})
                          </option>
                        ))}
                    </select>
                    <div className="flex gap-2">
                      <button
                        onClick={handleTransferStewardship}
                        disabled={!transferTargetId || savingTransfer}
                        className="text-sm px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors disabled:opacity-50"
                      >
                        {savingTransfer ? 'Transferring…' : 'Transfer Stewardship'}
                      </button>
                      <button
                        onClick={() => { setShowTransfer(false); setTransferTargetId(''); }}
                        className="text-sm px-4 py-2 border border-gray-300 text-gray-600 rounded-lg hover:bg-gray-50"
                      >
                        Cancel
                      </button>
                    </div>
                  </>
                )}
              </div>
            )}
          </div>
        </section>
      )}

      {/* Phase 50 — Leave Organization. Available to ANY active
          member (this is not an admin-only action). The informed-
          confirm dialog (D5) names what's lost — membership, held
          titles, and org-scoped delegations — and the inline
          transfer-first flow (D2) handles the sole-governor case. */}
      <section className="space-y-3">
        <h2 className="text-sm font-semibold text-gray-700 uppercase tracking-wide">
          Leave organization
        </h2>
        <div className="bg-white border border-gray-200 rounded-xl p-5 space-y-3">
          {leaveStage === 'idle' && (
            <>
              <p className="text-sm text-gray-700">
                Leaving means losing access to <strong>{currentOrg.name}</strong>'s proposals, members,
                and any role you hold here. If you're the only top leader,
                you'll be asked to hand off first.
              </p>
              <button
                onClick={() => setLeaveStage('confirm')}
                className="text-sm px-4 py-2 border border-gray-300 text-gray-700 rounded-lg hover:bg-gray-50 transition-colors"
              >
                Leave organization…
              </button>
            </>
          )}
          {leaveStage === 'confirm' && (
            <>
              <p className="text-sm text-gray-700">
                You're about to leave <strong>{currentOrg.name}</strong>. Here's what happens:
              </p>
              <ul className="text-xs text-gray-600 list-disc pl-5 space-y-1">
                <li>Your membership ends. You lose access to this organization's proposals, members list, and admin surfaces (if any).</li>
                <li>Any titles you hold in this organization (e.g. office or council seat) are revoked.</li>
                <li>Any delegations you've made within this organization are cleaned up.</li>
                <li>Other members who delegate to you in this organization will fall back to direct voting (the engine handles this automatically).</li>
              </ul>
              <p className="text-xs text-gray-500">
                You can rejoin later if the org's join policy allows it.
              </p>
              <div className="flex gap-2">
                <button
                  onClick={submitLeave}
                  disabled={leavingNow}
                  className="text-sm px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 transition-colors disabled:opacity-50"
                >
                  {leavingNow ? 'Leaving…' : 'Confirm and leave'}
                </button>
                <button
                  onClick={() => setLeaveStage('idle')}
                  disabled={leavingNow}
                  className="text-sm px-4 py-2 border border-gray-300 text-gray-600 rounded-lg hover:bg-gray-50 disabled:opacity-50"
                >
                  Cancel
                </button>
              </div>
            </>
          )}
          {leaveStage === 'transfer_required' && (
            <>
              <p className="text-sm text-gray-700">
                You're the only top leader of <strong>{currentOrg.name}</strong>. To leave, hand off
                stewardship to another active member first. Then come back and
                click Leave again to complete your departure.
              </p>
              <p className="text-xs text-gray-500">
                The successor takes the seat as the interim Steward, subject to
                the normal election / handoff processes the organization uses.
              </p>
              <label className="block text-xs text-gray-600">
                New Steward
              </label>
              <select
                value={leaveTransferTargetId}
                onChange={e => setLeaveTransferTargetId(e.target.value)}
                className="w-full max-w-md px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-400"
              >
                <option value="">Select a member…</option>
                {leaveTransferMembers
                  .filter(m => m.role !== 'steward')
                  .map(m => (
                    <option key={m.user_id} value={m.user_id}>
                      {m.display_name || m.username} ({m.role})
                    </option>
                  ))}
              </select>
              <div className="flex gap-2">
                <button
                  onClick={handleLeaveTransferThenRetry}
                  disabled={!leaveTransferTargetId || leavingNow}
                  className="text-sm px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors disabled:opacity-50"
                >
                  {leavingNow ? 'Transferring…' : 'Transfer stewardship'}
                </button>
                <button
                  onClick={() => { setLeaveStage('idle'); setLeaveTransferTargetId(''); }}
                  disabled={leavingNow}
                  className="text-sm px-4 py-2 border border-gray-300 text-gray-600 rounded-lg hover:bg-gray-50 disabled:opacity-50"
                >
                  Cancel
                </button>
              </div>
            </>
          )}
        </div>
      </section>

      {/* Danger Zone — Phase 45a F1 — permission-driven gate (recon GAP-5).
          org.delete is an OWNER_ONLY_KEY today; the permission check
          resolves to True only for Steward, identical to the prior
          role-string check. Switching the gate keeps the UI consistent
          with the Phase 12.5/12.6 convention used elsewhere on the page. */}
      {canDeleteOrg && (
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

import { useState, useEffect, useRef } from 'react';
import { useOrg } from '../../OrgContext';
import api from '../../api';
import { useToast } from '../../components/Toast';
import { useConfirm } from '../../components/ConfirmDialog';
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
  //
  // The org-delete endpoint (DELETE /api/orgs/{slug}) is one of two D4
  // hardcoded gates: its permission cannot be reassigned through the
  // role-permissions matrix. Anyone short of Steward who clicks "Delete
  // organization" hits the role-agnostic 403 with no path to fix it
  // through the matrix UI, which is a confusing UX path. So we hide the
  // entire Danger Zone section from non-Stewards. The backend 403 stays
  // as defense in depth for direct API callers (curl, etc.).
  //
  // The legacy 'owner' system_key is also accepted: pre-Stage-1 cached
  // /api/orgs responses may still report 'owner' for the same human user
  // briefly during deploy cutover, and we don't want to lock the actual
  // org owner out of the delete control they've always had.
  //
  // (Sub-org delete in SubOrgSettings is matrix-routed via sub_org.delete
  // and is correctly governed by has_permission server-side; that surface
  // is intentionally not gated this way.)
  const isSteward = !!(
    currentOrg &&
    (currentOrg.user_role === 'steward' || currentOrg.user_role === 'owner')
  );
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

  useEffect(() => {
    if (currentOrg) {
      setName(currentOrg.name);
      setDescription(currentOrg.description || '');
      // Phase 14 F3 — the join_policy enum expanded from {invite_only,
      // approval_required, open} to {invite_only_secret, invite_only_public,
      // approval_required, open}. The backend B1 migration renames legacy
      // 'invite_only' rows to 'invite_only_secret', and B5 rejects the old
      // value going forward. During the deploy cutover a stale /api/orgs
      // response could still report 'invite_only' to a freshly-loaded
      // bundle, so we coerce it to 'invite_only_secret' here so the radio
      // selection matches the intent ("don't expose me publicly"). After
      // a single save the value persists in the new form and this branch
      // is unreached.
      setJoinPolicy(
        currentOrg.join_policy === 'invite_only'
          ? 'invite_only_secret'
          : currentOrg.join_policy
      );
      const s = currentOrg.settings || {};
      setSettings(s);
      // Expand the SM section if the org currently has it on, or if any
      // SM key is customized away from the default.
      setSmExpanded(!!s.sustained_majority_enabled_default || smIsCustomized(s));
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
                <input
                  type="color"
                  value={accentColor}
                  onChange={(e) => setAccentColor(e.target.value)}
                  disabled={autoDeriveAccent}
                  className="h-10 w-14 border border-gray-300 rounded cursor-pointer p-0 disabled:cursor-not-allowed disabled:opacity-50"
                  aria-label="Accent color picker"
                />
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
        </div>
      </section>

      {/* Sustained-Majority Voting (Phase 8 — demoted to collapsed-by-default in 9.6;
          Phase 9.8 W C2 — dropped the "(advanced)" suffix and refreshed the
          helper copy now that the floor-activation logic is fixed in C1). */}
      <section className="space-y-3">
        <div className="flex items-baseline justify-between">
          <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide">
            Sustained-majority voting
          </h2>
          <a
            href="/help/sustained-majority"
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
              className="mt-0.5 accent-[var(--brand-accent)]"
            />
            <div>
              <p className="text-sm text-gray-700">Enable sustained-majority voting</p>
              <p className="text-xs text-gray-400">
                Off by default. Enable when your organization makes binding decisions that benefit from durable-consensus protection — proposals must maintain support throughout the voting window, not just at close.
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
                  className="mt-0.5 accent-[var(--brand-accent)]"
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
                  className="mt-0.5 accent-[var(--brand-accent)]"
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
                  className="w-full accent-[var(--brand-accent)]"
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
                  className="w-full accent-[var(--brand-accent)]"
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

      {/* Public Delegates */}
      <section className="space-y-3">
        <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide">Public Delegates</h2>
        <div className="bg-white border border-gray-200 rounded-xl p-5 space-y-4">
          <label className="flex items-center gap-3 cursor-pointer">
            <input
              type="checkbox"
              checked={settings.allow_public_delegates ?? true}
              onChange={e => updateSetting('allow_public_delegates', e.target.checked)}
              className="accent-[var(--brand-accent)]"
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
                    className="mt-0.5 accent-[var(--brand-accent)]"
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
          className="px-6 py-2 bg-[var(--brand-primary)] text-white text-sm rounded-lg hover:bg-[var(--brand-accent)] transition-colors disabled:opacity-50"
        >
          {saving ? 'Saving...' : 'Save Settings'}
        </button>
        {msg && (
          <span className={`text-sm ${msg === 'Settings saved' ? 'text-green-600' : 'text-red-600'}`}>{msg}</span>
        )}
      </div>

      {/* Danger Zone — Phase 12 Stage 2 F7 D4 UI hiding (see isSteward
          derivation comment at the top of this file). */}
      {isSteward && (
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

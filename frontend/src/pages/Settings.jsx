import { useState, useEffect, useCallback, useRef } from 'react';
import { useAuth } from '../AuthContext';
import { useOrg } from '../OrgContext';
import api from '../api';
import { resizeImageFile } from '../utils/imageResize';
import { labelForState, VERIFICATION_PROVENANCE_LABELS, UP_FRONT_ONE_IDENTITY_COPY } from '../verificationLabels';
import Avatar from '../components/Avatar';
import { useToast } from '../components/Toast';
import { useConfirm } from '../components/ConfirmDialog';
import AccessHistory from '../components/AccessHistory';
import { Link } from 'react-router-dom';

/**
 * Phase 52a — verification section with the real Didit "Start
 * verification" CTA. Shows current status + provenance; hides the
 * CTA when the user is already at the strongest state we can
 * produce from Didit (address_on_id) since re-verifying buys
 * nothing. Disclosure copy returned by the backend is rendered
 * verbatim BEFORE the redirect.
 */
function VerificationSection({ user }) {
  const [starting, setStarting] = useState(false);
  const [pendingDisclosure, setPendingDisclosure] = useState(null);
  const [pendingUrl, setPendingUrl] = useState(null);
  const [err, setErr] = useState('');

  const state = user?.verification_state || 'email_only';
  // Don't show the CTA once the user is already verified at our
  // strongest state.
  const showStartCta = state === 'email_only' || state === 'identity' || state === 'identity_unique';

  async function handleStart() {
    setStarting(true);
    setErr('');
    try {
      const resp = await api.post('/api/verification/session', {});
      setPendingDisclosure(resp.consent_disclosure || '');
      setPendingUrl(resp.session_url);
    } catch (e) {
      setErr(e?.message || 'Could not start verification.');
    } finally {
      setStarting(false);
    }
  }

  function handleProceed() {
    if (pendingUrl) {
      window.location.href = pendingUrl;
    }
  }

  function handleCancel() {
    setPendingDisclosure(null);
    setPendingUrl(null);
  }

  return (
    <section className="space-y-3">
      <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide">Identity verification</h2>
      <div className="bg-white border border-gray-200 rounded-xl p-5 space-y-2">
        <div className="flex items-baseline gap-3">
          <span className="text-xs text-gray-500">Status</span>
          <span className="text-sm text-gray-700">{labelForState(state)}</span>
        </div>
        {user?.verification_jurisdiction && (
          <div className="flex items-baseline gap-3">
            <span className="text-xs text-gray-500">Jurisdiction</span>
            <span className="text-sm text-gray-700">{user.verification_jurisdiction}</span>
          </div>
        )}
        {user?.verification_provenance && user.verification_provenance !== 'none' && (
          <div className="flex items-baseline gap-3">
            <span className="text-xs text-gray-500">Source</span>
            <span className="text-sm text-gray-700">
              {VERIFICATION_PROVENANCE_LABELS[user.verification_provenance] || user.verification_provenance}
            </span>
          </div>
        )}
        <p className="text-xs text-gray-500 pt-2">
          Some organizations may require identity verification to join, hold a role, or cast a vote on certain proposals.
        </p>

        {pendingDisclosure ? (
          <div className="mt-3 border-t border-gray-200 pt-3 space-y-3">
            <p className="text-sm text-gray-700">{pendingDisclosure}</p>
            {/* Phase 84 — clickable link to the provider's privacy policy
                (the backend disclosure string is plain text and cannot carry
                a link). */}
            <p className="text-xs text-gray-500">
              Read{' '}
              <a
                href="https://didit.me/terms/privacy-policy/"
                target="_blank"
                rel="noopener noreferrer"
                className="text-[var(--brand-accent)] hover:underline"
              >
                Didit&apos;s privacy policy
              </a>
              .
            </p>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={handleProceed}
                className="text-sm px-4 py-2 bg-[var(--brand-primary)] text-white rounded-lg hover:bg-[var(--brand-accent)] transition-colors"
              >
                Continue to identity provider
              </button>
              <button
                type="button"
                onClick={handleCancel}
                className="text-sm px-4 py-2 border border-gray-300 text-gray-600 rounded-lg hover:bg-gray-50 transition-colors"
              >
                Cancel
              </button>
            </div>
          </div>
        ) : showStartCta ? (
          <div className="mt-3 border-t border-gray-200 pt-3 space-y-2">
            {/* Phase 52e Stage 2 E5 — up-front one-identity expectation
                copy, shown before the user leaves for the verification
                provider so the dedup-block case downstream isn't a
                surprise. */}
            <p className="text-xs text-gray-600">{UP_FRONT_ONE_IDENTITY_COPY}</p>
            <button
              type="button"
              onClick={handleStart}
              disabled={starting}
              className="text-sm px-4 py-2 bg-[var(--brand-primary)] text-white rounded-lg hover:bg-[var(--brand-accent)] transition-colors disabled:opacity-50"
            >
              {starting ? 'Starting…' : 'Start verification'}
            </button>
            {err && (
              <p className="text-xs text-red-600 mt-2">{err}</p>
            )}
          </div>
        ) : null}
      </div>
    </section>
  );
}


const POLICY_OPTIONS = [
  {
    value: 'require_approval',
    label: 'Require my approval for all requests',
    desc: "You'll review each request individually",
  },
  {
    value: 'auto_approve_view',
    label: 'Auto-approve follow requests (view only)',
    desc: 'Anyone can follow and see your votes, but delegation still requires your approval',
  },
  {
    value: 'auto_approve_delegate',
    label: 'Auto-approve follow and delegate requests',
    desc: 'Anyone can follow you and delegate their votes to you automatically',
  },
];

// Phase 30 B1 — DelegateCard component removed along with the Settings
// page's obsolete public-delegate-registration section. The canonical
// surface is /{slug}/delegate-profile (DelegateProfile.jsx). See the
// "Public Delegate Page" section below for the replacement link.

export default function Settings() {
  const { user: authUser, refreshUser, logout } = useAuth();
  const { currentOrg } = useOrg();
  const toast = useToast();
  const confirm = useConfirm();
  const fileInputRef = useRef(null);
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);
  const [displayName, setDisplayName] = useState('');
  const [policy, setPolicy] = useState('require_approval');
  const [profileMsg, setProfileMsg] = useState('');
  const [policyMsg, setPolicyMsg] = useState('');
  // Phase 77 — direct-message opt-out.
  const [dmDisabled, setDmDisabled] = useState(false);
  const [dmMsg, setDmMsg] = useState('');
  const [pwCurrent, setPwCurrent] = useState('');
  const [pwNew, setPwNew] = useState('');
  const [pwConfirm, setPwConfirm] = useState('');
  const [pwMsg, setPwMsg] = useState('');
  const [logoutAllMsg, setLogoutAllMsg] = useState('');
  const [avatarMsg, setAvatarMsg] = useState('');
  const [avatarBusy, setAvatarBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const me = await api.get('/api/auth/me');
      setUser(me);
      setDisplayName(me.display_name);
      setPolicy(me.default_follow_policy);
      setDmDisabled(!!me.dm_disabled);
    } catch { /* ignore */ } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  async function saveProfile() {
    setProfileMsg('');
    try {
      await api.patch('/api/auth/me', { display_name: displayName });
      setProfileMsg('Saved');
      setTimeout(() => setProfileMsg(''), 2000);
    } catch (e) {
      setProfileMsg(e.message);
    }
  }

  async function savePolicy() {
    setPolicyMsg('');
    try {
      await api.patch('/api/auth/me', { default_follow_policy: policy });
      setPolicyMsg('Saved');
      setTimeout(() => setPolicyMsg(''), 2000);
    } catch (e) {
      setPolicyMsg(e.message);
    }
  }

  // Phase 77 — toggle DM opt-out (save-on-change).
  async function toggleDmDisabled(next) {
    setDmMsg('');
    setDmDisabled(next);
    try {
      await api.patch('/api/auth/me', { dm_disabled: next });
      setDmMsg('Saved');
      setTimeout(() => setDmMsg(''), 2000);
    } catch (e) {
      setDmDisabled(!next);
      setDmMsg(e.message || 'Could not save');
    }
  }

  async function handleAvatarUploadFile(file) {
    if (!file) return;
    setAvatarMsg('');
    setAvatarBusy(true);
    try {
      // Phase 9.9 W3 — client-side resize before upload. Brings phone
      // photos (5+ MB) down to ~30 KB so the upload succeeds quickly and
      // stays well under the backend ceiling. If the resize fails for any
      // reason (corrupt image, browser without canvas support), fall
      // through to upload the original file.
      let toUpload = file;
      try {
        toUpload = await resizeImageFile(file);
      } catch (resizeErr) {
        console.warn('Avatar resize failed; uploading original file', resizeErr);
        toUpload = file;
      }
      const form = new FormData();
      form.append('file', toUpload);
      // Phase 9.9 W4 — route through api wrapper so the auth refresh-and-
      // retry path covers expired access tokens during multipart upload.
      await api.postFormData('/api/users/me/avatar', form);
      toast.success('Avatar updated');
      await refreshUser();
      // Re-load the local user copy too so the Settings header avatar updates.
      const me = await api.get('/api/auth/me');
      setUser(me);
    } catch (e) {
      setAvatarMsg(e.message || 'Upload failed');
      toast.error(e.message || 'Upload failed');
    } finally {
      setAvatarBusy(false);
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  }

  async function handleAvatarRemove() {
    const ok = await confirm({
      title: 'Remove avatar?',
      message: 'Your profile will fall back to your initials. You can upload a new one any time.',
      destructive: true,
    });
    if (!ok) return;
    setAvatarMsg('');
    setAvatarBusy(true);
    try {
      await api.delete('/api/users/me/avatar');
      toast.success('Avatar removed');
      await refreshUser();
      const me = await api.get('/api/auth/me');
      setUser(me);
    } catch (e) {
      setAvatarMsg(e.message || 'Failed to remove avatar');
      toast.error(e.message || 'Failed to remove avatar');
    } finally {
      setAvatarBusy(false);
    }
  }

  async function handleChangePassword() {
    setPwMsg('');
    if (pwNew !== pwConfirm) { setPwMsg('Passwords do not match'); return; }
    try {
      await api.post('/api/auth/change-password', {
        current_password: pwCurrent,
        new_password: pwNew,
      });
      setPwMsg('Password changed');
      setPwCurrent(''); setPwNew(''); setPwConfirm('');
      setTimeout(() => setPwMsg(''), 3000);
    } catch (e) {
      setPwMsg(e.message);
    }
  }

  async function handleLogoutAll() {
    setLogoutAllMsg('');
    const ok = await confirm({
      title: 'Log Out Everywhere',
      message: 'This will log you out of all devices, including this one. Continue?',
      destructive: true,
    });
    if (!ok) return;
    try {
      const res = await api.post('/api/auth/logout-all', {});
      setLogoutAllMsg(res.message || 'Logged out of all devices');
      setTimeout(() => logout(), 1500);
    } catch (e) {
      setLogoutAllMsg(e.message);
    }
  }

  if (loading) return (
    <div className="flex justify-center items-center py-20">
      <div className="animate-spin w-8 h-8 border-4 border-[var(--brand-accent)] border-t-transparent rounded-full"></div>
    </div>
  );

  return (
    <div className="max-w-3xl mx-auto px-4 py-8 space-y-10">
      <h1 className="text-2xl font-semibold text-[var(--brand-primary)]">Settings</h1>

      {/* Section: Profile picture (Phase 9.8 W A2) */}
      <section className="space-y-3">
        <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide">Profile Picture</h2>
        <div className="bg-white border border-gray-200 rounded-xl p-5 flex items-center gap-5 flex-wrap">
          <Avatar user={user} size="lg" />
          <div className="flex-1 min-w-0 space-y-2">
            <p className="text-xs text-gray-500">
              JPEG, PNG, or WebP. Max 6 MB. Resized in your browser before upload.
            </p>
            <div className="flex gap-2 flex-wrap">
              <input
                ref={fileInputRef}
                type="file"
                accept="image/jpeg,image/png,image/webp"
                onChange={e => handleAvatarUploadFile(e.target.files?.[0])}
                className="hidden"
              />
              <button
                onClick={() => fileInputRef.current?.click()}
                disabled={avatarBusy}
                className="text-sm px-4 py-2 bg-[var(--brand-primary)] text-white rounded-lg hover:bg-[var(--brand-accent)] transition-colors disabled:opacity-50"
              >
                {avatarBusy ? 'Working…' : (user?.avatar_url ? 'Replace' : 'Upload')}
              </button>
              {user?.avatar_url && (
                <button
                  onClick={handleAvatarRemove}
                  disabled={avatarBusy}
                  className="text-sm px-4 py-2 border border-red-300 text-red-600 rounded-lg hover:bg-red-50 transition-colors disabled:opacity-50"
                >
                  Remove
                </button>
              )}
            </div>
            {avatarMsg && <p className="text-xs text-red-600">{avatarMsg}</p>}
          </div>
        </div>
      </section>

      {/* Section: Profile */}
      <section className="space-y-3">
        <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide">Profile Information</h2>
        <div className="bg-white border border-gray-200 rounded-xl p-5 space-y-4">
          <div>
            <label className="block text-xs text-gray-500 mb-1">Display Name</label>
            <input
              type="text"
              value={displayName}
              onChange={e => setDisplayName(e.target.value)}
              className="w-full max-w-xs px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[var(--brand-accent)]"
            />
          </div>
          <div>
            <label className="block text-xs text-gray-500 mb-1">Username</label>
            <p className="text-sm text-gray-600">@{user?.username}</p>
          </div>
          <div className="flex items-center gap-3">
            <button
              onClick={saveProfile}
              disabled={!displayName || displayName === user?.display_name}
              className="text-sm px-4 py-2 bg-[var(--brand-primary)] text-white rounded-lg hover:bg-[var(--brand-accent)] transition-colors disabled:opacity-50"
            >
              Save Changes
            </button>
            {profileMsg && <span className={`text-xs ${profileMsg === 'Saved' ? 'text-green-600' : 'text-red-600'}`}>{profileMsg}</span>}
          </div>
        </div>
      </section>

      {/* Phase 51 — read-only verification status; Phase 52a adds the
          real Didit-backed "Start verification" path. The CTA opens a
          hosted Didit session (modal preferred, redirect fallback) and
          relies on the webhook to update the user record; the FE
          re-reads on next load. Labels come from
          ``../verificationLabels`` so any future copy change is a
          one-file edit. */}
      <VerificationSection user={user} />

      {/* Section: Follow Preferences */}
      <section className="space-y-3">
        <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide">Follow & Delegation Preferences</h2>
        <div className="bg-white border border-gray-200 rounded-xl p-5 space-y-3">
          <p className="text-sm text-gray-600 mb-2">When someone sends you a follow request:</p>
          {POLICY_OPTIONS.map(opt => (
            <label key={opt.value} className="flex items-start gap-3 cursor-pointer">
              <input
                type="radio"
                name="policy"
                value={opt.value}
                checked={policy === opt.value}
                onChange={() => setPolicy(opt.value)}
                className="mt-0.5 accent-[var(--brand-accent)]"
              />
              <div>
                <p className="text-sm text-gray-700">{opt.label}</p>
                <p className="text-xs text-gray-400">{opt.desc}</p>
              </div>
            </label>
          ))}
          <div className="flex items-center gap-3 pt-2">
            <button
              onClick={savePolicy}
              disabled={policy === user?.default_follow_policy}
              className="text-sm px-4 py-2 bg-[var(--brand-primary)] text-white rounded-lg hover:bg-[var(--brand-accent)] transition-colors disabled:opacity-50"
            >
              Save Preferences
            </button>
            {policyMsg && <span className={`text-xs ${policyMsg === 'Saved' ? 'text-green-600' : 'text-red-600'}`}>{policyMsg}</span>}
          </div>
        </div>
      </section>

      {/* Section: Messaging (Phase 77) */}
      <section className="space-y-3">
        <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide">Messaging</h2>
        <div className="bg-white border border-gray-200 rounded-xl p-5">
          <label className="flex items-start gap-3 cursor-pointer">
            <input
              type="checkbox"
              checked={dmDisabled}
              onChange={(e) => toggleDmDisabled(e.target.checked)}
              className="mt-0.5 accent-[var(--brand-accent)]"
            />
            <span>
              <span className="block text-sm text-gray-700">Disable direct messages from other members</span>
              <span className="block text-xs text-gray-400">
                When enabled, other members can't start new message conversations with
                you. You can still be contacted by delegates you follow and via the org
                inbox. Existing conversations are not affected.
              </span>
            </span>
          </label>
          {dmMsg && <p className={`text-xs mt-2 ${dmMsg === 'Saved' ? 'text-green-600' : 'text-red-600'}`}>{dmMsg}</p>}
        </div>
      </section>

      {/* Section: Notifications (Phase 13 F4) */}
      <section className="space-y-3">
        <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide">Notifications</h2>
        <div className="bg-white border border-gray-200 rounded-xl p-5 flex items-center justify-between gap-4 flex-wrap">
          <div className="flex-1 min-w-0">
            <p className="text-sm text-gray-700">
              Choose which events generate in-app and email notifications.
            </p>
            <p className="text-xs text-gray-500 mt-1">
              Notifications are off by default. Pick the ones you want, set a digest cadence,
              and configure quiet hours.
            </p>
          </div>
          <Link
            to="/settings/notifications"
            className="text-sm px-4 py-2 border border-[var(--brand-accent)] text-[var(--brand-accent)] rounded-lg hover:bg-[var(--brand-accent)] hover:text-white transition-colors"
          >
            Manage notifications
          </Link>
        </div>
      </section>

      {/* Section: Public Delegate Registration */}
      {/* Phase 30 B1 — obsolete public-delegate-registration section
          replaced with a link to the canonical /{slug}/delegate-profile
          page. The legacy /api/delegates/register endpoint and the
          DelegateCard inline editor predate the per-topic visibility
          lifecycle (private / public / public_accepting) and don't
          match the current backend contract; managing your delegate
          page from here would 400 on most transitions. */}
      <section className="space-y-3">
        <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide">Public Delegate Page</h2>
        {currentOrg?.slug ? (
          <div className="p-4 bg-[var(--brand-surface-soft,#f3f4f6)] border border-gray-200 rounded-xl">
            <p className="text-sm text-gray-700 mb-3">
              Become a public delegate, set position statements per topic, and
              write vote rationales from your delegate page.
            </p>
            <Link
              to={`/${currentOrg.slug}/delegate-profile`}
              className="inline-block text-sm px-4 py-2 bg-[var(--brand-primary)] text-white rounded-lg hover:opacity-90"
            >
              Go to My Delegate Page
            </Link>
          </div>
        ) : (
          <p className="text-xs text-gray-400">
            Select an organization to manage your delegate page.
          </p>
        )}
      </section>

      {/* Section: Account */}
      <section className="space-y-3">
        <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide">Account</h2>
        <div className="bg-white border border-gray-200 rounded-xl p-5 space-y-4">
          <h3 className="text-sm font-medium text-gray-700">Change Password</h3>
          <div className="space-y-2 max-w-xs">
            <input
              type="password"
              value={pwCurrent}
              onChange={e => setPwCurrent(e.target.value)}
              placeholder="Current password"
              className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[var(--brand-accent)]"
            />
            <input
              type="password"
              value={pwNew}
              onChange={e => setPwNew(e.target.value)}
              placeholder="New password (min 8 chars)"
              className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[var(--brand-accent)]"
            />
            <input
              type="password"
              value={pwConfirm}
              onChange={e => setPwConfirm(e.target.value)}
              placeholder="Confirm new password"
              className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[var(--brand-accent)]"
            />
          </div>
          <div className="flex items-center gap-3">
            <button
              onClick={handleChangePassword}
              disabled={!pwCurrent || pwNew.length < 8}
              className="text-sm px-4 py-2 bg-[var(--brand-primary)] text-white rounded-lg hover:bg-[var(--brand-accent)] transition-colors disabled:opacity-50"
            >
              Change Password
            </button>
            {pwMsg && <span className={`text-xs ${pwMsg === 'Password changed' ? 'text-green-600' : 'text-red-600'}`}>{pwMsg}</span>}
          </div>

          <div className="pt-4 border-t border-gray-100">
            <h3 className="text-sm font-medium text-gray-700 mb-2">Sessions</h3>
            <p className="text-xs text-gray-400 mb-3">
              Log out of all devices. You will need to sign in again on every device.
            </p>
            <div className="flex items-center gap-3">
              <button
                onClick={handleLogoutAll}
                className="text-sm px-4 py-2 border border-red-300 text-red-600 rounded-lg hover:bg-red-50 transition-colors"
              >
                Log out of all devices
              </button>
              {logoutAllMsg && <span className="text-xs text-red-600">{logoutAllMsg}</span>}
            </div>
          </div>
        </div>
      </section>

      {/* Section: Data Access History */}
      <section className="space-y-3">
        <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide">Data Access History</h2>
        <AccessHistory />
      </section>
    </div>
  );
}

import { useState, useEffect, useCallback } from 'react';
import { useAuth } from '../AuthContext';
import { useOrg } from '../OrgContext';
import api from '../api';
import TopicBadge from '../components/TopicBadge';
import { useToast } from '../components/Toast';
import { useConfirm } from '../components/ConfirmDialog';

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

function DelegateCard({ topic, profile, onRegister, onEdit, onStepDown, confirm }) {
  const [editing, setEditing] = useState(false);
  const [bio, setBio] = useState(profile?.bio || '');
  const [registering, setRegistering] = useState(false);
  const [saving, setSaving] = useState(false);

  if (!profile || !profile.is_active) {
    // Not registered
    if (registering) {
      return (
        <div className="bg-white border border-gray-200 rounded-xl p-4 space-y-3">
          <div className="flex items-center gap-2">
            <TopicBadge topic={topic} />
            <span className="text-xs text-gray-400">Not registered</span>
          </div>
          <textarea
            value={bio}
            onChange={e => setBio(e.target.value)}
            placeholder="Tell others why they should trust you on this topic (50-1000 chars)"
            className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[#2E75B6] resize-none"
            rows={3}
          />
          <p className="text-xs text-gray-400">Your votes on {topic.name} proposals will become publicly visible.</p>
          <div className="flex gap-2">
            <button
              onClick={() => { onRegister(topic.id, bio); setRegistering(false); }}
              disabled={bio.length < 50}
              className="text-xs px-3 py-1.5 bg-[#1B3A5C] text-white rounded-lg hover:bg-[#2E75B6] transition-colors disabled:opacity-50"
            >
              Register
            </button>
            <button
              onClick={() => setRegistering(false)}
              className="text-xs px-3 py-1.5 border border-gray-300 text-gray-500 rounded-lg hover:bg-gray-50"
            >
              Cancel
            </button>
          </div>
        </div>
      );
    }

    return (
      <div className="bg-white border border-gray-200 rounded-xl p-4 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <TopicBadge topic={topic} />
          <span className="text-xs text-gray-400">Not registered</span>
        </div>
        <button
          onClick={() => setRegistering(true)}
          className="text-xs px-3 py-1.5 border border-[#2E75B6] text-[#2E75B6] rounded-lg hover:bg-[#2E75B6] hover:text-white transition-colors"
        >
          Become a Delegate
        </button>
      </div>
    );
  }

  // Active delegate profile
  return (
    <div className="bg-white border border-gray-200 rounded-xl p-4 space-y-2">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <TopicBadge topic={topic} />
          <span className="text-xs text-green-600 font-medium bg-green-50 px-2 py-0.5 rounded">Active</span>
        </div>
        <div className="flex gap-2">
          {!editing && (
            <button
              onClick={() => { setBio(profile.bio); setEditing(true); }}
              className="text-xs text-[#2E75B6] hover:underline"
            >
              Edit Bio
            </button>
          )}
          <button
            onClick={async () => {
              const ok = await confirm({
                title: 'Step Down as Delegate',
                message: `This will remove you as a public delegate for ${topic.name}. People who delegated to you on this topic will need to choose a new delegate. Are you sure?`,
                destructive: true,
              });
              if (ok) onStepDown(topic.id);
            }}
            className="text-xs text-red-500 hover:underline"
          >
            Step Down
          </button>
        </div>
      </div>
      {editing ? (
        <div className="space-y-2">
          <textarea
            value={bio}
            onChange={e => setBio(e.target.value)}
            className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[#2E75B6] resize-none"
            rows={3}
          />
          <div className="flex gap-2">
            <button
              onClick={async () => {
                setSaving(true);
                await onEdit(topic.id, bio);
                setSaving(false);
                setEditing(false);
              }}
              disabled={saving || bio.length < 50}
              className="text-xs px-3 py-1.5 bg-[#1B3A5C] text-white rounded-lg hover:bg-[#2E75B6] transition-colors disabled:opacity-50"
            >
              {saving ? 'Saving...' : 'Save'}
            </button>
            <button onClick={() => setEditing(false)} className="text-xs text-gray-500 hover:underline">Cancel</button>
          </div>
        </div>
      ) : (
        profile.bio && <p className="text-sm text-gray-600 italic">"{profile.bio}"</p>
      )}
    </div>
  );
}

export default function Settings() {
  const { user: authUser, logout } = useAuth();
  const { currentOrg } = useOrg();
  const toast = useToast();
  const confirm = useConfirm();
  const [user, setUser] = useState(null);
  const [topics, setTopics] = useState([]);
  const [profiles, setProfiles] = useState([]);
  const [loading, setLoading] = useState(true);
  const [displayName, setDisplayName] = useState('');
  const [policy, setPolicy] = useState('require_approval');
  const [profileMsg, setProfileMsg] = useState('');
  const [policyMsg, setPolicyMsg] = useState('');
  const [pwCurrent, setPwCurrent] = useState('');
  const [pwNew, setPwNew] = useState('');
  const [pwConfirm, setPwConfirm] = useState('');
  const [pwMsg, setPwMsg] = useState('');
  const [logoutAllMsg, setLogoutAllMsg] = useState('');

  const load = useCallback(async () => {
    try {
      const topicsUrl = currentOrg
        ? `/api/orgs/${currentOrg.slug}/topics`
        : '/api/topics';
      const [me, tops] = await Promise.all([
        api.get('/api/auth/me'),
        api.get(topicsUrl),
      ]);
      setUser(me);
      setDisplayName(me.display_name);
      setPolicy(me.default_follow_policy);
      setTopics(tops);
      // Get delegate profiles for current user
      const profileData = await api.get(`/api/users/${me.id}/profile`);
      setProfiles(profileData.delegate_profiles || []);
    } catch { /* ignore */ } finally {
      setLoading(false);
    }
  }, [currentOrg]);

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

  async function handleRegister(topicId, bio) {
    try {
      await api.post('/api/delegates/register', { topic_id: topicId, bio });
      load();
    } catch (e) {
      toast.error(e.message);
    }
  }

  async function handleEditBio(topicId, bio) {
    try {
      await api.post('/api/delegates/register', { topic_id: topicId, bio });
      load();
    } catch (e) {
      toast.error(e.message);
    }
  }

  async function handleStepDown(topicId) {
    try {
      await api.delete(`/api/delegates/register/${topicId}`);
      load();
    } catch (e) {
      toast.error(e.message);
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
      <div className="animate-spin w-8 h-8 border-4 border-[#2E75B6] border-t-transparent rounded-full"></div>
    </div>
  );

  // Build a map of profile by topic_id
  const profileByTopic = {};
  for (const p of profiles) {
    profileByTopic[p.topic_id] = p;
  }

  return (
    <div className="max-w-3xl mx-auto px-4 py-8 space-y-10">
      <h1 className="text-2xl font-semibold text-[#1B3A5C]">Settings</h1>

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
              className="w-full max-w-xs px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[#2E75B6]"
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
              className="text-sm px-4 py-2 bg-[#1B3A5C] text-white rounded-lg hover:bg-[#2E75B6] transition-colors disabled:opacity-50"
            >
              Save Changes
            </button>
            {profileMsg && <span className={`text-xs ${profileMsg === 'Saved' ? 'text-green-600' : 'text-red-600'}`}>{profileMsg}</span>}
          </div>
        </div>
      </section>

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
                className="mt-0.5 accent-[#2E75B6]"
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
              className="text-sm px-4 py-2 bg-[#1B3A5C] text-white rounded-lg hover:bg-[#2E75B6] transition-colors disabled:opacity-50"
            >
              Save Preferences
            </button>
            {policyMsg && <span className={`text-xs ${policyMsg === 'Saved' ? 'text-green-600' : 'text-red-600'}`}>{policyMsg}</span>}
          </div>
        </div>
      </section>

      {/* Section: Public Delegate Registration */}
      <section className="space-y-3">
        <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide">Public Delegate Registration</h2>
        <p className="text-xs text-gray-400">
          Register as a public delegate to let anyone delegate to you on a topic. Your votes on that topic become publicly visible.
        </p>
        {currentOrg?.settings?.public_delegate_policy === 'admin_approval' && (
          <div className="p-3 bg-blue-50 border border-blue-200 text-blue-700 text-xs rounded-lg">
            This organization requires admin approval for delegate applications. Your application will be reviewed by an administrator.
          </div>
        )}
        <div className="space-y-3">
          {topics.map(t => (
            <DelegateCard
              key={t.id}
              topic={t}
              profile={profileByTopic[t.id]}
              onRegister={handleRegister}
              onEdit={handleEditBio}
              onStepDown={handleStepDown}
              confirm={confirm}
            />
          ))}
        </div>
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
              className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[#2E75B6]"
            />
            <input
              type="password"
              value={pwNew}
              onChange={e => setPwNew(e.target.value)}
              placeholder="New password (min 8 chars)"
              className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[#2E75B6]"
            />
            <input
              type="password"
              value={pwConfirm}
              onChange={e => setPwConfirm(e.target.value)}
              placeholder="Confirm new password"
              className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[#2E75B6]"
            />
          </div>
          <div className="flex items-center gap-3">
            <button
              onClick={handleChangePassword}
              disabled={!pwCurrent || pwNew.length < 8}
              className="text-sm px-4 py-2 bg-[#1B3A5C] text-white rounded-lg hover:bg-[#2E75B6] transition-colors disabled:opacity-50"
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
    </div>
  );
}

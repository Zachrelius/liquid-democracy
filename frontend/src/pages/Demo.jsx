import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import PublicLayout from '../components/PublicLayout';
import { useToast } from '../components/Toast';
import api, { setTokens } from '../api';

const PERSONAS = [
  {
    username: 'alice',
    displayName: 'Alice',
    role: 'Voter + Admin',
    description:
      "A typical voter who delegates healthcare and economy to experts. Also an org admin, so you can try the admin tools.",
  },
  {
    username: 'dr_chen',
    displayName: 'Dr. Chen',
    role: 'Public Delegate',
    description:
      "A public delegate on healthcare and economy. See what it's like to be trusted with others' votes.",
  },
  {
    username: 'carol',
    displayName: 'Carol',
    role: 'Direct Voter',
    description: 'Votes directly on every proposal. No delegations.',
  },
  {
    username: 'dave',
    displayName: 'Dave',
    role: 'Chain Delegator',
    description:
      'Delegates everything to alice via global delegation. Shows how chains resolve.',
  },
  {
    username: 'frank',
    displayName: 'Frank',
    role: 'New Voter',
    description: 'No delegations or follows yet. Start fresh.',
  },
  {
    username: 'admin',
    displayName: 'Admin',
    role: 'Owner',
    description:
      'Full org owner. Create proposals, manage members, view analytics.',
  },
];

export default function Demo() {
  const navigate = useNavigate();
  const toast = useToast();
  const [loadingUser, setLoadingUser] = useState(null);

  async function handlePersonaLogin(username) {
    setLoadingUser(username);
    try {
      const data = await api.post('/api/auth/demo-login', { username });
      if (!data?.access_token) {
        throw new Error('Demo login did not return an access token.');
      }
      // Mirror AuthContext.login() — persist tokens to sessionStorage and
      // sync them into the api module. A full-page nav to /proposals
      // triggers AuthProvider's mount-time token restore, which hydrates
      // the user and redirects correctly through the protected routes.
      setTokens(data.access_token, data.refresh_token || null);
      sessionStorage.setItem('token', data.access_token);
      if (data.refresh_token) {
        sessionStorage.setItem('refreshToken', data.refresh_token);
      }
      window.location.assign('/proposals');
    } catch (err) {
      if (err?.status === 404) {
        toast.error('Demo login not available.');
      } else {
        toast.error(err?.message || 'Demo login failed.');
      }
      setLoadingUser(null);
    }
  }

  return (
    <PublicLayout>
      <div className="max-w-6xl mx-auto px-6 py-16">
        {/* Intro */}
        <div className="max-w-3xl">
          <p className="text-sm font-medium text-[#2E75B6] uppercase tracking-wider">
            Demo
          </p>
          <h1 className="mt-2 text-3xl sm:text-4xl font-semibold text-[#1B3A5C] tracking-tight">
            Try the platform
          </h1>
          <p className="mt-4 text-base text-[#2C3E50] leading-relaxed">
            This is a working demo of the Liquid Democracy platform. Vote,
            delegate, and explore as one of the pre-built personas below,
            or register your own account to try the full onboarding flow.
          </p>
        </div>

        {/* Persistent-data notice */}
        <div className="mt-6 max-w-3xl p-4 rounded-lg border border-amber-200 bg-amber-50 text-sm text-amber-900">
          <strong className="font-semibold">Heads up:</strong> this is a
          shared demo. Anything you create — proposals, delegations,
          votes — will be visible to other visitors. The demo data is
          reset periodically.
        </div>

        {/* Persona picker */}
        <section className="mt-12">
          <h2 className="text-xl font-semibold text-[#1B3A5C] mb-5">
            Sign in as a persona
          </h2>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {PERSONAS.map(p => (
              <PersonaCard
                key={p.username}
                persona={p}
                loading={loadingUser === p.username}
                disabled={loadingUser !== null && loadingUser !== p.username}
                onClick={() => handlePersonaLogin(p.username)}
              />
            ))}
          </div>
        </section>

        {/* Register-your-own */}
        <section className="mt-14 p-6 rounded-xl border border-gray-200 bg-white shadow-sm max-w-3xl">
          <h2 className="text-lg font-semibold text-[#1B3A5C] mb-2">
            Prefer to start fresh?
          </h2>
          <p className="text-sm text-[#2C3E50] leading-relaxed">
            <Link
              to="/register"
              className="text-[#2E75B6] font-medium hover:underline"
            >
              Register your own demo account
            </Link>{' '}
            and walk through the full onboarding flow including email
            verification.
          </p>
        </section>
      </div>
    </PublicLayout>
  );
}

function PersonaCard({ persona, loading, disabled, onClick }) {
  return (
    <div className="flex flex-col p-5 bg-white rounded-xl border border-gray-200 shadow-sm hover:border-[#2E75B6] transition-colors">
      <div className="flex items-center gap-3 mb-3">
        <div className="w-10 h-10 rounded-full bg-[#1B3A5C] text-white flex items-center justify-center text-sm font-bold">
          {persona.displayName.charAt(0).toUpperCase()}
        </div>
        <div>
          <div className="text-base font-semibold text-[#1B3A5C]">
            {persona.displayName}
          </div>
          <div className="text-xs text-gray-500">{persona.role}</div>
        </div>
      </div>
      <p className="text-sm text-[#2C3E50] leading-relaxed flex-1">
        {persona.description}
      </p>
      <button
        onClick={onClick}
        disabled={disabled || loading}
        className="mt-4 w-full py-2 bg-[#1B3A5C] text-white text-sm font-medium rounded-lg hover:bg-[#2E75B6] transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
      >
        {loading ? 'Signing in...' : `Sign in as ${persona.displayName}`}
      </button>
    </div>
  );
}

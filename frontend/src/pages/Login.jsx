import { useState, useEffect } from 'react';
import { useNavigate, useLocation, Link } from 'react-router-dom';
import { useAuth } from '../AuthContext';
import { urlFor } from '../utils/urls';
import api from '../api';

// Phase 11 — pick the best post-login landing path. Multiple orgs → /orgs
// (the picker auto-redirects single-org users so /orgs is also fine for
// that case). Zero orgs → /orgs (which renders the empty-state CTA).
function landingForOrgs(orgs) {
  if (!orgs || orgs.length === 0) return '/orgs';
  if (orgs.length === 1) return urlFor(orgs[0], 'proposals');
  // Pick the most-recent localStorage hint if it's still valid; otherwise
  // surface the picker.
  let hint = null;
  try { hint = localStorage.getItem('currentOrgSlug'); } catch { /* ignore */ }
  const hinted = hint ? orgs.find(o => o.slug === hint) : null;
  return hinted ? urlFor(hinted, 'proposals') : '/orgs';
}

// Phase 14 F2 — `?next=` query-param honoring for post-auth redirect.
//
// The public org landing page CTAs link to /login?next=/{slug} and
// /register?next=/{slug} so visitors who sign in or register from a
// splash return to that splash to complete their join action. We accept
// only same-origin relative paths — any value not starting with a single
// "/" is rejected (and we explicitly reject protocol-relative "//foo"
// values, which would otherwise navigate off-site). On rejection we fall
// back to the default landingForOrgs path so the auth flow still
// completes; we just don't honor the unsafe redirect.
//
// Phase 43 Cluster F (2026-05-30) — extracted to ../utils/resolveNext so
// VerifyEmail.jsx can share the same validator for its persisted-intent
// flow. Backwards-compat re-export of the local name kept for any future
// caller that grepped here.
import { resolveNext } from '../utils/resolveNext';

export default function Login() {
  const { login, register } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  // If the visitor lands on /register, start on the register tab
  const [tab, setTab] = useState(location.pathname === '/register' ? 'register' : 'login');
  // Phase 14 F2 — pull the `next` query-param so post-auth we can return
  // the user to the splash they came from. Validated via resolveNext;
  // null when absent or unsafe.
  const nextParam = (() => {
    try {
      const params = new URLSearchParams(location.search);
      return resolveNext(params.get('next'));
    } catch {
      return null;
    }
  })();
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);

  // Login form state
  const [loginUsername, setLoginUsername] = useState('');
  const [loginPassword, setLoginPassword] = useState('');

  // Register form state
  const [regUsername, setRegUsername] = useState('');
  const [regDisplayName, setRegDisplayName] = useState('');
  const [regEmail, setRegEmail] = useState('');
  const [regPassword, setRegPassword] = useState('');

  // Demo loading
  const [demoLoading, setDemoLoading] = useState(false);
  const [demoMsg, setDemoMsg] = useState('');

  // Demo quick-switch users
  const [demoUsers, setDemoUsers] = useState([]);

  // Phase 9.7 W8 — demo affordances (quick-switch grid + load-scenario button)
  // are hidden behind an opt-in toggle. First-time visitors (especially
  // invitation recipients landing here from /invite/:token's "have an account?
  // sign in" path, or anyone not specifically here for the demo) shouldn't see
  // a wall of "log in as Alice/Bob/Carol" buttons.
  const [showDemo, setShowDemo] = useState(false);

  useEffect(() => {
    // Try to fetch demo users (only works in debug mode)
    api.get('/api/auth/demo-users')
      .then(users => setDemoUsers(users))
      .catch(() => setDemoUsers([]));
  }, []);

  async function handleLogin(e) {
    e.preventDefault();
    setError('');
    setSubmitting(true);
    try {
      await login(loginUsername, loginPassword);
      // Phase 14 F2 — honor `?next=` first if present and safe (set by
      // public landing page CTAs so the visitor returns to the splash).
      // Falls through to the default org-derived landing if absent.
      if (nextParam) {
        navigate(nextParam);
        return;
      }
      // Check if user has orgs, redirect accordingly
      try {
        const orgs = await api.get('/api/orgs');
        if (orgs.length === 0) {
          // Check if platform needs setup
          const status = await api.get('/api/orgs/setup-status');
          if (status.needs_setup) {
            navigate('/setup');
            return;
          }
          navigate('/orgs');
          return;
        }
        navigate(landingForOrgs(orgs));
        return;
      } catch {
        // ignore -- fall through to /orgs (safe fallback)
      }
      navigate('/orgs');
    } catch (err) {
      setError(err.message || 'Login failed');
    } finally {
      setSubmitting(false);
    }
  }

  async function handleRegister(e) {
    e.preventDefault();
    setError('');
    setSubmitting(true);
    try {
      const result = await register(regUsername, regDisplayName, regEmail, regPassword);
      // Phase 43 Cluster F — persist `next` across the email-verification
      // round-trip. The /verify-email link emailed to the user has no `next`
      // param, so VerifyEmail.jsx reads this sessionStorage entry after a
      // successful verification to route back to the original intent
      // (e.g., /orgs/create). Same-browser case is the common one; cross-
      // browser verification falls through to the standard "Go to Login"
      // flow which is acceptable for v1 per the Phase 43 spec.
      if (nextParam) {
        try { sessionStorage.setItem('postVerifyNext', nextParam); } catch {
          // sessionStorage unavailable (private window) — graceful no-op.
        }
      }
      if (result.is_first_user) {
        navigate('/setup');
      } else if (nextParam) {
        // Phase 14 F2 — honor `?next=` after registration too. New users
        // arriving via a public org splash should return to that splash
        // (where they can request to join / join open orgs).
        navigate(nextParam);
      } else {
        // Phase 11 — fetch orgs and pick a slug-prefixed landing path. New
        // users typically have either zero orgs (→ /orgs empty-state) or
        // one auto-joined demo org (→ /{slug}/proposals).
        try {
          const orgs = await api.get('/api/orgs');
          navigate(landingForOrgs(orgs));
        } catch {
          navigate('/orgs');
        }
      }
    } catch (err) {
      setError(err.message || 'Registration failed');
    } finally {
      setSubmitting(false);
    }
  }

  async function handleDemo() {
    setDemoLoading(true);
    setDemoMsg('');
    setError('');
    try {
      const res = await api.post('/api/admin/seed', { scenario: 'healthcare' });
      setDemoMsg(res.message || 'Demo data loaded. Log in as alice / demo1234');
      // Refresh demo users after seeding
      try {
        const users = await api.get('/api/auth/demo-users');
        setDemoUsers(users);
      } catch { /* ignore */ }
    } catch (err) {
      setError(err.message || 'Failed to load demo data');
    } finally {
      setDemoLoading(false);
    }
  }

  async function handleQuickLogin(username) {
    setError('');
    setSubmitting(true);
    try {
      await login(username, 'demo1234');
      try {
        const orgs = await api.get('/api/orgs');
        if (orgs.length === 0) {
          const status = await api.get('/api/orgs/setup-status');
          if (status.needs_setup) {
            navigate('/setup');
            return;
          }
          navigate('/orgs');
          return;
        }
        navigate(landingForOrgs(orgs));
        return;
      } catch { /* ignore */ }
      navigate('/orgs');
    } catch (err) {
      setError(err.message || 'Quick login failed');
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="min-h-screen flex flex-col items-center justify-center bg-[#F8F9FA] px-4">
      {/* Header */}
      <div className="mb-8 text-center">
        <h1 className="text-3xl font-semibold text-[var(--brand-primary)] tracking-tight">
          Liquid Democracy
        </h1>
        <p className="mt-1 text-[#64748b] text-sm">
          Delegate your vote. Shape collective decisions.
        </p>
      </div>

      <div className="w-full max-w-md bg-white rounded-xl shadow-sm border border-gray-200">
        {/* Tabs */}
        <div className="flex border-b border-gray-200">
          {['login', 'register'].map(t => (
            <button
              key={t}
              type="button"
              aria-pressed={tab === t}
              onClick={() => { setTab(t); setError(''); }}
              className={`flex-1 py-3 text-sm font-medium capitalize transition-colors ${
                tab === t
                  ? 'text-[var(--brand-accent)] border-b-2 border-[var(--brand-accent)]'
                  : 'text-gray-500 hover:text-gray-700'
              }`}
            >
              {t}
            </button>
          ))}
        </div>

        <div className="p-6">
          {error && (
            <div role="alert" className="mb-4 p-3 bg-red-50 border border-red-200 text-red-700 text-sm rounded-lg">
              {error}
            </div>
          )}

          {tab === 'login' ? (
            <form onSubmit={handleLogin} className="space-y-4">
              <div>
                <label htmlFor="login-username" className="block text-sm font-medium text-gray-700 mb-1">Username</label>
                <input
                  id="login-username"
                  type="text"
                  autoComplete="username"
                  value={loginUsername}
                  onChange={e => setLoginUsername(e.target.value)}
                  required
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[var(--brand-accent)] focus:border-transparent"
                  placeholder="alice"
                />
              </div>
              <div>
                <label htmlFor="login-password" className="block text-sm font-medium text-gray-700 mb-1">Password</label>
                <input
                  id="login-password"
                  type="password"
                  autoComplete="current-password"
                  value={loginPassword}
                  onChange={e => setLoginPassword(e.target.value)}
                  required
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[var(--brand-accent)] focus:border-transparent"
                  placeholder="••••••••"
                />
              </div>
              <button
                type="submit"
                disabled={submitting}
                className="w-full py-2.5 bg-[var(--brand-primary)] text-white text-sm font-medium rounded-lg hover:bg-[var(--brand-accent)] transition-colors disabled:opacity-50"
              >
                {submitting ? 'Signing in...' : 'Sign In'}
              </button>
              <div className="text-center">
                <Link
                  to="/forgot-password"
                  className="text-sm text-[var(--brand-accent)] hover:underline"
                >
                  Forgot password?
                </Link>
              </div>
            </form>
          ) : (
            <form onSubmit={handleRegister} className="space-y-4">
              <div>
                <label htmlFor="register-username" className="block text-sm font-medium text-gray-700 mb-1">Username</label>
                <input
                  id="register-username"
                  type="text"
                  autoComplete="username"
                  aria-describedby="register-username-help"
                  value={regUsername}
                  onChange={e => setRegUsername(e.target.value)}
                  required
                  minLength={3}
                  maxLength={50}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[var(--brand-accent)] focus:border-transparent"
                  placeholder="your_username"
                />
                <p id="register-username-help" className="mt-1 text-xs text-gray-500">3-50 characters</p>
              </div>
              <div>
                <label htmlFor="register-display-name" className="block text-sm font-medium text-gray-700 mb-1">Display Name</label>
                <input
                  id="register-display-name"
                  type="text"
                  autoComplete="name"
                  value={regDisplayName}
                  onChange={e => setRegDisplayName(e.target.value)}
                  required
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[var(--brand-accent)] focus:border-transparent"
                  placeholder="Your Name"
                />
              </div>
              <div>
                <label htmlFor="register-email" className="block text-sm font-medium text-gray-700 mb-1">Email</label>
                <input
                  id="register-email"
                  type="email"
                  autoComplete="email"
                  value={regEmail}
                  onChange={e => setRegEmail(e.target.value)}
                  required
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[var(--brand-accent)] focus:border-transparent"
                  placeholder="you@example.com"
                />
              </div>
              <div>
                <label htmlFor="register-password" className="block text-sm font-medium text-gray-700 mb-1">Password</label>
                <input
                  id="register-password"
                  type="password"
                  autoComplete="new-password"
                  aria-describedby="register-password-help"
                  value={regPassword}
                  onChange={e => setRegPassword(e.target.value)}
                  required
                  minLength={8}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[var(--brand-accent)] focus:border-transparent"
                  placeholder="••••••••"
                />
                <p id="register-password-help" className="mt-1 text-xs text-gray-500">Minimum 8 characters</p>
              </div>
              <button
                type="submit"
                disabled={submitting}
                className="w-full py-2.5 bg-[var(--brand-primary)] text-white text-sm font-medium rounded-lg hover:bg-[var(--brand-accent)] transition-colors disabled:opacity-50"
              >
                {submitting ? 'Creating account...' : 'Create Account'}
              </button>
              <p className="text-xs text-gray-400 text-center">
                By registering, you agree to our{' '}
                <Link to="/terms" className="text-[var(--brand-accent)] hover:underline">Terms of Service</Link>
                {' '}and{' '}
                <Link to="/privacy" className="text-[var(--brand-accent)] hover:underline">Privacy Policy</Link>.
              </p>
            </form>
          )}

          {/* Phase 9.7 W8 — demo affordances are gated behind a deliberate
              opt-in. The data still loads on mount (the useEffect above runs
              regardless) so it's ready when the toggle flips. Once revealed,
              the affordances stay visible for the rest of the session. */}
          {showDemo && (
            <>
              {/* Demo quick-switch login */}
              {demoUsers.length > 0 && (
                <div className="mt-6 pt-5 border-t border-gray-100">
                  <p className="text-xs text-gray-400 text-center mb-3">
                    Quick Login (Demo Mode)
                  </p>
                  <div className="grid grid-cols-3 gap-2">
                    {demoUsers.map(u => (
                      <button
                        key={u.username}
                        onClick={() => handleQuickLogin(u.username)}
                        disabled={submitting}
                        className="flex flex-col items-center gap-1 p-2 bg-gray-50 border border-gray-200 rounded-lg hover:border-[var(--brand-accent)] hover:bg-blue-50 transition-colors disabled:opacity-50"
                      >
                        <div className="w-8 h-8 rounded-full bg-[var(--brand-primary)] text-white flex items-center justify-center text-xs font-bold">
                          {u.display_name.charAt(0).toUpperCase()}
                        </div>
                        <span className="text-xs text-gray-700 font-medium truncate w-full text-center">{u.display_name}</span>
                        <span className="text-[10px] text-gray-400">@{u.username}</span>
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {/* Demo loader */}
              <div className="mt-6 pt-5 border-t border-gray-100">
                <p className="text-xs text-gray-400 text-center mb-2">
                  First time? Load a demo scenario to explore the platform.
                </p>
                {demoMsg && (
                  <div role="status" aria-live="polite" className="mb-2 p-2 bg-green-50 border border-green-200 text-green-700 text-xs rounded-lg text-center">
                    {demoMsg}
                  </div>
                )}
                <button
                  onClick={handleDemo}
                  disabled={demoLoading}
                  className="w-full py-2 border border-[var(--brand-accent)] text-[var(--brand-accent)] text-sm font-medium rounded-lg hover:bg-[var(--brand-accent)] hover:text-white transition-colors disabled:opacity-50"
                >
                  {demoLoading ? 'Loading demo data...' : 'Load Demo Scenario'}
                </button>
                <p className="mt-1.5 text-xs text-gray-400 text-center">
                  After loading, log in as <strong>alice</strong> with password <strong>demo1234</strong>
                </p>
              </div>
            </>
          )}

          {!showDemo && (
            <div className="mt-6 pt-5 border-t border-gray-100 text-center">
              <button
                type="button"
                onClick={() => setShowDemo(true)}
                className="text-xs text-gray-500 hover:text-gray-700"
              >
                Just exploring? Try the demo →
              </button>
            </div>
          )}
        </div>
      </div>

      {/* Footer links */}
      <div className="mt-6 flex gap-4 text-xs text-gray-400">
        <Link to="/privacy" className="hover:text-[var(--brand-accent)] hover:underline">Privacy Policy</Link>
        <Link to="/terms" className="hover:text-[var(--brand-accent)] hover:underline">Terms of Service</Link>
      </div>
    </div>
  );
}

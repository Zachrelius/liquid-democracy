import { useState, useEffect } from 'react';
import { useNavigate, useLocation, Link } from 'react-router-dom';
import { useAuth } from '../AuthContext';
import api from '../api';

export default function Login() {
  const { login, register } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  // If the visitor lands on /register, start on the register tab
  const [tab, setTab] = useState(location.pathname === '/register' ? 'register' : 'login');
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
      } catch {
        // ignore -- fall through to proposals
      }
      navigate('/proposals');
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
      if (result.is_first_user) {
        navigate('/setup');
      } else {
        navigate('/proposals');
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
      } catch { /* ignore */ }
      navigate('/proposals');
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
        <h1 className="text-3xl font-semibold text-[#1B3A5C] tracking-tight">
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
              onClick={() => { setTab(t); setError(''); }}
              className={`flex-1 py-3 text-sm font-medium capitalize transition-colors ${
                tab === t
                  ? 'text-[#2E75B6] border-b-2 border-[#2E75B6]'
                  : 'text-gray-500 hover:text-gray-700'
              }`}
            >
              {t}
            </button>
          ))}
        </div>

        <div className="p-6">
          {error && (
            <div className="mb-4 p-3 bg-red-50 border border-red-200 text-red-700 text-sm rounded-lg">
              {error}
            </div>
          )}

          {tab === 'login' ? (
            <form onSubmit={handleLogin} className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Username</label>
                <input
                  type="text"
                  value={loginUsername}
                  onChange={e => setLoginUsername(e.target.value)}
                  required
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[#2E75B6] focus:border-transparent"
                  placeholder="alice"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Password</label>
                <input
                  type="password"
                  value={loginPassword}
                  onChange={e => setLoginPassword(e.target.value)}
                  required
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[#2E75B6] focus:border-transparent"
                  placeholder="••••••••"
                />
              </div>
              <button
                type="submit"
                disabled={submitting}
                className="w-full py-2.5 bg-[#1B3A5C] text-white text-sm font-medium rounded-lg hover:bg-[#2E75B6] transition-colors disabled:opacity-50"
              >
                {submitting ? 'Signing in...' : 'Sign In'}
              </button>
              <div className="text-center">
                <Link
                  to="/forgot-password"
                  className="text-sm text-[#2E75B6] hover:underline"
                >
                  Forgot password?
                </Link>
              </div>
            </form>
          ) : (
            <form onSubmit={handleRegister} className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Username</label>
                <input
                  type="text"
                  value={regUsername}
                  onChange={e => setRegUsername(e.target.value)}
                  required
                  minLength={3}
                  maxLength={50}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[#2E75B6] focus:border-transparent"
                  placeholder="your_username"
                />
                <p className="mt-1 text-xs text-gray-400">3-50 characters</p>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Display Name</label>
                <input
                  type="text"
                  value={regDisplayName}
                  onChange={e => setRegDisplayName(e.target.value)}
                  required
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[#2E75B6] focus:border-transparent"
                  placeholder="Your Name"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Email</label>
                <input
                  type="email"
                  value={regEmail}
                  onChange={e => setRegEmail(e.target.value)}
                  required
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[#2E75B6] focus:border-transparent"
                  placeholder="you@example.com"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Password</label>
                <input
                  type="password"
                  value={regPassword}
                  onChange={e => setRegPassword(e.target.value)}
                  required
                  minLength={8}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[#2E75B6] focus:border-transparent"
                  placeholder="••••••••"
                />
                <p className="mt-1 text-xs text-gray-400">Minimum 8 characters</p>
              </div>
              <button
                type="submit"
                disabled={submitting}
                className="w-full py-2.5 bg-[#1B3A5C] text-white text-sm font-medium rounded-lg hover:bg-[#2E75B6] transition-colors disabled:opacity-50"
              >
                {submitting ? 'Creating account...' : 'Create Account'}
              </button>
              <p className="text-xs text-gray-400 text-center">
                By registering, you agree to our{' '}
                <Link to="/terms" className="text-[#2E75B6] hover:underline">Terms of Service</Link>
                {' '}and{' '}
                <Link to="/privacy" className="text-[#2E75B6] hover:underline">Privacy Policy</Link>.
              </p>
            </form>
          )}

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
                    className="flex flex-col items-center gap-1 p-2 bg-gray-50 border border-gray-200 rounded-lg hover:border-[#2E75B6] hover:bg-blue-50 transition-colors disabled:opacity-50"
                  >
                    <div className="w-8 h-8 rounded-full bg-[#1B3A5C] text-white flex items-center justify-center text-xs font-bold">
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
              <div className="mb-2 p-2 bg-green-50 border border-green-200 text-green-700 text-xs rounded-lg text-center">
                {demoMsg}
              </div>
            )}
            <button
              onClick={handleDemo}
              disabled={demoLoading}
              className="w-full py-2 border border-[#2E75B6] text-[#2E75B6] text-sm font-medium rounded-lg hover:bg-[#2E75B6] hover:text-white transition-colors disabled:opacity-50"
            >
              {demoLoading ? 'Loading demo data...' : 'Load Demo Scenario'}
            </button>
            <p className="mt-1.5 text-xs text-gray-400 text-center">
              After loading, log in as <strong>alice</strong> with password <strong>demo1234</strong>
            </p>
          </div>
        </div>
      </div>

      {/* Footer links */}
      <div className="mt-6 flex gap-4 text-xs text-gray-400">
        <Link to="/privacy" className="hover:text-[#2E75B6] hover:underline">Privacy Policy</Link>
        <Link to="/terms" className="hover:text-[#2E75B6] hover:underline">Terms of Service</Link>
      </div>
    </div>
  );
}

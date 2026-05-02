import { useState, useEffect } from 'react';
import { useParams, useNavigate, Link } from 'react-router-dom';
import { useAuth } from '../AuthContext';
import api, { setTokens } from '../api';

/**
 * Phase 9.7 W3 — invitation acceptance page.
 *
 * Public route at `/invite/:token`. Anonymous visitors land here from the
 * email link sent by `send_invitation_email` (Phase 9.7 W4 changed the link
 * format to /invite/{token}). The page fetches invitation metadata via the
 * public, rate-limited GET /api/invitations/{token}/meta and renders one of
 * four states based on the visitor's auth state and whether their email
 * matches the invitation:
 *
 *   1. Unauthenticated, email doesn't have an account yet
 *      → registration form (email pre-filled, read-only). On submit, calls
 *        POST /api/auth/register with `invitation_token` set; backend
 *        consumes the invitation in the same transaction and skips
 *        IS_PUBLIC_DEMO=true auto-join (Phase 9.7 W1).
 *
 *   2. Unauthenticated, email has an existing account
 *      → login form (email pre-filled, read-only). On submit, calls
 *        POST /api/auth/login with `invitation_token` set; backend consumes
 *        the invitation post-auth.
 *
 *   3. Authenticated, signed-in email matches the invited email
 *      → "Accept invitation" card. Click the button to call the existing
 *        POST /api/orgs/join/{token} endpoint.
 *
 *   4. Authenticated, email mismatch
 *      → clear "this isn't your invitation" error with a sign-out option.
 *
 * User-exists detection strategy: the meta endpoint doesn't expose a
 * `user_exists` flag (the backend agent kept the response minimal:
 * org_name/slug + invited_email + role + expires_at). Rather than add a
 * separate "does this email have an account" probe — which would itself be
 * a token-enumeration vector — we render the registration form first and
 * fall back to login mode if the backend returns 400 "Email already in use".
 * The user can also flip the mode manually with the "Already have an
 * account?" link.
 *
 * Demo affordances (the quick-switch buttons that appear on /login) are
 * intentionally absent here. This is a focused single-purpose page.
 */
export default function InviteAccept() {
  const { token } = useParams();
  const navigate = useNavigate();
  const { user, loading: authLoading } = useAuth();

  const [meta, setMeta] = useState(null);
  const [loading, setLoading] = useState(true);
  const [fetchError, setFetchError] = useState(null);

  // Mode for unauthenticated visitors: 'register' (default) or 'login'.
  // Auto-flips to 'login' if registration returns "Email already in use".
  const [mode, setMode] = useState('register');

  // Form state
  const [displayName, setDisplayName] = useState('');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');

  // Submit state
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState('');

  // Fetch invitation metadata on mount.
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    api.get(`/api/invitations/${token}/meta`)
      .then((data) => {
        if (cancelled) return;
        setMeta(data);
        setFetchError(null);
      })
      .catch((err) => {
        if (cancelled) return;
        setMeta(null);
        // 404 / 410 / anything else — surface a friendly error.
        if (err?.status === 404 || err?.status === 410) {
          setFetchError({ kind: 'invalid', message: 'Invitation not found, expired, or already used.' });
        } else {
          setFetchError({
            kind: 'generic',
            message: 'Something went wrong loading this invitation. Please try again or ask your inviter to resend.',
          });
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, [token]);

  // ---------------------------------------------------------------------------
  // Loading / error gates
  // ---------------------------------------------------------------------------
  if (loading || authLoading) {
    return (
      <CenteredCard>
        <div className="flex justify-center py-8">
          <div className="animate-spin w-8 h-8 border-4 border-[#2E75B6] border-t-transparent rounded-full" />
        </div>
      </CenteredCard>
    );
  }

  if (fetchError) {
    return (
      <CenteredCard>
        <h1 className="text-2xl font-semibold text-[#1B3A5C] mb-3">Invitation unavailable</h1>
        <div className="mb-6 p-3 bg-red-50 border border-red-200 text-red-700 text-sm rounded-lg">
          {fetchError.message}
        </div>
        <Link
          to="/login"
          className="inline-block px-6 py-2.5 bg-[#1B3A5C] text-white text-sm font-medium rounded-lg hover:bg-[#2E75B6] transition-colors"
        >
          Go to sign in
        </Link>
      </CenteredCard>
    );
  }

  // ---------------------------------------------------------------------------
  // Authenticated path
  // ---------------------------------------------------------------------------
  if (user) {
    const matches = user.email && meta.invited_email
      && user.email.toLowerCase() === meta.invited_email.toLowerCase();

    if (!matches) {
      // State 4: email mismatch.
      return (
        <CenteredCard>
          <h1 className="text-2xl font-semibold text-[#1B3A5C] mb-3">
            Wrong account for this invitation
          </h1>
          <p className="text-sm text-gray-600 mb-6">
            This invitation is for <strong>{meta.invited_email}</strong>, but you're
            signed in as <strong>{user.email}</strong>. Sign out and try again, or have
            your inviter resend to your current address.
          </p>
          <button
            type="button"
            onClick={async () => {
              // Log out then hard-reload back into the invite page so the
              // visitor lands on the unauthenticated state (1 or 2). The
              // default logout() navigates to /login which would be a
              // dead-end for this flow.
              try {
                await api.logout();
              } catch { /* ignore */ }
              setTokens(null, null);
              sessionStorage.removeItem('token');
              sessionStorage.removeItem('refreshToken');
              window.location.assign(`/invite/${token}`);
            }}
            className="inline-block px-6 py-2.5 bg-[#1B3A5C] text-white text-sm font-medium rounded-lg hover:bg-[#2E75B6] transition-colors"
          >
            Sign out
          </button>
        </CenteredCard>
      );
    }

    // State 3: matches — show accept-invitation card.
    return (
      <CenteredCard>
        <h1 className="text-2xl font-semibold text-[#1B3A5C] mb-2">
          You're invited to join {meta.org_name}
        </h1>
        <p className="text-sm text-gray-600 mb-6">
          You'll join <strong>{meta.org_name}</strong> as a{' '}
          <span className="font-medium">{meta.role}</span>. Once you accept, you'll
          land on the proposals page for this organization.
        </p>
        {submitError && (
          <div className="mb-4 p-3 bg-red-50 border border-red-200 text-red-700 text-sm rounded-lg">
            {submitError}
          </div>
        )}
        <button
          type="button"
          disabled={submitting}
          onClick={async () => {
            setSubmitting(true);
            setSubmitError('');
            try {
              await api.post(`/api/orgs/join/${token}`);
              navigate('/proposals');
            } catch (err) {
              setSubmitError(err?.message || 'Failed to accept invitation.');
            } finally {
              setSubmitting(false);
            }
          }}
          className="inline-block px-6 py-2.5 bg-[#1B3A5C] text-white text-sm font-medium rounded-lg hover:bg-[#2E75B6] transition-colors disabled:opacity-50"
        >
          {submitting ? 'Accepting…' : `Accept invitation to ${meta.org_name}`}
        </button>
      </CenteredCard>
    );
  }

  // ---------------------------------------------------------------------------
  // Unauthenticated path: register-first (state 1) with fallback to login
  // (state 2). User can also flip manually.
  // ---------------------------------------------------------------------------

  async function handleRegister(e) {
    e.preventDefault();
    setSubmitting(true);
    setSubmitError('');
    try {
      // Backend: invitation_token in body causes _consume_invitation to run
      // in the same transaction as user-create, which (a) creates the org
      // membership and (b) gates _auto_join_demo_org out of the demo org.
      await api.post('/api/auth/register', {
        username,
        display_name: displayName,
        email: meta.invited_email,
        password,
        invitation_token: token,
      });
      // Mirror AuthContext.register: log in immediately so the navigated
      // /proposals route resolves under an authenticated session.
      const loginData = await api.login(username, password);
      setTokens(loginData.access_token, loginData.refresh_token);
      sessionStorage.setItem('token', loginData.access_token);
      if (loginData.refresh_token) {
        sessionStorage.setItem('refreshToken', loginData.refresh_token);
      }
      // Hard navigation so AuthProvider re-mounts and OrgContext picks up
      // the freshly-created membership without stale state.
      window.location.assign('/proposals');
    } catch (err) {
      const detail = err?.message || '';
      // Resilient client-side dispatch: if the email already has an account,
      // flip into login mode rather than dead-end the user. Backend register
      // returns 400 "Email already in use" for this case.
      if (err?.status === 400 && /already in use|already registered/i.test(detail)) {
        setMode('login');
        setSubmitError('That email already has an account. Sign in to accept the invitation.');
      } else {
        setSubmitError(detail || 'Registration failed.');
      }
    } finally {
      setSubmitting(false);
    }
  }

  async function handleLogin(e) {
    e.preventDefault();
    setSubmitting(true);
    setSubmitError('');
    try {
      // OAuth2 password grant: the invitation_token rides as an extra form
      // field. Backend (Phase 9.7 W1) reads it from the form and runs
      // _consume_invitation post-auth.
      const form = new URLSearchParams({
        username,
        password,
        invitation_token: token,
      });
      const res = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: form.toString(),
      });
      const data = await res.json();
      if (!res.ok) {
        throw { message: data?.detail || 'Login failed', status: res.status };
      }
      setTokens(data.access_token, data.refresh_token);
      sessionStorage.setItem('token', data.access_token);
      if (data.refresh_token) {
        sessionStorage.setItem('refreshToken', data.refresh_token);
      }
      window.location.assign('/proposals');
    } catch (err) {
      setSubmitError(err?.message || 'Sign-in failed.');
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <CenteredCard>
      <h1 className="text-2xl font-semibold text-[#1B3A5C] mb-1">
        Join {meta.org_name}
      </h1>
      <p className="text-sm text-gray-500 mb-6">
        You've been invited to <strong>{meta.org_name}</strong>. {mode === 'register'
          ? 'Create an account to accept.'
          : 'Sign in to your existing account to accept.'}
      </p>

      {submitError && (
        <div className="mb-4 p-3 bg-red-50 border border-red-200 text-red-700 text-sm rounded-lg">
          {submitError}
        </div>
      )}

      {mode === 'register' ? (
        <form onSubmit={handleRegister} className="space-y-4">
          <ReadOnlyEmailField email={meta.invited_email} />
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Username</label>
            <input
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              required
              minLength={3}
              maxLength={50}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[#2E75B6] focus:border-transparent"
              placeholder="your_username"
            />
            <p className="mt-1 text-xs text-gray-400">3-50 characters</p>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Display name</label>
            <input
              type="text"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              required
              className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[#2E75B6] focus:border-transparent"
              placeholder="Your Name"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Password</label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
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
            {submitting ? 'Creating account…' : `Create account & join ${meta.org_name}`}
          </button>
          <p className="text-xs text-gray-400 text-center">
            By creating an account, you agree to our{' '}
            <Link to="/terms" className="text-[#2E75B6] hover:underline">Terms</Link>{' '}and{' '}
            <Link to="/privacy" className="text-[#2E75B6] hover:underline">Privacy Policy</Link>.
          </p>
          <p className="text-xs text-center text-gray-500">
            Already have an account?{' '}
            <button
              type="button"
              onClick={() => { setMode('login'); setSubmitError(''); }}
              className="text-[#2E75B6] hover:underline"
            >
              Sign in instead
            </button>
          </p>
        </form>
      ) : (
        <form onSubmit={handleLogin} className="space-y-4">
          <ReadOnlyEmailField email={meta.invited_email} />
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Username</label>
            <input
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              required
              className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[#2E75B6] focus:border-transparent"
              placeholder="your_username"
              autoFocus
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Password</label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
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
            {submitting ? 'Signing in…' : `Sign in & join ${meta.org_name}`}
          </button>
          <p className="text-xs text-center text-gray-500">
            Don't have an account yet?{' '}
            <button
              type="button"
              onClick={() => { setMode('register'); setSubmitError(''); }}
              className="text-[#2E75B6] hover:underline"
            >
              Create one
            </button>
          </p>
        </form>
      )}
    </CenteredCard>
  );
}

function CenteredCard({ children }) {
  return (
    <div className="min-h-screen flex flex-col items-center justify-center bg-[#F8F9FA] px-4 py-10">
      <div className="mb-8 text-center">
        <h1 className="text-3xl font-semibold text-[#1B3A5C] tracking-tight">
          Liquid Democracy
        </h1>
        <p className="mt-1 text-[#64748b] text-sm">
          Delegate your vote. Shape collective decisions.
        </p>
      </div>
      <div className="w-full max-w-md bg-white rounded-xl shadow-sm border border-gray-200 p-6">
        {children}
      </div>
    </div>
  );
}

function ReadOnlyEmailField({ email }) {
  // Visually distinct (gray background, lock icon hint) so it reads as
  // intentionally non-editable. The backend rejects email mismatch on
  // submit so the read-only treatment is just UX clarity, not security.
  return (
    <div>
      <label className="block text-sm font-medium text-gray-700 mb-1">Email</label>
      <div className="relative">
        <input
          type="email"
          value={email}
          readOnly
          aria-readonly="true"
          className="w-full px-3 py-2 pr-10 border border-gray-200 bg-gray-50 text-gray-700 rounded-lg text-sm focus:outline-none cursor-not-allowed"
        />
        <span className="pointer-events-none absolute inset-y-0 right-0 flex items-center pr-3 text-gray-400">
          {/* lock glyph */}
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <rect x="3" y="11" width="18" height="11" rx="2" ry="2" />
            <path d="M7 11V7a5 5 0 0 1 10 0v4" />
          </svg>
        </span>
      </div>
      <p className="mt-1 text-xs text-gray-400">
        This invitation is tied to this email address.
      </p>
    </div>
  );
}

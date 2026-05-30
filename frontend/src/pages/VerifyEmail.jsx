import { useState, useEffect } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import api from '../api';
import { useAuth } from '../AuthContext';
import { resolveNext } from '../utils/resolveNext';

export default function VerifyEmail() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const { user, refreshUser } = useAuth();
  const token = searchParams.get('token');
  const [status, setStatus] = useState('verifying'); // verifying, success, error
  const [message, setMessage] = useState('');
  // Phase 43 Cluster F — pull persisted intent set by Login.jsx's register
  // handler when the user came in via a "Start an organization"-style CTA.
  // Same-browser case auto-navigates them to /orgs/create after success;
  // cross-browser falls through to the standard "Go to Login" button.
  const [persistedNext, setPersistedNext] = useState(null);

  useEffect(() => {
    try {
      const raw = sessionStorage.getItem('postVerifyNext');
      setPersistedNext(resolveNext(raw));
    } catch {
      // sessionStorage unavailable — leave null.
    }
  }, []);

  useEffect(() => {
    if (!token) {
      setStatus('error');
      setMessage('No verification token provided.');
      return;
    }

    api.post('/api/auth/verify-email', { token })
      .then(async () => {
        setStatus('success');
        setMessage('Your email has been verified successfully!');
        // Phase 43 Cluster F — if the same browser already has a session
        // (the user registered in this tab/browser), refresh the user so
        // email_verified becomes True, then auto-navigate to the
        // persisted intent. Clear the storage in either case so it can't
        // leak into an unrelated future flow.
        if (persistedNext) {
          try { sessionStorage.removeItem('postVerifyNext'); } catch {
            // ignore
          }
          if (user) {
            try { await refreshUser(); } catch {
              // best-effort; navigate anyway
            }
            navigate(persistedNext);
          }
          // If no session (cross-browser case), the success branch's
          // "Continue" button below threads persistedNext to /login.
        }
      })
      .catch(err => {
        setStatus('error');
        setMessage(err.message || 'Verification failed. The token may be invalid or expired.');
      });
  }, [token, persistedNext, user, refreshUser, navigate]);

  return (
    <div className="min-h-screen flex flex-col items-center justify-center bg-[#F8F9FA] px-4">
      <div className="w-full max-w-md bg-white rounded-xl shadow-sm border border-gray-200 p-8 text-center">
        <h1 className="text-2xl font-semibold text-[var(--brand-primary)] mb-4">Email Verification</h1>

        {status === 'verifying' && (
          <div className="text-gray-500">
            <div className="animate-spin w-8 h-8 border-4 border-[var(--brand-accent)] border-t-transparent rounded-full mx-auto mb-4"></div>
            <p>Verifying your email...</p>
          </div>
        )}

        {status === 'success' && (
          <div>
            <div className="w-16 h-16 bg-green-100 rounded-full flex items-center justify-center mx-auto mb-4">
              <svg className="w-8 h-8 text-green-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
              </svg>
            </div>
            <p className="text-green-700 mb-6">{message}</p>
            {/* Phase 43 Cluster F — if persistedNext is set, thread it
                through to /login so post-auth lands on the original intent
                (cross-browser case). Otherwise plain "Go to Login". */}
            <Link
              to={persistedNext
                ? `/login?next=${encodeURIComponent(persistedNext)}`
                : '/login'
              }
              className="inline-block px-6 py-2.5 bg-[var(--brand-primary)] text-white text-sm font-medium rounded-lg hover:bg-[var(--brand-accent)] transition-colors"
            >
              {persistedNext ? 'Continue' : 'Go to Login'}
            </Link>
          </div>
        )}

        {status === 'error' && (
          <div>
            <div className="w-16 h-16 bg-red-100 rounded-full flex items-center justify-center mx-auto mb-4">
              <svg className="w-8 h-8 text-red-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </div>
            <p className="text-red-700 mb-6">{message}</p>
            <Link
              to="/login"
              className="inline-block px-6 py-2.5 bg-[var(--brand-primary)] text-white text-sm font-medium rounded-lg hover:bg-[var(--brand-accent)] transition-colors"
            >
              Go to Login
            </Link>
          </div>
        )}
      </div>
    </div>
  );
}
